#!/usr/bin/env python3
"""Cover art for a lyric video, and putting it on the video.

    cover.py make -o out/cover.jpg --bg media/tree.jpg --title "Bridal Red" \
        --tag "THE ENGLISH VERSION OF O BABUL" --credit-label "LYRICS, CONCEIVED & PRODUCED BY" \
        --credit "Rajesh Ranjan" --layout center [--focus 0.5 0.42 1.0]
    cover.py make ... --bg media/clip.mp4@0.5         # a still from a clip, at 0.5 s
    cover.py apply out/video.mp4 out/cover.jpg -o out/video_cover.mp4

Layouts: center (title in the sky, credit along the bottom), right / left (a text column on a darkened side;
put the people on the other side with --focus). `apply` shows the cover for the first 0.5 s, dissolves into the
video, and embeds it as the file's thumbnail.
"""
import argparse, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "..", "fonts")
GOLD, CREAM = (232, 196, 128), (250, 244, 232)


def is_dev(s):
    return any("ऀ" <= c <= "ॿ" for c in s)


def font(name, size, wght=None):
    f = ImageFont.truetype(os.path.join(FONTS, name), size, layout_engine=ImageFont.Layout.RAQM)
    if wght:
        try: f.set_variation_by_axes([wght])
        except Exception: pass
    return f


def load_bg(spec):
    if "@" in spec and spec.rsplit("@", 1)[0].lower().endswith((".mp4", ".mov", ".m4v", ".webm")):
        path, t = spec.rsplit("@", 1)
        png = tempfile.mktemp(suffix=".png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", t, "-i", path, "-frames:v", "1", png], check=True)
        return Image.open(png).convert("RGB")
    return Image.open(spec).convert("RGB")


def crop(img, W, H, fx, fy, zoom):
    k = max(W / img.width, H / img.height) * zoom
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    x = min(max(int(fx * img.width - W / 2), 0), img.width - W)
    y = min(max(int(fy * img.height - H / 2), 0), img.height - H)
    return img.crop((x, y, x + W, y + H))


def shade(img, side, strength, reach):
    W, H = img.size
    a = np.array(img, np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    u = {"right": xx / W, "left": 1 - xx / W, "top": 1 - yy / H, "bottom": yy / H}[side]
    g = np.clip((u - (1 - reach)) / reach, 0, 1) ** 1.4 * strength
    a *= (1 - g)[..., None]
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    a *= (1 - 0.3 * np.clip((r - 0.7) / 0.7, 0, 1))[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def text(img, xy, s, f, fill, anchor, blur=10, spacing=0):
    m = Image.new("L", img.size, 0); d = ImageDraw.Draw(m)
    if spacing:
        total = sum(f.getlength(c) for c in s) + spacing * (len(s) - 1)
        x, y = xy
        x -= {"l": 0, "m": total / 2, "r": total}[anchor[0]]
        for c in s:
            d.text((x, y), c, font=f, fill=255, anchor="l" + anchor[1]); x += f.getlength(c) + spacing
    else:
        d.text(xy, s, font=f, fill=255, anchor=anchor)
    sh = m.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * 0.65))
    img.paste(Image.new("RGB", img.size, (0, 0, 0)), (0, 0), sh)
    img.paste(Image.new("RGB", img.size, fill), (0, 0), m)


def make(a):
    W, H = a.size
    s = H / 720
    img = crop(load_bg(a.bg), W, H, *a.focus)
    if a.layout == "center":
        img = shade(img, "bottom", 0.8, 0.4); img = shade(img, "top", 0.85, 0.55)
    else:
        img = shade(img, a.layout, 0.88, 0.58)
    tf = font("Tiro.ttf", int(128 * s)) if is_dev(a.title) else font("Lora.ttf", int(104 * s), 600)
    small = font("Lora.ttf", int(22 * s), 600)
    label = font("Lora.ttf", int(21 * s), 600)
    name = font("LoraI.ttf", int(34 * s), 500) if not is_dev(a.credit or "") else font("TiroI.ttf", int(34 * s))
    if a.layout == "center":
        ty = int(150 * s)
        text(img, (W / 2, ty), a.title, tf, CREAM, "ms", 18)
        if a.tag: text(img, (W / 2, ty + 52 * s), a.tag, small, GOLD, "ms", 9, 4)
        cx, cy, anc = W / 2, H - 92 * s, "m"
    else:
        x = W - 80 * s if a.layout == "right" else 80 * s
        anc = "r" if a.layout == "right" else "l"
        text(img, (x, 300 * s), a.title, tf, CREAM, anc + "s", 16)
        if a.tag: text(img, (x, 352 * s), a.tag, small, GOLD, anc + "s", 9, 4)
        x0, x1 = (x - 220 * s, x) if anc == "r" else (x, x + 220 * s)
        ImageDraw.Draw(img).line([(x0, 392 * s), (x1, 392 * s)], fill=GOLD, width=max(2, int(2 * s)))
        cx, cy = x, 450 * s
    if a.credit:
        if a.credit_label: text(img, (cx, cy), a.credit_label, label, GOLD, anc + "s", 9, 3)
        text(img, (cx, cy + 48 * s), a.credit, name, CREAM, anc + "s", 8)
    img.save(a.out, quality=94)
    print(a.out)


def apply(a):
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", a.video, "-loop", "1", "-t", "2", "-i", a.cover, "-i", a.cover,
           "-filter_complex", "[1:v]format=yuva420p,fade=t=out:st=0.5:d=0.8:alpha=1[c];[0:v][c]overlay=eof_action=pass[v]",
           "-map", "[v]", "-map", "0:a", "-map", "2:v", "-c:v:0", "libx264", "-preset", "veryfast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-c:a", "copy", "-c:v:1", "copy", "-disposition:v:1", "attached_pic",
           "-movflags", "+faststart", a.out]
    subprocess.run(cmd, check=True)
    print(a.out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("make")
    m.add_argument("-o", "--out", required=True)
    m.add_argument("--bg", required=True, help="image, or clip.mp4@SECONDS")
    m.add_argument("--title", required=True)
    m.add_argument("--tag")
    m.add_argument("--credit-label", default="LYRICS, CONCEIVED & PRODUCED BY")
    m.add_argument("--credit")
    m.add_argument("--layout", default="center", choices=["center", "right", "left"])
    m.add_argument("--focus", nargs=3, type=float, default=[0.5, 0.45, 1.0], metavar=("FX", "FY", "ZOOM"))
    m.add_argument("--size", nargs=2, type=int, default=[1280, 720])
    p = sub.add_parser("apply")
    p.add_argument("video"); p.add_argument("cover")
    p.add_argument("-o", "--out", required=True)
    a = ap.parse_args()
    (make if a.cmd == "make" else apply)(a)


if __name__ == "__main__":
    main()
