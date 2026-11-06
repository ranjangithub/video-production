#!/usr/bin/env python3
"""Time every lyric line and word against the sung vocals.

    align.py work/vocals.wav --audio SONG.mp3 [--lyrics work/lyrics.txt] -o work/words.json
             [--backend auto|whisper|omni|parakeet|phrase] [--lang hi|en|...] [--split-commas]

Lyrics come from --lyrics, or from the MP3's lyrics tag (Suno writes one). [Section] tags are dropped;
"[Soft Echo: babul... babul...]" tags become small echo lines.

Backends (auto picks the first that is available):
  whisper   faster-whisper word timestamps (needs a Hugging Face download; good for most languages)
  omni      Meta Omnilingual ASR 300M CTC via sherpa-onnx, from GitHub releases (1600 languages, Hindi works)
  parakeet  NVIDIA Parakeet TDT 0.6B v2 via sherpa-onnx, from GitHub releases (English only, very good)
  phrase    no model: finds sung phrases from the vocal track's loudness and maps lines onto them

Recognised text is matched to the lyrics on a script-independent consonant key, so Hindi heard as Urdu or
Gurmukhi script still matches the Devanagari lyrics. Lines the model missed are placed by interpolation and
marked "estimated": check those first.
"""
import argparse, difflib, json, os, re, subprocess, sys, tarfile, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.environ.get("LYRIC_MODELS", os.path.join(HERE, "..", "..", "..", "..", "models"))
REL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
OMNI = "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-int8-2025-11-12"
PARAKEET = "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"
SR = 16000

# ---------------- script-independent sound key ----------------
_DEV = {}
for chars, k in [("कखक़ख़", "k"), ("गघग़", "g"), ("चछ", "c"), ("जझज़", "j"), ("टठतथ", "t"), ("डढदधड़ढ़", "d"),
                 ("णनञङ", "n"), ("पफफ़", "p"), ("बभ", "b"), ("म", "m"), ("य", "y"), ("र", "r"), ("ल", "l"),
                 ("व", "v"), ("शषस", "s"), ("ह", "h"), ("अआइईउऊएऐओऔ", "a")]:
    for c in chars:
        if c != "\u093c": _DEV[c] = k              # skip the nukta dot inside composed letters
_URDU = {}
for chars, k in [("کكقخ", "k"), ("گغ", "g"), ("چ", "c"), ("جزذضظژ", "j"), ("تٹطة", "t"), ("دڈڑ", "d"),
                 ("نں", "n"), ("پف", "p"), ("ب", "b"), ("م", "m"), ("یيےئى", "y"), ("ر", "r"), ("ل", "l"),
                 ("و", "v"), ("سشصث", "s"), ("ہهح", "h"), ("اآع", "a")]:
    for c in chars: _URDU[c] = k
_LAT = {c: c for c in "bcdfghjklmnpqrstvwxyz"}
_LAT.update({"q": "k", "w": "v", "x": "k", "f": "p", "z": "j"})


def key(ch):
    if "਀" <= ch <= "੿":              # Gurmukhi mirrors the Devanagari block
        ch = chr(ord(ch) - 0x100)
    if ch in _DEV: return _DEV[ch]
    if ch in _URDU: return _URDU[ch]
    c = ch.lower()
    if c in _LAT: return _LAT[c]
    if c in "aeiou": return None                 # Latin vowels carry little for matching
    return None


# ---------------- lyrics ----------------
def lyrics_from_tag(audio):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags", "-of", "json", audio],
                         capture_output=True, text=True).stdout
    tags = json.loads(out or "{}").get("format", {}).get("tags", {})
    for k, v in tags.items():
        if k.lower().startswith(("lyrics", "unsyncedlyrics", "uslt")):
            return v
    return None


def parse_lyrics(text, split_commas):
    lines = []
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            continue
        m = re.match(r"^\[[^\]]*echo[^\]]*:\s*(.+?)\]$", s, re.I)
        if m:
            lines.append({"text": clean(m.group(1)), "kind": "echo"}); continue
        if s.startswith("[") or s.startswith("("):
            continue
        s = re.sub(r"\[[^\]]*\]", "", s).strip()
        parts = [p for p in re.split(r",\s*", s) if p.strip()] if (split_commas and "," in s) else [s]
        for p in parts:
            lines.append({"text": clean(p), "kind": "line"})
    return [l for l in lines if l["text"]]


