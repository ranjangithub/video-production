# Lyrics video studio for Claude Code

Turns a song and a folder of photos and clips into a lyric video with designed cover art. The lyrics sit small and
low over the pictures, and each word brightens as it is sung. It works for Hindi, English and many other languages.

Lyrics, conceived and produced by Rajesh Ranjan.

**Read the story behind it:** [From Poem to Video Song](https://ranjangithub.github.io/video-production/), an architect's guide to where gen AI belongs and how Claude skills make it repeatable ([source](docs/index.html)).

**Watch:** [ओ बाबुल (Hindi)](https://www.youtube.com/watch?v=i_AczcfaoUA) · [Bridal Red (English)](https://youtu.be/Qefa8oZxpzU)

## What's in here

```
CLAUDE.md                          standing rules Claude reads in every session
.claude/
  settings.json                    what Claude may run without asking, what it must ask for, what is denied; the render hook
  hooks/check_render.sh            after every render: checks the MP4 has video + audio and matches the song's length
  agents/cover-designer.md         subagent: three cover options, checked at thumbnail size
  agents/timing-checker.md         subagent: reviews lyric timing and flags misplaced lines
  skills/lyric-video/
    SKILL.md                       the skill: /lyric-video SONG.mp3 MEDIA/
    reference/style_plan.md        the plan format and directing rules
    reference/timing.md            how lyric timing works, and what to check
    scripts/separate.py            isolate the vocals (Demucs, or Spleeter ONNX on CPU)
    scripts/align.py               time every line and word (faster-whisper, Parakeet, Omnilingual, or phrase detection)
    scripts/make_plan.py           draft a style plan from the timing and the media folder
    scripts/render.py              render stills or the video, in parallel across CPU cores
    scripts/cover.py               make cover art, and put it on the video as first frame + thumbnail
    scripts/check_output.py        validate a rendered MP4 (used by the hook)
    fonts/                         Tiro Devanagari Hindi and Lora, SIL Open Font License
examples/
  o_babul_plan.json                the directed Hindi plan (shots + word-timed lyrics)
  bridal_red_plan.json             the directed English plan
scripts/batch.sh                   every song in songs/ to a finished video, headless (claude -p)
scripts/web.sh                     the web app: upload an MP3, download an MP4
app/                               the web app's server, pipeline, Claude director and page
songs/  media/  work/  out/  models/
```

## Setup (once)

```bash
# 1. Claude Code
npm install -g @anthropic-ai/claude-code

# 2. Tools
brew install ffmpeg            # or: sudo apt install ffmpeg
python3 -m pip install -r requirements.txt
# optional, better quality where Hugging Face is reachable:
# python3 -m pip install demucs faster-whisper

# 3. The repo
cd lyric-video-studio
chmod +x .claude/hooks/check_render.sh scripts/batch.sh
git init && git add -A && git commit -m "Lyric video studio"
```

Models download on first use into `models/` (from the sherpa-onnx GitHub releases): Spleeter separation (about
20 MB), Parakeet for English (about 650 MB) and Omnilingual for Hindi and other languages (about 360 MB).

## Making a video

```bash
cp ~/Music/Bridal_Red.mp3 songs/
cp ~/Pictures/wedding/* media/
claude
```

Then, inside Claude Code:

1. **Plan first.** Press Shift+Tab to switch to plan mode, then ask: "Plan a lyric video for songs/Bridal_Red.mp3 with media/".
   Claude reads the lyrics and media and proposes the shot list. Approve it or ask for changes.
2. **Run the skill.** `/lyric-video songs/Bridal_Red.mp3 media/`. Claude separates the vocals, times the
   lyrics, drafts and directs the plan, and shows you stills.
3. **Check timing.** Ask "use the timing-checker on work/bridal-red/words.json" if any lines say ESTIMATED.
4. **Render.** Claude renders in the background. The hook checks the file; if it is broken, Claude sees the
   problem and fixes it before telling you.
5. **Covers.** "Have the cover-designer make three covers". Pick one, and Claude applies it.
6. **Commit.** "Commit the plan." Every approved version of `style_plan.json` is in git history.

To redo the two reference videos, put the songs in `songs/` as `O_Babul.mp3` and `Bridal_Red.mp3`, and the
media in `media/` with the names used in the examples (`autumn_tree.mp4`, `embrace_and_car.mp4`,
`bride_in_car.mp4`, `wedding_venue.mp4`, `father_at_window.jpg`, `snow_tree.jpg`, `sprout.jpg`,
`grandfather_and_baby.jpg`, `swing.jpg`, `icicles.jpg`, `leaf.gif`, `autumn_house.jpg`, `dew_leaf.jpg`). Then:

```bash
python3 .claude/skills/lyric-video/scripts/render.py examples/bridal_red_plan.json -o out/bridal-red.mp4
```

## The web app: upload an MP3, download an MP4

For when you want a browser instead of a chat. It runs on your own computer and uses the same skill scripts.

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # lets Claude direct the shot list; leave unset for a plain draft
scripts/web.sh                            # opens http://localhost:8000
```

1. **Upload** the song and the photos, clips and GIFs. Add a title, a subtitle and the credit for the cover. Paste
   the lyrics only if the MP3 does not carry them.
2. **Wait** while it separates the vocals, times every word and asks Claude to direct. Progress shows live.
3. **Review** six preview frames, the lyric timing (lines placed by estimate are marked) and Claude's shot list,
   with a reason for each picture. Fix the lyrics and re-time in seconds, or ask Claude for another take.
4. **Render**, then **pick one of three covers** Claude proposed: a person, a place and a texture.
5. **Download** the MP4 (cover on the first frame and as its thumbnail) and the cover image.

How the director works: the app sends Claude the timed lyrics and small previews of every photo and three frames of
every clip, and Claude answers through a fixed tool schema. Code then checks and repairs the answer: shots in order
and covering the whole song, each at least 3 s, clips never running out, zoom and focus in range. So the judgement is
Claude's and the precision is code's. Set `LYRIC_DIRECTOR_MODEL` to choose the model (default `claude-sonnet-5-5`).
Projects are kept in `work/web/` and never leave your computer except for those previews.

| Piece | File |
| --- | --- |
| Web server and API | `app/server.py` |
| Job pipeline (runs the skill's scripts, one job at a time) | `app/pipeline.py` |
| Claude director, with checking and repair | `app/director.py` |
| The page | `app/static/index.html` |

## Many songs at once

```bash
scripts/batch.sh                 # every song in songs/ without a finished video
scripts/batch.sh songs/new.mp3   # one song
```

Each song runs as its own non-interactive Claude Code session (`claude -p`), with the same skill, rules and
permissions. Logs go to `out/logs/`.

## Permissions

`.claude/settings.json` lets Claude run the skill's scripts, ffmpeg and ffprobe, and write in `work/` and `out/`
without asking. Installing packages, downloading with curl and pushing to git need your approval. Deleting
recursively and changing anything in `songs/` or `media/` are denied, so your originals are never touched.

## Notes

- Renders take about 30 s per minute of song on 2 CPU cores at 720p; more cores are faster (`--jobs N`).
- Only use photos and footage you have the right to publish.
