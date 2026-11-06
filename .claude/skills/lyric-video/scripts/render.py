#!/usr/bin/env python3
"""Render a lyric video from a style plan.

    render.py PLAN.json --stills 12.3,40 -o work/stills      # PNG frames to check
    render.py PLAN.json -o out/video.mp4 [--range 30 45] [--jobs 2]

The plan (see reference/style_plan.md) holds the audio, the shots (photos, clips, GIFs) and the lyric chunks
with per-word times. Lyrics are drawn small, low in the frame, with each word brightening as it is sung.
"""
import argparse, json, math, os, subprocess, sys, tempfile
import numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "..", "fonts")


def smooth(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def is_devanagari(s):
    return any("ऀ" <= c <= "ॿ" for c in s)


class Plan:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        p = json.load(open(path))
        v = p.get("video", {})
        self.W, self.H, self.FPS = v.get("width", 1280), v.get("height", 720), v.get("fps", 30)
        self.XF = v.get("crossfade", 1.0)
        self.lyric_y = v.get("lyric_y", 0.875)
        self.lyric_size = v.get("lyric_size", 46)
        self.shade = v.get("bottom_shade", 0.42)
        self.audio = self.abs(p["audio"])
        self.duration = p["duration"]
        self.shots = p["shots"]
        for s in self.shots:
            s["src"] = self.abs(s["src"])
        self.chunks = p["chunks"]
        self.title = p.get("title")
        self.fonts = v.get("fonts", {})

    def abs(self, f):
        return f if os.path.isabs(f) else os.path.normpath(os.path.join(self.dir, f))


# ---------------- media ----------------
class Media:
    def __init__(self, W, H):
        self.W, self.H = W, H
        self.clips, self.imgs = {}, {}

    def cover(self, img):
        ih, iw = img.shape[:2]
        s = max(self.W / iw, self.H / ih)
        r = cv2.resize(img, (round(iw * s), round(ih * s)), interpolation=cv2.INTER_AREA)
        y0 = (r.shape[0] - self.H) // 2; x0 = (r.shape[1] - self.W) // 2
        return r[y0:y0 + self.H, x0:x0 + self.W]

    def frames(self, src):
        if src in self.clips:
            return self.clips[src]
        if len(self.clips) >= 2:
            self.clips.pop(next(iter(self.clips)))
        fr = []
        if src.lower().endswith(".gif"):
            g = Image.open(src)
            fps = 1000.0 / max(g.info.get("duration", 100), 10)
            try:
                while True:
                    fr.append(self.cover(cv2.cvtColor(np.array(g.convert("RGB")), cv2.COLOR_RGB2BGR)))
                    g.seek(g.tell() + 1)
            except EOFError:
                pass
        else:
            cap = cv2.VideoCapture(src); fps = cap.get(cv2.CAP_PROP_FPS) or 24
            while True:
                ok, f = cap.read()
                if not ok: break
                fr.append(self.cover(f))
        self.clips[src] = (fr, fps)
        return fr, fps

    def image(self, src):
        if src not in self.imgs:
            im = cv2.imread(src)
            if im is None:
                im = cv2.cvtColor(np.array(Image.open(src).convert("RGB")), cv2.COLOR_RGB2BGR)
            self.imgs[src] = im
        return self.imgs[src]


def is_motion(src):
    return src.lower().endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv", ".gif"))


class Renderer:
    def __init__(self, plan):
        self.p = plan
        W, H = plan.W, plan.H
        self.media = Media(W, H)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
        vig = 1 - 0.28 * np.clip((r - 0.65) / 0.75, 0, 1) ** 1.5
        g = np.clip((yy - 0.70 * H) / (0.30 * H), 0, 1)
        self.grade = (vig * (1 - plan.shade * g ** 1.6))[..., None].astype(np.float32)
        self.chunks = self.build_chunks()

    # ---- background ----
    def shot_frame(self, s, t):
        W, H, XF = self.p.W, self.p.H, self.p.XF
        lt = t - s["start"]
        if is_motion(s["src"]):
            fr, fps = self.media.frames(s["src"])
            n = len(fr)
            f = (s.get("clip_in", 0.0) + lt * s.get("speed", 1.0)) * fps
            if s.get("pingpong") or s["src"].lower().endswith(".gif"):
                per = max(2 * (n - 1), 1); f = f % per
                if f > n - 1: f = per - f
            f = min(max(f, 0), n - 1)
            i0 = int(f); i1 = min(i0 + 1, n - 1); a = f - i0
            if a < 0.02 or i0 == i1:
                return fr[i0].astype(np.float32)
            return fr[i0].astype(np.float32) * (1 - a) + fr[i1].astype(np.float32) * a
        img = self.media.image(s["src"])
        ih, iw = img.shape[:2]
        z0, z1 = s.get("zoom", [1.0, 1.12])
        f0 = s.get("f0", [0.5, 0.5]); f1 = s.get("f1", f0)
        p = smooth((t - (s["start"] - XF / 2)) / (s["end"] - s["start"] + XF))
        z = z0 + (z1 - z0) * p
        fx = f0[0] + (f1[0] - f0[0]) * p; fy = f0[1] + (f1[1] - f0[1]) * p
        k = max(W / iw, H / ih) * z
        vw, vh = W / k, H / k
        cx = min(max(fx * iw, vw / 2), iw - vw / 2)
        cy = min(max(fy * ih, vh / 2), ih - vh / 2)
        M = np.array([[k, 0, W / 2 - k * cx], [0, k, H / 2 - k * cy]], np.float32)
        return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT).astype(np.float32)

    def background(self, t):
        S, XF, D = self.p.shots, self.p.XF, self.p.duration
        out = np.zeros((self.p.H, self.p.W, 3), np.float32); tot = 0.0
        for i, s in enumerate(S):
            a0 = -1 if i == 0 else s["start"] - XF / 2
            a1 = D + 5 if i == len(S) - 1 else s["end"] + XF / 2
            if a0 <= t < a1:
                w = 1.0
                if i > 0: w = min(w, smooth((t - a0) / XF))
                if i < len(S) - 1: w = min(w, smooth((a1 - t) / XF))
                out += self.shot_frame(s, t) * w; tot += w
        out /= max(tot, 1e-6)
        out *= self.grade
        fin = smooth(t / 1.5)
        fo = S[-1].get("fade_out", 0)
        if fo: fin *= smooth((D - 0.3 - t) / fo)
        return out * fin

    # ---- text ----
    def font(self, text, kind, size):
        dev = is_devanagari(text)
        key = ("dev" if dev else "latin") + ("_italic" if kind == "echo" else "")
        default = {"dev": "Tiro.ttf", "dev_italic": "TiroI.ttf", "latin": "Lora.ttf", "latin_italic": "LoraI.ttf"}[key]
        path = self.p.fonts.get(key) or os.path.join(FONT_DIR, default)
        f = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        if not dev:
            try: f.set_variation_by_axes([600 if kind == "title" else 500])
            except Exception: pass
        return f

    def render_word(self, text, font):
        l, tp, rr, b = font.getbbox(text)
        pad = 24
        w, h = rr - l + 2 * pad, b - tp + 2 * pad
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).text((pad - l, pad - tp), text, font=font, fill=255)
        wide = np.array(m.filter(ImageFilter.GaussianBlur(8)), np.float32) / 255
        tight = np.array(m.filter(ImageFilter.GaussianBlur(2.2)), np.float32) / 255
        return dict(fill=np.array(m, np.float32) / 255, shadow=np.clip(wide * 0.78 + tight * 0.7, 0, 1),
                    w=w, h=h, ox=l - pad, oy=tp - pad)

    def build_chunks(self):
        P = self.p
        items = []
        if P.title:
            items.append(dict(P.title, kind="title"))
        items += [dict(c) for c in P.chunks]
        out = []
        for c in items:
            kind = c.get("kind", "line")
            size = int(c.get("size", {"line": P.lyric_size, "echo": round(P.lyric_size * 0.74),
                                       "title": round(P.lyric_size * 1.65)}[kind]))
            font = self.font(c["text"], kind, size)
            words = c["text"].split(" ")
            space = font.getlength(" ") * 1.05
            widths = [font.getlength(w) for w in words]
            total = sum(widths) + space * (len(words) - 1)
            if total > P.W * 0.9:                      # shrink lines that would not fit
                k = P.W * 0.9 / total
                font = self.font(c["text"], kind, int(size * k)); size = int(size * k)
                space = font.getlength(" ") * 1.05; widths = [font.getlength(w) for w in words]
                total = sum(widths) + space * (len(words) - 1)
            x = (P.W - total) / 2
            base_y = c.get("y", {"line": P.lyric_y, "echo": P.lyric_y + 0.01, "title": 0.80}[kind]) * P.H
            asc = font.getmetrics()[0]
            col = np.array(c.get("color_bgr", [235, 243, 255]), np.float32)
            wt = [w.get("start") for w in c.get("words", [])]
            if len(wt) != len(words) or any(v is None for v in wt):
                L = sum(len(w) for w in words); acc = 0; wt = []
                for w in words:
                    wt.append(c["start"] + (c["end"] - c["start"]) * 0.82 * acc / L); acc += len(w)
            ws = []
            for w, wd, t in zip(words, widths, wt):
                rw = self.render_word(w, font)
                rw["x"] = int(round(x + rw["ox"])); rw["y"] = int(round(base_y - asc * 0.62 + rw["oy"]))
                rw["t"] = t; rw["color"] = col
                ws.append(rw); x += wd + space
            out.append(dict(start=c["start"], end=c["end"], kind=kind, words=ws,
                            fi=1.6 if kind == "title" else 0.45, fo=1.4 if kind == "title" else 0.5, post=0.35))
        # never let a fading line overlap the next one
        lines = [c for c in out if c["kind"] != "title"]
        for a, b in zip(lines, lines[1:]):
            limit = b["start"] - 0.30
            room = limit - a["end"]
            if room < 0.85:
                if room < 0.3:
                    a["end"] = limit - 0.3; room = 0.3
                a["post"] = 0.0; a["fo"] = room
        return out

    def draw(self, img, c, t):
        a0, a1 = c["start"] - 0.25, c["end"] + c["post"]
        if not (a0 <= t <= a1 + c["fo"]): return
        vis = smooth((t - a0) / c["fi"]) * smooth((a1 + c["fo"] - t) / c["fo"])
        if vis <= 0: return
        rise = (1 - smooth((t - a0) / 0.7)) * 10
        W, H = self.p.W, self.p.H
        for w in c["words"]:
            lit = {"line": 0.55 + 0.45 * smooth((t - w["t"] + 0.05) / 0.3), "echo": 0.75}.get(c["kind"], 1.0)
            x, y = w["x"], int(w["y"] + rise)
            x0, y0 = max(x, 0), max(y, 0); x1, y1 = min(x + w["w"], W), min(y + w["h"], H)
            if x1 <= x0 or y1 <= y0: continue
            sx, sy = x0 - x, y0 - y
            fill = w["fill"][sy:sy + y1 - y0, sx:sx + x1 - x0][..., None]
            shad = w["shadow"][sy:sy + y1 - y0, sx:sx + x1 - x0][..., None]
            reg = img[y0:y1, x0:x1]
            reg *= (1 - 0.8 * vis * shad)
            al = fill * vis * lit
            reg[:] = reg * (1 - al) + w["color"] * al

    def frame(self, t):
        img = self.background(t)
        for c in self.chunks:
            self.draw(img, c, t)
        return np.clip(img, 0, 255).astype(np.uint8)


