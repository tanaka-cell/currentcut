# KATACHI — 15 s showreel

Opening reel for **KATACHI**, a fictional Tokyo design studio. The name means
"shape/form" (形), so the film is built on the design fundamentals:
point → line → plane → form. Once the studio is shown to be about form, it
cuts to the work, then lands on the logo.

**Output:** `out/katachi-showreel.mp4`. 1920×1080, 60 fps, 15.000 s,
H.264 + AAC. It has 10-sample motion blur (180° shutter) and a synthesised
score. The last frame hands back to the first, so the reel loops cleanly
on autoplay.

| Time | Beat | Shot |
|---|---|---|
| 0.00 | 0 | **Point.** A vermilion dot pops onto a crosshair. A shockwave follows, then 627 dots ripple out into a halftone wave. |
| 1.88 | 4 | **Line.** Every dot stretches into its neighbours. The rows swell into ridgelines and fold into one line. |
| 2.81 | 6 | That line becomes an easing curve in a graph editor. A cursor drags the handles to `cubic-bezier(0.16, 1, 0.3, 1)`, the curve snaps straight and rings like a plucked string. |
| 3.75 | 8 | **Plane.** The line swells to flood the frame. Circle, triangle and square slide in, swap places, and morph into each other. |
| 5.63 | 12 | **Form.** An iris opens on the same shapes, now extruded into sphere, pyramid and cube. They hop on the beat. |
| 7.03 | 15 | The camera dollies into the cube face… |
| 7.50 | 16 | …**drop.** Eight services, one cut per beat, then per half beat: Brand Identity, Motion, Typography, Digital Product, Editorial, Spatial, Campaign, Track Record. |
| 10.31 | 22 | Pull back to a 3×3 grid with every piece still running. The logo waits in the centre cell. |
| 11.25 | 24 | The grid clears and the camera pushes into the centre. The mark jumps into its lockup on three notes. |
| 11.72 | 25 | **KATACHI** rises and widens from condensed to extended, with a real variable-font interpolation. |
| 12.2 | 26 | 見えないものに、かたちを。 / *Giving shape to the unseen.* |
| 14.06 | 30 | Everything folds back into the dot. The iris closes and the dot pops out, back to frame 0. |

## How it is built

- `reel.js` holds the whole film as one pure function `draw(ctx, t)` on a
  2D canvas. Nothing depends on wall-clock time, so the live preview and the
  offline render run the same code, and any frame can be rendered alone.
- Motion blur averages 10 samples across half a frame. Grain goes on after
  the blur, so it stays sharp.
- Canvas can only step `font-stretch` through keywords. So the words whose
  width and weight morph (the `KATACHI` wordmark and the `Aa` specimen) are
  drawn as outlines interpolated between Archivo's nine masters.
  `tools/build_assets.py` exports those outlines and the kerned advances,
  shaped with HarfBuzz.
- `audio/score.py` synthesises the score with numpy/scipy: 128 BPM, so
  32 beats land exactly on 15 s. Every sound effect sits on a cue taken
  from the reel's timeline.

## Rebuild

```sh
# fonts + glyph outlines (needs fonttools, brotli, uharfbuzz; npm-packed fontsource dirs)
python3 tools/build_assets.py <fontsource-dir>
# score (needs numpy, scipy)
python3 audio/score.py
# video (needs Playwright + Chromium; ffmpeg from $FFMPEG or imageio-ffmpeg)
node render.mjs                     # out/katachi-showreel.mp4
node render.mjs --sheet             # quick contact sheet (no motion blur)
node render.mjs --stills 3.3,12.9   # out/stills/t*.png
```

To watch it live, serve the folder (`npx serve .`) and open `index.html`.
Space plays and pauses, the arrow keys step one frame, and clicking the bar
seeks.

Fonts: Archivo, Instrument Serif, JetBrains Mono and Noto Sans JP (subset
to the characters the reel sets) are all under the SIL Open Font License
1.1. Each one's notice is in `fonts/OFL-*.txt`. KATACHI and everything about
it are invented.
