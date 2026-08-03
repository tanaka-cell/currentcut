"""Fill a station's own telop order sheet.

Every programme uses a different sheet, so CurrentCut does not impose a layout.
The director uploads the sheet their programme already uses; Gemini reads the
header row once and works out which column means what; CurrentCut then writes
the drafted telops into a *copy of that file*, leaving the station's formatting,
column widths, print area and logo untouched.

Writing into the original workbook — rather than rendering our own lookalike —
is the whole point: the sheet that comes out is the one the telop operator
already knows how to read.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from ..clients.gemini_client import gemini
from ..models.schemas import TelopEntry

# What we can supply for each row. The mapping step decides which of these
# the uploaded sheet actually has a column for.
FIELDS = {
    "order": "通し番号 / No.",
    "in_tc": "IN点タイムコード",
    "out_tc": "OUT点タイムコード",
    "telop_type": "テロップ種別（名前スーパー・データ・コメントフォローなど）",
    "line1": "表示文字 1行目",
    "line2": "表示文字 2行目",
    "text_all": "表示文字（1セルにまとめる場合）",
    "source_note": "出典表記",
    "caution": "備考・確認事項",
}


class ColumnMapping(BaseModel):
    header_row: int = Field(description="1-based row number holding the column headers")
    first_data_row: int = Field(description="1-based row number where entries start")
    columns: dict[str, str] = Field(
        default_factory=dict,
        description="Our field name -> column letter in the sheet, e.g. {'in_tc': 'B'}")
    sheet_name: str = ""
    notes: str = ""


_MAPPING_PROMPT = """You are reading a Japanese television telop order sheet
(テロップ発注表) so that it can be filled in automatically.

Below is the top-left region of the uploaded spreadsheet, given as
"CELL: value" lines.

{grid}

Work out:
- header_row: which row holds the column headings
- first_data_row: the first row where an entry should be written
- columns: for each of our fields below, the column letter in this sheet that
  it belongs in. Omit a field entirely if the sheet has no column for it.
  Never guess: if you are unsure what a column means, leave it out.

Our fields:
{fields}

Notes on Japanese telop sheets: 「スーパー」「テロップ」「文字」「表示文字」
usually mean the displayed text; 「IN」「アウト」「TC」 are timecodes;
「種別」「種類」 is the telop type; 「出典」「ソース」 is the attribution;
「備考」「注意」 is remarks. If the displayed text has one column rather than
one per line, map it to text_all instead of line1/line2.

Return JSON."""


def read_grid(xlsx_path: Path, max_rows: int = 12, max_cols: int = 14) -> tuple[str, str]:
    """A small text view of the sheet for the mapping step."""
    from openpyxl import load_workbook
    from openpyxl.utils import get_column_letter

    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    cells = []
    for row in range(1, min(ws.max_row, max_rows) + 1):
        for col in range(1, min(ws.max_column, max_cols) + 1):
            value = ws.cell(row=row, column=col).value
            if value is not None and str(value).strip():
                cells.append(f"{get_column_letter(col)}{row}: {str(value).strip()[:40]}")
    return "\n".join(cells), ws.title


def infer_mapping(xlsx_path: str | Path) -> ColumnMapping:
    """Ask Gemini what this particular sheet's columns mean."""
    grid, sheet_name = read_grid(Path(xlsx_path))
    if gemini.mock:
        return _mock_mapping(grid, sheet_name)
    fields = "\n".join(f"- {k}: {v}" for k, v in FIELDS.items())
    try:
        mapping = gemini.structured(
            _MAPPING_PROMPT.format(grid=grid, fields=fields), ColumnMapping)
    except Exception as exc:
        raise RuntimeError(f"could not read the sheet layout: {exc}") from exc
    mapping.sheet_name = mapping.sheet_name or sheet_name
    if not mapping.columns:
        raise RuntimeError("no columns could be identified in this sheet")
    return mapping


def _mock_mapping(grid: str, sheet_name: str) -> ColumnMapping:
    """Deterministic mapping by header keyword, for tests and for running
    without credentials."""
    import re

    keywords = {
        "order": ("no", "番号"), "in_tc": ("in", "イン", "開始"),
        "out_tc": ("out", "アウト", "終了"), "telop_type": ("種別", "種類"),
        "text_all": ("表示文字", "テロップ", "スーパー", "文字"),
        "source_note": ("出典", "ソース"), "caution": ("備考", "注意", "確認"),
    }
    found: dict[str, str] = {}
    header_row = 1
    for entry in grid.split("\n"):
        m = re.match(r"([A-Z]+)(\d+): (.*)", entry)
        if not m:
            continue
        col, row, value = m.group(1), int(m.group(2)), m.group(3).lower()
        for field, words in keywords.items():
            if field not in found and any(w in value for w in words):
                found[field] = col
                header_row = row
    return ColumnMapping(header_row=header_row, first_data_row=header_row + 1,
                         columns=found, sheet_name=sheet_name, notes="keyword mapping")


def _tc(seconds: float, fps: int = 30) -> str:
    seconds = max(0.0, seconds)
    total = int(round(seconds * fps))
    f = total % fps
    s = (total // fps) % 60
    m = (total // (fps * 60)) % 60
    h = total // (fps * 3600)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def fill_sheet(template_path: str | Path, mapping: ColumnMapping,
               entries: list[TelopEntry], out_path: str | Path) -> Path:
    """Write the entries into a copy of the station's own workbook."""
    from openpyxl import load_workbook

    template_path, out_path = Path(template_path), Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, out_path)

    wb = load_workbook(out_path)
    ws = wb[mapping.sheet_name] if mapping.sheet_name in wb.sheetnames else wb.active

    for i, entry in enumerate(entries):
        row = mapping.first_data_row + i
        lines = entry.text_lines or [""]
        values = {
            "order": entry.order,
            "in_tc": _tc(entry.in_seconds),
            "out_tc": _tc(entry.out_seconds),
            "telop_type": _TYPE_JA.get(entry.telop_type, entry.telop_type),
            "line1": lines[0],
            "line2": lines[1] if len(lines) > 1 else "",
            "text_all": "\n".join(lines),
            "source_note": entry.source_note,
            "caution": entry.caution,
        }
        for field, column in mapping.columns.items():
            if field not in values:
                continue
            cell = ws[f"{column}{row}"]
            cell.value = values[field]
            if field == "text_all" and len(lines) > 1:
                from openpyxl.styles import Alignment
                cell.alignment = Alignment(wrap_text=True, vertical="center")

    wb.save(out_path)
    return out_path


_TYPE_JA = {
    "name": "名前スーパー",
    "data": "データテロップ",
    "comment": "コメントフォロー",
    "place": "場所スーパー",
    "title": "タイトル",
}


def write_csv(entries: list[TelopEntry], out_path: str | Path) -> Path:
    """Fallback when no station template has been uploaded yet."""
    import csv

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["No", "IN", "OUT", "種別", "表示文字", "出典表記", "備考", "裏付け"])
        for e in entries:
            writer.writerow([e.order, _tc(e.in_seconds), _tc(e.out_seconds),
                             _TYPE_JA.get(e.telop_type, e.telop_type),
                             "\n".join(e.text_lines), e.source_note, e.caution,
                             e.evidence_status.value])
    return out_path
