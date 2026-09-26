'use strict';
// KATACHI — 15 s design-studio showreel.
// Every pixel is a pure function of time: draw(t) paints the frame at t
// seconds, so the preview player and the offline renderer share one code
// path and any frame can be rendered in any order.
(() => {

// ─── Canvas, clock, palette ──────────────────────────────────────────────
const W = 1920, H = 1080, CX = W / 2, CY = H / 2, TAU = Math.PI * 2;
const FPS = 60, DUR = 15;
const BPM = 128, B = 60 / BPM;            // 32 beats land exactly on 15 s
const bt = n => n * B;

const T = {
  pop: 0.05, ring: bt(1), grid: bt(2), wave: 1.2,
  line: bt(4), curve: bt(6),
  plane: bt(8), shuffle: bt(10), morph: bt(11),
  form: bt(12), jump: bt(14), push: bt(15),
  drop: bt(16), pull: bt(22), gridOut: bt(23),
  logo: bt(24), lock: bt(25), out: bt(30),
};

const C = {
  ink: '#0E0E10', paper: '#EFEBE3', verm: '#FF4A1C', cobalt: '#2B3BFF',
  sheet: '#F9F7F2', mute: '#8C877E', grey: '#CFCAC0',
};

// ─── Math & easing ───────────────────────────────────────────────────────
const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const lerp = (a, b, t) => a + (b - a) * t;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const E = {
  lin: x => x,
  inQuad: x => x * x,
  outQuad: x => 1 - (1 - x) * (1 - x),
  inCubic: x => x * x * x,
  outCubic: x => 1 - (1 - x) ** 3,
  inOutCubic: x => x < .5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2,
  inQuart: x => x ** 4,
  outQuart: x => 1 - (1 - x) ** 4,
  inOutQuart: x => x < .5 ? 8 * x ** 4 : 1 - (-2 * x + 2) ** 4 / 2,
  outQuint: x => 1 - (1 - x) ** 5,
  inOutQuint: x => x < .5 ? 16 * x ** 5 : 1 - (-2 * x + 2) ** 5 / 2,
  inExpo: x => x <= 0 ? 0 : 2 ** (10 * x - 10),
  outExpo: x => x >= 1 ? 1 : 1 - 2 ** (-10 * x),
  inOutExpo: x => x <= 0 ? 0 : x >= 1 ? 1 : x < .5 ? 2 ** (20 * x - 10) / 2 : (2 - 2 ** (-20 * x + 10)) / 2,
  outBack: (x, s = 1.70158) => 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2,
  inBack: (x, s = 1.70158) => (s + 1) * x ** 3 - s * x * x,
  inOutSine: x => -(Math.cos(Math.PI * x) - 1) / 2,
};
const ease = (t, a, b, fn = E.outExpo) => fn(seg(t, a, b));
// Damped spring settling from 0 to 1.
const spring = (x, f = 3.2, d = 7) => x <= 0 ? 0 : 1 - Math.exp(-d * x) * Math.cos(f * TAU * x);
// A decaying kick: 0 → 1 → 0 with a single overshoot, for squash pulses.
const kick = (x, d = 9, f = 2.2) => x <= 0 ? 0 : Math.exp(-d * x) * Math.sin(f * TAU * x);

function cubicBezier(x1, y1, x2, y2) {
  const ax = 3 * x1 - 3 * x2 + 1, bx = 3 * x2 - 6 * x1, cx = 3 * x1;
  const ay = 3 * y1 - 3 * y2 + 1, by = 3 * y2 - 6 * y1, cy = 3 * y1;
  const sx = s => ((ax * s + bx) * s + cx) * s;
  const sy = s => ((ay * s + by) * s + cy) * s;
  return x => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let lo = 0, hi = 1, s = x;
    for (let i = 0; i < 40; i++) {
      const v = sx(s);
      if (Math.abs(v - x) < 1e-6) break;
      if (v < x) lo = s; else hi = s;
      s = (lo + hi) / 2;
    }
    return sy(s);
  };
}
const bez = (p0, p1, p2, p3, s) => {
  const u = 1 - s;
  return u * u * u * p0 + 3 * u * u * s * p1 + 3 * u * s * s * p2 + s * s * s * p3;
};

function mulberry(seed) {
  return () => {
    seed |= 0; seed = seed + 0x6D2B79F5 | 0;
    let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

const hexRGB = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
const rgba = (c, a = 1) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
const mixRGB = (a, b, t) => [0, 1, 2].map(i => lerp(a[i], b[i], t));
const mix = (a, b, t, alpha = 1) => rgba(mixRGB(hexRGB(a), hexRGB(b), t), alpha);
const alpha = (h, a) => rgba(hexRGB(h), a);
// k < 1 darkens toward black, k > 1 lightens toward white.
function shade(h, k) {
  const c = hexRGB(h);
  return k < 1 ? rgba(mixRGB(c, [4, 4, 8], 1 - k)) : rgba(mixRGB(c, [255, 255, 255], k - 1));
}

// ─── Drawing helpers ─────────────────────────────────────────────────────
function font(ctx, px, fam = 'Archivo', wt = 400, style = 'normal', stretch = 'normal') {
  ctx.font = `${style} ${wt} ${px}px "${fam}"`;
  ctx.fontStretch = stretch;
}
const MONO = (ctx, px, wt = 500) => font(ctx, px, 'JetBrains Mono', wt);

function rrect(ctx, x, y, w, h, r) {
  r = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function fill(ctx, color) {
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, W, H);
}

// Radial profile of a primitive: distance from centre to its edge along
// angle th. Morphing interpolates these radii, so any primitive can melt
// into any other without point-correspondence bookkeeping.
const TRI_IN = 0.5;  // inradius / circumradius of an equilateral triangle
function radial(kind, th, size) {
  if (kind === 'circle') return size;
  if (kind === 'square') return size / Math.max(Math.abs(Math.cos(th)), Math.abs(Math.sin(th)));
  // triangle pointing up; `size` is its circumradius
  let m = -1;
  for (const n of [Math.PI / 2, Math.PI / 2 + TAU / 3, Math.PI / 2 - TAU / 3]) {
    m = Math.max(m, Math.cos(th - n));
  }
  return size * TRI_IN / m;
}
// Draw a primitive, or a morph between two, centred on (x, y).
function shapePath(ctx, x, y, a, sa, b = a, sb = sa, k = 0, rot = 0, sx = 1, sy = 1) {
  ctx.beginPath();
  if (k <= 0 || a === b && sa === sb) {
    exactShape(ctx, x, y, a, sa, rot, sx, sy);
    return;
  }
  if (k >= 1) {
    exactShape(ctx, x, y, b, sb, rot, sx, sy);
    return;
  }
  const N = 240;
  for (let i = 0; i <= N; i++) {
    const th = -Math.PI / 2 + TAU * i / N;
    const r = lerp(radial(a, th - rot, sa), radial(b, th - rot, sb), k);
    const px = x + Math.cos(th) * r * sx, py = y + Math.sin(th) * r * sy;
    i ? ctx.lineTo(px, py) : ctx.moveTo(px, py);
  }
  ctx.closePath();
}
function exactShape(ctx, x, y, kind, s, rot, sx, sy) {
  if (kind === 'circle') {
    ctx.ellipse(x, y, s * sx, s * sy, 0, 0, TAU);
    return;
  }
  const pts = kind === 'square'
    ? [[-s, -s], [s, -s], [s, s], [-s, s]]
    : [0, 1, 2].map(i => {
        const a = -Math.PI / 2 + i * TAU / 3;
        return [Math.cos(a) * s, Math.sin(a) * s];
      });
  const c = Math.cos(rot), n = Math.sin(rot);
  pts.forEach(([px, py], i) => {
    const X = x + (px * c - py * n) * sx, Y = y + (px * n + py * c) * sy;
    i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y);
  });
  ctx.closePath();
}

// Letters that roll up through a mask, one after another.
function rollText(ctx, str, x, y, o) {
  const {
    t, tIn, tOut = 1e9, size, color, fam = 'Archivo', wt = 400, style = 'normal',
    stretch = 'normal', stagger = 0.02, dur = 0.5, align = 'left', ls = 0, outDur = 0.3,
  } = o;
  if (t < tIn || t > tOut + outDur + stagger * str.length) return 0;
  font(ctx, size, fam, wt, style, stretch);
  ctx.letterSpacing = `${ls}px`;
  const full = ctx.measureText(str).width;
  const x0 = align === 'center' ? x - full / 2 : align === 'right' ? x - full : x;
  ctx.save();
  ctx.beginPath();
  ctx.rect(x0 - size, y - size * 1.02, full + size * 2, size * 1.3);
  ctx.clip();
  ctx.fillStyle = color;
  for (let k = 0; k < str.length; k++) {
    const ch = str[k];
    if (ch === ' ') continue;
    const pre = ctx.measureText(str.slice(0, k)).width;
    const pin = E.outExpo(seg(t, tIn + k * stagger, tIn + k * stagger + dur));
    const pout = E.inExpo(seg(t, tOut + k * stagger * .5, tOut + k * stagger * .5 + outDur));
    if (pin <= 0 || pout >= 1) continue;
    const dy = (1 - pin) * size * 1.15 - pout * size * 1.15;
    ctx.fillText(ch, x0 + pre, y + dy);
  }
  ctx.restore();
  ctx.letterSpacing = '0px';
  return full;
}

// Plain text with a typewriter reveal.
function typeText(ctx, str, x, y, t, t0, cps, color, px = 15, align = 'left') {
  const n = Math.floor((t - t0) * cps);
  if (n <= 0) return;
  MONO(ctx, px);
  ctx.fillStyle = color;
  ctx.textAlign = align;
  const shown = str.slice(0, n);
  ctx.fillText(shown + (n < str.length && Math.floor(t * 8) % 2 ? '▌' : ''), x, y);
  ctx.textAlign = 'left';
}

// ─── Variable-font words (Archivo, interpolated from its masters) ────────
const G = window.GLYPHS;
function avarMap(n) {
  const s = G.avar.wght;
  for (let i = 1; i < s.length; i++) {
    if (n <= s[i][0]) {
      const [a0, b0] = s[i - 1], [a1, b1] = s[i];
      return lerp(b0, b1, (n - a0) / (a1 - a0));
    }
  }
  return 1;
}
function masterWeights(wght, wdth) {
  const nw = avarMap(wght < 600 ? (wght - 600) / 500 : (wght - 600) / 300);
  const nd = wdth < 100 ? (wdth - 100) / 38 : (wdth - 100) / 25;
  const [w0, w1, fw] = nw < 0 ? [0, 1, nw + 1] : [1, 2, nw];
  const [d0, d1, fd] = nd < 0 ? [0, 1, nd + 1] : [1, 2, nd];
  return [
    [w0 * 3 + d0, (1 - fw) * (1 - fd)], [w0 * 3 + d1, (1 - fw) * fd],
    [w1 * 3 + d0, fw * (1 - fd)], [w1 * 3 + d1, fw * fd],
  ];
}
function wordLayout(word, wght, wdth) {
  const Wd = G.words[word];
  const mw = masterWeights(clamp(wght, 100, 900), clamp(wdth, 62, 125));
  let x = 0;
  const glyphs = Wd.glyphs.map((g, i) => {
    const n = Wd.masters[0].outlines[g].length;
    const pts = new Float32Array(n);
    let adv = 0, off = 0;
    for (const [mi, w] of mw) {
      if (!w) continue;
      const m = Wd.masters[mi];
      adv += m.adv[i] * w;
      off += m.off[i] * w;
      const o = m.outlines[g];
      for (let j = 0; j < n; j++) pts[j] += o[j] * w;
    }
    const gl = { g, x: x + off, adv, pts, ops: Wd.ops[g] };
    x += adv;
    return gl;
  });
  return { glyphs, width: x };
}
function glyphPath(ops, pts) {
  const p = new Path2D();
  let j = 0;
  for (const op of ops) {
    if (op === 'M') { p.moveTo(pts[j], pts[j + 1]); j += 2; }
    else if (op === 'L') { p.lineTo(pts[j], pts[j + 1]); j += 2; }
    else if (op === 'Q') { p.quadraticCurveTo(pts[j], pts[j + 1], pts[j + 2], pts[j + 3]); j += 4; }
    else if (op === 'C') { p.bezierCurveTo(pts[j], pts[j + 1], pts[j + 2], pts[j + 3], pts[j + 4], pts[j + 5]); j += 6; }
    else p.closePath();
  }
  return p;
}

// ─── Shared furniture: chapter labels, HUD ───────────────────────────────
const LABEL_Y = 988;
function sceneLabel(ctx, t, tIn, tOut, idx, word, jp, color, fast = false) {
  const st = fast ? 0.012 : 0.022, dur = fast ? 0.32 : 0.5, outDur = 0.2;
  MONO(ctx, 15);
  rollText(ctx, idx, 100, LABEL_Y - 150, {
    t, tIn, tOut, size: 15, color: alpha(color, .7), fam: 'JetBrains Mono', wt: 500,
    stagger: 0.01, dur, ls: 2, outDur,
  });
  const w = rollText(ctx, word, 96, LABEL_Y, {
    t, tIn: tIn + 0.02, tOut, size: 132, color, fam: 'Instrument Serif', style: 'italic',
    stagger: st, dur, outDur,
  });
  rollText(ctx, jp, 96 + w + 26, LABEL_Y - 6, {
    t, tIn: tIn + 0.08, tOut, size: 46, color, fam: 'Noto Sans JP', wt: 700, stagger: st, dur, outDur,
  });
}

const CHAPTERS = [
  { t0: 0.32, t1: T.line, idx: '01 / 04 — FUNDAMENTALS', w: 'Point.', jp: '点', c: C.paper },
  { t0: T.line, t1: T.plane, idx: '02 / 04 — FUNDAMENTALS', w: 'Line.', jp: '線', c: C.paper },
  { t0: T.plane, t1: T.form, idx: '03 / 04 — FUNDAMENTALS', w: 'Plane.', jp: '面', c: C.ink },
  { t0: T.form, t1: T.drop, idx: '04 / 04 — FUNDAMENTALS', w: 'Form.', jp: '形', c: C.ink },
];
function chapterLabels(ctx, t) {
  if (t > T.drop) return;
  for (const ch of CHAPTERS) {
    if (t < ch.t0 || t > ch.t1 + 0.5) continue;
    sceneLabel(ctx, t, ch.t0 + 0.03, ch.t1 - 0.24, ch.idx, ch.w, ch.jp, ch.c);
  }
}

function hudColor(t) {
  if (t < T.plane) return C.paper;
  if (t < T.drop) return C.ink;
  if (t < T.pull) {
    const k = currentMontage(t);
    return MS[k].hud;
  }
  if (t < T.logo) return C.paper;
  return C.ink;
}
function timecode(t) {
  const f = Math.round(t * FPS);
  const s = Math.floor(f / FPS), fr = f % FPS;
  return `00:00:${String(s).padStart(2, '0')}:${String(fr).padStart(2, '0')}`;
}
function hud(ctx, t) {
  const a = ease(t, 0.25, 0.6, E.outCubic) * (1 - ease(t, T.logo - 0.1, T.logo + 0.25, E.inCubic));
  if (a <= 0) return;
  const col = hudColor(t);
  ctx.save();
  ctx.globalAlpha = a * 0.8;
  ctx.strokeStyle = col;
  ctx.lineWidth = 1.5;
  const m = 44, l = 20 * ease(t, 0.25, 0.7);
  ctx.beginPath();
  for (const [x, y, dx, dy] of [[m, m, 1, 1], [W - m, m, -1, 1], [m, H - m, 1, -1], [W - m, H - m, -1, -1]]) {
    ctx.moveTo(x + dx * l, y); ctx.lineTo(x, y); ctx.lineTo(x, y + dy * l);
  }
  ctx.stroke();
  MONO(ctx, 14, 500);
  ctx.letterSpacing = '2px';
  ctx.fillStyle = col;
  ctx.globalAlpha = a * 0.8 * (1 - ease(t, T.pull, T.pull + 0.15) );
  ctx.fillText('SHOWREEL 2026', 100, 92);
  ctx.textAlign = 'right';
  ctx.fillText(`TC ${timecode(t)}`, W - 100, 92);
  ctx.fillText('DESIGN STUDIO — TOKYO', W - 100, H - 80);
  ctx.textAlign = 'left';
  ctx.letterSpacing = '0px';
  ctx.restore();
}

// ═══ ACT I — POINT → LINE (0 – 3.75 s) ═══════════════════════════════════
const SP = 60;
const DOTS = [];
for (let j = -9; j <= 9; j++) {
  for (let i = -16; i <= 16; i++) {
    DOTS.push({ i, j, x: CX + i * SP, y: CY + j * SP, d: Math.hypot(i * SP, j * SP) });
  }
}
const GRAPH = { x: 640, y: 800, w: 640, h: 520 };
const P1_LIN = [1 / 3, 1 / 3], P2_LIN = [2 / 3, 2 / 3];
const P1_EXP = [0.16, 1.0], P2_EXP = [0.30, 1.0];

function handles(t) {
  const k1 = ease(t, 3.08, 3.32, E.inOutCubic), k2 = ease(t, 3.34, 3.56, E.inOutCubic);
  return [
    [lerp(P1_LIN[0], P1_EXP[0], k1), lerp(P1_LIN[1], P1_EXP[1], k1)],
    [lerp(P2_LIN[0], P2_EXP[0], k2), lerp(P2_LIN[1], P2_EXP[1], k2)],
  ];
}
const gx = u => GRAPH.x + u * GRAPH.w, gy = v => GRAPH.y - v * GRAPH.h;

function act1(ctx, t) {
  fill(ctx, C.ink);

  // Crosshair: two hairlines with ticks every grid step; the ticks become
  // the dot field.
  const ca = 1 - ease(t, T.grid, T.grid + 0.3, E.outCubic);
  if (ca > 0 && t > 0.1) {
    const hx = 980 * ease(t, 0.1, 0.75), hy = 560 * ease(t, 0.14, 0.75);
    ctx.strokeStyle = alpha(C.paper, 0.28 * ca);
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(CX - hx, CY); ctx.lineTo(CX + hx, CY);
    ctx.moveTo(CX, CY - hy); ctx.lineTo(CX, CY + hy);
    for (let k = 1; k <= 16; k++) {
      const o = k * SP;
      if (o < hx) { ctx.moveTo(CX + o, CY - 6); ctx.lineTo(CX + o, CY + 6); ctx.moveTo(CX - o, CY - 6); ctx.lineTo(CX - o, CY + 6); }
      if (o < hy) { ctx.moveTo(CX - 6, CY + o); ctx.lineTo(CX + 6, CY + o); ctx.moveTo(CX - 6, CY - o); ctx.lineTo(CX + 6, CY - o); }
    }
    ctx.stroke();
  }

  // Coordinates readout beside the origin.
  if (t < T.line) {
    const la = 1 - ease(t, T.line - 0.25, T.line, E.inCubic);
    ctx.globalAlpha = la;
    typeText(ctx, 'x 960  y 540', CX + 30, CY - 28, t, 0.28, 40, alpha(C.paper, .75), 15);
    const n = Math.round(627 * ease(t, T.grid, T.grid + 0.5, E.lin));
    if (n > 0) {
      MONO(ctx, 15);
      ctx.fillStyle = alpha(C.verm, .95);
      ctx.fillText(`n = ${n}`, CX + 30, CY - 52);
    }
    ctx.globalAlpha = 1;
  }

  // Shockwave rings on the first two beats.
  for (const [t0, R, w] of [[T.ring, 340, 2], [T.grid, 1200, 1.5]]) {
    const p = seg(t, t0, t0 + 0.7);
    if (p <= 0 || p >= 1) continue;
    ctx.strokeStyle = alpha(C.verm, (1 - p) * 0.9);
    ctx.lineWidth = w + 6 * (1 - p);
    ctx.beginPath();
    ctx.arc(CX, CY, 16 + R * E.outCubic(p), 0, TAU);
    ctx.stroke();
  }

  if (t < T.line + 0.5) dotField(ctx, t);
  else if (t < T.curve + 0.02) ridges(ctx, t);
  if (t >= T.curve) graphEditor(ctx, t);

  // The origin dot.
  if (t < T.line + 0.35) {
    let r = 16 * E.outBack(seg(t, T.pop, T.pop + 0.45), 2.8);
    r *= 1 + 0.45 * kick(t - T.ring, 7, 1.4) + 0.3 * kick(t - T.grid, 7, 1.4);
    r = lerp(r, 2, ease(t, T.line, T.line + 0.3, E.inOutCubic));
    if (r > 0.2) {
      ctx.fillStyle = C.verm;
      ctx.beginPath();
      ctx.arc(CX, CY, r, 0, TAU);
      ctx.fill();
    }
  }
}

function dotField(ctx, t) {
  if (t < T.grid) return;
  const wave = ease(t, T.wave, T.wave + 0.35, E.inOutCubic);
  ctx.lineCap = 'round';
  for (const p of DOTS) {
    if (p.i === 0 && p.j === 0 && t < T.line + 0.2) continue;
    const ta = T.grid + p.d / 2300;
    const s = E.outBack(seg(t, ta, ta + 0.3), 3);
    if (s <= 0) continue;
    const w = Math.sin(p.d * 0.017 - (t - T.wave) * 11);
    let r = 3.4 * s * (1 + 0.85 * wave * w);
    // Point → line: each dot stretches sideways until it meets its neighbours.
    const ts = T.line + Math.abs(p.i) * 0.008;
    const k = ease(t, ts, ts + 0.24, E.inOutCubic);
    const hl = lerp(0, SP / 2 + 0.5, k);
    r = lerp(r, 1.6, k);
    const isAxis = p.j === 0;
    ctx.strokeStyle = isAxis && t > T.line ? mix(C.paper, C.verm, k) : alpha(C.paper, lerp(.9, .8, k));
    ctx.lineWidth = r * 2;
    ctx.beginPath();
    ctx.moveTo(p.x - hl, p.y);
    ctx.lineTo(p.x + hl + 0.01, p.y);
    ctx.stroke();
  }
  ctx.lineCap = 'butt';
}

// Joy-Division ridgelines that swell, then fold into a single line.
function ridges(ctx, t) {
  const amp = 120 * ease(t, T.line + 0.36, T.line + 0.62, E.outCubic);
  const rows = [];
  for (let j = -9; j <= 9; j++) rows.push(j);
  rows.sort((a, b) => (a === 0) - (b === 0) || a - b);  // centre row last
  for (const j of rows) {
    const m = ease(t, 2.5 + Math.abs(j) * 0.007, T.curve - 0.02, E.inOutExpo);
    const y0 = lerp(CY + j * SP, CY, m);
    const A = amp * (1 - m) * (0.55 + 0.45 * Math.cos(j / 9 * Math.PI / 2));
    ctx.beginPath();
    for (let x = -20; x <= W + 20; x += 8) {
      const env = Math.exp(-(((x - CX) / 360) ** 2));
      const n = (0.55 + 0.45 * Math.sin(x * 0.021 + j * 1.3 + t * 7)) *
        (0.6 + 0.4 * Math.sin(x * 0.0071 - j * 0.9 + t * 3.1));
      const y = y0 - A * env * n;
      x === -20 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    if (j !== 0) {
      ctx.save();
      ctx.lineTo(W + 20, H + 20); ctx.lineTo(-20, H + 20); ctx.closePath();
      ctx.fillStyle = C.ink;
      ctx.fill();
      ctx.restore();
    }
    ctx.strokeStyle = j === 0 ? C.verm : alpha(C.paper, .82 * (1 - ease(t, T.curve - 0.12, T.curve, E.inCubic)));
    ctx.lineWidth = j === 0 ? lerp(3.2, 4, m) : 3.2;
    ctx.stroke();
  }
}

function graphEditor(ctx, t) {
  const enter = ease(t, T.curve, T.curve + 0.32, E.inOutExpo);
  const exit = ease(t, 3.52, 3.68, E.inExpo);
  const furn = ease(t, 2.92, 3.15, E.outCubic) * (1 - ease(t, 3.46, 3.6, E.inCubic));
  const [p1, p2] = handles(t);

  // Furniture: grid, axes, labels.
  if (furn > 0) {
    ctx.save();
    ctx.globalAlpha = furn;
    ctx.strokeStyle = alpha(C.paper, .08);
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let k = 1; k < 4; k++) {
      ctx.moveTo(gx(k / 4), gy(0)); ctx.lineTo(gx(k / 4), gy(1));
      ctx.moveTo(gx(0), gy(k / 4)); ctx.lineTo(gx(1), gy(k / 4));
    }
    ctx.stroke();
    ctx.strokeStyle = alpha(C.paper, .4);
    ctx.beginPath();
    ctx.moveTo(gx(0), gy(1.08)); ctx.lineTo(gx(0), gy(0)); ctx.lineTo(gx(1.08), gy(0));
    ctx.stroke();
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(gx(0), gy(1)); ctx.lineTo(gx(1), gy(1)); ctx.lineTo(gx(1), gy(0));
    ctx.stroke();
    ctx.setLineDash([]);
    MONO(ctx, 13);
    ctx.fillStyle = alpha(C.paper, .5);
    ctx.fillText('0', gx(0) - 18, gy(0) + 20);
    ctx.fillText('1', gx(1) - 4, gy(0) + 22);
    ctx.fillText('1', gx(0) - 18, gy(1) + 5);
    ctx.fillText('TIME →', gx(1) - 48, gy(0) + 44);
    ctx.save();
    ctx.translate(gx(0) - 30, gy(0.5));
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('VALUE →', -30, 0);
    ctx.restore();
    const f = v => v.toFixed(2);
    MONO(ctx, 22, 500);
    ctx.fillStyle = alpha(C.paper, .9);
    ctx.fillText(`cubic-bezier(${f(p1[0])}, ${f(p1[1])}, ${f(p2[0])}, ${f(p2[1])})`, gx(0), gy(1) - 44);
    ctx.restore();
  }

  // The curve itself: flat line → linear diagonal → dragged into an ease.
  const N = 160;
  const pts = [];
  for (let i = 0; i <= N; i++) {
    const s = i / N;
    const lx = lerp(-40, W + 40, s), ly = CY;
    const cx = gx(bez(0, p1[0], p2[0], 1, s)), cy = gy(bez(0, p1[1], p2[1], 1, s));
    let x = lerp(lx, cx, enter), y = lerp(ly, cy, enter);
    x = lerp(x, lx, exit); y = lerp(y, ly, exit);
    // Pluck: the released string rings for a moment.
    const pl = seg(t, 3.66, 3.75);
    if (pl > 0) y += 18 * Math.sin(Math.PI * s) * Math.sin(pl * TAU * 2.5) * (1 - pl);
    pts.push([x, y]);
  }
  ctx.strokeStyle = C.verm;
  ctx.lineWidth = 4;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  pts.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
  ctx.stroke();

  // Handles.
  const ha = ease(t, 3.0, 3.16, E.outBack) * (1 - ease(t, 3.44, 3.56, E.inBack));
  if (ha > 0) {
    const A = [gx(0), gy(0)], D = [gx(1), gy(1)];
    const H1 = [gx(p1[0]), gy(p1[1])], H2 = [gx(p2[0]), gy(p2[1])];
    ctx.strokeStyle = alpha(C.paper, .6 * clamp(ha));
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(...A); ctx.lineTo(...H1);
    ctx.moveTo(...D); ctx.lineTo(...H2);
    ctx.stroke();
    const grab1 = t > 3.06 && t < 3.34, grab2 = t > 3.32 && t < 3.58;
    for (const [P, g] of [[H1, grab1], [H2, grab2]]) {
      ctx.fillStyle = g ? C.verm : C.ink;
      ctx.strokeStyle = C.paper;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(P[0], P[1], 9 * ha, 0, TAU);
      ctx.fill(); ctx.stroke();
    }
    ctx.fillStyle = C.paper;
    for (const P of [A, D]) ctx.fillRect(P[0] - 6 * ha, P[1] - 6 * ha, 12 * ha, 12 * ha);
  }

  // A ball riding the current easing, plus its 1-D preview on the right.
  const ba = ease(t, 3.05, 3.2) * (1 - ease(t, 3.44, 3.56));
  if (ba > 0) {
    const fn = cubicBezier(p1[0], p1[1], p2[0], p2[1]);
    const s = ((t - 3.05) % 0.5) / 0.5;
    const v = fn(s);
    ctx.globalAlpha = ba;
    ctx.fillStyle = C.paper;
    ctx.beginPath();
    ctx.arc(gx(s), gy(v), 7, 0, TAU);
    ctx.fill();
    ctx.strokeStyle = alpha(C.paper, .2);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(gx(1.18), gy(0)); ctx.lineTo(gx(1.18), gy(1));
    ctx.stroke();
    ctx.fillStyle = C.verm;
    ctx.beginPath();
    ctx.arc(gx(1.18), gy(v), 13, 0, TAU);
    ctx.fill();
    ctx.globalAlpha = 1;
  }

  // The designer's cursor drags each handle into place.
  const cpath = [
    [2.94, [1500, 1000]], [3.07, [gx(P1_LIN[0]), gy(P1_LIN[1])]],
    [3.32, [gx(P1_EXP[0]), gy(P1_EXP[1])]], [3.36, [gx(P2_LIN[0]), gy(P2_LIN[1])]],
    [3.56, [gx(P2_EXP[0]), gy(P2_EXP[1])]], [3.74, [1560, 1120]],
  ];
  if (t > cpath[0][0] && t < cpath[cpath.length - 1][0]) {
    let pos = cpath[0][1];
    for (let i = 1; i < cpath.length; i++) {
      const [ta, pa] = cpath[i - 1], [tb, pb] = cpath[i];
      if (t >= ta && t <= tb) {
        const dragging = i === 2 || i === 4;
        const k = dragging ? E.inOutCubic(seg(t, ta, tb)) : E.inOutQuart(seg(t, ta, tb));
        if (i === 2) pos = [gx(handles(t)[0][0]), gy(handles(t)[0][1])];
        else if (i === 4) pos = [gx(handles(t)[1][0]), gy(handles(t)[1][1])];
        else pos = [lerp(pa[0], pb[0], k), lerp(pa[1], pb[1], k)];
      }
    }
    cursor(ctx, pos[0] + 4, pos[1] + 4, t > 3.06 && t < 3.58 ? 0.9 : 1);
  }
}

function cursor(ctx, x, y, s = 1, col = C.paper, line = C.ink) {
  ctx.save();
  ctx.translate(x, y);
  ctx.scale(s * 1.5, s * 1.5);
  ctx.beginPath();
  ctx.moveTo(0, 0); ctx.lineTo(0, 22); ctx.lineTo(5.5, 16.8); ctx.lineTo(9.4, 25.5);
  ctx.lineTo(13, 24); ctx.lineTo(9.2, 15.6); ctx.lineTo(16.5, 15.6); ctx.closePath();
  ctx.fillStyle = col;
  ctx.strokeStyle = line;
  ctx.lineWidth = 1.4;
  ctx.lineJoin = 'round';
  ctx.fill(); ctx.stroke();
  ctx.restore();
}

// ═══ ACT II — PLANE (3.75 – 5.625 s) ═════════════════════════════════════
const PLANE_Y = 480;
const SHAPE_SIZE = { circle: 150, square: 135, triangle: 200 };
function planeObjects(t) {
  // [kind, colour, entry time, entry direction]
  const defs = [
    ['circle', C.ink, bt(8.5), [-1, 0]],
    ['triangle', C.paper, bt(9), [0, -1]],
    ['square', C.cobalt, bt(9.5), [0, 1]],
  ];
  const start = [560, 960, 1360];
  const shuffled = [960, 1360, 560];
  const arcs = [-150, 130, -260];
  const spins = [0, TAU / 3, Math.PI / 2];
  const settle = [0, Math.PI - TAU / 3, 0];  // finish the turn on a symmetry of the new shape
  const morphTo = ['triangle', 'square', 'circle'];
  const sh = ease(t, T.shuffle, T.shuffle + 0.42, E.inOutExpo);
  const mo = ease(t, T.morph, T.morph + 0.34, E.inOutExpo);
  return defs.map(([kind, col, te, dir], i) => {
    const pin = ease(t, te, te + 0.55, E.outExpo);
    const off = (1 - pin);
    let x = lerp(start[i], shuffled[i], sh) + dir[0] * off * 1300;
    let y = PLANE_Y + dir[1] * off * 900 + arcs[i] * Math.sin(Math.PI * sh);
    const rot = (1 - spring(seg(t, te, te + 0.9), 1.6, 5)) * 0.5 * (i % 2 ? 1 : -1) + spins[i] * sh + settle[i] * mo;
    // squash when landing / launching
    const sq = 0.14 * kick(t - te - 0.18, 10, 1.6) + 0.1 * kick(t - T.shuffle - 0.35, 10, 1.6);
    return {
      kind, to: morphTo[i], k: mo, col, x, y, rot, sx: 1 + sq, sy: 1 - sq, vis: t >= te,
    };
  });
}

function planeScene(ctx, t) {
  fill(ctx, C.ink);
  // The line swells into a plane.
  const fl = ease(t, T.plane, T.plane + 0.32, E.outExpo);
  const hh = lerp(4, H + 40, fl);
  ctx.fillStyle = C.verm;
  ctx.fillRect(0, CY - hh / 2, W, hh);

  // Swiss grid construction.
  ctx.strokeStyle = alpha(C.ink, .16);
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let c = 0; c <= 12; c++) {
    const x = 96 + c * (W - 192) / 12;
    const g = ease(t, T.plane + 0.1 + c * 0.018, T.plane + 0.55 + c * 0.018, E.outExpo);
    ctx.moveTo(x, 0); ctx.lineTo(x, H * g);
  }
  const gh = ease(t, T.plane + 0.2, T.plane + 0.7, E.outExpo);
  for (const y of [PLANE_Y - 250, PLANE_Y + 250]) {
    ctx.moveTo(0, y); ctx.lineTo(W * gh, y);
  }
  ctx.stroke();

  // Big editorial numeral.
  rollText(ctx, '03', W - 96, 356, {
    t, tIn: T.plane + 0.1, tOut: T.form - 0.2, size: 260, color: C.ink, wt: 900,
    stretch: 'expanded', align: 'right', stagger: 0.05,
  });

  for (const o of planeObjects(t)) {
    if (!o.vis) continue;
    ctx.fillStyle = o.col;
    shapePath(ctx, o.x, o.y, o.kind, SHAPE_SIZE[o.kind], o.to, SHAPE_SIZE[o.to], o.k, o.rot, o.sx, o.sy);
    ctx.fill();
  }

  // Dimension callouts that track the shapes.
  const ca = ease(t, bt(9.6), bt(9.6) + 0.3) * (1 - ease(t, T.shuffle - 0.05, T.shuffle + 0.1));
  if (ca > 0) {
    ctx.globalAlpha = ca;
    MONO(ctx, 13);
    ctx.fillStyle = C.ink;
    const labels = ['○  r = 150', '△  R = 200', '□  a = 270'];
    planeObjects(t).forEach((o, i) => {
      ctx.fillText(labels[i], o.x - 50, PLANE_Y + 250 + 30);
      ctx.fillRect(o.x - 1, PLANE_Y + 225, 2, 12);
    });
    ctx.globalAlpha = 1;
  }
}

// ═══ ACT III — FORM (5.625 – 7.5 s) ══════════════════════════════════════
function rotY([x, y, z], a) { const c = Math.cos(a), s = Math.sin(a); return [x * c + z * s, y, -x * s + z * c]; }
function rotX([x, y, z], a) { const c = Math.cos(a), s = Math.sin(a); return [x, y * c - z * s, y * s + z * c]; }
function proj(p, cam) {
  const d = p[2] - cam.z, s = cam.f / d;
  return [CX + (p[0] - cam.x) * s, CY + (p[1] - cam.y) * s, d, s];
}
const LIGHT = (() => { const v = [-0.5, -0.58, -0.643]; const n = Math.hypot(...v); return v.map(c => c / n); })();

const CUBE = {
  v: [[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1], [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]].map(p => p.map(c => c * 135)),
  f: [[0, 1, 2, 3], [4, 5, 1, 0], [3, 2, 6, 7], [1, 5, 6, 2], [4, 0, 3, 7], [5, 4, 7, 6]],
};
const PYR = {
  v: [[0, -200, 0], [-173, 100, -173], [173, 100, -173], [173, 100, 173], [-173, 100, 173]],
  f: [[0, 2, 1], [0, 3, 2], [0, 4, 3], [0, 1, 4], [1, 2, 3, 4]],
};

function drawMesh(ctx, mesh, pos, rx, ry, kz, sc, base, cam, edge = 0, ramp = null) {
  const V = mesh.v.map(([x, y, z]) => {
    let p = [x * sc[0], y * sc[1], z * kz * sc[2]];
    p = rotX(rotY(p, ry), rx);
    return [p[0] + pos[0], p[1] + pos[1], p[2] + pos[2]];
  });
  const P = V.map(p => proj(p, cam));
  const faces = mesh.f.map(f => {
    let area = 0;
    for (let i = 0; i < f.length; i++) {
      const a = P[f[i]], b = P[f[(i + 1) % f.length]];
      area += a[0] * b[1] - b[0] * a[1];
    }
    // Newell normal (inward by construction, so negate).
    let n = [0, 0, 0];
    for (let i = 0; i < f.length; i++) {
      const a = V[f[i]], b = V[f[(i + 1) % f.length]];
      n[0] += (a[1] - b[1]) * (a[2] + b[2]);
      n[1] += (a[2] - b[2]) * (a[0] + b[0]);
      n[2] += (a[0] - b[0]) * (a[1] + b[1]);
    }
    const nl = Math.hypot(...n) || 1;
    n = n.map(c => c / nl);
    const z = f.reduce((s, i) => s + V[i][2], 0) / f.length;
    return { f, area, n, z };
  }).filter(o => o.area > 0.5 && P.every(p => p[2] > 1));
  faces.sort((a, b) => b.z - a.z);
  for (const o of faces) {
    const lit = Math.max(0, -(o.n[0] * LIGHT[0] + o.n[1] * LIGHT[1] + o.n[2] * LIGHT[2]));
    const k = 0.55 + 0.7 * lit;
    ctx.fillStyle = ramp ? mix(ramp[0], ramp[1], lit) : shade(base, k);
    ctx.beginPath();
    o.f.forEach((i, j) => j ? ctx.lineTo(P[i][0], P[i][1]) : ctx.moveTo(P[i][0], P[i][1]));
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = ctx.fillStyle;
    ctx.lineWidth = 1;
    ctx.stroke();
    if (edge > 0) {
      ctx.strokeStyle = alpha(C.paper, edge);
      ctx.lineWidth = 1.5;
      ctx.stroke();
    }
  }
}

function sphere(ctx, pos, R, ry, kz, sc, cam, col) {
  const p = proj(pos, cam);
  const r = R * p[3];
  if (p[2] <= 1) return;
  const rx = r * sc[0], ryy = r * sc[1];
  ctx.save();
  ctx.beginPath();
  ctx.ellipse(p[0], p[1], rx, ryy, 0, 0, TAU);
  ctx.fillStyle = col;
  ctx.fill();
  ctx.clip();
  // terminator
  ctx.fillStyle = shade(col, 0.62);
  ctx.globalAlpha = kz;
  ctx.beginPath();
  ctx.ellipse(p[0], p[1], rx, ryy, 0, 0, TAU);
  ctx.ellipse(p[0] - rx * 0.28, p[1] - ryy * 0.3, rx * 1.02, ryy * 1.02, 0, 0, TAU);
  ctx.fill('evenodd');
  // meridians
  ctx.strokeStyle = alpha(C.paper, 0.35);
  ctx.lineWidth = 1.5;
  for (let k = 0; k < 6; k++) {
    const a = ry + k * Math.PI / 6;
    const sx = Math.sin(a);
    ctx.beginPath();
    ctx.ellipse(p[0], p[1], Math.abs(sx) * rx, ryy, 0, Math.cos(a) > 0 ? -Math.PI / 2 : Math.PI / 2, Math.cos(a) > 0 ? Math.PI / 2 : Math.PI * 1.5);
    ctx.stroke();
  }
  for (const la of [-0.5, 0, 0.5]) {
    ctx.beginPath();
    ctx.ellipse(p[0], p[1] + la * ryy * 0.9 * 1, rx * Math.cos(Math.asin(la * 0.9)), ryy * 0.18, 0, 0, Math.PI);
    ctx.stroke();
  }
  // highlight
  ctx.fillStyle = shade(col, 1.35);
  ctx.globalAlpha = 0.9 * kz;
  ctx.beginPath();
  ctx.ellipse(p[0] - rx * 0.38, p[1] - ryy * 0.42, rx * 0.13, ryy * 0.08, -0.6, 0, TAU);
  ctx.fill();
  ctx.restore();
}

function line3(ctx, a, b, cam) {
  const near = cam.z + 30;
  if (a[2] < near && b[2] < near) return;
  const cut = (p, q) => { const k = (near - p[2]) / (q[2] - p[2]); return [lerp(p[0], q[0], k), lerp(p[1], q[1], k), near]; };
  if (a[2] < near) a = cut(a, b);
  if (b[2] < near) b = cut(b, a);
  const A = proj(a, cam), Bp = proj(b, cam);
  ctx.moveTo(A[0], A[1]); ctx.lineTo(Bp[0], Bp[1]);
}

const FLOOR_Y = 250;
function formScene(ctx, t) {
  fill(ctx, C.paper);
  const lt = t - T.form;
  // camera: dolly into the cube's front face for the drop
  const pan = ease(t, T.push, T.push + 0.32, E.inOutCubic);
  const zk = E.inCubic(seg(t, T.push, T.drop));
  const dist = Math.exp(lerp(Math.log(1400 - 135), Math.log(4), zk));
  const cam = { x: lerp(0, 400, pan), y: lerp(0, -60, pan), z: -(dist + 135), f: 1400 };

  // floor grid in perspective, fading into the horizon
  const ga = ease(lt, 0.1, 0.6);
  if (ga > 0) {
    ctx.save();
    ctx.strokeStyle = alpha(C.ink, 0.22 * ga);
    ctx.lineWidth = 1;
    ctx.beginPath();
    const reach = lerp(0, 1, ease(lt, 0.08, 0.7, E.outExpo));
    for (let x = -3000; x <= 3000; x += 200) line3(ctx, [x, FLOOR_Y, -1200], [x, FLOOR_Y, lerp(-1200, 6000, reach)], cam);
    for (let z = -1200; z <= 6000; z += 200) line3(ctx, [-3000 * reach, FLOOR_Y, z], [3000 * reach, FLOOR_Y, z], cam);
    ctx.stroke();
    const hz = proj([0, FLOOR_Y, 60000], cam)[1];
    const g = ctx.createLinearGradient(0, hz - 2, 0, hz + 230);
    g.addColorStop(0, alpha(C.paper, 1));
    g.addColorStop(1, alpha(C.paper, 0));
    ctx.fillStyle = g;
    ctx.fillRect(0, hz - 400, W, 632);
    ctx.restore();
  }

  const objs = [
    { kind: 'sphere', x: -400, col: C.verm, delay: 0 },
    { kind: 'pyr', x: 0, col: C.ink, delay: 0.06 },
    { kind: 'cube', x: 400, col: C.cobalt, delay: 0.12 },
  ].map((o, i) => {
    const ex = ease(lt, 0.05 + o.delay, 0.55 + o.delay, E.outExpo);
    // hop on beat 14 with squash & stretch
    const jt = t - (T.jump + i * 0.07);
    let hop = 0, sx = 1, sy = 1;
    if (jt > -0.08 && jt < 0.5) {
      if (jt < 0) { const a = seg(jt, -0.08, 0); sy = 1 - 0.18 * Math.sin(a * Math.PI / 2); sx = 1 + 0.12 * Math.sin(a * Math.PI / 2); }
      else if (jt < 0.4) { const a = jt / 0.4; hop = 4 * a * (1 - a) * 170; const v = 1 - 2 * a; sy = 1 + 0.16 * v * v * (a < .5 ? 1 : .6); sx = 1 / Math.sqrt(sy); }
      else { const a = seg(jt, 0.4, 0.5); const q = Math.sin(a * Math.PI); sy = 1 - 0.2 * q; sx = 1 + 0.14 * q; }
    }
    const bob = Math.sin(t * 2.4 + i * 1.7) * 8 * ex;
    let ry = lerp(0, 0.62 + i * 0.25, ex) + Math.max(0, lt - 0.3) * (0.7 + i * 0.25);
    let rx = lerp(0, -0.38, ex);
    if (o.kind === 'cube') {
      // square up to the camera before the dolly hits the face
      const sq = ease(t, T.push, T.push + 0.34, E.inOutCubic);
      const target = Math.ceil(ry / (Math.PI / 2) + 0.35) * (Math.PI / 2);
      const ryPush = lerp(0.62 + 0.5 + (T.push - T.form - 0.3) * 1.2, target, 1);
      ry = lerp(ry, ryPush, sq);
      rx = lerp(rx, 0, sq);
      hop *= 1 - sq;
    }
    return { ...o, ex, hop, sx, sy, bob, ry, rx, y: -60 - hop + bob * (1 - pan) };
  });

  // shadows
  for (const o of objs) {
    const sp = proj([o.x, FLOOR_Y, 0], cam);
    if (sp[2] <= 1) continue;
    const r = 170 * sp[3] * (1 - o.hop / 500);
    ctx.fillStyle = alpha(C.ink, 0.13 * o.ex * (1 - o.hop / 300));
    ctx.beginPath();
    ctx.ellipse(sp[0], sp[1], r, r * 0.16, 0, 0, TAU);
    ctx.fill();
  }

  const order = objs.slice().sort((a, b) => Math.abs(b.x - cam.x) - Math.abs(a.x - cam.x));
  for (const o of order) {
    const pos = [o.x, o.y, 0];
    const sc = [o.sx, o.sy, 1];
    if (o.kind === 'sphere') sphere(ctx, pos, 150, o.ry * 1.6, o.ex, sc, cam, o.col);
    else if (o.kind === 'pyr') drawMesh(ctx, PYR, pos, o.rx, o.ry, o.ex, sc, o.col, cam, 0.18 * o.ex, ['#0B0B0E', '#6A6A76']);
    else drawMesh(ctx, CUBE, pos, o.rx, o.ry, o.ex, sc, o.col, cam);
  }

  // measurement annotation on the cube
  const aa = ease(lt, 0.45, 0.7) * (1 - ease(t, T.push - 0.05, T.push + 0.1));
  if (aa > 0) {
    ctx.globalAlpha = aa;
    MONO(ctx, 13);
    ctx.fillStyle = C.ink;
    ctx.strokeStyle = C.ink;
    ctx.lineWidth = 1;
    const tags = [['SPHERE  r150', -400], ['PYRAMID  h300', 0], ['CUBE  270³', 400]];
    for (const [s, x] of tags) {
      const p = proj([x, FLOOR_Y, 0], cam);
      ctx.beginPath();
      ctx.moveTo(p[0], p[1] + 14); ctx.lineTo(p[0], p[1] + 44);
      ctx.stroke();
      ctx.textAlign = 'center';
      ctx.fillText(s, p[0], p[1] + 64);
      ctx.textAlign = 'left';
    }
    ctx.globalAlpha = 1;
  }
  // the last frames are the cube face: hand over to the cobalt of the next shot
  const hand = ease(t, T.drop - 0.05, T.drop);
  if (hand > 0) fill(ctx, alpha(C.cobalt, hand));
}

// ═══ ACT IV — MONTAGE (7.5 – 11.25 s) ════════════════════════════════════
function mBrand(ctx, lt) {
  const cx = 770, cy = 470;
  const g = ease(lt, 0, 0.5);
  ctx.strokeStyle = alpha(C.paper, .45);
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(cx - 1100 * g, cy); ctx.lineTo(cx + 1100 * g, cy);
  ctx.moveTo(cx, cy - 600 * g); ctx.lineTo(cx, cy + 600 * g);
  ctx.stroke();
  const xs = [cx - 290, cx, cx + 290];
  const kinds = ['circle', 'triangle', 'square'];
  const size = { circle: 112, triangle: 150, square: 102 };
  const cols = [C.verm, C.paper, C.ink];
  ctx.setLineDash([6, 8]);
  ctx.lineDashOffset = -lt * 40;
  xs.forEach((x, i) => {
    const d = ease(lt, 0.03 + i * 0.05, 0.45 + i * 0.05, E.outCubic);
    ctx.beginPath();
    ctx.arc(x, cy, 148, -Math.PI / 2, -Math.PI / 2 + TAU * d);
    ctx.stroke();
  });
  ctx.setLineDash([]);
  // golden-ratio construction circle around the whole mark
  const d0 = ease(lt, 0.02, 0.6, E.outCubic);
  ctx.strokeStyle = alpha(C.paper, .3);
  ctx.beginPath();
  ctx.arc(cx, cy, 460, Math.PI, Math.PI + TAU * d0);
  ctx.stroke();
  xs.forEach((x, i) => {
    const s = E.outBack(seg(lt, 0.1 + i * 0.06, 0.4 + i * 0.06), 2.2);
    if (s <= 0) return;
    ctx.fillStyle = cols[i];
    shapePath(ctx, x, cy, kinds[i], size[kinds[i]] * s, kinds[i], size[kinds[i]] * s, 0, 0);
    ctx.fill();
    // anchor squares
    ctx.strokeStyle = C.paper;
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x - 5, cy - 5, 10, 10);
  });
  // dimension line
  const dl = ease(lt, 0.2, 0.5, E.outCubic);
  if (dl > 0) {
    ctx.strokeStyle = alpha(C.paper, .7);
    ctx.lineWidth = 1;
    const y = cy - 210;
    ctx.beginPath();
    ctx.moveTo(xs[0], y); ctx.lineTo(lerp(xs[0], xs[1], dl), y);
    ctx.moveTo(xs[0], y - 8); ctx.lineTo(xs[0], y + 8);
    if (dl > .98) { ctx.moveTo(xs[1], y - 8); ctx.lineTo(xs[1], y + 8); }
    ctx.stroke();
    ctx.globalAlpha = dl;
    MONO(ctx, 14);
    ctx.fillStyle = C.paper;
    ctx.fillText('1x = 290', (xs[0] + xs[1]) / 2 - 34, y - 14);
    ctx.globalAlpha = 1;
  }
  // colour chips
  const chips = [[C.verm, 'VERMILION', '#FF4A1C'], [C.paper, 'PAPER', '#EFEBE3'], [C.ink, 'INK', '#0E0E10']];
  chips.forEach(([c, n, h], i) => {
    const k = ease(lt, 0.12 + i * 0.06, 0.55 + i * 0.06, E.outExpo);
    const x = lerp(W + 40, 1440, k), y = 300 + i * 150;
    ctx.fillStyle = c;
    ctx.fillRect(x, y, 104, 104);
    ctx.strokeStyle = alpha(C.paper, .5);
    ctx.strokeRect(x + .5, y + .5, 104, 104);
    MONO(ctx, 15, 600);
    ctx.fillStyle = C.paper;
    ctx.fillText(n, x + 128, y + 40);
    MONO(ctx, 14, 400);
    ctx.fillStyle = alpha(C.paper, .7);
    ctx.fillText(h, x + 128, y + 66);
  });
}

