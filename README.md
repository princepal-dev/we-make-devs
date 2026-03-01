# ISL Voice Backend

Indian Sign Language to Voice AI — Real-time sign-to-speech backend using Vision Agents, Roboflow, Gemini, and ElevenLabs.

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/) (or pip)

## Setup

```bash
# Install uv (recommended): curl -LsSf https://astral.sh/uv/install.sh | sh

# Create venv and install dependencies
uv sync

# Or with pip (Python 3.12+):
pip install "vision-agents[getstream,gemini,elevenlabs,deepgram]" roboflow python-dotenv stream-chat Pillow opencv-python

# Copy env template and fill keys
cp .env.example .env
# Edit .env with your API keys

# Optional: for free-tier deployment (e.g. Render)
# APP_URL=https://your-app.onrender.com
# LOG_LEVEL=INFO  # or DEBUG for sign detection logs
```

## Run

```bash
uv run main.py serve
```

Server starts at `http://localhost:8000`. Swagger docs: `http://localhost:8000/docs`.

## Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/sessions` | Start agent session |
| DELETE | `/sessions/{session_id}` | End session |
| GET | `/sessions/{session_id}` | Session status |
| POST | `/auth/token` | Get Stream WebRTC token |
| GET | `/keepalive` | Keep-alive (ping every 10 min on free tier) |
| GET | `/health` | Health check |
| GET | `/ready` | Readiness check |

## Examples

**Get Stream token (for mobile app):**
```bash
curl -X POST http://localhost:8000/auth/token \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test-user", "user_name": "Test User"}'
```

**Create session:**
```bash
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"call_type": "default", "call_id": "test-123"}'
```

**Health check:**
```bash
curl http://localhost:8000/health
```

**Keepalive (for external cron or self-ping):**
```bash
curl http://localhost:8000/keepalive
```