def clean(s):
    s = s.strip().rstrip(",.;:").strip()
    if s.endswith("…") and s.count("…") == 1:
        s = s[:-1].strip()
    return s


# ---------------- recognisers: each returns [(char, time)] ----------------
def load_vocals(path):
    import soundfile as sf
    tmp = path + ".16k.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", str(SR), tmp], check=True)
    y, _ = sf.read(tmp, dtype="float32")
    os.remove(tmp)
    return y


def fetch(name):
    folder = os.path.join(MODELS, name)
    if os.path.isdir(folder):
        return folder
    os.makedirs(MODELS, exist_ok=True)
    print(f"downloading {name} ...", flush=True)
    tmp = folder + ".tar.bz2"
    urllib.request.urlretrieve(REL + name + ".tar.bz2", tmp)
    with tarfile.open(tmp) as t:
        t.extractall(MODELS)
    os.remove(tmp)
    return folder


def windowed(rec, y, win=15.0, step=12.0):
    chars = []
    for i, st in enumerate(np.arange(0, len(y) / SR, step)):
        a, b = int(st * SR), int(min(st + win, len(y) / SR) * SR)
        if b - a < SR: break
        s = rec.create_stream(); s.accept_waveform(SR, y[a:b]); rec.decode_stream(s)
        r = s.result
        lo = st + (win - step) / 2 if i > 0 else 0.0
        hi = st + win - (win - step) / 2
        for tok, ts in zip(r.tokens, r.timestamps):
            t = st + ts
            if lo <= t < hi:
                for ch in tok.replace("▁", " "):
                    chars.append((ch, round(t, 2)))
        print(f"  {st:6.1f}s  {r.text}", flush=True)
    return chars


def rec_omni(y, lang):
    import sherpa_onnx as so
    d = fetch(OMNI)
    rec = so.OfflineRecognizer.from_omnilingual_asr_ctc(model=os.path.join(d, "model.int8.onnx"),
                                                        tokens=os.path.join(d, "tokens.txt"), num_threads=os.cpu_count() or 2)
    return windowed(rec, y)


def rec_parakeet(y, lang):
    import sherpa_onnx as so
    d = fetch(PARAKEET)
    rec = so.OfflineRecognizer.from_transducer(encoder=os.path.join(d, "encoder.int8.onnx"),
                                               decoder=os.path.join(d, "decoder.int8.onnx"),
                                               joiner=os.path.join(d, "joiner.int8.onnx"),
                                               tokens=os.path.join(d, "tokens.txt"), model_type="nemo_transducer",
                                               num_threads=os.cpu_count() or 2)
    return windowed(rec, y)


def rec_whisper(y, lang):
    from faster_whisper import WhisperModel
    m = WhisperModel(os.environ.get("WHISPER_MODEL", "medium"), device="auto", compute_type="int8")
    segs, _ = m.transcribe(y, language=lang, word_timestamps=True, vad_filter=False)
    chars = []
    for s in segs:
        print(f"  {s.start:6.1f}s  {s.text}", flush=True)
        for w in s.words:
            for ch in w.word:
                chars.append((ch, round(w.start, 2)))
    return chars


# ---------------- phrase detection (no model) ----------------
def phrases(y):
    import librosa
    hop = 160
    rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=hop)[0]
    db = np.convolve(20 * np.log10(rms + 1e-6), np.ones(10) / 10, "same")
    t = np.arange(len(db)) * hop / SR
    on = db > np.percentile(db, 40)
    segs, s = [], None
    for i, o in enumerate(on):
        if o and s is None: s = i
        if not o and s is not None: segs.append([t[s], t[i]]); s = None
    merged = []
    for a, b in segs:
        if merged and a - merged[-1][1] < 0.35: merged[-1][1] = b
        else: merged.append([a, b])
    return [m for m in merged if m[1] - m[0] > 0.25]


