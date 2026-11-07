"""Lyric video studio: a local web front end for the lyric-video skill.

    python3 -m uvicorn app.server:app --port 8000      (or: scripts/web.sh)

then open http://localhost:8000. Upload a song and its photos and clips, review the timing and the preview
stills, render, pick a cover, download the MP4. Set ANTHROPIC_API_KEY to let Claude direct the shot list.
"""
import json, os, re, secrets, shutil, subprocess, time
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline

app = FastAPI(title="Lyric video studio")
HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(pipeline.WORK, exist_ok=True)

AUDIO = (".mp3", ".wav", ".m4a", ".flac", ".ogg")
MEDIA = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".webm")
MAX_FILE = 500 * 1024 * 1024


def project(pid):
    if not re.fullmatch(r"[a-z0-9]{10}", pid or "") or not os.path.isdir(os.path.join(pipeline.WORK, pid)):
        raise HTTPException(404, "no such project")
    return pipeline.Project(pid)


def safe_name(name, i):
    base, ext = os.path.splitext(os.path.basename(name or ""))
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")[:60] or f"file{i}"
    return f"{i:02d}_{base}{ext.lower()}"


async def save(upload, dest):
    size = 0
    with open(dest, "wb") as f:
        while chunk := await upload.read(1 << 20):
            size += len(chunk)
            if size > MAX_FILE:
                raise HTTPException(413, f"{upload.filename} is larger than 500 MB")
            f.write(chunk)


@app.post("/api/projects")
async def create(song: UploadFile = File(...), media: list[UploadFile] = File(default=[]),
                 title: str = Form(""), tag: str = Form(""), credit: str = Form("Rajesh Ranjan"), lyrics: str = Form("")):
    if not song.filename.lower().endswith(AUDIO):
        raise HTTPException(400, "the song must be an MP3, WAV, M4A, FLAC or OGG file")
    media = [m for m in media if m.filename]
    bad = [m.filename for m in media if not m.filename.lower().endswith(MEDIA)]
    if bad:
        raise HTTPException(400, "not a photo, clip or GIF: " + ", ".join(bad))
    if not media:
        raise HTTPException(400, "add at least one photo or clip")
    pid = secrets.token_hex(5)
    p = pipeline.Project(pid)
    os.makedirs(p.p("media"))
    ext = os.path.splitext(song.filename)[1].lower()
    await save(song, p.p("song" + ext))
    if ext != ".mp3":                                    # everything downstream reads song.mp3
        os.rename(p.p("song" + ext), p.p("song_src" + ext))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", p.p("song_src" + ext), "-q:a", "2", p.p("song.mp3")], check=True)
    for i, m in enumerate(media):
        await save(m, p.p("media", safe_name(m.filename, i)))
    if lyrics.strip():
        open(p.p("lyrics.txt"), "w").write(lyrics)
    if not title:
        title = os.path.splitext(song.filename)[0].replace("_", " ").strip()
    p.set(id=pid, title=title.strip(), tag=tag.strip(), credit=credit.strip(), created=time.time(), stage="uploaded",
          song_name=song.filename, busy=False)
    pipeline.start(p, "analyze")
    return {"id": pid}


@app.get("/api/projects")
def list_projects():
    out = []
    for pid in sorted(os.listdir(pipeline.WORK)):
        s = pipeline.Project(pid).status()
        if s.get("id"): out.append({k: s.get(k) for k in ("id", "title", "stage", "created")})
    return sorted(out, key=lambda s: -(s.get("created") or 0))


