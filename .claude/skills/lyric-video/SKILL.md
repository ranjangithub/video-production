---
name: lyric-video
description: Make a lyric video (MP4) from a song and the user's photos and clips. Lyrics sit small and low over the pictures, each word brightening as it is sung, with designed cover art. Use when the user wants a lyric video, animated lyrics or a song video, in Hindi, English or any language.
argument-hint: "[song.mp3] [media-folder]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(ffmpeg *) Bash(ffprobe *)
---

# Lyric video

Song: `$0` (default: the newest file in `songs/`). Media: `$1` (default: `media/`).

The scripts do the mechanical work. **You are the director**: you decide which picture goes on which line, and
you check the frames before rendering. Work in `work/<song-slug>/`; final files go in `out/`.

## 1. Lyrics and timing

```bash
ffprobe -v error -show_entries format_tags -of default=nw=1 SONG.mp3       # Suno puts the lyrics in a tag
python3 ${CLAUDE_SKILL_DIR}/scripts/separate.py SONG.mp3 -o work/SLUG/vocals.wav
python3 ${CLAUDE_SKILL_DIR}/scripts/align.py work/SLUG/vocals.wav --audio SONG.mp3 -o work/SLUG/words.json
```

- Only use lyrics the user gives you or that ship inside their file.
- For Hindi, add `--split-commas` so long lines show as half-lines.
- `align.py` prints every line. Lines marked `ESTIMATED` were placed from the vocal track, not heard by the
  model. Tell the user which ones, and ask the **timing-checker** subagent to review the file.
- Details and backends: `reference/timing.md`.

## 2. Draft the plan

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/make_plan.py work/SLUG/words.json --media MEDIA -o work/SLUG/style_plan.json --title "TITLE"
```

## 3. Direct it

The draft puts media in filename order. Look at every photo and at frames from every clip
(`ffmpeg -ss 2 -i clip.mp4 -frames:v 1 work/SLUG/peek.jpg`), then edit `style_plan.json`
(format: `reference/style_plan.md`):

- Put each picture on the line that is about it. Follow the song's story and seasons.
- Never open on a person. Open on a place or texture, then bring people in.
- Clips: pick `clip_in` and `speed` so the key moment (an embrace, a car leaving) lands on its line.
- Keep faces clear of the bottom fifth, where the lyrics sit. Move `f0`/`f1` (focus) if a face is low.
- Vary the order; reuse a picture only with a different crop or part of a clip.

Check frames before a full render:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py work/SLUG/style_plan.json --stills 20.5,61,140 -o work/SLUG/stills
```

Look at the stills. Fix overlapping lines, unreadable text over white or busy areas, and awkward crops.

## 4. Render

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py work/SLUG/style_plan.json --range 80 100 -o work/SLUG/preview.mp4
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py work/SLUG/style_plan.json -o out/SLUG.mp4
```

Renders run in parallel across all CPU cores. Run the full render in the background. The project's hook
checks every rendered MP4 (streams, length against the song) and reports a problem straight back to you.

## 5. Cover

Hand this to the **cover-designer** subagent, or run it yourself:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/cover.py make -o out/SLUG_cover.jpg --bg MEDIA/tree.jpg --title "TITLE" \
  --tag "SUBTITLE" --credit "NAME" --layout center
python3 ${CLAUDE_SKILL_DIR}/scripts/cover.py apply out/SLUG.mp4 out/SLUG_cover.jpg -o out/SLUG_final.mp4
```

Make three options (a person, a place, a texture), show them, and apply the one the user picks.

## Rules

- Never generate a likeness of a real person; work only with the photos and clips the user supplies.
- If the video is going public, remind the user to use only footage and photos they may publish.
- After each render, show frames and ask what to change. Their taste decides.
- Commit `style_plan.json` after each round the user approves (`git add work/SLUG/style_plan.json`).