function ballAt(lt) {
  const Tb = 0.52, vx = 720;
  const x = ((lt * vx + 760) % 2300) - 190;
  const ph = ((lt + Tb * 0.5) % Tb) / Tb;
  const h = 4 * ph * (1 - ph) * 380;
  return { x, ph, h, vy: -4 * 380 * (1 - 2 * ph) / Tb, vx };
}
function mMotion(ctx, lt) {
  const ground = 690, R = 52;
  const g = ease(lt, 0, 0.4);
  ctx.strokeStyle = C.ink;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(CX - 870 * g, ground); ctx.lineTo(CX + 870 * g, ground);
  ctx.stroke();
  // trajectory
  ctx.fillStyle = alpha(C.cobalt, .5);
  for (let k = -30; k <= 30; k++) {
    const b = ballAt(lt + k * 0.018);
    if (Math.abs(b.x - ballAt(lt).x) > 900) continue;
    ctx.beginPath();
    ctx.arc(b.x, ground - R - b.h, 2.2, 0, TAU);
    ctx.fill();
  }
  // onion skin
  for (let k = 7; k >= 1; k--) {
    const b = ballAt(Math.max(0, lt - k * 0.04));
    if (b.x > ballAt(lt).x + 5) continue;
    ctx.strokeStyle = alpha(C.ink, 0.5 - k * 0.055);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(b.x, ground - R - b.h, R, 0, TAU);
    ctx.stroke();
  }
  // the ball, squashed and stretched along its velocity
  const b = ballAt(lt);
  let sx = 1, sy = 1, ang = Math.atan2(b.vy, b.vx);
  const sp = Math.min(1, Math.hypot(b.vx, b.vy) / 3200);
  sx = 1 + 0.32 * sp * sp; sy = 1 / sx;
  let y = ground - R - b.h;
  const cd = Math.min(b.ph, 1 - b.ph);
  if (cd < 0.07) {
    const q = 1 - cd / 0.07;
    ang = 0; sx = 1 + 0.42 * q; sy = 1 - 0.34 * q;
    y = ground - R * sy;
  }
  ctx.save();
  ctx.translate(b.x, y);
  ctx.rotate(ang);
  ctx.fillStyle = C.verm;
  ctx.beginPath();
  ctx.ellipse(0, 0, R * sx, R * sy, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
  // timeline with keyframes and playhead
  const ty = 800, tl = ease(lt, 0.05, 0.45);
  ctx.globalAlpha = tl;
  ctx.strokeStyle = alpha(C.ink, .3);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(96, ty); ctx.lineTo(W - 96, ty);
  for (let x = 96; x <= W - 96; x += 36) { ctx.moveTo(x, ty - (x % 180 === 96 % 180 ? 10 : 5)); ctx.lineTo(x, ty); }
  ctx.stroke();
  ctx.fillStyle = C.ink;
  for (let x = 96 + 72; x < W - 96; x += 324) {
    ctx.save(); ctx.translate(x, ty); ctx.rotate(Math.PI / 4); ctx.fillRect(-6, -6, 12, 12); ctx.restore();
  }
  const ph = clamp(b.x, 96, W - 96);
  ctx.fillStyle = C.verm;
  ctx.fillRect(ph - 1, ty - 26, 2, 40);
  ctx.beginPath(); ctx.moveTo(ph - 8, ty - 34); ctx.lineTo(ph + 8, ty - 34); ctx.lineTo(ph, ty - 24); ctx.fill();
  MONO(ctx, 13);
  ctx.fillText(`F ${String(Math.floor(lt * 60) % 1000).padStart(3, '0')}`, ph + 12, ty - 22);
  ctx.globalAlpha = 1;
  // tiny graph editor
  const gx0 = 1500, gy0 = 290, gw = 320, gh = 150;
  const ga = ease(lt, 0.08, 0.4);
  ctx.globalAlpha = ga;
  ctx.strokeStyle = alpha(C.ink, .25);
  ctx.strokeRect(gx0, gy0 - gh, gw, gh);
  ctx.strokeStyle = C.ink;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i <= 40; i++) {
    const u = i / 40, v = Math.abs(Math.sin(u * Math.PI * 2 + 0.3));
    const x = gx0 + u * gw, y = gy0 - v * gh * .9;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  MONO(ctx, 12);
  ctx.fillStyle = alpha(C.ink, .6);
  ctx.fillText('POSITION Y — GRAPH', gx0, gy0 - gh - 12);
  const u = (b.x - 96) / (W - 192);
  if (u > 0 && u < 1) { ctx.fillStyle = C.verm; ctx.fillRect(gx0 + u * gw - 1, gy0 - gh, 2, gh); }
  ctx.globalAlpha = 1;
}

function mType(ctx, lt) {
  const wght = 500 + 400 * Math.sin(lt * 3.6 - 1.1);
  const wdth = 93.5 + 31.5 * Math.sin(lt * 2.3 + 0.2);
  const L = wordLayout('Aa', wght, wdth);
  const s = 0.64, base = 720;
  const ox = 760 - L.width * s / 2;
  // metric guides
  const gl = ease(lt, 0, 0.35);
  const metrics = [[0, 'BASELINE 0'], [528, 'X-HEIGHT 528'], [686, 'CAP 686']];
  ctx.lineWidth = 1;
  for (const [v, n] of metrics) {
    const y = base - v * s;
    ctx.strokeStyle = alpha(C.verm, .7);
    ctx.beginPath(); ctx.moveTo(96, y); ctx.lineTo(96 + (W - 192) * gl, y); ctx.stroke();
    MONO(ctx, 12);
    ctx.fillStyle = alpha(C.verm, gl);
    ctx.fillText(n, 100, y - 8);
  }
  const pin = ease(lt, 0, 0.3, E.outExpo);
  ctx.save();
  ctx.beginPath(); ctx.rect(0, 0, W, base + 2); ctx.clip();
  for (const gph of L.glyphs) {
    ctx.save();
    ctx.translate(ox + gph.x * s, base + (1 - pin) * 480);
    ctx.scale(s, -s);
    ctx.fillStyle = C.paper;
    ctx.fill(glyphPath(gph.ops, gph.pts));
    ctx.restore();
  }
  ctx.restore();
  // Bézier nodes on top: on-curve squares, off-curve circles, handles.
  const na = ease(lt, 0.1, 0.35);
  if (na > 0) {
    ctx.globalAlpha = na;
    for (const gph of L.glyphs) {
      const X = v => ox + (gph.x + v) * s, Y = v => base - v * s;
      let j = 0, prev = null, start = null;
      const on = [], off = [], hl = [];
      for (const op of gph.ops) {
        if (op === 'M') { prev = start = [X(gph.pts[j]), Y(gph.pts[j + 1])]; on.push(prev); j += 2; }
        else if (op === 'L') { prev = [X(gph.pts[j]), Y(gph.pts[j + 1])]; on.push(prev); j += 2; }
        else if (op === 'Q') {
          const c = [X(gph.pts[j]), Y(gph.pts[j + 1])], e = [X(gph.pts[j + 2]), Y(gph.pts[j + 3])];
          hl.push([prev, c, e]); off.push(c); on.push(e); prev = e; j += 4;
        } else if (op === 'Z') prev = start;
      }
      ctx.strokeStyle = alpha(C.paper, .45);
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (const [a, c, e] of hl) { ctx.moveTo(...a); ctx.lineTo(...c); ctx.lineTo(...e); }
      ctx.stroke();
      ctx.fillStyle = C.ink;
      ctx.strokeStyle = C.verm;
      ctx.lineWidth = 1.5;
      for (const p of on) { ctx.fillRect(p[0] - 4, p[1] - 4, 8, 8); ctx.strokeRect(p[0] - 4, p[1] - 4, 8, 8); }
      ctx.strokeStyle = C.paper;
      for (const p of off) { ctx.beginPath(); ctx.arc(p[0], p[1], 3.5, 0, TAU); ctx.fill(); ctx.stroke(); }
    }
    ctx.globalAlpha = 1;
  }
  // axis sliders
  const sa = ease(lt, 0.05, 0.4);
  const sliders = [['wght', wght, 100, 900], ['wdth', wdth, 62, 125]];
  sliders.forEach(([n, v, a, b], i) => {
    const x0 = 1440, x1 = 1824, y = 330 + i * 110;
    const k = ease(lt, 0.05 + i * .05, 0.45 + i * .05);
    ctx.globalAlpha = sa;
    MONO(ctx, 15, 600);
    ctx.fillStyle = C.paper;
    ctx.fillText(n.toUpperCase(), x0, y - 22);
    ctx.textAlign = 'right';
    ctx.fillText(v.toFixed(0), x1, y - 22);
    ctx.textAlign = 'left';
    ctx.strokeStyle = alpha(C.paper, .3);
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(lerp(x0, x1, k), y); ctx.stroke();
    const kx = lerp(x0, x1, (v - a) / (b - a));
    ctx.strokeStyle = C.verm;
    ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(Math.min(kx, lerp(x0, x1, k)), y); ctx.stroke();
    ctx.fillStyle = C.paper;
    ctx.beginPath(); ctx.arc(kx, y, 9 * k, 0, TAU); ctx.fill();
    ctx.globalAlpha = 1;
  });
  MONO(ctx, 13);
  ctx.fillStyle = alpha(C.paper, .55 * sa);
  ctx.fillText('ARCHIVO VARIABLE — 2 AXES', 1440, 560);
}

function mDigital(ctx, lt) {
  const up = ease(lt, 0, 0.45, E.outExpo);
  const px = 960, pw = 380, ph = 760;
  const py = 120 + (1 - up) * 300;
  ctx.save();
  ctx.translate(px, py + ph / 2);
  ctx.rotate((1 - up) * -0.12);
  ctx.translate(-px, -(py + ph / 2));
  // hard offset shadow
  ctx.fillStyle = alpha(C.ink, .25);
  rrect(ctx, px - pw / 2 + 18, py + 22, pw, ph, 58); ctx.fill();
  ctx.fillStyle = C.ink;
  rrect(ctx, px - pw / 2, py, pw, ph, 58); ctx.fill();
  const sx = px - pw / 2 + 12, sy = py + 12, sw = pw - 24, sh = ph - 24;
  ctx.fillStyle = C.sheet;
  rrect(ctx, sx, sy, sw, sh, 46); ctx.fill();
  ctx.save();
  rrect(ctx, sx, sy, sw, sh, 46); ctx.clip();
  ctx.fillStyle = C.ink;
  rrect(ctx, px - 50, sy + 12, 100, 28, 14); ctx.fill();
  font(ctx, 34, 'Archivo', 800, 'normal', 'semi-expanded');
  ctx.fillStyle = C.ink;
  ctx.fillText('Hello, Aki', sx + 28, sy + 104);
  MONO(ctx, 12);
  ctx.fillStyle = C.mute;
  ctx.fillText('TODAY · 3 TASKS', sx + 28, sy + 130);
  const cards = [[150, 180, C.cobalt], [150 + 196, 120, '#FFFFFF'], [150 + 332, 92, '#FFFFFF']];
  cards.forEach(([oy, h, c], i) => {
    const k = ease(lt, 0.06 + i * 0.05, 0.5 + i * 0.05, E.outExpo);
    const y = sy + oy + (1 - k) * 120;
    ctx.globalAlpha = k;
    ctx.fillStyle = c;
    rrect(ctx, sx + 20, y, sw - 40, h, 22); ctx.fill();
    if (i === 0) {
      const p = 0.72 * ease(lt, 0.15, 0.7, E.outCubic);
      ctx.strokeStyle = alpha(C.paper, .25); ctx.lineWidth = 10;
      ctx.beginPath(); ctx.arc(sx + 90, y + 90, 44, 0, TAU); ctx.stroke();
      ctx.strokeStyle = C.paper; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.arc(sx + 90, y + 90, 44, -Math.PI / 2, -Math.PI / 2 + TAU * p); ctx.stroke();
      ctx.lineCap = 'butt';
      font(ctx, 22, 'Archivo', 800);
      ctx.fillStyle = C.paper; ctx.textAlign = 'center';
      ctx.fillText(`${Math.round(p * 100)}%`, sx + 90, y + 98);
      ctx.textAlign = 'left';
      font(ctx, 22, 'Archivo', 700);
      ctx.fillText('Brand refresh', sx + 158, y + 80);
      MONO(ctx, 12); ctx.fillStyle = alpha(C.paper, .7);
      ctx.fillText('DUE FRI · 4 FILES', sx + 158, y + 106);
    } else if (i === 1) {
      ctx.fillStyle = C.grey;
      [0.8, 0.62, 0.7].forEach((w, r) => { rrect(ctx, sx + 44, y + 30 + r * 26, (sw - 88) * w, 12, 6); ctx.fill(); });
    } else {
      font(ctx, 22, 'Archivo', 700); ctx.fillStyle = C.ink;
      ctx.fillText('Motion', sx + 44, y + 54);
      const on = E.outBack(seg(lt, 0.32, 0.5), 2);
      const tx = sx + sw - 44 - 70, ty = y + 28;
      ctx.fillStyle = mix(C.grey, C.verm, clamp(on));
      rrect(ctx, tx, ty, 70, 38, 19); ctx.fill();
      ctx.fillStyle = '#FFFFFF';
      ctx.beginPath(); ctx.arc(tx + 19 + on * 32, ty + 19, 15, 0, TAU); ctx.fill();
    }
    ctx.globalAlpha = 1;
  });
  ctx.restore();
  ctx.restore();
  // floating chips
  const fa = ease(lt, 0.1, 0.5, E.outExpo);
  const bob = Math.sin(lt * 3) * 10;
  ctx.globalAlpha = fa;
  const bx = 430 - (1 - fa) * 200, by = 330 + bob;
  ctx.fillStyle = C.ink;
  rrect(ctx, bx + 8, by + 8, 300, 76, 38); ctx.fill();
  ctx.fillStyle = C.paper;
  rrect(ctx, bx, by, 300, 76, 38); ctx.fill();
  ctx.strokeStyle = C.ink; ctx.lineWidth = 2.5; ctx.stroke();
  font(ctx, 26, 'Archivo', 700);
  ctx.fillStyle = C.ink;
  ctx.fillText('Get started  →', bx + 40, by + 47);
  const cx0 = 1250 + (1 - fa) * 200, cy0 = 560 - bob;
  ctx.fillStyle = C.ink;
  rrect(ctx, cx0 + 8, cy0 + 8, 300, 200, 20); ctx.fill();
  ctx.fillStyle = C.paper;
  rrect(ctx, cx0, cy0, 300, 200, 20); ctx.fill();
  ctx.strokeStyle = C.ink; ctx.stroke();
  [0.45, 0.7, 0.55, 0.9, 0.75].forEach((h, i) => {
    const k = ease(lt, 0.15 + i * 0.04, 0.6 + i * 0.04, E.outExpo);
    const bh = 120 * h * k * (1 + 0.08 * Math.sin(lt * 4 + i));
    ctx.fillStyle = i === 3 ? C.verm : C.ink;
    ctx.fillRect(cx0 + 34 + i * 50, cy0 + 170 - bh, 30, bh);
  });
  ctx.globalAlpha = 1;
  // cursor taps the toggle
  const tgx = px + pw / 2 - 12 - 44 - 35, tgy = py + 12 + 482 + 47;
  const ck = ease(lt, 0.02, 0.28, E.inOutCubic);
  const cxp = lerp(1500, tgx, ck), cyp = lerp(980, tgy, ck);
  const press = 1 - 0.18 * Math.sin(Math.PI * seg(lt, 0.28, 0.4));
  const rip = seg(lt, 0.3, 0.75);
  if (rip > 0 && rip < 1) {
    ctx.strokeStyle = alpha(C.ink, 1 - rip);
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.arc(tgx, tgy, 10 + 70 * E.outCubic(rip), 0, TAU); ctx.stroke();
  }
  cursor(ctx, cxp, cyp, press, C.ink, C.paper);
}

function mEditorial(ctx, lt) {
  const x0 = 250, y0 = 96, pw = 710, ph = 760;
  const k = ease(lt, 0, 0.4, E.outExpo);
  ctx.save();
  ctx.translate(CX, y0 + ph / 2);
  ctx.scale(lerp(1.08, 1, k), lerp(1.08, 1, k));
  ctx.translate(-CX, -(y0 + ph / 2));
  ctx.fillStyle = C.sheet;
  ctx.fillRect(x0, y0, pw * 2, ph);
  const sg = ctx.createLinearGradient(CX - 60, 0, CX + 60, 0);
  sg.addColorStop(0, 'rgba(0,0,0,0)'); sg.addColorStop(0.5, 'rgba(0,0,0,.14)'); sg.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = sg; ctx.fillRect(CX - 60, y0, 120, ph);
  // grid overlay
  ctx.strokeStyle = alpha(C.cobalt, .22);
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let p = 0; p < 2; p++) for (let c = 0; c <= 6; c++) {
    const x = x0 + p * pw + 50 + c * (pw - 100) / 6;
    ctx.moveTo(x, y0); ctx.lineTo(x, y0 + ph * ease(lt, c * 0.01, 0.35 + c * 0.01));
  }
  ctx.stroke();
  MONO(ctx, 11);
  ctx.fillStyle = C.mute;
  ctx.fillText('KATACHI QUARTERLY — ISSUE 12', x0 + 50, y0 + 48);
  ctx.fillText('032', x0 + 50, y0 + ph - 30);
  ctx.textAlign = 'right';
  ctx.fillText('033', x0 + pw * 2 - 50, y0 + ph - 30);
  ctx.fillText('ESSAY', x0 + pw * 2 - 50, y0 + 48);
  ctx.textAlign = 'left';
  ['Form', 'follows', 'feeling.'].forEach((w, i) => {
    rollText(ctx, w, x0 + 46, y0 + 200 + i * 116, {
      t: lt, tIn: 0.02 + i * 0.05, size: 128, color: C.ink, fam: 'Instrument Serif',
      style: i === 2 ? 'italic' : 'normal', stagger: 0.012, dur: 0.4,
    });
  });
  const rnd = mulberry(7);
  ctx.fillStyle = alpha(C.ink, .28);
  for (let col = 0; col < 2; col++) {
    for (let r = 0; r < 9; r++) {
      const w = (col ? 0.85 : 1) * (r === 8 ? 0.5 : 0.8 + rnd() * 0.2) * 280;
      const d = ease(lt, 0.1 + r * 0.02 + col * 0.05, 0.4 + r * 0.02 + col * 0.05, E.outCubic);
      ctx.fillRect(x0 + 50 + col * 318, y0 + 560 + r * 18, w * d, 7);
    }
  }
  // right page: halftone image
  const ix = x0 + pw + 50, iy = y0 + 90, iw = pw - 100, ih = 430;
  const rv = ease(lt, 0.03, 0.4, E.outExpo);
  ctx.save();
  ctx.beginPath(); ctx.rect(ix, iy, iw, ih * rv); ctx.clip();
  ctx.fillStyle = C.verm; ctx.fillRect(ix, iy, iw, ih);
  ctx.fillStyle = C.ink;
  const sc = 20;
  for (let yy = iy + sc / 2; yy < iy + ih; yy += sc) {
    for (let xx = ix + sc / 2; xx < ix + iw; xx += sc) {
      const d = Math.hypot(xx - (ix + iw * 0.62), yy - (iy + ih * 0.55)) / 260;
      const r = clamp(1 - d + 0.12 * Math.sin(lt * 5 + xx * 0.02)) * sc * 0.48;
      if (r > 0.5) { ctx.beginPath(); ctx.arc(xx, yy, r, 0, TAU); ctx.fill(); }
    }
  }
  ctx.restore();
  MONO(ctx, 11);
  ctx.fillStyle = C.mute;
  ctx.fillText('FIG. 03 — THE SHAPE OF LIGHT', ix, iy + ih + 26);
  rollText(ctx, '“Design is how an idea', ix, iy + ih + 110, {
    t: lt, tIn: 0.12, size: 40, color: C.ink, fam: 'Instrument Serif', style: 'italic', stagger: 0.006, dur: 0.35,
  });
  rollText(ctx, 'learns to stand up.”', ix, iy + ih + 156, {
    t: lt, tIn: 0.16, size: 40, color: C.ink, fam: 'Instrument Serif', style: 'italic', stagger: 0.006, dur: 0.35,
  });
  ctx.restore();
}

