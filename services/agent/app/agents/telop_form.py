"""Print telop text onto the programme's own order form (PDF or JPEG).

Every programme's form is different, so CurrentCut does not try to understand
all of it. The director supplies their form with the fixed parts already filled
in — programme name, font and size specification, whatever their programme
wants — and CurrentCut prints only the telop characters onto it.

That leaves exactly one thing to work out per programme: where the characters
go. Gemini proposes that area from the uploaded form; the director confirms or
nudges it once, and it is stored with the programme and reused. One sheet per
telop, out as a print-ready PDF and as JPEGs to send to the telop operator.

Deliberately NOT automated: programme name, serial number, font, size, colour,
scene. Those differ per programme and belong to the director's own form.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from ..clients.gemini_client import gemini
from ..models.schemas import TelopEntry

# Gemini returns boxes as [ymin, xmin, ymax, xmax] normalised to 0–1000.
BOX_SCALE = 1000.0


class TextArea(BaseModel):
    """Where the telop characters are written on this programme's form."""
    box: list[int] = Field(description="[ymin, xmin, ymax, xmax] normalised to 0-1000")
    reading_direction: str = Field(default="horizontal", description="horizontal | vertical")
    confirmed_by_director: bool = False
    note: str = ""


_AREA_PROMPT = """This is a blank Japanese television telop order form
(テロップ発注書). A director writes ONE telop on ONE sheet by hand and gives it
to the telop operator.

Find only one thing: the area where the telop characters themselves are
written. It is the large open box or grid of squares in the middle of the
sheet — not the small labelled fields around the edge (programme name, serial
number, font and size specification), which are filled in separately.

Return it as box [ymin, xmin, ymax, xmax] normalised to 0-1000, and say whether
the squares run in vertical columns ("vertical") or across in rows
("horizontal"). Give a one-line note describing what you matched, so a human
can tell at a glance whether you found the right box."""


def infer_text_area(form_path: str | Path) -> TextArea:
    form_path = Path(form_path)
    if gemini.mock:
        return TextArea(box=[250, 60, 640, 940], note="default area (no credentials)")
    from google.genai import types

    client = gemini._real()
    suffix = form_path.suffix.lower()
    mime = {".png": "image/png", ".pdf": "application/pdf"}.get(suffix, "image/jpeg")
    try:
        response = client.models.generate_content(
            model=config.GEMINI_VIDEO_MODEL,
            contents=[types.Part.from_bytes(data=form_path.read_bytes(), mime_type=mime),
                      _AREA_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_schema=TextArea),
        )
    except Exception as exc:
        raise RuntimeError(f"could not read the form: {exc}") from exc
    area = response.parsed
    if not isinstance(area, TextArea):
        import json
        area = TextArea.model_validate(json.loads(response.text))
    if len(area.box) != 4 or not all(0 <= v <= 1000 for v in area.box):
        raise RuntimeError("the area returned for this form is not a usable box")
    return area


def _load_form(form_path: Path):
    """The form may be a PDF; render its first page."""
    from PIL import Image

    if form_path.suffix.lower() != ".pdf":
        return Image.open(form_path).convert("RGB")
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError("PDF forms need PyMuPDF installed; or upload the form as JPEG") from exc
    page = fitz.open(form_path).load_page(0)
    pix = page.get_pixmap(dpi=200)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _font(size: int):
    from PIL import ImageFont

    path = Path(config.FONT_FILE)
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_sheets(form_path: str | Path, area: TextArea, entries: list[TelopEntry],
                  out_dir: str | Path) -> dict:
    """One filled sheet per telop. Only the characters are printed."""
    from PIL import ImageDraw

    form_path, out_dir = Path(form_path), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _load_form(form_path)
    width, height = base.size

    ymin, xmin, ymax, xmax = area.box
    x0, y0 = int(xmin / BOX_SCALE * width), int(ymin / BOX_SCALE * height)
    x1, y1 = int(xmax / BOX_SCALE * width), int(ymax / BOX_SCALE * height)
    box_w, box_h = max(1, x1 - x0), max(1, y1 - y0)

    pages, jpegs = [], []
    for entry in entries:
        sheet = base.copy()
        draw = ImageDraw.Draw(sheet)
        lines = [l for l in (entry.text_lines or [""]) if l] or [""]

        if area.reading_direction == "vertical":
            _draw_vertical(draw, lines, x0, y0, box_w, box_h)
        else:
            _draw_horizontal(draw, lines, x0, y0, box_w, box_h)

        jpeg = out_dir / f"telop_{entry.order:03d}.jpg"
        sheet.save(jpeg, "JPEG", quality=92)
        jpegs.append(str(jpeg))
        pages.append(sheet)

    pdf_path = out_dir / "telop_sheets.pdf"
    if pages:
        pages[0].save(pdf_path, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return {"pdf": str(pdf_path) if pages else "", "jpegs": jpegs, "sheets": len(pages)}


def _draw_horizontal(draw, lines: list[str], x0: int, y0: int, w: int, h: int) -> None:
    longest = max(len(l) for l in lines) or 1
    size = max(10, min(int(w / longest * 0.92), int(h / len(lines) * 0.70)))
    font = _font(size)
    line_height = int(size * 1.3)
    cursor = y0 + max(0, (h - line_height * len(lines)) // 2)
    for line in lines:
        span = draw.textlength(line, font=font)
        draw.text((x0 + (w - span) / 2, cursor), line, fill=(20, 20, 20), font=font)
        cursor += line_height


def _draw_vertical(draw, lines: list[str], x0: int, y0: int, w: int, h: int) -> None:
    """Vertical forms read top-to-bottom, columns right-to-left."""
    tallest = max(len(l) for l in lines) or 1
    size = max(10, min(int(h / tallest * 0.92), int(w / len(lines) * 0.70)))
    font = _font(size)
    col_width = int(size * 1.3)
    cursor_x = x0 + w - max(0, (w - col_width * len(lines)) // 2) - col_width
    for line in lines:
        cursor_y = y0 + max(0, (h - size * len(line)) // 2)
        for ch in line:
            draw.text((cursor_x, cursor_y), ch, fill=(20, 20, 20), font=font)
            cursor_y += size
        cursor_x -= col_width
