"""Build the font assets the showreel loads.

    python3 tools/build_assets.py <fontsource-dir>

<fontsource-dir> holds the unpacked npm packages
@fontsource-variable/archivo, @fontsource/instrument-serif,
@fontsource-variable/jetbrains-mono and @fontsource/noto-sans-jp
(`npm pack` each, then untar). All four are SIL OFL 1.1.

Writes:
  fonts/*.woff2      the faces the canvas draws with (Noto Sans JP is
                     subset to the Japanese the reel actually sets)
  lib/glyphs.js      Archivo outlines for the words whose weight/width
                     morphs continuously; canvas can only step through
                     font-stretch keywords, so those words are drawn as
                     paths interpolated between the font's own masters
"""

import io
import json
import shutil
import sys
from pathlib import Path

import uharfbuzz as hb
from fontTools import subset
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"

# Every Japanese string set in reel.js. Keep in sync when copy changes.
JP_TEXT = (
    "点線面形見えないものに、かたちを。"
    "東京デザインスタジオブランディングモーションタイポグラフィ"
    "デジタルエディトリアル空間キャンペーン実績"
)

# Archivo's masters sit at wght 100/600/900 x wdth 62/100/125, so
# bilinear interpolation between these nine instances (in normalized,
# avar-mapped space) reproduces the variable font exactly.
WGHT = [100, 600, 900]
WDTH = [62, 100, 125]
MORPH_WORDS = ["KATACHI", "Aa"]


class FlatPen(BasePen):
    """Records M/L/Q/C/Z with flat coordinates; structure is identical
    across instances, so coordinate arrays can be lerped directly."""

    def __init__(self, glyphset):
        super().__init__(glyphset)
        self.ops = []
        self.pts = []

    def _moveTo(self, p):
        self.ops.append("M")
        self.pts += p

    def _lineTo(self, p):
        self.ops.append("L")
        self.pts += p

    def _qCurveToOne(self, p1, p2):
        self.ops.append("Q")
        self.pts += p1 + p2

    def _curveToOne(self, p1, p2, p3):
        self.ops.append("C")
        self.pts += p1 + p2 + p3

    def _closePath(self):
        self.ops.append("Z")

    def _endPath(self):
        pass


def copy_faces(src: Path) -> None:
    FONTS.mkdir(exist_ok=True)
    pick = {
        "archivo-latin-standard-normal.woff2": "archivo-var.woff2",
        "instrument-serif-latin-400-normal.woff2": "instrument-serif.woff2",
        "instrument-serif-latin-400-italic.woff2": "instrument-serif-italic.woff2",
        "jetbrains-mono-latin-wght-normal.woff2": "jetbrains-mono-var.woff2",
    }
    for name, out in pick.items():
        hit = next(src.rglob(name))
        shutil.copy(hit, FONTS / out)
    # OFL 1.1: each face travels with its own copyright notice and licence.
    for pkg, name in [
        ("fontsource-variable-archivo", "archivo"),
        ("fontsource-instrument-serif", "instrument-serif"),
        ("fontsource-variable-jetbrains-mono", "jetbrains-mono"),
        ("fontsource-noto-sans-jp", "noto-sans-jp"),
    ]:
        lic = next(src.rglob(f"{pkg}*/package/LICENSE"))
        shutil.copy(lic, FONTS / f"OFL-{name}.txt")

    jp = next(src.rglob("noto-sans-jp-japanese-700-normal.woff2"))
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    font = subset.load_font(str(jp), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=JP_TEXT + " ")
    sub.subset(font)
    subset.save_font(font, str(FONTS / "noto-sans-jp-700-subset.woff2"), opts)


def build_glyphs(src: Path) -> None:
    path = next(src.rglob("archivo-latin-standard-normal.woff2"))
    base = TTFont(path)
    upm = base["head"].unitsPerEm
    avar = {
        tag: sorted(seg.items())
        for tag, seg in base["avar"].segments.items()
    }
    # HarfBuzz cannot read WOFF2; hand it the decompressed sfnt.
    sfnt = TTFont(path)
    sfnt.flavor = None
    buf_io = io.BytesIO()
    sfnt.save(buf_io)
    raw = buf_io.getvalue()

    words = {}
    for word in MORPH_WORDS:
        glyph_names = None
        glyph_data = {}
        masters = []  # per (wght, wdth): {advances: [...], outlines: {g: pts}}
        for w in WGHT:
            for d in WDTH:
                inst = instancer.instantiateVariableFont(
                    TTFont(path), {"wght": w, "wdth": d}
                )
                gs = inst.getGlyphSet()

                face = hb.Face(raw)
                hbfont = hb.Font(face)
                hbfont.set_variations({"wght": w, "wdth": d})
                buf = hb.Buffer()
                buf.add_str(word)
                buf.guess_segment_properties()
                hb.shape(hbfont, buf, {"kern": True, "liga": False})
                order = inst.getGlyphOrder()
                names = [order[i.codepoint] for i in buf.glyph_infos]
                adv = [p.x_advance for p in buf.glyph_positions]
                offs = [p.x_offset for p in buf.glyph_positions]
                if glyph_names is None:
                    glyph_names = names
                assert names == glyph_names

                outlines = {}
                for g in dict.fromkeys(names):
                    pen = FlatPen(gs)
                    gs[g].draw(pen)
                    if g not in glyph_data:
                        glyph_data[g] = "".join(pen.ops)
                    assert glyph_data[g] == "".join(pen.ops), g
                    outlines[g] = [round(v, 1) for v in pen.pts]
                masters.append({"adv": adv, "off": offs, "outlines": outlines})
        words[word] = {
            "glyphs": glyph_names,
            "ops": glyph_data,
            "masters": masters,
        }

    out = {
        "upm": upm,
        "wght": WGHT,
        "wdth": WDTH,
        "avar": avar,
        "words": words,
    }
    js = "// Generated by tools/build_assets.py. Do not edit.\n"
    js += "window.GLYPHS = " + json.dumps(out, separators=(",", ":")) + ";\n"
    (ROOT / "lib" / "glyphs.js").write_text(js)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    copy_faces(src)
    build_glyphs(src)
    for f in sorted(FONTS.iterdir()):
        print(f"{f.name:40s} {f.stat().st_size:>9,d}")
    g = ROOT / "lib" / "glyphs.js"
    print(f"{'lib/glyphs.js':40s} {g.stat().st_size:>9,d}")
