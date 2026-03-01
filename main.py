"""
ISL Voice Backend — Indian Sign Language to Voice AI.
Vision Agents + Stream WebRTC. Mobile app uses /api prefix for all endpoints.
"""

import asyncio
import logging
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from vision_agents.core import Agent, AgentLauncher, Runner, User
from vision_agents.plugins import deepgram, elevenlabs, gemini, getstream

from agent.isl_processor import ISLProcessor

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

BASE_URL = os.getenv("APP_URL", "https://we-make-devs.onrender.com").rstrip("/")
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
HEALTH_RESPONSE = {"status": "ok"}
KEEPALIVE_RESPONSE = {"status": "ok", "message": "keepalive"}

_INSTRUCTIONS_CACHE: str | None = None
_STREAM_CHAT_CLIENT: object | None = None
_CONFIG_CACHE: dict | None = None


def _load_instructions() -> str:
    global _INSTRUCTIONS_CACHE
    if _INSTRUCTIONS_CACHE is not None:
        return _INSTRUCTIONS_CACHE
    path = Path(__file__).parent / "agent" / "instructions.md"
    if not path.exists():
        logger.error("Missing instructions: %s", path)
        sys.exit(1)
    _INSTRUCTIONS_CACHE = path.read_text(encoding="utf-8")
    return _INSTRUCTIONS_CACHE


def _validate_env() -> None:
    required = [
        "STREAM_API_KEY", "STREAM_API_SECRET",
        "GOOGLE_API_KEY", "ELEVENLABS_API_KEY", "DEEPGRAM_API_KEY",
        "ROBOFLOW_API_KEY", "ROBOFLOW_WORKSPACE", "ROBOFLOW_PROJECT",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.warning("Missing env: %s", ", ".join(missing))


async def create_agent(**kwargs) -> Agent:
    voice_id = os.getenv("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID
    return Agent(
        edge=getstream.Edge(),
        agent_user=User(name="ISL Voice", id="isl-voice-agent"),
        instructions=_load_instructions(),
        processors=[ISLProcessor(fps=5)],
        llm=gemini.Realtime(fps=3),
        tts=elevenlabs.TTS(model_id="eleven_turbo_v2", voice_id=voice_id),
        stt=deepgram.STT(model="nova-3", language="en-IN"),
    )


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
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


def _get_config() -> dict:
    """Cached config for /config endpoint (env unchanged at runtime)."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = {
            "stream_api_key": os.getenv("STREAM_API_KEY", ""),
            "base_url": BASE_URL,
            "api_prefix": "/api",
        }
    return _CONFIG_CACHE


def _add_routes(runner: Runner) -> None:
    class TokenRequest(BaseModel):
        user_id: str
        user_name: str = ""

    index_path = Path(__file__).parent / "static" / "index.html"

    async def _auth_token(req: TokenRequest) -> dict:
        user_id = (req.user_id or "").strip()
        if not user_id:
            raise HTTPException(status_code=400, detail="user_id required")
        api_key, api_secret = os.getenv("STREAM_API_KEY"), os.getenv("STREAM_API_SECRET")
        if not api_key or not api_secret:
            raise HTTPException(status_code=500, detail="Stream credentials not configured")
        try:
            global _STREAM_CHAT_CLIENT
            if _STREAM_CHAT_CLIENT is None:
                from stream_chat import StreamChat
                _STREAM_CHAT_CLIENT = StreamChat(api_key=api_key, api_secret=api_secret)
            token = _STREAM_CHAT_CLIENT.create_token(user_id)
            name = (req.user_name or "").strip() or user_id
            return {"token": token, "user_id": user_id, "user_name": name}
        except Exception as e:
            logger.exception("Token creation failed: %s", e)
            raise HTTPException(status_code=500, detail="Failed to create token")

    @runner.fast_api.get("/", response_class=HTMLResponse)
    async def home():
        if index_path.exists():
            return FileResponse(index_path, media_type="text/html")
        return HTMLResponse("<h1>ISL Voice</h1><p><a href='/docs'>API Docs</a></p>")

    @runner.fast_api.post("/auth/token")
    async def auth_post(body: TokenRequest):
        return await _auth_token(body)

    @runner.fast_api.get("/auth/token")
    async def auth_get(user_id: str = "", user_name: str = ""):
        return await _auth_token(TokenRequest(user_id=user_id, user_name=user_name))

    @runner.fast_api.get("/config")
    async def config():
        return _get_config()

    @runner.fast_api.get("/health")
    async def health():
        return HEALTH_RESPONSE

    @runner.fast_api.get("/keepalive")
    async def keepalive():
        return KEEPALIVE_RESPONSE


def _add_keepalive_loop(runner: Runner) -> None:
    @runner.fast_api.on_event("startup")
    async def _start():
        if not os.getenv("APP_URL"):
            return
        url = f"{BASE_URL}/keepalive"
        async def _loop():
            while True:
                await asyncio.sleep(600)
                try:
                    await asyncio.to_thread(
                        lambda: urllib.request.urlopen(urllib.request.Request(url), timeout=10)
                    )
                except Exception as e:
                    logger.warning("Keepalive failed: %s", e)
        asyncio.create_task(_loop())
        logger.info("Keepalive: %s every 10 min", url)


def _add_middleware(runner: Runner) -> None:
    @runner.fast_api.middleware("http")
    async def rewrite_api(request, call_next):
        p = request.scope.get("path", "")
        if p.startswith("/api"):
            p = p[4:] or "/"
        if p == "/token":
            p = "/auth/token"  # /api/token -> /auth/token
        request.scope["path"] = p
        return await call_next(request)

    runner.fast_api.add_middleware(GZipMiddleware, minimum_size=500)
    runner.fast_api.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )


if __name__ == "__main__":
    _validate_env()
    _load_instructions()

    runner = _create_runner()
    _add_routes(runner)
    _add_keepalive_loop(runner)
    _add_middleware(runner)

    print("\n✋ ISL Voice — BASE_URL/api/health | /api/config | /api/auth/token | /api/sessions\n")
    runner.cli()
