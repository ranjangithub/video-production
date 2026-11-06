#!/usr/bin/env python3
"""Isolate the vocals of a song.

    separate.py SONG.mp3 -o work/vocals.wav [--backend auto|demucs|spleeter]

auto: Demucs if installed (best; uses PyTorch, GPU or Apple silicon if available), otherwise the Spleeter
2-stem ONNX model run through sherpa-onnx (CPU only, no PyTorch). The Spleeter model is downloaded from the
sherpa-onnx GitHub releases into models/ on first use.
"""
import argparse, os, shutil, subprocess, sys, tarfile, tempfile, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.environ.get("LYRIC_MODELS", os.path.join(HERE, "..", "..", "..", "..", "models"))
SPLEETER_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/source-separation-models/"
                "sherpa-onnx-spleeter-2stems-fp16.tar.bz2")


def fetch(url, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    name = url.rsplit("/", 1)[1]
    folder = os.path.join(dest_dir, name.replace(".tar.bz2", ""))
    if os.path.isdir(folder):
        return folder
    print(f"downloading {name} ...", flush=True)
    tmp = os.path.join(dest_dir, name)
    urllib.request.urlretrieve(url, tmp)
    with tarfile.open(tmp) as t:
        t.extractall(dest_dir)
    os.remove(tmp)
    return folder


def demucs(song, out):
    tmp = tempfile.mkdtemp()
    subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-o", tmp, song], check=True)
    stem = os.path.splitext(os.path.basename(song))[0]
    for root, _, files in os.walk(tmp):
        if "vocals.wav" in files and stem in root:
            shutil.move(os.path.join(root, "vocals.wav"), out)
            return
    sys.exit("demucs ran but no vocals.wav was found")


def spleeter(song, out):
    import sherpa_onnx as so, soundfile as sf
    d = fetch(SPLEETER_URL, MODELS)
    wav = tempfile.mktemp(suffix=".wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", song, "-ar", "44100", "-ac", "2", wav], check=True)
    cfg = so.OfflineSourceSeparationConfig(model=so.OfflineSourceSeparationModelConfig(
        spleeter=so.OfflineSourceSeparationSpleeterModelConfig(
            vocals=os.path.join(d, "vocals.fp16.onnx"), accompaniment=os.path.join(d, "accompaniment.fp16.onnx")),
        num_threads=os.cpu_count() or 2))
    sep = so.OfflineSourceSeparation(cfg)
    x, sr = sf.read(wav, dtype="float32", always_2d=True)
    res = sep.process(sample_rate=sr, samples=np.ascontiguousarray(x.T))
    sf.write(out, np.asarray(res.stems[0].data).T, res.sample_rate)
    os.remove(wav)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("song")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--backend", default="auto", choices=["auto", "demucs", "spleeter"])
    a = ap.parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    b = a.backend
    if b == "auto":
        try:
            import demucs  # noqa: F401
            b = "demucs"
        except ImportError:
            b = "spleeter"
    print(f"separating with {b}", flush=True)
    (demucs if b == "demucs" else spleeter)(a.song, a.out)
    print(a.out)


if __name__ == "__main__":
    main()
