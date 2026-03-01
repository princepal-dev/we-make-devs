# ISL Voice Backend — Docker image for Render (includes FFmpeg for PyAV)
FROM python:3.12-slim-bookworm

# FFmpeg + dev libs required by PyAV (vision-agents dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libavformat-dev \
    libavcodec-dev \
    libavdevice-dev \
    libavutil-dev \
    libavfilter-dev \
    libswscale-dev \
    libswresample-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY agent/ agent/
COPY main.py ./
COPY static/ static/

RUN pip install --no-cache-dir uv && uv pip install --system -e .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
# Render provides PORT; default 8000 for local
ENV PORT=8000

CMD ["sh", "-c", "python main.py serve --host 0.0.0.0 --port ${PORT}"]
