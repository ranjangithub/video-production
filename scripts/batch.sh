#!/usr/bin/env bash
# Turn every song in songs/ into a lyric video without a chat, using Claude Code's non-interactive mode.
# Each song gets its own run; logs go to out/logs/. Permissions come from .claude/settings.json.
#
#   scripts/batch.sh              # all songs that have no video yet
#   scripts/batch.sh songs/x.mp3  # just one
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p out/logs

songs=("$@")
[ ${#songs[@]} -eq 0 ] && songs=(songs/*.mp3)

for song in "${songs[@]}"; do
  slug=$(basename "$song" .mp3 | tr '[:upper:] ' '[:lower:]-')
  if [ -f "out/${slug}_final.mp4" ]; then
    echo "skip $song (out/${slug}_final.mp4 exists)"; continue
  fi
  echo "== $song"
  claude -p "/lyric-video $song media/

This is an unattended run: do not stop for approval. Direct the plan yourself following the skill and
CLAUDE.md, check stills, render the full video, make the three covers with the cover-designer subagent, apply
the place cover, and write out/${slug}_final.mp4. At the end, list any lyric lines that were placed by
estimate." > "out/logs/${slug}.log" 2>&1 || echo "   failed, see out/logs/${slug}.log"
  echo "   -> out/${slug}_final.mp4"
done
