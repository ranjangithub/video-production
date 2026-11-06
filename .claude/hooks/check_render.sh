#!/usr/bin/env bash
# PostToolUse hook: after any Bash call that rendered an MP4 (render.py or cover.py apply), check the file.
# Exit 2 sends the problem back to Claude so it fixes it before telling the user the video is ready.
set -u
input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)

case "$cmd" in
  *render.py*|*"cover.py apply"*) ;;
  *) exit 0 ;;
esac
case "$cmd" in *--stills*) exit 0 ;; esac

out=$(printf '%s' "$cmd" | python3 -c '
import shlex, sys
a = shlex.split(sys.stdin.read())
for i, x in enumerate(a):
    if x in ("-o", "--out") and i + 1 < len(a) and a[i + 1].endswith(".mp4"):
        print(a[i + 1]); break')
[ -z "$out" ] && exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -f "$out" ] || { echo "render hook: $out was not written" >&2; exit 2; }

checker=.claude/skills/lyric-video/scripts/check_output.py
args=("$out")
# a full render (no --range) must match the song's length
if [[ "$cmd" != *--range* ]]; then
  plan=$(printf '%s' "$cmd" | python3 -c '
import shlex, sys
for x in shlex.split(sys.stdin.read()):
    if x.endswith(".json"): print(x); break')
  if [ -n "$plan" ] && [ -f "$plan" ]; then
    song=$(python3 -c 'import json,os,sys; p=sys.argv[1]; a=json.load(open(p))["audio"]; print(a if os.path.isabs(a) else os.path.join(os.path.dirname(p), a))' "$plan")
    [ -f "$song" ] && args+=(--audio "$song")
  fi
fi
if ! msg=$(python3 "$checker" "${args[@]}" 2>&1); then
  echo "render hook: $msg" >&2
  exit 2
fi
exit 0