function mSpatial(ctx, lt) {
  const N = 6, cell = 120, hw = cell * 0.4;
  const az = 0.62 + lt * 0.3, el = 0.58;
  const ox = 1060, oy = 600;
  const ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(el), se = Math.sin(el);
  // orthographic camera looking down at `el`; larger zr is nearer the viewer
  const P = (x, y, z) => {
    const xr = x * ca - z * sa, zr = x * sa + z * ca;
    return [ox + xr, oy + zr * se - y * ce, zr];
  };
  const rnd = mulberry(11);
  const accents = new Map([[8, C.verm], [21, C.cobalt], [27, C.verm], [14, C.ink], [33, C.cobalt]]);
  const boxes = [];
  for (let i = 0; i < N; i++) for (let j = 0; j < N; j++) {
    const id = i * N + j;
    const x = (i - (N - 1) / 2) * cell, z = (j - (N - 1) / 2) * cell;
    const rise = E.outExpo(seg(lt, (i + j) * 0.014, 0.42 + (i + j) * 0.014));
    const h = (50 + 200 * (0.5 + 0.5 * Math.sin(i * 0.9 + j * 0.7 - lt * 3.2)) + rnd() * 50) * rise;
    boxes.push({ x, z, h, col: accents.get(id), id, zr: x * sa + z * ca });
  }
  // ground grid
  ctx.strokeStyle = alpha(C.ink, .13);
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let k = -5; k <= 5; k++) {
    const a = P(k * cell, 0, -5 * cell), b = P(k * cell, 0, 5 * cell);
    const c = P(-5 * cell, 0, k * cell), d = P(5 * cell, 0, k * cell);
    ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.moveTo(c[0], c[1]); ctx.lineTo(d[0], d[1]);
  }
  ctx.stroke();
  boxes.sort((a, b) => a.zr - b.zr);
  const sides = [[[-1, -1], [1, -1], [0, -1]], [[1, -1], [1, 1], [1, 0]], [[1, 1], [-1, 1], [0, 1]], [[-1, 1], [-1, -1], [-1, 0]]];
  for (const bx of boxes) {
    if (bx.h < 1) continue;
    const base = bx.col || '#E9E5DD';
    for (const [[u0, v0], [u1, v1], [nx, nz]] of sides) {
      const nzr = nx * sa + nz * ca;
      if (nzr <= 0) continue;
      const nxr = nx * ca - nz * sa;
      const k = 0.62 + 0.28 * (nxr < 0 ? 1 : 0);
      const a0 = P(bx.x + u0 * hw, 0, bx.z + v0 * hw), a1 = P(bx.x + u1 * hw, 0, bx.z + v1 * hw);
      const b1 = P(bx.x + u1 * hw, bx.h, bx.z + v1 * hw), b0 = P(bx.x + u0 * hw, bx.h, bx.z + v0 * hw);
      ctx.fillStyle = shade(base, k);
      ctx.beginPath();
      ctx.moveTo(a0[0], a0[1]); ctx.lineTo(a1[0], a1[1]); ctx.lineTo(b1[0], b1[1]); ctx.lineTo(b0[0], b0[1]);
      ctx.closePath(); ctx.fill();
      ctx.strokeStyle = alpha(C.ink, .3); ctx.lineWidth = 1; ctx.stroke();
    }
    const top = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([u, v]) => P(bx.x + u * hw, bx.h, bx.z + v * hw));
    ctx.fillStyle = bx.col ? shade(bx.col, 1.06) : '#FFFFFF';
    ctx.beginPath();
    top.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.closePath(); ctx.fill();
    ctx.strokeStyle = alpha(C.ink, .4); ctx.stroke();
  }
  // callout
  const cA = ease(lt, 0.12, 0.4);
  const tgt = boxes.find(b => b.id === 8);
  const tp = P(tgt.x, tgt.h, tgt.z);
  ctx.globalAlpha = cA;
  ctx.strokeStyle = C.ink; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(tp[0], tp[1]); ctx.lineTo(tp[0] + 110, tp[1] - 150); ctx.lineTo(tp[0] + 330, tp[1] - 150); ctx.stroke();
  ctx.fillStyle = C.ink; ctx.beginPath(); ctx.arc(tp[0], tp[1], 5, 0, TAU); ctx.fill();
  MONO(ctx, 14, 600);
  ctx.fillText('PAVILION A — 1:200', tp[0] + 116, tp[1] - 164);
  ctx.globalAlpha = 1;
}

