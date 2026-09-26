// Offline renderer: drives reel.js frame by frame in headless Chromium and
// pipes the frames into ffmpeg. The composition is a pure function of time,
// so frames can be split across workers and rendered in any order.
//
//   node render.mjs                       full 1080p60 render with audio
//   node render.mjs --stills 0.5,3.2      PNG stills at those times
//   node render.mjs --sheet               contact sheet of the whole reel
//   options: --workers N  --sub N (motion-blur samples, default 10)  --out path
import { spawn } from 'node:child_process';
import { createReadStream, existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { dirname, extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ROOT = dirname(fileURLToPath(import.meta.url));

function loadPlaywright() {
  for (const p of ['playwright', '/opt/node22/lib/node_modules/playwright']) {
    try { return require(p); } catch { /* try next */ }
  }
  throw new Error('playwright not found (npm i -g playwright)');
}
function ffmpegBin() {
  if (process.env.FFMPEG) return process.env.FFMPEG;
  try {
    const { execSync } = require('node:child_process');
    return execSync('python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"').toString().trim();
  } catch { return 'ffmpeg'; }
}

const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf(`--${name}`);
  if (i < 0) return def;
  const v = args[i + 1];
  return v === undefined || v.startsWith('--') ? true : v;
};

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.woff2': 'font/woff2', '.wav': 'audio/wav', '.png': 'image/png' };
function serve() {
  const srv = createServer((req, res) => {
    const p = join(ROOT, decodeURIComponent(new URL(req.url, 'http://x').pathname));
    if (!p.startsWith(ROOT) || !existsSync(p)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'content-type': TYPES[extname(p)] || 'application/octet-stream' });
    createReadStream(p).pipe(res);
  });
  return new Promise(ok => srv.listen(0, '127.0.0.1', () => ok(srv)));
}

async function openPage(browser, port) {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  page.on('pageerror', e => { console.error('page error:', e.message); process.exitCode = 1; });
  page.on('console', m => { if (m.type() === 'error') console.error('console:', m.text()); });
  await page.goto(`http://127.0.0.1:${port}/index.html?render`);
  await page.evaluate(() => window.REEL.ready);
  return page;
}

async function grab(page, frame, sub) {
  await page.evaluate(([f, s]) => window.REEL.renderFrame(f, s), [frame, sub]);
  return page.screenshot({ type: 'png', clip: { x: 0, y: 0, width: 1920, height: 1080 } });
}

function ff(argv, label) {
  const p = spawn(ffmpegBin(), ['-hide_banner', '-loglevel', 'error', '-y', ...argv], { stdio: ['pipe', 'inherit', 'inherit'] });
  const done = new Promise((ok, bad) => p.on('close', c => c === 0 ? ok() : bad(new Error(`${label}: ffmpeg exited ${c}`))));
  return { stdin: p.stdin, done };
}
const write = (stream, buf) => new Promise(ok => stream.write(buf) ? ok() : stream.once('drain', ok));

async function main() {
  const { chromium } = loadPlaywright();
  const srv = await serve();
  const port = srv.address().port;
  const browser = await chromium.launch({
    args: ['--force-color-profile=srgb', '--disable-lcd-text', '--font-render-hinting=none'],
  });
  const outDir = join(ROOT, 'out');
  mkdirSync(outDir, { recursive: true });
  const FPS = 60, FRAMES = 900;
  const sub = +opt('sub', 10);

  if (opt('stills')) {
    const page = await openPage(browser, port);
    const times = String(opt('stills')).split(',').map(Number);
    const dir = join(outDir, 'stills');
    mkdirSync(dir, { recursive: true });
    for (const t of times) {
      const f = Math.round(t * FPS);
      const png = await grab(page, f, +opt('sub', 1));
      const file = join(dir, `t${t.toFixed(3)}.png`);
      writeFileSync(file, png);
      console.log(file);
    }
  } else if (opt('sheet')) {
    // one frame every `step` seconds, tiled 6 wide at 320×180
    const step = +opt('step', 0.25);
    const page = await openPage(browser, port);
    const tmp = join(outDir, '.sheet');
    rmSync(tmp, { recursive: true, force: true });
    mkdirSync(tmp);
    let n = 0;
    for (let t = +opt('from', 0); t < +opt('to', 15); t += step) {
      writeFileSync(join(tmp, `${String(n++).padStart(4, '0')}.png`), await grab(page, Math.round(t * FPS), +opt('sub', 1)));
    }
    const cols = 6, rows = Math.ceil(n / cols);
    const file = resolve(opt('out', join(outDir, 'contact-sheet.png')));
    const { done } = ff(['-i', join(tmp, '%04d.png'), '-vf',
      `scale=384:216,tile=${cols}x${rows}:padding=4:color=black`,
      '-frames:v', '1', file], 'sheet');
    await done;
    rmSync(tmp, { recursive: true, force: true });
    console.log(file);
  } else {
    const workers = +opt('workers', 4);
    const per = Math.ceil(FRAMES / workers);
    const segs = [];
    const t0 = Date.now();
    let doneFrames = 0;
    await Promise.all(Array.from({ length: workers }, async (_, w) => {
      const a = w * per, b = Math.min(FRAMES, a + per);
      if (a >= b) return;
      const page = await openPage(browser, port);
      const file = join(outDir, `.seg${w}.mkv`);
      segs[w] = file;
      const enc = ff(['-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
        '-c:v', 'libx264rgb', '-preset', 'ultrafast', '-qp', '0', file], `seg${w}`);
      for (let f = a; f < b; f++) {
        await write(enc.stdin, await grab(page, f, sub));
        if (++doneFrames % 60 === 0) {
          const el = (Date.now() - t0) / 1000;
          console.log(`${doneFrames}/${FRAMES} frames  ${el.toFixed(0)}s  eta ${(el / doneFrames * (FRAMES - doneFrames)).toFixed(0)}s`);
        }
      }
      enc.stdin.end();
      await enc.done;
    }));
    const list = join(outDir, '.segs.txt');
    writeFileSync(list, segs.filter(Boolean).map(s => `file '${s}'`).join('\n'));
    const file = resolve(opt('out', join(outDir, 'katachi-showreel.mp4')));
    const wav = join(ROOT, 'audio', 'score.wav');
    const audioIn = existsSync(wav) && !opt('mute') ? ['-i', wav] : [];
    const { done } = ff(['-f', 'concat', '-safe', '0', '-i', list, ...audioIn,
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-pix_fmt', 'yuv420p',
      '-profile:v', 'high', '-tune', 'animation', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
      ...(audioIn.length ? ['-c:a', 'aac', '-b:a', '256k', '-shortest'] : []),
      '-movflags', '+faststart', file], 'final');
    await done;
    for (const s of segs.filter(Boolean)) rmSync(s, { force: true });
    rmSync(list, { force: true });
    console.log(`${file}  (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
  }
  await browser.close();
  srv.close();
}

main().catch(e => { console.error(e); process.exit(1); });
