"""Telop drafting and filling a station's own order sheet."""
from pathlib import Path


def test_telops_drafted_with_types_and_timecodes(overnight_run):
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    entries = store.list(project_id, "telops", TelopEntry)
    assert entries, "telops must be drafted"
    assert entries == sorted(entries, key=lambda e: e.order)
    for e in entries:
        assert e.text_lines and any(l.strip() for l in e.text_lines)
        assert e.out_seconds >= e.in_seconds
        assert len(e.text_lines) <= 2, "a telop may not exceed two lines"


def test_telops_carry_no_japanese_punctuation(overnight_run):
    """Broadcast telops do not carry 。 or 、."""
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    for e in store.list(project_id, "telops", TelopEntry):
        joined = "".join(e.text_lines)
        assert "。" not in joined and "、" not in joined, f"punctuation in telop: {joined}"


def test_data_telops_state_their_source_or_flag_the_gap(overnight_run):
    """A figure on screen either carries its source or is flagged for the director."""
    from app.models.schemas import EvidenceStatus, TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    for e in store.list(project_id, "telops", TelopEntry):
        if e.telop_type != "data":
            continue
        if e.evidence_status in (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
                                 EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED):
            assert e.source_note, "a confirmed figure must carry its attribution"
        else:
            assert e.caution, "an unconfirmed figure must be flagged before it is set"


def test_no_off_record_text_reaches_the_telop_sheet(overnight_run):
    from app.models.schemas import Segment, TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    off = [s for s in store.list(project_id, "segments", Segment) if "オフレコ" in s.transcript]
    assert off
    for e in store.list(project_id, "telops", TelopEntry):
        joined = "".join(e.text_lines) + e.source_note
        assert "銀座" not in joined
        assert "オフレコ" not in joined


def test_fills_a_station_sheet_keeping_its_own_layout(overnight_run, tmp_path):
    """The filled sheet must be the station's workbook, not a lookalike."""
    from openpyxl import Workbook, load_workbook

    from app.agents import telop_sheet
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    entries = store.list(project_id, "telops", TelopEntry)

    # A fictional programme's sheet: title row, then headers on row 3.
    template = tmp_path / "station_format.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "テロップ発注"
    ws["A1"] = "◯◯番組 テロップ発注表"
    ws["A3"], ws["B3"], ws["C3"] = "No", "IN点", "アウト点"
    ws["D3"], ws["E3"], ws["F3"], ws["G3"] = "種別", "表示文字", "出典", "備考"
    ws.column_dimensions["E"].width = 42          # station's own formatting
    wb.save(template)

    mapping = telop_sheet.infer_mapping(template)
    assert mapping.columns, "columns must be identified"
    assert "text_all" in mapping.columns

    out = telop_sheet.fill_sheet(template, mapping, entries, tmp_path / "filled.xlsx")
    assert out.exists()

    filled = load_workbook(out)
    ws2 = filled["テロップ発注"]
    assert ws2["A1"].value == "◯◯番組 テロップ発注表", "the station's own header must survive"
    assert ws2.column_dimensions["E"].width == 42, "the station's formatting must survive"

    text_col = mapping.columns["text_all"]
    first = ws2[f"{text_col}{mapping.first_data_row}"].value
    assert first and str(first).strip(), "entries must be written into the sheet"


def test_figures_are_never_broken_across_lines():
    """"5万6000店" split as "5万600" / "0店" is a different number on screen."""
    from app.agents.telop import _fit

    for text in ["コンビニ 全国 5万6000店 手軽に飲める時代",
                 "訪日外国人は356万人 過去最高を更新した",
                 "この店は1日およそ100杯 10年で3割減"]:
        lines = _fit(text)
        for line in lines[:-1]:
            assert not line[-1].isdigit(), f"a line ends mid-figure: {lines}"
        for line in lines[1:]:
            assert not line[0].isdigit() or "万" not in "".join(lines[:1]), lines


def test_csv_fallback_when_no_template(overnight_run, tmp_path):
    from app.agents import telop_sheet
    from app.models.schemas import TelopEntry
    from app.storage import store

    project_id, _ = overnight_run
    entries = store.list(project_id, "telops", TelopEntry)
    path = telop_sheet.write_csv(entries, tmp_path / "telops.csv")
    body = Path(path).read_text(encoding="utf-8-sig")
    assert "表示文字" in body and "出典表記" in body
    assert body.count("\n") >= len(entries)