const MARQUEE = 'SHAPE THE UNSEEN — ';
function mCampaign(ctx, lt) {
  ctx.save();
  ctx.translate(CX, CY);
  ctx.rotate(-0.14);
  font(ctx, 150, 'Archivo', 900, 'normal', 'expanded');
  const uw = ctx.measureText(MARQUEE).width;
  const styles = ['fill', 'stroke', 'verm', 'stroke', 'fill', 'stroke', 'verm'];
  for (let r = 0; r < 7; r++) {
    const y = -560 + r * 165;
    const dir = r % 2 ? 1 : -1;
    const k = ease(lt, r * 0.02, 0.45 + r * 0.02, E.outExpo);
    let off = ((lt * 700 * dir + r * 333) % uw + uw) % uw;
    off += (1 - k) * 900 * dir;
    const st = styles[r];
    ctx.lineWidth = 2.5;
    for (let x = -1500 - uw + off; x < 1500; x += uw) {
      if (st === 'stroke') { ctx.strokeStyle = alpha(C.paper, .8); ctx.strokeText(MARQUEE, x, y); }
      else { ctx.fillStyle = st === 'verm' ? C.verm : C.paper; ctx.fillText(MARQUEE, x, y); }
    }
  }
  ctx.restore();
  // rotating badge
  const bs = E.outBack(seg(lt, 0.08, 0.4), 2);
  if (bs > 0) {
    const bx = 1540, by = 330, R = 130 * bs;
    ctx.fillStyle = C.paper;
    ctx.beginPath(); ctx.arc(bx, by, R, 0, TAU); ctx.fill();
    ctx.fillStyle = C.verm;
    shapePath(ctx, bx, by, 'triangle', 44 * bs); ctx.fill();
    MONO(ctx, 17, 700);
    ctx.fillStyle = C.ink;
    const txt = 'KATACHI · NEW SEASON · 2026 · ';
    const step = TAU / txt.length;
    for (let i = 0; i < txt.length; i++) {
      const a = lt * 1.2 + i * step;
      ctx.save();
      ctx.translate(bx + Math.cos(a) * R * 0.76, by + Math.sin(a) * R * 0.76);
      ctx.rotate(a + Math.PI / 2);
      ctx.fillText(txt[i], -5, 0);
      ctx.restore();
    }
  }
}

