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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from vision_agents.core import Agent, AgentLauncher, Runner, User
from vision_agents.plugins import gemini, getstream

from agent.isl_processor import ISLProcessor

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
)
logger = logging.getLogger(__name__)

BASE_URL = os.getenv("APP_URL", "https://we-make-devs.onrender.com").rstrip("/")
HEALTH_RESPONSE = {"status": "ok", "message": "ISL Voice API"}
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
        "GOOGLE_API_KEY",
        "ROBOFLOW_API_KEY", "ROBOFLOW_WORKSPACE", "ROBOFLOW_PROJECT",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.warning("Missing env: %s", ", ".join(missing))


async def create_agent(**kwargs) -> Agent:
    return Agent(
        edge=getstream.Edge(),
        agent_user=User(name="ISL Voice", id="isl-voice-agent"),
        instructions=_load_instructions(),
        processors=[ISLProcessor(fps=5)],
        llm=gemini.Realtime(fps=3),  # Handles STT/TTS natively; no separate Deepgram/ElevenLabs
    )


# Delay (seconds) before agent joins — gives mobile app time to join the call first.
# We poll Stream for participants; proceed as soon as one joins or after this timeout.
PARTICIPANT_JOIN_DELAY = int(os.getenv("PARTICIPANT_JOIN_DELAY", "30"))
PARTICIPANT_POLL_INTERVAL = int(os.getenv("PARTICIPANT_POLL_INTERVAL", "2"))
AGENT_USER_ID = "isl-voice-agent"


# Video API uses video.stream-io-api.com; chat uses chat.stream-io-api.com
STREAM_VIDEO_BASE_URL = "https://video.stream-io-api.com/"


async def _has_non_agent_participant(call_type: str, call_id: str) -> bool:
    """Check if the call has at least one participant who is not the agent."""
    try:
        from getstream import Stream
    except ImportError:
        return False
    api_key = os.getenv("STREAM_API_KEY")
    api_secret = os.getenv("STREAM_API_SECRET")
    if not api_key or not api_secret:
        return False
    try:
        client = Stream(
            api_key=api_key,
            api_secret=api_secret,
            base_url=STREAM_VIDEO_BASE_URL,
        )
        resp = await asyncio.to_thread(
            client.video.query_call_members, id=call_id, type=call_type
        )
        members = getattr(resp, "data", resp)
        if hasattr(members, "members"):
            members = members.members
        if not members:
            return False
        for m in members:
            uid = getattr(m, "user_id", None)
            if not uid and hasattr(m, "user"):
                u = getattr(m, "user", None)
                uid = getattr(u, "id", None) if u else None
            if uid and str(uid) != AGENT_USER_ID:
                return True
        return False
    except Exception as e:
        err = str(e).lower()
        # Call doesn't exist yet (404) or not found = no participants
        if "find call" in err or "404" in err or "not found" in err:
            return False
        logger.debug("Participant poll error: %s", e)
        return False


async def _wait_for_participant(call_type: str, call_id: str, max_wait: int) -> bool:
    """Poll for a non-agent participant; return True if one joins within max_wait seconds."""
    elapsed = 0
    while elapsed < max_wait:
        if await _has_non_agent_participant(call_type, call_id):
            return True
        await asyncio.sleep(min(PARTICIPANT_POLL_INTERVAL, max_wait - elapsed))
        elapsed += PARTICIPANT_POLL_INTERVAL
    return False


async def join_call(agent: Agent, call_type: str, call_id: str, **kwargs) -> None:
    await agent.create_user()  # Required: upsert agent user in Stream before create_call
    if PARTICIPANT_JOIN_DELAY > 0:
        logger.info(
            "Polling for participant (max %ds, interval %ds)...",
            PARTICIPANT_JOIN_DELAY,
            PARTICIPANT_POLL_INTERVAL,
        )
        found = await _wait_for_participant(call_type, call_id, PARTICIPANT_JOIN_DELAY)
        if found:
            logger.info("Participant detected, agent joining.")
        else:
            logger.info("No participant after %ds, agent joining anyway.", PARTICIPANT_JOIN_DELAY)
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

    @runner.fast_api.get("/api")
    async def api_root():
        """Return JSON for BASE_URL + /api (connection test)."""
        return {"status": "ok", "message": "ISL Voice API"}

    @runner.fast_api.get("/api/health")
    async def api_health():
        """Explicit /api/health — avoids Runner's /health which may return different format."""
        return HEALTH_RESPONSE

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
        if p in ("/api", "/api/health"):
            pass
        elif p.startswith("/api/"):
            p = "/" + p[5:]
            if p == "/token":
                p = "/auth/token"
        request.scope["path"] = p
        response = await call_next(request)
        # Treat session-not-found 404 as 200 (session ended or never existed)
        if response.status_code == 404 and "/sessions" in p:
            return JSONResponse(
                status_code=200,
                content={"status": "ended", "message": "Session not found or already ended"},
            )
        return response

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
