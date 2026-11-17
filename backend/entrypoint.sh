#!/bin/sh
set -e

# Optional: pass a YouTube cookies.txt as a base64 secret (helps when YouTube blocks datacenter IPs).
if [ -n "$YTDLP_COOKIES_B64" ]; then
  echo "$YTDLP_COOKIES_B64" | base64 -d > /tmp/cookies.txt
  export YTDLP_COOKIES=/tmp/cookies.txt
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-7860}"