function odometer(ctx, str, x, y, size, lt, delay) {
  font(ctx, size, 'Archivo', 900, 'normal', 'expanded');
  let cx = x;
  const h = size * 0.86;
  ctx.save();
  ctx.beginPath(); ctx.rect(x - 20, y - h - 10, 2000, h + 34); ctx.clip();
  [...str].forEach((ch, i) => {
    const w = ctx.measureText(ch).width;
    if (/\d/.test(ch)) {
      const target = +ch + 10 * (2 + i);
      const v = target * E.outExpo(seg(lt, delay + i * 0.05, delay + 0.7 + i * 0.05));
      const d0 = Math.floor(v), f = v - d0;
      ctx.fillText(String(d0 % 10), cx, y - f * (h + 20));
      ctx.fillText(String((d0 + 1) % 10), cx, y + (1 - f) * (h + 20));
    } else {
      const k = ease(lt, delay + 0.3, delay + 0.6, E.outBack);
      ctx.fillText(ch, cx, y + (1 - k) * (h + 20));
    }
    cx += w;
  });
  ctx.restore();
}
function mNumbers(ctx, lt) {
  const cols = [['12', 'YEARS'], ['340+', 'PROJECTS'], ['46', 'AWARDS']];
  const xs = [100, 500, 1270];
  const rl = ease(lt, 0, 0.4);
  ctx.fillStyle = C.ink;
  ctx.fillRect(96, 250, (W - 192) * rl, 2);
  MONO(ctx, 14, 600);
  ctx.fillText('SINCE 2014 — TOKYO / REMOTE', 100, 230);
  cols.forEach(([n, l], i) => {
    ctx.fillStyle = C.ink;
    odometer(ctx, n, xs[i], 560, 210, lt, i * 0.04);
    const la = ease(lt, 0.1 + i * 0.04, 0.4 + i * 0.04);
    ctx.globalAlpha = la;
    MONO(ctx, 18, 600);
    ctx.letterSpacing = '4px';
    ctx.fillText(l, xs[i] + 4, 630);
    ctx.letterSpacing = '0px';
    ctx.globalAlpha = 1;
  });
}

