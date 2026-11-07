"""The director: decides which picture goes on which lyric line, and proposes three covers.

Uses Claude through the Anthropic API when ANTHROPIC_API_KEY is set. The model sees the timed lyrics and
small previews of every photo and clip, and answers through a tool call with a fixed schema. Its answer is
then checked and repaired in code (times, ranges, coverage), because the plan must be exact even when the
judgement is the model's. Without a key, or if the call fails, a plain draft is used instead.
"""
import base64, io, json, os, subprocess, tempfile
from PIL import Image

MODEL = os.environ.get("LYRIC_DIRECTOR_MODEL", "claude-sonnet-5-5")
MOTION = (".mp4", ".mov", ".m4v", ".webm", ".mkv")

RULES = """You are directing a lyric video. The lyrics sit small at the bottom of the frame; your job is the pictures.

Rules:
- Put each picture on the lyric line that is about it. Follow the song's story and seasons forward.
- Never open on a person. Open on a place or a texture, then bring people in.
- For clips, choose clip_in and speed so the key moment (an embrace, a car leaving) lands on its line.
  speed 0.4-1.0 (below 0.4 stutters). A clip shown for longer than (its length - clip_in) / speed will freeze.
- Photos get a slow push or pull: zoom_from -> zoom_to between 1.0 and 1.5, focus_from -> focus_to as x,y in 0..1
  of the source. Put focus_to on a face to push in on it. Keep faces in the upper two thirds.
- Hold a strong photo 10-15 s; clips 5-10 s. Instrumental breaks can hold one picture or a slow clip.
- Use every media item at least once if it fits the story. Reuse only with a different crop or a different part
  of a clip. Vary the order.
- Shots must cover the whole song from 0 to the end, in order, each at least 3 s long.
- Covers: propose exactly three: one with people (an emotional moment), one place (with open sky or space for the
  title), one texture or detail. Layout "center" needs open space at the top; "right"/"left" put the text on that
  side, so the people should be on the other side (use focus x to push them there; zoom 1.0-1.5)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "shots": {"type": "array", "items": {"type": "object", "properties": {
            "media": {"type": "integer", "description": "media id"},
            "start": {"type": "number"}, "end": {"type": "number"},
            "clip_in": {"type": "number"}, "speed": {"type": "number"},
            "zoom_from": {"type": "number"}, "zoom_to": {"type": "number"},
            "focus_from": {"type": "array", "items": {"type": "number"}},
            "focus_to": {"type": "array", "items": {"type": "number"}},
            "why": {"type": "string", "description": "one short line: which lyric this picture tells"}},
            "required": ["media", "start", "end", "why"]}},
        "covers": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["person", "place", "texture"]},
            "media": {"type": "integer"},
            "time": {"type": "number", "description": "for clips: the second to take the still from"},
            "layout": {"type": "string", "enum": ["center", "right", "left"]},
            "focus": {"type": "array", "items": {"type": "number"}, "description": "[x, y, zoom]"},
            "why": {"type": "string"}},
            "required": ["kind", "media", "layout", "why"]}},
        "notes": {"type": "string", "description": "two or three sentences on the story you built"},
    },
    "required": ["shots", "covers"],
}


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try: return float(out)
    except ValueError: return 0.0


def describe_media(paths):
    out = []
    for i, p in enumerate(paths):
        low = p.lower()
        kind = "clip" if low.endswith(MOTION) else "gif" if low.endswith(".gif") else "photo"
        item = {"id": i, "file": os.path.basename(p), "kind": kind, "path": p}
        if kind == "clip":
            item["duration"] = round(probe_duration(p), 2)
        elif kind == "photo":
            with Image.open(p) as im:
                item["size"] = list(im.size)
        out.append(item)
    return out


def _jpeg_b64(img, side=512):
    img = img.convert("RGB"); img.thumbnail((side, side))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode()


def previews(item):
    """[(caption, base64 jpeg)] for one media item."""
    p, k = item["path"], item["kind"]
    if k == "photo":
        with Image.open(p) as im:
            return [(f"media {item['id']}: photo {item['file']} ({im.width}x{im.height})", _jpeg_b64(im))]
    if k == "gif":
        with Image.open(p) as im:
            return [(f"media {item['id']}: looping GIF {item['file']}", _jpeg_b64(im))]
    d = item.get("duration", 0) or 1
    res = []
    for t in (0.1 * d, 0.5 * d, 0.9 * d):
        f = tempfile.mktemp(suffix=".jpg")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", p, "-frames:v", "1", f], check=False)
        if os.path.exists(f):
            with Image.open(f) as im:
                res.append((f"media {item['id']}: clip {item['file']} ({d:.1f}s long), frame at {t:.1f}s", _jpeg_b64(im, 384)))
            os.remove(f)
    return res


def lyric_sheet(lines, duration):
    rows, prev = [], 0.0
    for i, l in enumerate(lines):
        if l["start"] - prev > 6:
            rows.append(f"      {prev:6.1f}-{l['start']:6.1f}  (instrumental)")
        tag = " [echo]" if l.get("kind") == "echo" else ""
        rows.append(f"{i:3d}.  {l['start']:6.1f}-{l['end']:6.1f}  {l['text']}{tag}")
        prev = l["end"]
    if duration - prev > 6:
        rows.append(f"      {prev:6.1f}-{duration:6.1f}  (instrumental outro)")
    return "\n".join(rows)


def ask_claude(title, lines, duration, media, log=print):
    import anthropic
    client = anthropic.Anthropic()
    content = [{"type": "text", "text": f"{RULES}\n\nSong: {title}\nDuration: {duration:.1f} s\n\nTimed lyrics:\n"
                                         f"{lyric_sheet(lines, duration)}\n\nMedia (previews follow):"}]
    for item in media:
        for cap, b64 in previews(item):
            content.append({"type": "text", "text": cap})
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    content.append({"type": "text", "text": "Now submit the shot list and three covers with submit_plan."})
    log(f"asking {MODEL} to direct ({len(media)} media items)...")
    msg = client.messages.create(model=MODEL, max_tokens=8000,
                                 tools=[{"name": "submit_plan", "description": "Submit the video's shot list and covers.",
                                         "input_schema": SCHEMA}],
                                 tool_choice={"type": "tool", "name": "submit_plan"},
                                 messages=[{"role": "user", "content": content}])
    for block in msg.content:
        if getattr(block, "type", "") == "tool_use":
            return block.input
    raise RuntimeError("the model did not return a plan")


# ---------------- checking and repairing the model's answer ----------------
def clamp(v, lo, hi, default):
    try: v = float(v)
    except (TypeError, ValueError): return default
    return min(max(v, lo), hi)


def repair(answer, media, duration):
    n = len(media)
    shots = [s for s in answer.get("shots", []) if isinstance(s.get("media"), int) and 0 <= s["media"] < n]
    shots.sort(key=lambda s: float(s.get("start", 0)))
    out = []
    for s in shots:
        st = clamp(s.get("start"), 0, duration, 0)
        if out and st - out[-1]["start"] < 3.0:      # the previous shot would be too short: this one replaces it
            st = out.pop()["start"]
        m = media[s["media"]]
        shot = {"src": m["path"], "start": round(st, 2), "why": str(s.get("why", ""))[:200]}
        if m["kind"] == "clip":
            shot["clip_in"] = round(clamp(s.get("clip_in"), 0, max(m.get("duration", 1) - 0.5, 0), 0), 2)
            shot["speed"] = round(clamp(s.get("speed"), 0.3, 1.5, 1.0), 2)
        elif m["kind"] == "gif":
            shot.update(speed=round(clamp(s.get("speed"), 0.3, 1.5, 0.6), 2), pingpong=True)
        else:
            shot["zoom"] = [round(clamp(s.get("zoom_from"), 1.0, 1.6, 1.0), 3), round(clamp(s.get("zoom_to"), 1.0, 1.6, 1.12), 3)]
            f0 = s.get("focus_from") or [0.5, 0.5]; f1 = s.get("focus_to") or f0
            shot["f0"] = [round(clamp(f0[0] if len(f0) > 0 else 0.5, 0, 1, .5), 3), round(clamp(f0[1] if len(f0) > 1 else 0.5, 0, 1, .5), 3)]
            shot["f1"] = [round(clamp(f1[0] if len(f1) > 0 else 0.5, 0, 1, .5), 3), round(clamp(f1[1] if len(f1) > 1 else 0.5, 0, 1, .5), 3)]
        out.append(shot)
    if not out:
        raise ValueError("no usable shots in the model's answer")
    out[0]["start"] = 0.0
    for a, b in zip(out, out[1:]):
        a["end"] = b["start"]
    out[-1]["end"] = round(duration, 2)
    if duration - out[-1]["start"] < 3 and len(out) > 1:
        out[-2]["end"] = out[-1]["end"]; out.pop()
    for s in out:                                      # a clip must not run out before its shot ends
        m = next(x for x in media if x["path"] == s["src"])
        if m["kind"] == "clip":
            avail = max(m.get("duration", 1) - s["clip_in"], 0.5)
            need = s["end"] - s["start"]
            if avail / s["speed"] < need:
                s["speed"] = round(max(avail / need, 0.4), 2)
                if avail / s["speed"] < need:          # still too short: play it forward and back
                    s["clip_in"] = 0.0; s["pingpong"] = True
    out[-1]["fade_out"] = 4.0
    covers = []
    for c in answer.get("covers", [])[:3]:
        if not isinstance(c.get("media"), int) or not 0 <= c["media"] < n: continue
        m = media[c["media"]]
        f = c.get("focus") or [0.5, 0.45, 1.0]
        f = (f + [0.5, 0.45, 1.0])[:3]
        bg = m["path"] + (f"@{clamp(c.get('time'), 0, max(m.get('duration', 1) - 0.1, 0), 0.5):.2f}" if m["kind"] == "clip" else "")
        covers.append({"kind": c.get("kind", "place"), "bg": bg, "layout": c.get("layout", "center"),
                       "focus": [clamp(f[0], 0, 1, .5), clamp(f[1], 0, 1, .45), clamp(f[2], 1, 1.6, 1.0)],
                       "why": str(c.get("why", ""))[:200]})
    return out, covers or fallback_covers(media)


# ---------------- without the API ----------------
def fallback_covers(media):
    photos = [m for m in media if m["kind"] == "photo"]
    clips = [m for m in media if m["kind"] == "clip"]
    covers = []
    if clips:
        covers.append({"kind": "person", "bg": clips[0]["path"] + "@0.50", "layout": "right", "focus": [0.8, 0.45, 1.25], "why": "first clip"})
    for m, layout in zip(photos[:3 - len(covers)], ["center", "right", "center"]):
        covers.append({"kind": "place", "bg": m["path"], "layout": layout, "focus": [0.5, 0.42, 1.0], "why": m["file"]})
    return covers[:3]


def direct(title, lines, duration, media_paths, draft_shots, log=print):
    """Returns (shots, covers, notes, used_model). draft_shots come from make_plan.py and are the fallback."""
    media = describe_media(media_paths)
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            answer = ask_claude(title, lines, duration, media, log)
            shots, covers = repair(answer, media, duration)
            log(f"Claude directed {len(shots)} shots")
            return shots, covers, answer.get("notes", ""), MODEL
        except Exception as e:
            log(f"Claude director unavailable ({type(e).__name__}: {str(e)[:160]}); using the plain draft")
    else:
        log("no ANTHROPIC_API_KEY set; using the plain draft (media in filename order)")
    return draft_shots, fallback_covers(media), "", None
