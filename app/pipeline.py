"""Runs the lyric-video skill's scripts for one web project, one step at a time, recording progress.

A project lives in work/web/<id>/:
    song.mp3  media/  lyrics.txt  status.json  log.txt
    vocals.wav  words.json  style_plan.json  stills/  video.mp4  covers/  final.mp4
"""
import json, os, re, subprocess, sys, threading, time, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, ".claude", "skills", "lyric-video", "scripts")
WORK = os.path.join(ROOT, "work", "web")
sys.path.insert(0, SCRIPTS)
import align as _align          # noqa: E402  (lyrics tag reader)
import make_plan as _make_plan  # noqa: E402  (media list, draft cuts)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import director                 # noqa: E402

CPU_LOCK = threading.Lock()     # renders and recognition are CPU-heavy: one job at a time


class Project:
    def __init__(self, pid):
        self.id = pid
        self.dir = os.path.join(WORK, pid)
        self.p = lambda *a: os.path.join(self.dir, *a)

    # ---- state ----
    def status(self):
        try: return json.load(open(self.p("status.json")))
        except Exception: return {"id": self.id, "stage": "unknown"}

    def set(self, **kw):
        s = self.status(); s.update(kw); s["updated"] = time.time()
        json.dump(s, open(self.p("status.json"), "w"), ensure_ascii=False, indent=1)
        return s

    def log(self, msg):
        with open(self.p("log.txt"), "a") as f:
            f.write(time.strftime("%H:%M:%S ") + msg.rstrip() + "\n")

    def run(self, args, label):
        self.log(f"$ {label}")
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=ROOT)
        tail = []
        for line in proc.stdout:
            line = line.rstrip()
            if not line or "warn" in line.lower(): continue
            tail = (tail + [line])[-20:]
            self.log("  " + line)
        if proc.wait():
            raise RuntimeError(f"{label} failed: " + (tail[-1] if tail else "no output"))

    def py(self, script, *args, label=None):
        self.run([sys.executable, os.path.join(SCRIPTS, script), *args], label or script)

    # ---- helpers ----
    def media_paths(self):
        return [m["src"] for m in _make_plan.media_list(self.p("media"))]

    def lyrics_text(self):
        if os.path.exists(self.p("lyrics.txt")):
            return open(self.p("lyrics.txt")).read()
        return _align.lyrics_from_tag(self.p("song.mp3")) or ""

    def is_hindi(self):
        return bool(re.search(r"[ऀ-ॿ]", self.lyrics_text()))

    # ---- steps ----
    def analyze(self, redirect=True):
        st = self.status()
        text = self.lyrics_text()
        if not text.strip():
            self.set(stage="needs_lyrics", error="This MP3 has no lyrics inside it. Paste the lyrics and try again.")
            return
        open(self.p("lyrics.txt"), "w").write(text)
        self.set(stage="separating", error=None)
        if not os.path.exists(self.p("vocals.wav")):
            self.py("separate.py", self.p("song.mp3"), "-o", self.p("vocals.wav"), label="separating the vocals")
        self.set(stage="timing")
        args = [self.p("vocals.wav"), "--audio", self.p("song.mp3"), "--lyrics", self.p("lyrics.txt"),
                "-o", self.p("words.json")]
        if self.is_hindi(): args.append("--split-commas")
        self.py("align.py", *args, label="timing every word")
        words = json.load(open(self.p("words.json")))
        title = st.get("title") or "Untitled"
        self.py("make_plan.py", self.p("words.json"), "--media", self.p("media"), "-o", self.p("style_plan.json"),
                "--title", title, label="drafting the plan")
        plan = json.load(open(self.p("style_plan.json")))
        if redirect or not os.path.exists(self.p("covers.json")):
            self.set(stage="directing")
            shots, covers, notes, model = director.direct(title, words["lines"], words["duration"],
                                                          self.media_paths(), plan["shots"], log=self.log)
            json.dump({"covers": covers, "notes": notes, "model": model}, open(self.p("covers.json"), "w"), indent=1)
        else:                                       # re-timing: keep the shots already chosen
            shots = json.load(open(self.p("shots.json")))
        json.dump(shots, open(self.p("shots.json"), "w"), indent=1)
        plan["shots"] = shots
        json.dump(plan, open(self.p("style_plan.json"), "w"), ensure_ascii=False, indent=1)
        self.stills(plan)
        est = [i for i, l in enumerate(words["lines"]) if l.get("estimated")]
        self.set(stage="review", backend=words.get("backend"), estimated=est,
                 director=json.load(open(self.p("covers.json"))).get("model"))

    def stills(self, plan):
        self.set(stage="stills")
        chunks = [c for c in plan["chunks"] if c.get("kind") == "line"]
        picks = chunks[::max(1, len(chunks) // 6)][:6]
        times = [round(min(c["start"] + 1.2, c["end"] - 0.2), 2) for c in picks] or [plan["duration"] / 2]
        os.makedirs(self.p("stills"), exist_ok=True)
        for f in os.listdir(self.p("stills")): os.remove(self.p("stills", f))
        self.py("render.py", self.p("style_plan.json"), "--stills", ",".join(map(str, times)), "-o", self.p("stills"),
                label="drawing preview stills")

    def render(self):
        self.set(stage="rendering", error=None)
        self.py("render.py", self.p("style_plan.json"), "-o", self.p("video.mp4"), label="rendering the video")
        self.py("check_output.py", self.p("video.mp4"), "--audio", self.p("song.mp3"), label="checking the video")
        self.covers()

    def covers(self):
        self.set(stage="covers")
        st = self.status(); ideas = json.load(open(self.p("covers.json")))["covers"]
        os.makedirs(self.p("covers"), exist_ok=True)
        made = []
        for i, c in enumerate(ideas[:3], 1):
            out = self.p("covers", f"cover_{i}.jpg")
            args = ["make", "-o", out, "--bg", c["bg"], "--title", st.get("title") or "Untitled",
                    "--layout", c["layout"], "--focus", *map(str, c["focus"]), "--credit", st.get("credit") or ""]
            if st.get("tag"): args += ["--tag", st["tag"]]
            try:
                self.py("cover.py", *args, label=f"cover {i} ({c.get('kind')})"); made.append(i)
            except RuntimeError as e:
                self.log(str(e))
        self.set(stage="pick_cover", covers=made)

    def finish(self, n):
        self.set(stage="finishing", cover=n)
        self.py("cover.py", "apply", self.p("video.mp4"), self.p("covers", f"cover_{n}.jpg"), "-o", self.p("final.mp4"),
                label="putting the cover on the video")
        self.py("check_output.py", self.p("final.mp4"), "--audio", self.p("song.mp3"), label="checking the final video")
        self.set(stage="done")


def start(project, step, *args):
    """Run a step in the background. Returns False if this project is already busy."""
    if project.status().get("busy"):
        return False
    project.set(busy=True, error=None)

    def work():
        with CPU_LOCK:
            try:
                getattr(project, step)(*args)
            except Exception as e:
                project.log(traceback.format_exc())
                project.set(stage="error", error=str(e)[:300])
            finally:
                project.set(busy=False)
    threading.Thread(target=work, daemon=True).start()
    return True