@app.get("/api/projects/{pid}")
def get(pid: str):
    p = project(pid); s = p.status()
    s["lyrics"] = p.lyrics_text()
    if os.path.exists(p.p("words.json")):
        w = json.load(open(p.p("words.json")))
        s["lines"] = [{k: l.get(k) for k in ("text", "start", "end", "kind", "estimated", "matched")} for l in w["lines"]]
        s["duration"] = w["duration"]
    if os.path.exists(p.p("shots.json")):
        names = {m: os.path.basename(m) for m in p.media_paths()}
        s["shots"] = [{"start": x["start"], "end": x["end"], "media": names.get(x["src"], os.path.basename(x["src"])),
                       "why": x.get("why", "")} for x in json.load(open(p.p("shots.json")))]
    if os.path.exists(p.p("covers.json")):
        c = json.load(open(p.p("covers.json")))
        s["notes"] = c.get("notes", ""); s["cover_ideas"] = [{"kind": x.get("kind"), "why": x.get("why")} for x in c["covers"]]
    s["stills"] = sorted(os.listdir(p.p("stills"))) if os.path.isdir(p.p("stills")) else []
    s["media"] = [os.path.basename(m) for m in p.media_paths()]
    s["has_video"] = os.path.exists(p.p("video.mp4"))
    s["has_final"] = os.path.exists(p.p("final.mp4"))
    try:
        s["log"] = open(p.p("log.txt")).read().splitlines()[-14:]
    except FileNotFoundError:
        s["log"] = []
    return s


@app.post("/api/projects/{pid}/lyrics")
def set_lyrics(pid: str, lyrics: str = Form(...)):
    p = project(pid)
    if not lyrics.strip(): raise HTTPException(400, "the lyrics are empty")
    open(p.p("lyrics.txt"), "w").write(lyrics)
    redirect = not os.path.exists(p.p("shots.json"))
    if not pipeline.start(p, "analyze", redirect): raise HTTPException(409, "this project is busy")
    return {"ok": True}


@app.post("/api/projects/{pid}/redirect")
def redirect(pid: str):
    p = project(pid)
    if not pipeline.start(p, "analyze", True): raise HTTPException(409, "this project is busy")
    return {"ok": True}


@app.post("/api/projects/{pid}/render")
def render(pid: str):
    p = project(pid)
    if not os.path.exists(p.p("style_plan.json")): raise HTTPException(400, "analyse the song first")
    if not pipeline.start(p, "render"): raise HTTPException(409, "this project is busy")
    return {"ok": True}


@app.post("/api/projects/{pid}/cover/{n}")
def pick_cover(pid: str, n: int):
    p = project(pid)
    if not os.path.exists(p.p("covers", f"cover_{n}.jpg")): raise HTTPException(404, "no such cover")
    if not pipeline.start(p, "finish", n): raise HTTPException(409, "this project is busy")
    return {"ok": True}


@app.get("/files/{pid}/{kind}/{name}")
def files(pid: str, kind: str, name: str):
    p = project(pid)
    if kind == "out" and name in ("video.mp4", "final.mp4"):
        path = p.p(name)
    elif kind not in ("stills", "covers", "media") or "/" in name or name.startswith("."):
        raise HTTPException(404)
    else:
        path = p.p(kind, name)
    if not os.path.isfile(path): raise HTTPException(404)
    return FileResponse(path)


@app.get("/download/{pid}/{what}")
def download(pid: str, what: str):
    p = project(pid); s = p.status()
    slug = re.sub(r"[^A-Za-z0-9]+", "_", s.get("title") or "lyric_video").strip("_") or "lyric_video"
    if what == "video":
        f = p.p("final.mp4") if os.path.exists(p.p("final.mp4")) else p.p("video.mp4")
        name = f"{slug}.mp4"
    elif what == "cover" and s.get("cover"):
        f, name = p.p("covers", f"cover_{s['cover']}.jpg"), f"{slug}_cover.jpg"
    else:
        raise HTTPException(404)
    if not os.path.exists(f): raise HTTPException(404, "not ready yet")
    return FileResponse(f, filename=name)


@app.delete("/api/projects/{pid}")
def delete(pid: str):
    p = project(pid)
    if p.status().get("busy"): raise HTTPException(409, "this project is busy")
    shutil.rmtree(p.dir)
    return {"ok": True}


@app.get("/api/info")
def info():
    return {"director": "claude" if os.environ.get("ANTHROPIC_API_KEY") else "draft",
            "model": pipeline.director.MODEL}


app.mount("/", StaticFiles(directory=os.path.join(HERE, "static"), html=True), name="static")
