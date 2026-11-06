#!/usr/bin/env python3
"""Draft a style plan from timed lyrics and a media folder.

    make_plan.py work/words.json --media media/ -o work/style_plan.json --title "Bridal Red"

Cuts the timeline into shots (a change at a line start every ~8-12 s, plus a cut at each instrumental break),
fills them with the media in filename order (duplicates removed), and copies every lyric line with its
word times. This is a starting point: Claude then re-orders the shots so each picture lands on the line
that is about it (see reference/style_plan.md).
"""
import argparse, glob, hashlib, json, os, subprocess

IMG = (".jpg", ".jpeg", ".png", ".webp", ".heic")
VID = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".gif")


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try: return float(out)
    except ValueError: return 3.0


def media_list(folder):
    seen, out = set(), []
    for f in sorted(glob.glob(os.path.join(folder, "*"))):
        if not f.lower().endswith(IMG + VID): continue
        h = hashlib.md5(open(f, "rb").read()).hexdigest()
        if h in seen: continue                         # identical files uploaded twice
        seen.add(h)
        out.append({"src": os.path.abspath(f), "motion": f.lower().endswith(VID),
                    "dur": duration(f) if f.lower().endswith(VID) else None})
    return out


def cuts(lines, dur, min_shot=8.0, max_shot=12.5):
    starts = [l["start"] for l in lines]
    c = [0.0]
    if starts and starts[0] > 3: c.append(round(starts[0] - 0.1, 2))
    for i, l in enumerate(lines):
        nxt = lines[i + 1]["start"] if i + 1 < len(lines) else dur
        if nxt - l["end"] > 6:                         # instrumental break: cut after the line
            c.append(round(l["end"] + 0.5, 2)); c.append(round(nxt - 0.1, 2))
        elif l["start"] - c[-1] >= min_shot:
            c.append(round(l["start"] - 0.1, 2))
    out = [c[0]]
    for t in sorted(set(c[1:])):
        if t - out[-1] >= 3.0: out.append(t)
    # split shots that are too long
    fin = []
    for a, b in zip(out, out[1:] + [dur]):
        n = max(1, int((b - a) // max_shot) + (1 if (b - a) % max_shot > max_shot / 2 else 0))
        fin += [round(a + (b - a) * k / n, 2) for k in range(n)]
    fin = [t for t in fin if t <= dur - 3.0]
    return fin + [dur]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("words")
    ap.add_argument("--media", required=True)
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--hd", action="store_true", help="1920x1080 instead of 1280x720")
    a = ap.parse_args()
    w = json.load(open(a.words))
    lines, dur = w["lines"], w["duration"]
    media = media_list(a.media)
    if not media:
        raise SystemExit(f"no photos or clips in {a.media}")
    edges = cuts(lines, dur)
    shots = []
    for i, (s, e) in enumerate(zip(edges, edges[1:])):
        m = media[i % len(media)]; slot = e - s
        shot = {"src": m["src"], "start": s, "end": round(e, 2)}
        if m["motion"]:
            if m["src"].lower().endswith(".gif"):
                shot.update(speed=0.6, pingpong=True)
            else:
                shot.update(clip_in=0.0, speed=round(min(1.0, max(0.4, m["dur"] / slot)), 2))
        else:
            shot.update(zoom=[1.0, 1.12] if i % 2 == 0 else [1.14, 1.0], f0=[0.5, 0.5], f1=[0.5, 0.45])
        shots.append(shot)
    shots[-1]["fade_out"] = 4.0
    first = lines[0]["start"] if lines else dur
    title = None
    if a.title and first > 4:
        title = {"text": a.title, "start": 1.2, "end": round(min(first - 1.5, 16.0), 2)}
    chunks = [{"start": l["start"], "end": l["end"], "text": l["text"], "kind": l.get("kind", "line"),
               "words": l.get("words", []), **({"estimated": True} if l.get("estimated") else {})} for l in lines]
    W, H = (1920, 1080) if a.hd else (1280, 720)
    plan = {"video": {"width": W, "height": H, "fps": 30, "crossfade": 1.0, "lyric_y": 0.875,
                      "lyric_size": round(46 * H / 720), "bottom_shade": 0.42},
            "audio": w["audio"], "duration": dur, "title": title, "shots": shots, "chunks": chunks}
    json.dump(plan, open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"{len(shots)} shots from {len(media)} media files, {len(chunks)} lyric lines -> {a.out}")
    for s in shots:
        print(f"  {s['start']:7.2f}-{s['end']:7.2f}  {os.path.basename(s['src'])}")


if __name__ == "__main__":
    main()