const MS = [
  { draw: mBrand, bg: C.cobalt, hud: C.paper, lab: C.paper, t: bt(16), w: 'Brand Identity', jp: 'ブランディング' },
  { draw: mMotion, bg: C.paper, hud: C.ink, lab: C.ink, t: bt(17), w: 'Motion', jp: 'モーション', tr: 'circle' },
  { draw: mType, bg: C.ink, hud: C.paper, lab: C.paper, t: bt(18), w: 'Typography', jp: 'タイポグラフィ', tr: 'slideUp' },
  { draw: mDigital, bg: C.verm, hud: C.ink, lab: C.ink, t: bt(19), w: 'Digital Product', jp: 'デジタル', tr: 'diamond' },
  { draw: mEditorial, bg: C.ink, hud: C.paper, lab: C.paper, t: bt(20), w: 'Editorial', jp: 'エディトリアル', tr: 'slideLeft' },
  { draw: mSpatial, bg: C.paper, hud: C.ink, lab: C.ink, t: bt(20.5), w: 'Spatial', jp: '空間', tr: 'tri' },
  { draw: mCampaign, bg: C.cobalt, hud: C.paper, lab: C.paper, t: bt(21), w: 'Campaign', jp: 'キャンペーン', tr: 'slideDown' },
  { draw: mNumbers, bg: C.verm, hud: C.ink, lab: C.ink, t: bt(21.5), w: 'Track Record', jp: '実績', tr: 'circle' },
];
function currentMontage(t) {
  let k = 0;
  for (let i = 0; i < MS.length; i++) if (t >= MS[i].t) k = i;
  return k;
}
function drawShot(ctx, k, lt) {
  const m = MS[k];
  fill(ctx, m.bg);
  ctx.save();
  m.draw(ctx, lt);
  ctx.restore();
  const idx = `S—${String(k + 1).padStart(2, '0')} / 08 — WHAT WE SHAPE`;
  sceneLabel(ctx, lt, 0, 1e9, idx, m.w, m.jp, m.lab, k >= 4);
}

