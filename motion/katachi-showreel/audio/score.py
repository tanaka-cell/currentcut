"""Synthesise the showreel score: 128 BPM, 32 beats, exactly 15 s.

    python3 audio/score.py            -> audio/score.wav (48 kHz, stereo, 24-bit)

Everything is generated here (no samples), and every sound effect is
placed on a cue taken from reel.js, so picture and sound share one clock.
"""

import wave
from pathlib import Path

import numpy as np
from scipy import signal

SR = 48_000
DUR = 15.0
N = int(SR * DUR)
B = 60 / 128
bt = lambda n: n * B  # noqa: E731
rng = np.random.default_rng(128)

# ─── cues mirrored from reel.js ─────────────────────────────────────────────
T = dict(
    pop=0.05, ring=bt(1), grid=bt(2), wave=1.2, line=bt(4), curve=bt(6),
    plane=bt(8), shuffle=bt(10), morph=bt(11), form=bt(12), jump=bt(14),
    push=bt(15), drop=bt(16), pull=bt(22), grid_out=bt(23), logo=bt(24),
    lock=bt(25), out=bt(30),
)
CUTS = [bt(b) for b in (17, 18, 19, 20, 20.5, 21, 21.5)]


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


class Bus:
    def __init__(self):
        self.L = np.zeros(N + SR * 3)
        self.R = np.zeros(N + SR * 3)

    def add(self, t0, x, gain=1.0, pan=0.0):
        """Place mono (or (2, n) stereo) audio at t0 seconds, equal-power pan."""
        i = int(round(t0 * SR))
        if i < 0:
            x = x[..., -i:]
            i = 0
        if x.ndim == 1:
            a = (pan + 1) * np.pi / 4
            l, r = x * np.cos(a) * np.sqrt(2), x * np.sin(a) * np.sqrt(2)
        else:
            l, r = x
        n = min(len(l), len(self.L) - i)
        if n <= 0:
            return
        self.L[i:i + n] += l[:n] * gain
        self.R[i:i + n] += r[:n] * gain

    def stereo(self):
        return np.stack([self.L, self.R])


def tt(d):
    return np.arange(int(d * SR)) / SR


def env_ad(n_or_t, a, d):
    t = n_or_t if isinstance(n_or_t, np.ndarray) else tt(n_or_t)
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-np.maximum(0, t - a) / d)


def sos(kind, f, order=2):
    return signal.butter(order, f, btype=kind, fs=SR, output='sos')


def filt(x, kind, f, order=2):
    return signal.sosfilt(sos(kind, f, order), x)


def noise(d):
    return rng.standard_normal(int(d * SR))


def sweep_filter(x, f0, f1, q=1.2, curve='exp'):
    """Time-varying resonant band-pass (Chamberlin SVF), cutoff f0 -> f1."""
    n = len(x)
    if curve == 'exp':
        fc = f0 * (f1 / f0) ** (np.arange(n) / n)
    else:
        fc = np.linspace(f0, f1, n)
    F = 2 * np.sin(np.pi * np.minimum(fc, SR / 6) / SR)
    damp = 1 / q
    low = band = 0.0
    out = np.empty(n)
    for i in range(n):
        low += F[i] * band
        high = x[i] - low - damp * band
        band += F[i] * high
        out[i] = band
    return out


# ─── instruments ────────────────────────────────────────────────────────────
def kick(amp=1.0, dec=0.32, punch=1.0):
    t = tt(0.6)
    f = 44 + 150 * np.exp(-t * 30) * punch
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-t / dec)
    click = filt(noise(0.6), 'highpass', 2500) * np.exp(-t / 0.004) * 0.35
    return np.tanh((body + click) * 1.6) * amp


def clap(amp=1.0):
    t = tt(0.4)
    n = filt(noise(0.4), 'bandpass', [900, 5200])
    e = np.zeros_like(t)
    for k, o in enumerate((0, 0.011, 0.022)):
        e += (t >= o) * np.exp(-np.maximum(0, t - o) / (0.006 if k < 2 else 0.12))
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t / 0.04) * 0.3
    return (n * e * 0.5 + tone) * amp


def hat(amp=1.0, dec=0.035):
    t = tt(0.2)
    return filt(noise(0.2), 'highpass', 7500, 4) * np.exp(-t / dec) * amp


