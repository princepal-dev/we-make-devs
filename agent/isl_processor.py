"""ISL Video Processor — Roboflow-based Indian Sign Language detection with debouncing."""

import asyncio
import logging
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from vision_agents.core.processors import VideoProcessor
from vision_agents.core.utils.video_forwarder import VideoForwarder

logger = logging.getLogger(__name__)

# Lazy import to allow startup without Roboflow if keys missing
_roboflow: Optional[Any] = None


def _parse_version(val: Optional[str]) -> int:
    """Parse ROBOFLOW_VERSION, e.g. '1', '1.0', 'v2' -> int."""
    s = (val or "1").strip().lstrip("v")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 1


def _get_roboflow_model() -> Any:
    """Lazy-load Roboflow model."""
    global _roboflow
    if _roboflow is None:
        from roboflow import Roboflow

        api_key = os.getenv("ROBOFLOW_API_KEY")
        workspace = os.getenv("ROBOFLOW_WORKSPACE")
        project = os.getenv("ROBOFLOW_PROJECT")
        version = _parse_version(os.getenv("ROBOFLOW_VERSION", "1"))

        if not all([api_key, workspace, project]):
            raise ValueError(
                "ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE, ROBOFLOW_PROJECT required"
            )

        rf = Roboflow(api_key=api_key)
        project_obj = rf.workspace(workspace).project(project)
        _roboflow = project_obj.version(version).model
    return _roboflow


class ISLProcessor(VideoProcessor):
    """Custom VideoProcessor for Indian Sign Language detection via Roboflow."""

    name = "isl_processor"
    DEBOUNCE_SEC = 0.5
    SILENCE_FLUSH_SEC = 1.5
    CONFIDENCE_THRESHOLD = 60
    MAX_FRAME_SIZE = 640  # Resize long edge for faster Roboflow API calls

    def __init__(self, fps: int = 5):
        self.fps = fps
        self._forwarder: Optional[VideoForwarder] = None
        self._agent: Optional[Any] = None

        self.sign_buffer: List[str] = []
        self._last_sign: Optional[str] = None
        self._last_sign_time: float = 0.0
        self._last_detection_time: float = 0.0
        self._model = None
        self._flush_lock = asyncio.Lock()

    def attach_agent(self, agent: Any) -> None:
        """Store agent reference for triggering LLM when buffer flushes."""
        self._agent = agent

    def _ensure_model(self) -> None:
        if self._model is None:
            self._model = _get_roboflow_model()

    def _predict_frame_sync(self, frame) -> Optional[Dict[str, Any]]:
        """Sync Roboflow prediction. Run via executor to avoid blocking event loop."""
        path = None
        try:
            self._ensure_model()
            import cv2

            img = frame.to_ndarray(format="bgr24")
            h, w = img.shape[:2]
            if max(h, w) > self.MAX_FRAME_SIZE:
                scale = self.MAX_FRAME_SIZE / max(h, w)
                new_w, new_h = int(w * scale), int(h * scale)
                img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            fd, path = tempfile.mkstemp(suffix=".jpg")
            os.close(fd)
            if not cv2.imwrite(path, img):
                return None
            # Try with confidence; some Roboflow versions use different param names
            conf_arg = self.CONFIDENCE_THRESHOLD / 100
            try:
                result = self._model.predict(path, confidence=conf_arg)
            except TypeError:
                result = self._model.predict(path)
            # Handle Prediction object (has .json()) or dict
            data = result.json() if hasattr(result, "json") else result
            if not isinstance(data, dict):
                return None
            # Classification: top + confidence; Detection: predictions list
            top_cls = data.get("top")
            top_conf = data.get("confidence")
            if top_cls is not None and top_conf is not None:
                return {"class": str(top_cls).upper(), "confidence": float(top_conf)}
            preds = data.get("predictions", [])
            if not preds:
                return None
            p = preds[0]
            if isinstance(p, dict):
                cls = p.get("class") or p.get("class_name", "UNKNOWN")
                conf = float(p.get("confidence", 0) or 0)
            else:
                cls = getattr(p, "class", None) or getattr(p, "class_name", "UNKNOWN")
                conf = float(getattr(p, "confidence", 0) or 0)
            return {"class": str(cls).upper(), "confidence": conf}
        except Exception as e:
            logger.exception("Roboflow inference error: %s", e)
            return None
        finally:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError as oe:
                    logger.debug("Failed to remove temp file %s: %s", path, oe)

    async def _trigger_speech(self, prompt: str) -> None:
        """Send prompt to agent to speak via simple_response."""
        if self._agent:
            try:
                await self._agent.simple_response(prompt)
            except Exception as e:
                logger.exception("Failed to trigger speech: %s", e)

    async def _process_frame(self, frame) -> None:
        """Process a single video frame: detect signs, debounce, flush on silence."""
        pred = await asyncio.to_thread(self._predict_frame_sync, frame)
        now = time.monotonic()

        if pred:
            sign = pred["class"]
            confidence = pred["confidence"]
            self._last_detection_time = now

            # Debounce: skip if same sign within DEBOUNCE_SEC
            if sign == self._last_sign and (now - self._last_sign_time) < self.DEBOUNCE_SEC:
                return

            self._last_sign = sign
            self._last_sign_time = now
            self.sign_buffer.append(sign)
            logger.debug("Sign: %s (%.0f%%)", sign, confidence * 100)
            return

        # No detection — check for silence flush (lock prevents double-flush)
        silence_duration = now - self._last_detection_time
        if self.sign_buffer and silence_duration >= self.SILENCE_FLUSH_SEC:
            async with self._flush_lock:
                if not self.sign_buffer:
                    return
                signs_str = ", ".join(f"[{s}]" for s in self.sign_buffer)
                prompt = f"Signs detected: {signs_str}. Speak the sentence now."
                logger.info("Flushing buffer: %s", prompt)
                self.sign_buffer.clear()
                self._last_sign = None
            await self._trigger_speech(prompt)

    async def process_video(
        self,
        track,
        participant_id: Optional[str],
        shared_forwarder: Optional[VideoForwarder] = None,
    ) -> None:
        """Register frame handler with shared forwarder."""
        if self._forwarder:
            await self._forwarder.remove_frame_handler(self._process_frame)

        self._forwarder = shared_forwarder
        if self._forwarder:
            self._forwarder.add_frame_handler(
                self._process_frame,
                fps=float(self.fps),
                name="isl_processor",
            )

    async def stop_processing(self) -> None:
        """Remove frame handler when video tracks are removed."""
        if self._forwarder:
            await self._forwarder.remove_frame_handler(self._process_frame)
            self._forwarder = None

    async def close(self) -> None:
        """Clean up resources."""
        await self.stop_processing()
