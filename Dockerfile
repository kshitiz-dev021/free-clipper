# FreeClipper backend: runs locally with Docker or on Hugging Face Spaces (Docker SDK, port 7860).
FROM python:3.11-slim

ARG WHISPER_MODEL=tiny
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    DATA_DIR=/tmp/freeclipper \
    HF_HOME=/home/user/.cache/huggingface \
    WHISPER_MODEL=${WHISPER_MODEL}

# ffmpeg + bold caption fonts (Montserrat, Liberation Sans fallback)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-montserrat fonts-liberation fontconfig ca-certificates curl \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# JavaScript runtime used by yt-dlp to solve YouTube's player challenges
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Hugging Face Spaces runs containers as uid 1000
RUN useradd -m -u 1000 user && \
    mkdir -p /tmp/freeclipper/jobs && \
    chown -R user:user /tmp/freeclipper
USER user
ENV PATH="/home/user/.local/bin:${PATH}"
WORKDIR /home/user/app

COPY --chown=user backend/requirements.txt .
RUN pip install --user -r requirements.txt

# Pre-download the local Whisper model so the offline fallback works instantly
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')" \
    || echo "Whisper model prefetch skipped; it will download on first use"

COPY --chown=user backend/ .

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fs "http://localhost:${PORT}/api/health" || exit 1

CMD ["./entrypoint.sh"]