def saw_additive(f, t, n_harm=24, bright=1.0):
    y = np.zeros_like(t)
    for h in range(1, n_harm + 1):
        if f * h > SR / 2.2:
            break
        y += np.sin(2 * np.pi * f * h * t + h * 0.7) / h * np.exp(-(h - 1) / (6 * bright))
    return y


def pad(notes, d, amp=1.0, att=0.6, rel=0.8, bright=0.7):
    t = tt(d + rel)
    L = np.zeros_like(t)
    R = np.zeros_like(t)
    for m in notes:
        f = midi(m)
        for cents, side in ((-9, 'L'), (0, 'C'), (8, 'R')):
            v = saw_additive(f * 2 ** (cents / 1200), t, 16, bright)
            if side == 'L':
                L += v
            elif side == 'R':
                R += v
            else:
                L += v * .7
                R += v * .7
    e = np.minimum(1, t / att) * np.clip((d + rel - t) / rel, 0, 1)
    k = amp / (len(notes) * 3)
    return np.stack([L * e * k, R * e * k])


def pluck(m, amp=1.0, dec=0.35):
    f = midi(m)
    t = tt(dec * 4)
    y = np.zeros_like(t)
    for h in range(1, 14):
        if f * h > SR / 2.2:
            break
        y += np.sin(2 * np.pi * f * h * t) / h * np.exp(-t * (1 / dec + h * 2.2))
    return y * np.minimum(1, t / 0.002) * amp


def string_pluck(f, d=1.2, amp=1.0):
    """Karplus-Strong, for the plucked line."""
    n = int(d * SR)
    p = int(SR / f)
    buf = rng.uniform(-1, 1, p)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = 0.996 * 0.5 * (buf[i % p] + buf[(i + 1) % p])
    return out * amp


def bell(m, amp=1.0, dec=1.6):
    f = midi(m)
    t = tt(dec * 3)
    idx = 2.2 * np.exp(-t / 0.25)
    y = np.sin(2 * np.pi * f * t + idx * np.sin(2 * np.pi * f * 3.5 * t))
    y += 0.3 * np.sin(2 * np.pi * f * 2 * t) * np.exp(-t / (dec * .4))
    return y * np.exp(-t / dec) * np.minimum(1, t / 0.003) * amp


def bass(m, d, amp=1.0):
    f = midi(m)
    t = tt(d + 0.05)
    y = saw_additive(f, t, 18, 0.5) * 0.6 + np.sin(2 * np.pi * f * t) * 0.9
    cut = 180 + 1400 * np.exp(-t / 0.06)
    # cheap filter envelope: blend a bright and a dark copy
    dark = filt(y, 'lowpass', 220, 2)
    k = np.clip((cut - 180) / 1400, 0, 1)
    y = dark * (1 - k) + y * k
    e = np.minimum(1, t / 0.004) * np.clip((d + 0.05 - t) / 0.05, 0, 1)
    return np.tanh(y * e * 1.4) * amp


def whoosh(d=0.35, f0=300, f1=4000, amp=1.0, q=1.6):
    t = tt(d)
    x = sweep_filter(noise(d), f0, f1, q)
    e = np.sin(np.pi * np.clip(t / d, 0, 1)) ** 1.5
    return x * e * amp * 0.6


def riser(d, amp=1.0):
    t = tt(d)
    x = sweep_filter(noise(d), 300, 9000, 2.2)
    f = 110 * 2 ** (np.linspace(0, 2.2, len(t)))
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.25 + np.sin(2 * np.pi * np.cumsum(f * 1.5) / SR) * 0.12
    e = (t / d) ** 2.2
    return (x * 0.7 + tone) * e * amp


def sub_drop(d=1.4, f0=70, f1=28, amp=1.0):
    t = tt(d)
    f = f1 + (f0 - f1) * np.exp(-t * 3)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.6) * np.minimum(1, t / 0.005) * amp


def impact(amp=1.0):
    t = tt(1.6)
    n = filt(noise(1.6), 'bandpass', [80, 7000]) * np.exp(-t / 0.35) * 0.35
    return (n + sub_drop(1.6, 90, 30) * 0.9) * amp


def reverse_swell(d, amp=1.0, hp=1500):
    t = tt(d)
    x = filt(noise(d), 'highpass', hp)
    return x * (t / d) ** 3 * amp


def blip(m, amp=1.0, dec=0.06):
    t = tt(dec * 5)
    f = midi(m)
    return np.sin(2 * np.pi * f * t) * np.exp(-t / dec) * np.minimum(1, t / 0.001) * amp