function transition(ctx, type, p, prev, next) {
  if (p >= 1) { next(); return; }
  if (type.startsWith('slide')) {
    const [dx, dy] = { slideUp: [0, -1], slideDown: [0, 1], slideLeft: [-1, 0] }[type];
    ctx.save(); ctx.translate(dx * W * p, dy * H * p); prev(); ctx.restore();
    ctx.save(); ctx.translate(dx * W * (p - 1), dy * H * (p - 1)); next(); ctx.restore();
    return;
  }
  prev();
  ctx.save();
  ctx.beginPath();
  if (type === 'circle') ctx.arc(CX, CY, p * 1130, 0, TAU);
  else if (type === 'diamond') exactShape(ctx, CX, CY, 'square', p * 1520, Math.PI / 4 + p * Math.PI / 2, 1, 1);
  else exactShape(ctx, CX, CY, 'triangle', p * 2300, p * TAU / 3, 1, 1);
  ctx.clip();
  next();
  ctx.restore();
}

// 3×3 contact-sheet grid; the centre cell holds the logo shot.
const CELL = { w: 560, h: 315, gap: 24 };
const GRID_ORDER = [0, 1, 2, 3, 'logo', 4, 5, 6, 7];
function cellRect(n) {
  const c = n % 3, r = Math.floor(n / 3);
  const x0 = (W - (CELL.w * 3 + CELL.gap * 2)) / 2, y0 = (H - (CELL.h * 3 + CELL.gap * 2)) / 2;
  return [x0 + c * (CELL.w + CELL.gap), y0 + r * (CELL.h + CELL.gap), CELL.w, CELL.h];
}
function viewLerp(a, b, e) {
  // zoom between two view rects about their shared fixed point
  const wv = Math.exp(lerp(Math.log(a[2]), Math.log(b[2]), e));
  const k = (wv - a[2]) / (b[2] - a[2] || 1);
  return [lerp(a[0], b[0], k), lerp(a[1], b[1], k), wv, wv * H / W];
}

function montage(ctx, t) {
  if (t < T.pull) {
    const k = currentMontage(t);
    const m = MS[k];
    const lt = t - m.t;
    const td = k >= 4 ? 0.2 : 0.26;
    if (k > 0 && lt < td) {
      const p = m.tr.startsWith('slide') ? E.inOutQuart(seg(lt, -0.02, td)) : E.outExpo(seg(lt, 0, td));
      transition(ctx, m.tr, p, () => drawShot(ctx, k - 1, t - MS[k - 1].t), () => drawShot(ctx, k, lt));
    } else drawShot(ctx, k, lt);
    return;
  }
  fill(ctx, '#18181C');
  const full = [0, 0, W, H];
  let view;
  if (t < T.gridOut + 0.1) view = viewLerp(cellRect(8), full, ease(t, T.pull, T.pull + 0.44, E.inOutExpo));
  else view = viewLerp(full, cellRect(4), ease(t, T.gridOut + 0.13, T.logo, E.inOutExpo));
  const vs = W / view[2];
  const order = [0, 1, 2, 5, 8, 7, 6, 3];
  GRID_ORDER.forEach((id, n) => {
    const [x, y, w, h] = cellRect(n);
    let s = 1;
    if (id !== 'logo') {
      const d = T.gridOut + order.indexOf(n) * 0.022;
      s = 1 - E.inBack(seg(t, d, d + 0.22), 2.2);
      if (s <= 0.001) return;
    }
    ctx.save();
    ctx.translate((x + w / 2 - view[0]) * vs, (y + h / 2 - view[1]) * vs);
    ctx.scale(vs * s * w / W, vs * s * h / H);
    ctx.translate(-W / 2, -H / 2);
    const rad = id === 'logo' ? 36 * (1 - ease(t, T.logo - 0.2, T.logo)) : 36;
    rrect(ctx, 0, 0, W, H, rad);
    ctx.clip();
    if (id === 'logo') logoScene(ctx, t);
    else drawShot(ctx, id, t - MS[id].t);
    ctx.restore();
    ctx.save();
    ctx.translate((x + w / 2 - view[0]) * vs, (y + h / 2 - view[1]) * vs);
    ctx.scale(vs * s * w / W, vs * s * h / H);
    ctx.translate(-W / 2, -H / 2);
    rrect(ctx, 0, 0, W, H, rad);
    ctx.restore();
    ctx.strokeStyle = alpha(C.paper, 0.16 * (id === 'logo' ? 1 - ease(t, T.logo - 0.2, T.logo) : 1));
    ctx.lineWidth = 1.5;
    ctx.stroke();
  });
}

// ═══ ACT V — LOGO & END CARD (11.25 – 15 s) ══════════════════════════════
const MARK = [
  { kind: 'circle', col: C.verm, s0: 78, s1: 52, land: T.lock - 0.1 },
  { kind: 'triangle', col: C.cobalt, s0: 100, s1: 66, land: T.lock - 0.05 },
  { kind: 'square', col: C.ink, s0: 70, s1: 47, land: T.lock },
];
const MARK_Y = 318, MARK_GAP = 132;
function markState(t, i) {
  const m = MARK[i];
  const pre = [CX - 200 + i * 200, CY];
  const fin = [CX + (i - 1) * MARK_GAP, MARK_Y];
  const launch = T.logo + 0.08 + i * 0.05;
  const k = seg(t, launch, m.land);
  const e = E.inOutCubic(k);
  let x = lerp(pre[0], fin[0], e);
  let y = lerp(pre[1], fin[1], e) - Math.sin(Math.PI * k) * 170;
  let s = lerp(m.s0, m.s1, e);
  let rot = [0, TAU / 3, Math.PI / 2][i] * E.inOutCubic(k);
  let sx = 1, sy = 1;
  // idle breathing before launch
  if (t < launch) {
    const b = Math.sin(t * 3 + i * 1.3);
    y += b * 6;
    const an = seg(t, launch - 0.1, launch);
    sy = 1 - 0.22 * Math.sin(an * Math.PI / 2); sx = 1 + 0.16 * Math.sin(an * Math.PI / 2);
  } else if (k > 0 && k < 1) {
    const v = Math.abs(Math.cos(Math.PI * k));
    sy = 1 + 0.12 * (1 - v); sx = 1 / sy;
  }
  // landing squash + beat pulses on the end card
  const land = kick(t - m.land, 8, 1.8) * 0.28;
  let pulse = 0;
  for (const b of [28, 29]) pulse += kick(t - bt(b) - i * 0.06, 9, 1.5) * 0.12;
  sx += land + pulse; sy -= land + pulse * 0.6;
  return { ...m, x, y, s, rot, sx, sy };
}

