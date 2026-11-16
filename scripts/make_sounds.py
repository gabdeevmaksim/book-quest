#!/usr/bin/env python3
"""make_sounds.py — synthesizes the app's sound effects into assets/sounds/*.mp3.

Run from the repo root (needs numpy + ffmpeg):
    python3 scripts/make_sounds.py
Five small mono clips, played in the browser by sounds.py:
    click.mp3    any button press
    roll.mp3     dice tumble + landing — timed to app.animate_roll (18 faces, slowing down)
    item.mp3     something new in the backpack
    success.mp3  a check or fight won (bright, rising)
    fail.mp3     a check or fight lost (dark, falling)
Edit the recipes below and re-run to change how they sound.
"""
import os, subprocess
import numpy as np

SR = 44100
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = f"{ROOT}/assets/sounds"

def t_(dur): return np.arange(int(dur * SR)) / SR
def hz(midi): return 440.0 * 2 ** ((midi - 69) / 12)
def filt(x, fc, high=False):
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    g = 1 / np.sqrt(1 + (f / fc) ** 4)
    return np.fft.irfft(X * (np.sqrt(np.maximum(0, 1 - g * g)) if high else g), len(x))
def att(x, ms=2):
    n = min(len(x), int(SR * ms / 1000)); x[:n] *= np.linspace(0, 1, n); return x
def put(buf, sig, at, gain=1.0):
    i = int(at * SR); sig = sig[: len(buf) - i]; buf[i:i + len(sig)] += sig * gain

def knock(rng, freq, dur=0.05, low=False):            # die on wood
    t = t_(dur)
    y = np.sin(2 * np.pi * freq * t) * np.exp(-t * (60 if low else 95))
    y += 0.5 * filt(rng.uniform(-1, 1, len(t)), 2500) * np.exp(-t * 140)
    return att(y, 1)
def bell(freq, dur=1.0):
    t = t_(dur); y = np.zeros_like(t)
    for r, a, dcy in ((1, 1, 5), (2.76, .4, 8), (5.4, .18, 12)):
        y += a * np.sin(2 * np.pi * freq * r * t) * np.exp(-t * dcy)
    return att(y, 2)
def pop(f0, f1, dur=0.09):
    t = t_(dur); ph = 2 * np.pi * np.cumsum(f0 + (f1 - f0) * (t / dur) ** 0.6) / SR
    return att(np.sin(ph) * np.exp(-t * 18) * np.minimum(1, (dur - t) / 0.02), 3)

def click():
    rng = np.random.RandomState(1); b = np.zeros(int(0.12 * SR)); t = t_(0.04)
    put(b, att(np.sin(2 * np.pi * 980 * t) * np.exp(-t * 110), 1), 0, 0.55)
    put(b, knock(rng, 300, 0.06, low=True), 0, 0.40)
    return b

def roll():
    """Same rhythm as app.animate_roll: 18 faces at 0.05 + i*0.004 s, then the die lands."""
    rng = np.random.RandomState(4); b = np.zeros(int(2.0 * SR)); t = 0.0
    for i in range(18):
        put(b, knock(rng, rng.uniform(900, 1700)), t, 0.55 * (1 - i / 40))
        if i % 3 == 1: put(b, knock(rng, rng.uniform(500, 800), 0.04), t + 0.02, 0.22)   # the second die / table
        t += 0.05 + i * 0.004
    put(b, knock(rng, 210, 0.18, low=True), t, 0.95); put(b, knock(rng, 1200), t, 0.40)
    return b

def item():
    b = np.zeros(int(1.0 * SR))
    put(b, pop(420, 760), 0, 0.40)                     # into the pack...
    put(b, bell(hz(81), 0.9), 0.05, 0.45)              # ...and a little two-note sparkle
    put(b, bell(hz(86), 0.9), 0.14, 0.50)
    return b

def pluck(freq, dur=0.9):                             # a soft, dull string
    t = t_(dur); y = np.zeros_like(t)
    for k in range(1, 6):
        y += np.sin(2 * np.pi * freq * k * t) / k ** 1.4 * np.exp(-t * (3.0 + 1.5 * k))
    return att(y, 4)

def success():
    """Bright and rising: a quick major arpeggio of bells."""
    b = np.zeros(int(1.3 * SR))
    for i, note in enumerate((74, 78, 81, 86)):        # D F# A D
        put(b, bell(hz(note), 1.0), 0.085 * i, 0.40 + 0.05 * i)
    return b

def fail():
    """Dark and falling: a dull thump, then two low notes stepping down. No bells."""
    rng = np.random.RandomState(9); b = np.zeros(int(1.2 * SR)); t = t_(0.5)
    ph = 2 * np.pi * np.cumsum(55 + 90 * np.exp(-t * 18)) / SR
    put(b, att(np.sin(ph) * np.exp(-t * 8), 2), 0, 0.90)
    put(b, filt(rng.uniform(-1, 1, len(t)), 700) * np.exp(-t * 24), 0, 0.60)
    put(b, pluck(hz(51), 0.8), 0.10, 0.55)             # Eb3
    put(b, pluck(hz(50), 0.9), 0.30, 0.60)             # D3 — a semitone drop
    return b

def save(name, sig):
    sig = sig / max(1e-9, np.abs(sig).max()) * 0.85
    n = int(0.01 * SR); sig[-n:] *= np.linspace(1, 0, n)
    os.makedirs(OUT, exist_ok=True)
    pcm = (sig * 32767).astype("<i2").tobytes()          # straight into ffmpeg: no temp file
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", "64k", f"{OUT}/{name}.mp3"], input=pcm, check=True)
    print(name, f"{len(sig) / SR:.2f}s", os.path.getsize(f"{OUT}/{name}.mp3"), "bytes")

if __name__ == "__main__":
    for name, fn in (("click", click), ("roll", roll), ("item", item), ("success", success), ("fail", fail)):
        save(name, fn())