def pop(amp=1.0):
    t = tt(0.12)
    f = 300 + 900 * np.exp(-t * 60)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.03) * amp


def click(amp=1.0):
    t = tt(0.03)
    return filt(noise(0.03), 'bandpass', [2000, 9000]) * np.exp(-t / 0.003) * amp


def boing(m0, m1, amp=1.0, d=0.28):
    t = tt(d)
    f = midi(m0) * (midi(m1) / midi(m0)) ** np.clip(t / d, 0, 1)
    vib = 1 + 0.02 * np.sin(2 * np.pi * 18 * t)
    return np.sin(2 * np.pi * np.cumsum(f * vib) / SR) * np.exp(-t / (d * .5)) * amp


# ─── arrangement ────────────────────────────────────────────────────────────
drums, bassb, music, sfx = Bus(), Bus(), Bus(), Bus()
kicks = []

AM9 = [57, 60, 64, 67, 71]
FMAJ7 = [53, 57, 60, 64]
G6 = [55, 59, 62, 64]
CMAJ9 = [48, 55, 59, 62, 64]
BAR = 4 * B

# Intro: point, ripple, wave
sfx.add(T['pop'], pop(0.7))
sfx.add(T['pop'], click(0.4))
sfx.add(T['ring'], sub_drop(1.2, 75, 40, 0.55))
sfx.add(T['ring'], bell(81, 0.12, 0.9), pan=0.2)
blips = sorted(T['grid'] + rng.uniform(0, 1, 60) ** 1.4 * 0.5)
scale = [69, 72, 74, 76, 79, 81, 84, 86, 88, 91]
for k, tb in enumerate(blips):
    m = scale[min(len(scale) - 1, int(k / len(blips) * len(scale) + rng.integers(0, 2)))]
    sfx.add(tb, blip(m, 0.07, 0.04), pan=float(rng.uniform(-0.8, 0.8)))
music.add(0.7, pad(AM9, bt(4) - 0.7 + 0.3, 0.55, att=1.0, rel=0.5, bright=0.5))
sfx.add(T['wave'] - 0.1, whoosh(0.7, 200, 1800, 0.25, 3))

# Line: stretch, ridges, merge, graph editor
sfx.add(T['line'], whoosh(0.35, 3000, 600, 0.3, 2), pan=-0.2)
sfx.add(T['line'], whoosh(0.35, 3000, 600, 0.3, 2), pan=0.2)
music.add(bt(4), pad(FMAJ7, BAR, 0.6, att=0.1, rel=0.3, bright=0.6))
for b in (4, 5, 6, 7):
    drums.add(bt(b), kick(0.55, 0.22, 0.6))
    kicks.append((bt(b), 0.4))
for b in np.arange(4.5, 8, 1):
    drums.add(bt(b), hat(0.25), pan=0.3)
sfx.add(T['curve'] - 0.3, whoosh(0.34, 5000, 400, 0.4, 2.5))
for tc in (3.07, 3.36):
    sfx.add(tc, click(0.5), pan=-0.1)
    sfx.add(tc, blip(88, 0.1, 0.02))
for tc in (3.32, 3.56):
    sfx.add(tc, click(0.35), pan=0.1)
sfx.add(3.08, whoosh(0.24, 600, 2400, 0.12, 4), pan=-0.3)
sfx.add(3.36, whoosh(0.22, 700, 2600, 0.12, 4), pan=0.3)
sfx.add(3.66, string_pluck(midi(45), 1.6, 0.5))
sfx.add(3.66, string_pluck(midi(57), 1.2, 0.2))
drums.add(bt(7), reverse_swell(B, 0.25, 3000))

# Plane + Form: the groove arrives
chords_groove = [(bt(8), AM9, BAR), (bt(12), FMAJ7, BAR / 2), (bt(14), G6, BAR / 2),
                 (bt(16), AM9, BAR), (bt(20), FMAJ7, BAR / 2), (bt(22), G6, BAR / 2)]
roots = {id(AM9): 33, id(FMAJ7): 29, id(G6): 31}
for t0, ch, d in chords_groove:
    music.add(t0, pad(ch, d, 0.5, att=0.05, rel=0.25, bright=0.8))
    # off-beat bass
    nb = int(round(d / B))
    for k in range(nb):
        root = roots[id(ch)]
        m = root + (12 if k % 2 else 0)
        bassb.add(t0 + (k + 0.5) * B, bass(m, B * 0.42, 0.45))