def place_by_phrases(lines, ph, first=False):
    ph = [list(p) for p in ph]
    if first:                                         # unheard lines usually follow the last heard one
        ph = ph[:len(lines)]
    while len(ph) > len(lines):                       # merge the closest pair
        gaps = [ph[i + 1][0] - ph[i][1] for i in range(len(ph) - 1)]
        i = int(np.argmin(gaps)); ph[i][1] = ph[i + 1][1]; del ph[i + 1]
    while len(ph) < len(lines):                       # split the longest
        i = int(np.argmax([b - a for a, b in ph])); a, b = ph[i]; m = (a + b) / 2
        ph[i:i + 1] = [[a, m - 0.1], [m + 0.1, b]]
    for l, (a, b) in zip(lines, ph):
        l["start"], l["end"], l["estimated"] = round(a, 2), round(b, 2), True
        spread_words(l)


def spread_words(l):
    ws = l["text"].split(" ")
    L = sum(len(w) for w in ws); acc = 0; l["words"] = []
    for w in ws:
        l["words"].append({"text": w, "start": round(l["start"] + (l["end"] - l["start"]) * 0.82 * acc / L, 2)})
        acc += len(w)


# ---------------- matching ----------------
def match(lines, chars, duration, ph=None):
    """Match line by line, each searched for just after the previous one, so repeated choruses
    land on the right repeat."""
    heard = [(key(c), t) for c, t in chars if key(c)]
    hk = [k for k, _ in heard]; ht = [t for _, t in heard]
    cursor_t = 0.0
    for li, l in enumerate(lines):
        ws = l["text"].split(" ")
        seq, owner = [], []
        for wi, w in enumerate(ws):
            for c in w:
                k = key(c)
                if k: seq.append(k); owner.append(wi)
        l["words"] = [{"text": w, "start": None} for w in ws]
        l["start"] = l["end"] = None; l["matched"] = f"0/{len(ws)}"; l["estimated"] = True
        if not seq:
            continue
        if l["kind"] == "echo":                       # echoes repeat the line before; place them by phrase
            continue
        L = max(int(len(seq) * 1.4) + 2, 4)
        cands = []
        for j in range(len(hk)):
            if ht[j] < cursor_t: continue
            dt = ht[j] - cursor_t
            if dt > 35: break
            r = difflib.SequenceMatcher(None, seq, hk[j:j + L], autojunk=False).ratio()
            if r >= 0.45 and (dt < 15 or r >= 0.75 or li == 0):  # far away needs a strong match
                cands.append((r, j))
        if not cands:
            continue
        top = max(r for r, _ in cands)
        j = next(j for r, j in cands if r >= top - 0.12)   # the earliest strong match, not a later repeat
        sm = difflib.SequenceMatcher(None, seq, hk[j:j + L], autojunk=False)
        hit = {}
        for a0, b0, n in sm.get_matching_blocks():
            for q in range(n):
                hit.setdefault(owner[a0 + q], []).append(ht[j + b0 + q])
        allt = sorted(t for v in hit.values() for t in v)
        med = allt[len(allt) // 2]
        hit = {wi: [t for t in v if t >= med - 2.5] for wi, v in hit.items()}   # drop stray early letters
        hit = {wi: v for wi, v in hit.items() if v}
        for wi in hit: l["words"][wi]["start"] = min(hit[wi])
        got = [w["start"] for w in l["words"] if w["start"] is not None]
        l["matched"] = f"{len(got)}/{len(ws)}"
        l["estimated"] = len(got) < max(1, (len(ws) + 1) // 2)
        l["start"] = min(got)
        l["end"] = round(max(max(v) for v in hit.values()) + 0.6, 2)
        if not l["estimated"]:
            cursor_t = l["start"] + 0.8
    # monotonic + fill gaps by interpolation over character counts
    known = [i for i, l in enumerate(lines) if l["start"] is not None and not l["estimated"]]
    for i in range(1, len(known)):
        if lines[known[i]]["start"] <= lines[known[i - 1]]["start"]:
            lines[known[i]]["estimated"] = True
    known = [i for i, l in enumerate(lines) if l["start"] is not None and not l["estimated"]]
    anchors = [(-1, 0.0)] + [(i, lines[i]["start"]) for i in known] + [(len(lines), duration)]
    for (ia, ta), (ib, tb) in zip(anchors, anchors[1:]):
        gap = list(range(ia + 1, ib))
        if not gap: continue
        t0 = lines[ia]["end"] + 0.3 if ia >= 0 else ta
        inside = [p for p in (ph or []) if p[0] >= t0 - 0.2 and p[1] <= tb + 0.2 and p[1] - p[0] > 0.6]
        if inside:                                    # put the unheard lines on the sung phrases in the gap
            sub = [lines[i] for i in gap]
            place_by_phrases(sub, inside, first=True)
            continue
        span = max(tb - t0, 0.5 * len(gap))
        sizes = [len(lines[i]["text"]) for i in gap]; tot = sum(sizes); acc = 0
        for i, s in zip(gap, sizes):
            lines[i]["start"] = round(t0 + span * acc / tot, 2)
            lines[i]["end"] = round(t0 + span * (acc + s) / tot - 0.2, 2)
            lines[i]["estimated"] = True
            acc += s
    for li, l in enumerate(lines):
        nxt = lines[li + 1]["start"] if li + 1 < len(lines) else duration
        l["end"] = round(min(l["end"], nxt - 0.15), 2)
        if l["end"] <= l["start"]: l["end"] = round(l["start"] + 0.8, 2)
        ws = l["words"]
        if ws and ws[0]["start"] is None: ws[0]["start"] = l["start"]
        for k, w in enumerate(ws):                    # fill missing word times inside the line
            if w["start"] is None:
                prev = ws[k - 1]["start"]
                nx = next((j for j in range(k + 1, len(ws)) if ws[j]["start"] is not None), None)
                tn = ws[nx]["start"] if nx is not None else l["end"] - 0.3
                jn = nx if nx is not None else len(ws)
                w["start"] = round(prev + (tn - prev) * 1 / (jn - k + 1), 2)
            w["start"] = round(min(max(w["start"], l["start"]), l["end"]), 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vocals")
    ap.add_argument("--audio", required=True, help="the original song (for duration and the lyrics tag)")
    ap.add_argument("--lyrics", help="text file, one sung line per line")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--backend", default="auto", choices=["auto", "whisper", "omni", "parakeet", "phrase"])
    ap.add_argument("--lang", default=None, help="hi, en, ... (auto-detected from the lyrics' script)")
    ap.add_argument("--split-commas", action="store_true", help="show each comma-separated half-line on its own")
    a = ap.parse_args()

    text = open(a.lyrics).read() if a.lyrics else lyrics_from_tag(a.audio)
    if not text:
        sys.exit("no lyrics: pass --lyrics FILE (the MP3 has no lyrics tag)")
    lines = parse_lyrics(text, a.split_commas)
    lang = a.lang or ("hi" if any("ऀ" <= c <= "ॿ" for l in lines for c in l["text"]) else "en")
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.audio],
                               capture_output=True, text=True).stdout.strip())
    y = load_vocals(a.vocals)

    order = {"auto": ["whisper", "parakeet" if lang == "en" else "omni", "omni", "phrase"]}.get(a.backend, [a.backend])
    used = None
    for b in order:
        try:
            if b == "phrase":
                place_by_phrases(lines, phrases(y)); used = b; break
            cache = f"{a.out}.{b}.chars.json"         # recognition is slow; rerun matching for free
            if os.path.exists(cache):
                chars = [tuple(c) for c in json.load(open(cache))]
            else:
                print(f"recognising with {b} ...", flush=True)
                chars = {"whisper": rec_whisper, "omni": rec_omni, "parakeet": rec_parakeet}[b](y, lang)
                json.dump(chars, open(cache, "w"), ensure_ascii=False)
            match(lines, chars, dur, phrases(y)); used = b; break
        except Exception as e:                        # missing package, blocked download, ...
            print(f"  {b} unavailable: {type(e).__name__}: {str(e)[:120]}", flush=True)
    json.dump({"audio": os.path.abspath(a.audio), "duration": dur, "lang": lang, "backend": used, "lines": lines},
              open(a.out, "w"), ensure_ascii=False, indent=1)
    print(f"\nbackend: {used}")
    for l in lines:
        flag = "  ESTIMATED" if l.get("estimated") else ""
        print(f"{l['start']:7.2f} {l['end']:7.2f}  {l.get('matched', ''):>5}  {l['text']}{flag}")
    print(a.out)


if __name__ == "__main__":
    main()
