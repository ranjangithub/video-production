# Lyric video studio

This repo turns songs written by Rajesh Ranjan into lyric videos, using the `lyric-video` skill in
`.claude/skills/lyric-video/`. Start with `/lyric-video songs/SONG.mp3 media/`.

## Folders

- `songs/` — input MP3s (Suno files carry the lyrics in a tag)
- `media/` — the user's photos, clips and GIFs
- `work/<song-slug>/` — vocals, `words.json`, `style_plan.json`, stills. Commit the plan; the rest is ignored
- `out/` — finished videos and covers (ignored by git)
- `models/` — downloaded speech and separation models (ignored by git)
- `app/` — the local web app (upload MP3 → download MP4); `scripts/web.sh` starts it. It calls the same skill scripts, so change behaviour in the scripts, not in the app
- `work/web/` — the web app's projects (ignored by git)
- `examples/` — the directed plans for "O Babul" and "Bridal Red", as references for style

## Standing rules

- Lyrics only from the user or from the song file itself. Never look up or invent lyrics.
- Never generate a likeness of a real person. Use only the photos and clips in `media/`.
- Lyrics stay small and low (bottom eighth of the frame) and must never cover faces.
- Fonts: Tiro Devanagari Hindi for Devanagari, Lora for Latin script (both in the skill's `fonts/`).
- Credit on covers: "LYRICS, CONCEIVED & PRODUCED BY" / "Rajesh Ranjan".
- Default output: 1280×720, 30 fps, H.264 + AAC, cover as first frame and embedded thumbnail.

## Working style

- Plan first for a new song: propose the shot list (which picture on which line, and why), then wait for approval.
- Check stills before every full render. Render in the background; the hook validates each MP4.
- Tell the user which lyric lines were placed by estimate rather than heard.
- After the user approves a version, commit `work/<slug>/style_plan.json` with a short message ("bridal-red: tree cover, lyrics lower").