function logoScene(ctx, t) {
  fill(ctx, C.paper);
  const out = T.out;
  // Outro: triangle and square fold into the circle, the circle carries
  // itself to the centre, and the iris closes on it.
  const absorb = ease(t, out + 0.02, out + 0.26, E.inCubic);
  const move = ease(t, out + 0.16, out + 0.48, E.inOutCubic);
  const iris = ease(t, out + 0.22, out + 0.64, E.inOutExpo);

  // wordmark — Archivo morphing from condensed to extended while it rises
  const wd = lerp(62, 125, ease(t, T.lock - 0.05, T.lock + 0.62, E.inOutQuart));
  const wg = lerp(600, 900, ease(t, T.lock - 0.05, T.lock + 0.4, E.outCubic));
  const L = wordLayout('KATACHI', wg, wd);
  const s = 0.205, base = 590;
  const ox = CX - L.width * s / 2;
  if (t > T.lock - 0.1) {
    ctx.save();
    ctx.beginPath(); ctx.rect(0, base - 700 * s * 1.15, W, 700 * s * 1.15 + 4); ctx.clip();
    L.glyphs.forEach((g, i) => {
      const pin = ease(t, T.lock - 0.08 + i * 0.035, T.lock + 0.45 + i * 0.035, E.outExpo);
      const pout = ease(t, out - 0.1 + i * 0.02, out + 0.12 + i * 0.02, E.inCubic);
      const dy = (1 - pin) * 170 + pout * 170;
      ctx.save();
      ctx.translate(ox + g.x * s, base + dy);
      ctx.scale(s, -s);
      ctx.fillStyle = C.ink;
      ctx.fill(glyphPath(g.ops, g.pts));
      ctx.restore();
    });
    ctx.restore();
  }

  // descriptor + taglines
  if (t > T.lock) {
    const tOut = out - 0.12;
    const la = ease(t, T.lock + 0.35, T.lock + 0.8, E.outCubic);
    const oa = 1 - ease(t, out - 0.06, out + 0.1, E.inCubic);
    ctx.save();
    ctx.globalAlpha = la * oa;
    ctx.strokeStyle = C.ink;
    ctx.lineWidth = 1.5;
    const rw = 560 * E.outExpo(la);
    ctx.beginPath(); ctx.moveTo(CX - rw, 640); ctx.lineTo(CX + rw, 640); ctx.stroke();
    MONO(ctx, 14, 600);
    ctx.letterSpacing = '5px';
    ctx.fillStyle = C.ink;
    ctx.textAlign = 'center';
    ctx.fillText('DESIGN STUDIO  ·  TOKYO  ·  EST. 2014', CX, 676);
    ctx.textAlign = 'left';
    ctx.letterSpacing = '0px';
    ctx.restore();
    rollText(ctx, '見えないものに、かたちを。', CX, 790, {
      t, tIn: T.lock + 0.45, tOut, size: 50, color: C.ink, fam: 'Noto Sans JP', wt: 700,
      align: 'center', stagger: 0.028, dur: 0.55, ls: 4, outDur: 0.2,
    });
    rollText(ctx, 'Giving shape to the unseen.', CX, 856, {
      t, tIn: T.lock + 0.7, tOut, size: 42, color: '#6E695F', fam: 'Instrument Serif', style: 'italic',
      align: 'center', stagger: 0.012, dur: 0.5, outDur: 0.2,
    });
    const fa = ease(t, T.lock + 0.9, T.lock + 1.3) * oa;
    ctx.globalAlpha = fa;
    MONO(ctx, 13, 500);
    ctx.letterSpacing = '3px';
    ctx.fillStyle = alpha(C.ink, .55);
    ctx.textAlign = 'center';
    ctx.fillText('BRANDING  /  MOTION  /  DIGITAL  /  EDITORIAL  /  SPATIAL', CX, H - 84);
    ctx.textAlign = 'left';
    ctx.letterSpacing = '0px';
    ctx.globalAlpha = 1;
  }

  // the mark
  const states = [0, 1, 2].map(i => markState(t, i));
  const c0 = states[0];
  const gulp = kick(t - out - 0.26, 9, 1.6) * 0.3;
  const dot = {
    x: lerp(c0.x, CX, move), y: lerp(c0.y, CY, move), r: lerp(c0.s, 70, move),
    sx: c0.sx + gulp, sy: c0.sy - gulp * 0.7,
  };
  states.forEach((st, i) => {
    let { x, y, s: sz, rot, sx, sy } = st;
    if (i > 0) {
      x = lerp(x, dot.x, absorb);
      y = lerp(y, dot.y, absorb);
      sz *= 1 - absorb;
      if (sz <= 0.5) return;
    } else {
      ({ x, y, r: sz, sx, sy } = dot);
    }
    ctx.fillStyle = st.col;
    shapePath(ctx, x, y, st.kind, sz, st.kind, sz, 0, rot, sx, sy);
    ctx.fill();
  });

  // iris closes on the point, leaving it alone on ink — frame 0 again
  if (iris > 0) {
    const R = lerp(1250, 0, iris);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.arc(dot.x, dot.y, Math.max(0, R), 0, TAU, true);
    ctx.fillStyle = C.ink;
    ctx.fill('evenodd');
    ctx.restore();
    // the same circle, redrawn above the ink, settles to frame 0's size
    let r = lerp(dot.r, 16, ease(t, out + 0.4, out + 0.64, E.inOutCubic));
    r *= 1 + 0.35 * Math.sin(Math.PI * seg(t, 14.64, 14.76));
    r *= 1 - E.inBack(seg(t, 14.74, 14.92), 2.5);
    if (r > 0.1) {
      ctx.fillStyle = C.verm;
      ctx.beginPath(); ctx.ellipse(dot.x, dot.y, r * dot.sx, r * dot.sy, 0, 0, TAU); ctx.fill();
    }
  }
}

// ─── Master timeline ─────────────────────────────────────────────────────
// Camera shake on the three big hits; the frame zooms just enough to hide
// the edges it would otherwise reveal.
function shake(t) {
  let x = 0, y = 0;
  for (const [t0, a] of [[T.plane, 9], [T.drop, 14], [T.lock, 7]]) {
    const d = t - t0;
    if (d < 0 || d > 0.4) continue;
    const e = a * Math.exp(-d * 13);
    x += e * Math.sin(d * 97 + t0);
    y += e * Math.cos(d * 83 + t0 * 2);
  }
  return [x, y];
}
function draw(ctx, t) {
  ctx.save();
  const [sx, sy] = shake(t);
  if (sx || sy) {
    const z = 1 + Math.max(2 * Math.abs(sx) / W, 2 * Math.abs(sy) / H) + 0.001;
    ctx.translate(CX + sx, CY + sy);
    ctx.scale(z, z);
    ctx.translate(-CX, -CY);
  }
  if (t < T.plane) act1(ctx, t);
  else if (t < T.form) planeScene(ctx, t);
  else if (t < T.drop) {
    const ir = ease(t, T.form, T.form + 0.26, E.inOutExpo);
    if (ir < 1) {
      planeScene(ctx, t);
      ctx.save();
      ctx.beginPath(); ctx.arc(CX, PLANE_Y, ir * 1250, 0, TAU); ctx.clip();
      formScene(ctx, t);
      ctx.restore();
    } else formScene(ctx, t);
  } else if (t < T.logo) montage(ctx, t);
  else logoScene(ctx, t);
  chapterLabels(ctx, t);
  hud(ctx, t);
  ctx.restore();
}

// ─── Film grain (applied after motion blur so it stays crisp) ────────────
const grainTile = (() => {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d');
  const img = g.createImageData(256, 256);
  const r = mulberry(1234);
  for (let i = 0; i < img.data.length; i += 4) {
    const v = 128 + (r() + r() + r() - 1.5) * 120;
    img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
    img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  return c;
})();
function grain(ctx, frame) {
  const r = mulberry(frame * 7919 + 17);
  const pat = ctx.createPattern(grainTile, 'repeat');
  ctx.save();
  ctx.globalCompositeOperation = 'overlay';
  ctx.globalAlpha = 0.09;
  ctx.translate(-Math.floor(r() * 256), -Math.floor(r() * 256));
  ctx.fillStyle = pat;
  ctx.fillRect(0, 0, W + 256, H + 256);
  ctx.restore();
}

// ─── Output: offline renderer + live preview ─────────────────────────────
const stage = document.getElementById('stage');
const out = stage.getContext('2d');
const work = document.createElement('canvas');
work.width = W; work.height = H;
const wctx = work.getContext('2d');

// Motion blur: average `sub` samples across a 180° shutter.
function renderFrame(frame, sub = 10, shutter = 0.5) {
  const t0 = frame / FPS;
  for (let s = 0; s < sub; s++) {
    const dt = sub > 1 ? ((s + 0.5) / sub - 0.5) * shutter / FPS : 0;
    const t = ((t0 + dt) % DUR + DUR) % DUR;
    wctx.setTransform(1, 0, 0, 1, 0, 0);
    draw(wctx, t);
    out.globalAlpha = 1 / (s + 1);
    out.drawImage(work, 0, 0);
  }
  out.globalAlpha = 1;
  grain(out, frame);
}

const FONTS = [
  ['Archivo', 'fonts/archivo-var.woff2', { weight: '100 900', stretch: '62% 125%' }],
  ['Instrument Serif', 'fonts/instrument-serif.woff2', { style: 'normal' }],
  ['Instrument Serif', 'fonts/instrument-serif-italic.woff2', { style: 'italic' }],
  ['JetBrains Mono', 'fonts/jetbrains-mono-var.woff2', { weight: '100 800' }],
  ['Noto Sans JP', 'fonts/noto-sans-jp-700-subset.woff2', { weight: '700' }],
];
const ready = Promise.all(FONTS.map(async ([fam, url, desc]) => {
  const f = new FontFace(fam, `url(${url})`, desc);
  await f.load();
  document.fonts.add(f);
}));

window.REEL = { ready, renderFrame, FPS, DUR, frames: FPS * DUR, W, H, T, B };

if (new URLSearchParams(location.search).has('render')) {
  document.body.classList.add('render');
  return;
}

// Preview: audio is the clock when it is available.
const audio = document.getElementById('score');
const btn = document.getElementById('play');
const bar = document.getElementById('bar'), fillEl = document.getElementById('fill');
const tcEl = document.getElementById('tc');
let playing = false, startWall = 0, pausedAt = 0, audioOK = true;
audio.addEventListener('error', () => { audioOK = false; });
const now = () => playing
  ? (audioOK && !audio.paused ? audio.currentTime : (performance.now() - startWall) / 1000)
  : pausedAt;
function setPlaying(p) {
  playing = p;
  btn.textContent = p ? '❚❚ pause' : '▶ play';
  if (p) {
    startWall = performance.now() - pausedAt * 1000;
    if (audioOK) { audio.currentTime = pausedAt; audio.play().catch(() => { audioOK = false; }); }
  } else {
    pausedAt = now();
    audio.pause();
  }
}
btn.onclick = () => setPlaying(!playing);
bar.onclick = e => {
  const r = bar.getBoundingClientRect();
  pausedAt = clamp((e.clientX - r.left) / r.width) * DUR;
  startWall = performance.now() - pausedAt * 1000;
  if (audioOK) audio.currentTime = pausedAt;
};
document.addEventListener('keydown', e => {
  if (e.code === 'Space') { e.preventDefault(); setPlaying(!playing); }
  if (!playing && (e.code === 'ArrowRight' || e.code === 'ArrowLeft')) {
    pausedAt = clamp(pausedAt + (e.code === 'ArrowRight' ? 1 : -1) / FPS, 0, DUR - 1 / FPS);
  }
});
audio.addEventListener('ended', () => { pausedAt = 0; setPlaying(true); });
ready.then(() => {
  const loop = () => {
    let t = now();
    if (playing && t >= DUR) { pausedAt = 0; startWall = performance.now(); if (audioOK) { audio.currentTime = 0; audio.play(); } t = 0; }
    const f = Math.min(Math.floor(t * FPS), FPS * DUR - 1);
    renderFrame(f, 1);
    fillEl.style.width = `${(t / DUR) * 100}%`;
    tcEl.textContent = timecode(t);
    requestAnimationFrame(loop);
  };
  loop();
});
})();