for b in range(8, 24):
    drums.add(bt(b), kick(1.0 if b >= 16 else 0.85))
    kicks.append((bt(b), 0.65))
    if b % 2 == 1:
        drums.add(bt(b), clap(0.5 if b >= 16 else 0.4))
    for s in (0.5,) if b < 16 else (0.25, 0.5, 0.75):
        drums.add(bt(b + s), hat(0.18 if s == 0.5 else 0.08), pan=0.35 if s == 0.5 else -0.25)
# 16th pluck arpeggio over plane/form
arp_notes = {bt(8): AM9, bt(12): FMAJ7, bt(14): G6}
arp_t = sorted(arp_notes)
for k in range(int((bt(15) - bt(8)) / (B / 4))):
    t0 = bt(8) + k * B / 4
    ch = arp_notes[[a for a in arp_t if a <= t0 + 1e-6][-1]]
    m = ch[(k * 3) % len(ch)] + 12
    music.add(t0, pluck(m, 0.11, 0.12), pan=0.5 if k % 2 else -0.5)

sfx.add(T['plane'], impact(0.55))
sfx.add(T['plane'] - 0.02, whoosh(0.4, 120, 900, 0.5, 1.2))
for i, b in enumerate((8.5, 9, 9.5)):
    sfx.add(bt(b) - 0.06, whoosh(0.26, 500, 3500, 0.35, 1.8), pan=(-0.6, 0, 0.6)[i])
    sfx.add(bt(b) + 0.18, kick(0.35, 0.12, 0.3), pan=(-0.6, 0, 0.6)[i])
sfx.add(T['shuffle'] - 0.05, whoosh(0.45, 400, 5000, 0.4, 1.4))
sfx.add(T['morph'], boing(64, 76, 0.2, 0.3), pan=-0.4)
sfx.add(T['morph'] + 0.04, boing(67, 79, 0.18, 0.3), pan=0.4)
sfx.add(T['form'] - 0.25, reverse_swell(0.28, 0.35, 2000))
sfx.add(T['form'], bell(76, 0.12, 0.8), pan=-0.3)
sfx.add(T['form'], bell(83, 0.1, 0.8), pan=0.3)
for i, m in enumerate((72, 76, 79)):
    sfx.add(T['jump'] + i * 0.07, boing(m - 5, m + 7, 0.16, 0.26), pan=(-0.5, 0, 0.5)[i])
    sfx.add(T['jump'] + i * 0.07 + 0.4, kick(0.3, 0.1, 0.2), pan=(-0.5, 0, 0.5)[i])

# Build into the drop: riser plus a snare roll that doubles its rate
drums.add(T['push'], riser(bt(16) - T['push'], 0.55))
roll = [T['push'] + k * B / 4 for k in range(4)] + [T['push'] + B + k * B / 8 for k in range(4)]
for k, tr in enumerate(roll):
    drums.add(tr, clap(0.12 + 0.03 * k))
sfx.add(bt(16) - 0.35, whoosh(0.36, 200, 8000, 0.5, 1.2))

# Drop: montage
sfx.add(T['drop'], impact(1.0))
music.add(T['drop'], bell(81, 0.1, 1.2), pan=0.3)
for c in CUTS:
    sfx.add(c - 0.05, whoosh(0.2, 800, 6000, 0.22, 1.6), pan=float(rng.uniform(-0.5, 0.5)))
# 3-3-2 chord stabs across the montage
stab_times = [bt(bar0 + off) for bar0 in (16, 20) for off in (0, 1.5, 3)]
for s in (s for s in stab_times if s < T['pull']):
    ch = AM9 if s < bt(20) else (FMAJ7 if s < bt(22) else G6)
    for m in ch:
        music.add(s, pluck(m + 12, 0.07, 0.18), pan=float(rng.uniform(-0.3, 0.3)))

# Pull back to the grid, cells pop away, suction into the logo
sfx.add(T['pull'] - 0.02, whoosh(0.5, 6000, 300, 0.45, 1.3))
for k in range(8):
    sfx.add(T['grid_out'] + k * 0.022 + 0.12, blip(84 + k, 0.08, 0.03), pan=np.sin(k) * 0.7)
sfx.add(T['grid_out'] + 0.1, reverse_swell(T['logo'] - T['grid_out'] - 0.1, 0.45, 800))