def encode(plan, t0, t1, out):
    r = Renderer(plan)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{plan.W}x{plan.H}", "-r", str(plan.FPS), "-i", "-", "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    n0, n1 = int(round(t0 * plan.FPS)), int(round(t1 * plan.FPS))
    for n in range(n0, n1):
        p.stdin.write(r.frame(n / plan.FPS).tobytes())
        if (n - n0) % (plan.FPS * 30) == 0:
            print(f"  {n / plan.FPS:6.1f}s", flush=True)
    p.stdin.close(); p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--stills", help="comma-separated times; writes PNGs into the -o folder")
    ap.add_argument("--range", nargs=2, type=float, metavar=("T0", "T1"))
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="parallel render parts")
    ap.add_argument("--part", nargs=2, type=float, help=argparse.SUPPRESS)
    a = ap.parse_args()
    plan = Plan(a.plan)

    if a.stills:
        os.makedirs(a.out, exist_ok=True)
        r = Renderer(plan)
        for ts in a.stills.split(","):
            f = os.path.join(a.out, f"still_{float(ts):07.2f}.png")
            cv2.imwrite(f, r.frame(float(ts))); print(f)
        return
    if a.part:
        encode(plan, a.part[0], a.part[1], a.out); return

    t0, t1 = a.range if a.range else (0.0, plan.duration)
    jobs = max(1, min(a.jobs, int((t1 - t0) // 20) or 1))
    tmp = tempfile.mkdtemp(prefix="render_", dir=os.path.dirname(os.path.abspath(a.out)) or ".")
    edges = [t0 + (t1 - t0) * i / jobs for i in range(jobs + 1)]
    edges = [round(e * plan.FPS) / plan.FPS for e in edges]
    procs, parts = [], []
    for i in range(jobs):
        part = os.path.join(tmp, f"p{i}.mp4"); parts.append(part)
        procs.append(subprocess.Popen([sys.executable, __file__, a.plan, "-o", part, "--part", str(edges[i]), str(edges[i + 1])]))
    print(f"rendering {t1 - t0:.1f}s in {jobs} part(s)...", flush=True)
    if any(p.wait() for p in procs):
        sys.exit("a render part failed")
    lst = os.path.join(tmp, "list.txt")
    open(lst, "w").write("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-ss", str(t0), "-t", str(t1 - t0), "-i", plan.audio, "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", a.out], check=True)
    for p in parts: os.remove(p)
    os.remove(lst); os.rmdir(tmp)
    print(a.out)


if __name__ == "__main__":
    main()
