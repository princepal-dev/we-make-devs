# ISL Voice Backend

Indian Sign Language to Voice AI — Real-time sign-to-speech backend using Vision Agents, Roboflow, Gemini, ElevenLabs, and Stream WebRTC.

**Mobile integration:** [RORK_PROMPT.md](./RORK_PROMPT.md) | [MOBILE_APP_INTEGRATION.md](./MOBILE_APP_INTEGRATION.md)

---

## Quick start

```bash
uv sync
cp .env.example .env
# Edit .env with API keys

uv run main.py serve
```

Server: `http://localhost:8000` · Docs: `http://localhost:8000/docs`

---

## API

**Base URL:** `https://we-make-devs.onrender.com`

**Rule:** All endpoints use the `/api` prefix. No user configuration needed.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/health` | Health check |
| GET | `/api/config` | Config (`stream_api_key`, `base_url`, `api_prefix`) |
| POST | `/api/auth/token` | Get Stream token (body: `user_id`, `user_name`) |
| GET | `/api/auth/token` | Get token (query: `user_id`, `user_name`) — for tokenProvider |
| POST | `/api/sessions` | Start agent (body: `call_type`, `call_id`) |
| DELETE | `/api/sessions/{id}` | End session |

**Note:** `/api/token` is rewritten to `/api/auth/token`.

---

## Examples

```bash
# Health
curl https://we-make-devs.onrender.com/api/health

# Config
curl https://we-make-devs.onrender.com/api/config

# Token (POST)
curl -X POST https://we-make-devs.onrender.com/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user-123", "user_name": "John"}'

# Token (GET, for tokenProvider)
curl "https://we-make-devs.onrender.com/api/auth/token?user_id=user-123&user_name=John"

# Start session
curl -X POST https://we-make-devs.onrender.com/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"call_type": "default", "call_id": "call-123"}'
```

---

## Setup

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/) or pip

```bash
uv sync

# Or pip
pip install "vision-agents[getstream,gemini,elevenlabs,deepgram]" roboflow python-dotenv stream-chat Pillow opencv-python
```

Copy `.env.example` to `.env` and fill in:

- `STREAM_API_KEY`, `STREAM_API_SECRET`
- `GOOGLE_API_KEY`, `ELEVENLABS_API_KEY`, `DEEPGRAM_API_KEY`
- `ROBOFLOW_API_KEY`, `ROBOFLOW_WORKSPACE`, `ROBOFLOW_PROJECT`
- `APP_URL` (optional, for keepalive self-ping on free tier)

---

## Docker

```bash
docker build -t isl-voice .
docker run -p 8000:8000 --env-file .env isl-voice
```

On Render: Runtime = Docker, use `render.yaml` or add env vars in the Dashboard.
