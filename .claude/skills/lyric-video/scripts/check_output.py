#!/usr/bin/env python3
"""Check a rendered video: it has video and audio, and its length matches the song.

    check_output.py out/video.mp4 [--audio SONG.mp3] [--tolerance 1.0]

Exits 1 with a reason when something is wrong. The render hook runs this after every render.
"""
import argparse, json, subprocess, sys


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
                          "-of", "json", path], capture_output=True, text=True)
    if out.returncode:
        return None
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--audio")
    ap.add_argument("--tolerance", type=float, default=1.0)
    a = ap.parse_args()
    v = probe(a.video)
    if not v:
        sys.exit(f"{a.video}: not a readable video file")
    kinds = [s.get("codec_type") for s in v.get("streams", [])]
    problems = []
    if "video" not in kinds: problems.append("no video stream")
    if "audio" not in kinds: problems.append("no audio stream (the song was not muxed in)")
    dur = float(v["format"].get("duration", 0))
    if dur < 1: problems.append(f"duration is {dur:.2f}s")
    if a.audio:
        s = probe(a.audio)
        sd = float(s["format"]["duration"]) if s else 0
        if sd and abs(dur - sd) > a.tolerance and dur < sd - a.tolerance:
            problems.append(f"video is {dur:.1f}s but the song is {sd:.1f}s")
    if problems:
        sys.exit(f"{a.video}: " + "; ".join(problems))
    w = next((s for s in v["streams"] if s.get("codec_type") == "video"), {})
    print(f"OK {a.video}: {dur:.1f}s, {w.get('width')}x{w.get('height')}, audio present")


if __name__ == "__main__":
    main()
