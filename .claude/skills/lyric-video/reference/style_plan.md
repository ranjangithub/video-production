# style_plan.json

`make_plan.py` writes a working draft. Edit it before rendering: this is where the video gets its story.

## Top level

| Field | Meaning |
| --- | --- |
| `video.width`, `video.height`, `video.fps` | 1280×720 at 30 fps by default; `--hd` gives 1920×1080 (about twice as slow) |
| `video.crossfade` | seconds of dissolve between shots (default 1.0) |
| `video.lyric_y` | vertical centre of the lyric line, 0–1 (default 0.875: the bottom eighth) |
| `video.lyric_size` | lyric font size in pixels at 720p (default 46) |
| `video.bottom_shade` | how much the bottom of the frame is darkened behind the lyrics, 0–1 (default 0.42) |
| `video.fonts` | optional overrides: `{"dev": path, "dev_italic": path, "latin": path, "latin_italic": path}` |
| `audio`, `duration` | the song; paths may be relative to the plan file |
| `title` | `{text, start, end}` shown large during the intro, or `null` |
| `shots` | the pictures, in time order (below) |
| `chunks` | the lyric lines, in time order (below) |

## Shots

```json
{"src": "../../media/hug.mp4", "start": 38.95, "end": 48.8, "clip_in": 0.0, "speed": 1.0}
{"src": "../../media/window.jpg", "start": 103.3, "end": 118.9, "zoom": [1.02, 1.2], "f0": [0.5, 0.5], "f1": [0.66, 0.42]}
{"src": "../../media/leaf.gif", "start": 70.4, "end": 81.9, "speed": 0.55, "pingpong": true}
{"src": "../../media/house.jpg", "start": 226.0, "end": 241.5, "zoom": [1.0, 1.12], "fade_out": 4.0}
```

- Shots should touch end to start; each dissolves into the next over `video.crossfade` seconds.
- **Photos** get a slow push or pull: `zoom` from → to, while the focus point moves from `f0` to `f1`
  (x, y of the source image, 0–1). Zoom in on a face by putting `f1` on it; a `zoom` above 1.3 makes a close crop.
- **Clips** play muted from `clip_in` at `speed`. Use `speed` below 1 to stretch a short clip over a long line
  (0.4–0.6 looks like deliberate slow motion; below 0.4 starts to stutter). Use several entries of one clip with
  different `clip_in` to use different moments of it.
- To land a clip's moment on a word: `start = word_time - (moment_in_clip - clip_in) / speed`.
- **GIFs** loop; `pingpong: true` plays them forward and back so the loop has no jump.
- `fade_out` on the last shot fades the picture to black over that many seconds.

## Chunks

```json
{"start": 17.64, "end": 21.4, "text": "शाख़ों पे धानी चुनरिया", "kind": "line",
 "words": [{"text": "शाख़ों", "start": 17.64}, {"text": "पे", "start": 18.6}, {"text": "धानी", "start": 19.0}, {"text": "चुनरिया", "start": 20.12}]}
{"start": 218.4, "end": 224.6, "text": "home again… home again…", "kind": "echo"}
```

- `kind`: `line` (each word brightens when sung), `echo` (smaller, italic, softer, for backing echoes).
- `words[].start` drives the highlight. Missing word times are spread across the line by word length.
- `estimated: true` marks a line that was placed from the vocal track, not heard by the model. Check those.
- Optional per chunk: `size` (pixels), `y` (0–1, e.g. 0.12 to put a line at the top over a low face),
  `color_bgr` (default warm white `[235, 243, 255]`).
- Lines never overlap on screen: when the next line starts soon, the renderer shortens the fade-out automatically.
  If two lines still collide, move the earlier `end` back.

## Rules of thumb

1. One picture per idea in the lyric. A line about leaving gets the car; a line about waiting gets the window.
2. Seasons and story should move forward: autumn farewell → winter waiting → spring return.
3. Hold a strong photo for 10–15 s; change clips faster (5–10 s).
4. Faces in the upper two thirds. If a face is low, set `y` on those chunks to put the lyric at the top.
5. Every repeat of the chorus can return to the same picture family (the same tree, the same house), so the
   chorus feels like coming home.
6. Instrumental breaks: let one picture breathe, or use a GIF or slow clip. No lyric needed.
