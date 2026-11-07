#!/usr/bin/env bash
# Start the Lyric Video Studio web app on this computer: http://localhost:8000
# Set ANTHROPIC_API_KEY first to let Claude direct the shot list (otherwise a plain draft is used).
set -euo pipefail
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Note: ANTHROPIC_API_KEY is not set, so the shot list will be a plain draft, not directed by Claude."
fi
echo "Lyric Video Studio: http://localhost:${PORT}"
( sleep 2; command -v open >/dev/null && open "http://localhost:${PORT}" || command -v xdg-open >/dev/null && xdg-open "http://localhost:${PORT}" ) >/dev/null 2>&1 &
exec python3 -m uvicorn app.server:app --host 127.0.0.1 --port "$PORT"
