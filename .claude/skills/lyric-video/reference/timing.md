# Timing the lyrics

## Pipeline

```
SONG.mp3 → separate.py → vocals.wav → align.py (+ lyrics) → words.json → make_plan.py
```

`separate.py` uses Demucs when it is installed (`pip install demucs`, best quality, uses PyTorch and a GPU or
Apple silicon if present). Otherwise it uses a Spleeter 2-stem ONNX model through sherpa-onnx (CPU, about
20 MB, downloaded from GitHub releases into `models/`).

## align.py backends

`--backend auto` tries them in this order and uses the first that works:

| Backend | Model | Where it comes from | Best for |
| --- | --- | --- | --- |
| `whisper` | faster-whisper (`WHISPER_MODEL`, default `medium`) | Hugging Face | most languages, if Hugging Face is reachable |
| `parakeet` | NVIDIA Parakeet TDT 0.6B v2, int8 ONNX (about 650 MB) | sherpa-onnx GitHub releases | English; near word-perfect on clean vocals |
| `omni` | Meta Omnilingual ASR 300M CTC, int8 ONNX (about 360 MB) | sherpa-onnx GitHub releases | Hindi and 1,600 other languages |
| `phrase` | none | — | anything; places lines on sung phrases found from loudness |

Recognition results are cached next to the output (`words.json.omni.chars.json`), so re-running after a lyric
fix is instant.

## How matching works

The recognised text is turned into a consonant key that ignores script. श and ش and s are all "s". So when the
model hears Hindi but writes some words in Urdu or Gurmukhi script, it still matches the Devanagari lyrics. Each
line is searched for just after the line before, so repeated choruses land on the right repeat.

Lines the model could not hear (soft echoes, very melismatic phrases) are placed on the sung phrases found in the
vocal track between their neighbours, and marked `ESTIMATED`.

## What to check

- Repeats of the same line should last about the same time each time.
- An `ESTIMATED` line that is much longer than its repeats is probably spanning an instrumental break. Move it
  onto the right phrase.
- If timing drifts later in the song, the lyrics are probably missing a repeat or include an unsung line. Fix
  the lyrics file and re-run (the cached recognition makes it fast).
- To fix a line by hand, edit its `start`, `end` and `words[].start` in `words.json` (or later in
  `style_plan.json`).

## Results on the two reference songs

| Song | Backend | Lines heard | Notes |
| --- | --- | --- | --- |
| Bridal Red (English) | parakeet | 40 of 41 | the final echo placed by phrase |
| O Babul (Hindi) | omni | 23 of 34 | soft "ओ बाबुल" refrains and closing echoes placed by phrase |
