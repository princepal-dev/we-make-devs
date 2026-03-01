"""
ISL Voice Backend — Indian Sign Language to Voice AI.
Vision Agents Runner + custom /auth/token for Stream WebRTC.
"""

import asyncio
import logging
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# Load env FIRST before any plugin imports
load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from vision_agents.core import Agent, AgentLauncher, Runner, User
from vision_agents.plugins import deepgram, elevenlabs, gemini, getstream

from agent.isl_processor import ISLProcessor

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)

# Default voice from .env.example (Rachel)
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Cache instructions in memory (avoid disk read per session)
_INSTRUCTIONS_CACHE: str | None = None
_STREAM_CHAT_CLIENT: object | None = None


def _load_instructions() -> str:
    """Load agent instructions. Cached in memory for reuse across sessions."""
    global _INSTRUCTIONS_CACHE
    if _INSTRUCTIONS_CACHE is not None:
        return _INSTRUCTIONS_CACHE
    instructions_path = Path(__file__).parent / "agent" / "instructions.md"
    if not instructions_path.exists():
        logger.error("Missing instructions file: %s", instructions_path)
        sys.exit(1)
    try:
        _INSTRUCTIONS_CACHE = instructions_path.read_text(encoding="utf-8")
        return _INSTRUCTIONS_CACHE
    except OSError as e:
        logger.error("Failed to read instructions: %s", e)
        sys.exit(1)


def _validate_env() -> None:
    """Validate required env vars at startup. Log warnings for optional ones."""
    required = {
        "STREAM_API_KEY": "Stream WebRTC",
        "STREAM_API_SECRET": "Stream WebRTC",
        "GOOGLE_API_KEY": "Gemini LLM",
        "ELEVENLABS_API_KEY": "ElevenLabs TTS",
        "DEEPGRAM_API_KEY": "Deepgram STT",
        "ROBOFLOW_API_KEY": "Roboflow ISL detection",
        "ROBOFLOW_WORKSPACE": "Roboflow workspace",
        "ROBOFLOW_PROJECT": "Roboflow project",
    }
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.warning(
            "Missing env vars (agent may fail at runtime): %s",
            ", ".join(missing),
        )


async def create_agent(**kwargs) -> Agent:
    """Factory: create ISL Voice agent with Roboflow processor, Gemini, ElevenLabs, Deepgram."""
    instructions = _load_instructions()
    voice_id = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID

    agent = Agent(
        edge=getstream.Edge(),
        agent_user=User(name="ISL Voice", id="isl-voice-agent"),
        instructions=instructions,
        processors=[ISLProcessor(fps=5)],
        llm=gemini.Realtime(fps=3),
        tts=elevenlabs.TTS(model_id="eleven_turbo_v2", voice_id=voice_id),
        stt=deepgram.STT(model="nova-3", language="en-IN"),
    )
    return agent


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    """Join the call, wait for participant, run until finish."""
    call = await agent.create_call(call_type, call_id)

    async with agent.join(call):
        await agent.finish()


def _create_runner() -> Runner:
    launcher = AgentLauncher(
        create_agent=create_agent,
        join_call=join_call,
        max_concurrent_sessions=10,
        max_sessions_per_call=1,
    )
    return Runner(launcher)


def _add_custom_routes(runner: Runner) -> None:
    """Add custom /auth/token endpoint for Stream WebRTC auth."""

    from fastapi import HTTPException
    from pydantic import BaseModel

    class TokenRequest(BaseModel):
        user_id: str
        user_name: str = ""

    @runner.fast_api.post("/auth/token")
    async def auth_token(body: TokenRequest):
        """Generate Stream token for mobile app WebRTC auth."""
        user_id = (body.user_id or "").strip()
        user_name = (body.user_name or "").strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")

        api_key = os.getenv("STREAM_API_KEY")
        api_secret = os.getenv("STREAM_API_SECRET")
        if not api_key or not api_secret:
            raise HTTPException(
                status_code=500,
                detail="Stream credentials not configured",
            )

        try:
            global _STREAM_CHAT_CLIENT
            if _STREAM_CHAT_CLIENT is None:
                from stream_chat import StreamChat

                _STREAM_CHAT_CLIENT = StreamChat(api_key=api_key, api_secret=api_secret)
            token = _STREAM_CHAT_CLIENT.create_token(user_id)
            return {
                "token": token,
                "user_id": user_id,
                "user_name": user_name or user_id,
            }
        except Exception as e:
            logger.exception("Token creation failed: %s", e)
            # Don't leak internal details; return generic message
            raise HTTPException(
                status_code=500,
                detail="Failed to create token. Check server logs.",
            )


def _add_keepalive(runner: Runner) -> None:
    """Add /keepalive endpoint and background self-ping for free-tier deployment."""

    @runner.fast_api.get("/keepalive")
    async def keepalive():
        """Health-check endpoint. Ping every 10 min to prevent free-tier spin-down."""
        return {"status": "ok", "message": "keepalive"}

    app_url = os.getenv("APP_URL", "").rstrip("/")

    def _ping_sync(base_url: str) -> None:
        try:
            req = urllib.request.Request(f"{base_url}/keepalive")
            with urllib.request.urlopen(req, timeout=10) as _:
                logger.debug("Keepalive self-ping OK")
        except Exception as e:
            logger.warning("Keepalive self-ping failed: %s", e)

    async def _keepalive_loop() -> None:
        """Background loop: ping self every 10 minutes to prevent free-tier spin-down."""
        while True:
            await asyncio.sleep(600)  # 10 minutes
            await asyncio.to_thread(_ping_sync, app_url)

    @runner.fast_api.on_event("startup")
    async def _start_keepalive_task():
        if app_url:
            asyncio.create_task(_keepalive_loop())
            logger.info("Keepalive: self-pinging %s/keepalive every 10 min", app_url)
        else:
            logger.info(
                "Keepalive: Set APP_URL in .env to enable self-ping (e.g. https://your-app.onrender.com)"
            )


def _print_startup_banner() -> None:
    print("""
✋ ISL Voice Backend starting...
   Endpoints:
   ├── POST   /sessions       → Start agent session
   ├── DELETE /sessions/{id}  → End session
   ├── GET    /sessions/{id}  → Session status
   ├── POST   /auth/token     → Get Stream token
   ├── GET    /keepalive      → Keep-alive (ping every 10 min on free tier)
   └── GET    /health         → Health check

   Docs: http://localhost:8000/docs
""")


if __name__ == "__main__":
    _validate_env()
    _load_instructions()  # Fail fast if instructions file missing
    runner = _create_runner()
    _add_custom_routes(runner)
    _add_keepalive(runner)

    # GZip compression for API responses (saves bandwidth)
    runner.fast_api.add_middleware(GZipMiddleware, minimum_size=500)

    # CORS for mobile app
    runner.fast_api.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _print_startup_banner()
    runner.cli()