# Logo: breakdown, three-note sonic logo, chord
music.add(T['logo'], pad(CMAJ9, BAR * 2 - 0.2, 0.7, att=0.35, rel=0.6, bright=0.55))
bassb.add(T['logo'], bass(36, BAR * 2 - 0.6, 0.3))
for i in range(3):
    sfx.add(T['logo'] + 0.08 + i * 0.05, whoosh(0.3, 400, 3000, 0.2, 1.6), pan=(-0.5, 0, 0.5)[i])
for m, tl in zip((76, 79, 84), (T['lock'] - 0.1, T['lock'] - 0.05, T['lock'])):
    sfx.add(tl, bell(m, 0.3, 1.4), pan=(m - 79) / 10)
sfx.add(T['lock'], impact(0.55))
drums.add(T['lock'], kick(0.8, 0.4))
kicks.append((T['lock'], 0.5))
for m in CMAJ9:
    music.add(T['lock'], pluck(m + 24, 0.06, 0.6), pan=float(rng.uniform(-0.6, 0.6)))
sfx.add(T['lock'] + 0.05, whoosh(0.7, 3000, 9000, 0.08, 3))
for b in (28, 29):
    drums.add(bt(b), kick(0.35, 0.18, 0.4))
    kicks.append((bt(b), 0.25))

# Outro: gather, iris, the point pops out -> loops to frame 0
sfx.add(T['out'], whoosh(0.45, 5000, 200, 0.35, 1.2))
sfx.add(T['out'] + 0.26, blip(79, 0.18, 0.05))
sfx.add(T['out'] + 0.26, kick(0.25, 0.08, 0.2))
sfx.add(T['out'] + 0.22, reverse_swell(0.42, 0.25, 600))
sfx.add(14.86, pop(0.55))
sfx.add(14.86, click(0.3))

# ─── mix ────────────────────────────────────────────────────────────────────
def reverb(x, decay=1.6, mix=0.18):
    n = int(decay * 2 * SR)
    t = np.arange(n) / SR
    out = []
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-t * 6.9 / decay)
        ir = filt(ir, 'lowpass', 6000)
        ir[: int(0.012 * SR)] = 0
        ir /= np.sqrt(np.sum(ir ** 2))
        out.append(signal.fftconvolve(x[ch], ir)[: x.shape[1]])
    return x + np.stack(out) * mix


# sidechain: duck the music under each kick
duck = np.ones(len(music.L))
tgrid = np.arange(len(duck)) / SR
for tk, depth in kicks:
    m = tgrid >= tk
    duck[m] *= 1 - depth * np.exp(-(tgrid[m] - tk) / 0.09)

mus = music.stereo() * duck * 0.9
bas = bassb.stereo() * duck
drm = drums.stereo()
fx = sfx.stereo()

mus = reverb(mus, 2.2, 0.35)
fx = reverb(fx, 1.4, 0.22)
mix = drm * 0.9 + bas * 0.8 + mus + fx * 0.9
mix = filt(mix, 'highpass', 25)
mix = mix[:, :N]

# loop hygiene: short fade-in/out so frame 0 follows frame 899 without a click
fade = int(0.004 * SR)
mix[:, :fade] *= np.linspace(0, 1, fade)
tail = int(0.08 * SR)
mix[:, -tail:] *= np.linspace(1, 0, tail) ** 2

# glue: set the level so only transient peaks reach the soft clipper,
# then peak-normalise to -1 dBFS
print(f'  pre-glue peak {np.max(np.abs(mix)):.2f}, p99.9 {np.percentile(np.abs(mix), 99.9):.2f}')
mix *= 0.85 / np.percentile(np.abs(mix), 99.9)
mix = np.tanh(mix)
mix *= 10 ** (-1 / 20) / np.max(np.abs(mix))

out = Path(__file__).with_name('score.wav')
pcm = (np.clip(mix.T, -1, 1) * (2 ** 23 - 1)).astype('<i4')
raw = np.frombuffer(pcm.tobytes(), dtype=np.uint8).reshape(-1, 4)[:, :3].tobytes()
with wave.open(str(out), 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(3)
    w.setframerate(SR)
    w.writeframes(raw)

rms = lambda a, b: 20 * np.log10(np.sqrt(np.mean(mix[:, int(a * SR):int(b * SR)] ** 2)) + 1e-9)  # noqa: E731
print(out, f'{N / SR:.3f}s')
for name, a, b in [('intro', 0, 3.75), ('plane/form', 3.75, 7.5), ('drop', 7.5, 11.25), ('logo', 11.25, 15)]:
    print(f'  {name:11s} {rms(a, b):6.1f} dBFS rms')
