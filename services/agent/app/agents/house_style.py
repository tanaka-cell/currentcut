"""Learn a programme's house style from scripts it has already aired.

Not fine-tuning. Ten scripts is nowhere near enough to train a model, and a
trained model would be a black box the director could not argue with. Instead
Gemini reads the scripts once and writes down what the programme actually does
— how it opens, how long the blocks run, how the narration ends its sentences,
how it words a source credit — as a short, readable profile stored with the
programme. The director can read that profile and correct it, and it is then
injected into script and telop drafting.

Two rules hold this in place:

1. **Form, never content.** The profile describes how the programme writes, not
   what it has said. Facts, names and figures from past broadcasts must not
   leak into a new feature through the back door.
2. **Past scripts never leave the building.** They are the programme's own
   material, so they are stored as confidential and are never eligible for
   external search — the egress gate only ever sees claims from this shoot's
   footage.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config
from ..clients.gemini_client import gemini
from ..models.schemas import new_id, now_iso
from ..storage import store

SUPPORTED = (".txt", ".md", ".pdf", ".docx")
MAX_SCRIPTS = 20


class CornerBlock(BaseModel):
    """One block of the recurring corner's structure."""
    order: int = Field(description="1-based position in the running order")
    role: str = Field(description="What this block is called or does: 掴み / 導入 / 本題 / 転換 / 締め など")
    purpose: str = Field(default="", description="What it has to achieve, in one line")
    typical_seconds: int = Field(default=0, description="How long it usually runs")
    shot_type: str = Field(
        default="other",
        description="What is usually on screen here: interview | reaction | broll | exterior | other")
    notes: str = Field(default="", description="How it is usually handled")


class HouseStyle(BaseModel):
    id: str = Field(default_factory=lambda: new_id("sty"))
    project_id: str = ""

    corner_name: str = Field(default="", description="The recurring corner these scripts are from")
    total_duration_seconds: int = Field(default=0, description="Typical finished length")
    blocks: list[CornerBlock] = Field(
        default_factory=list,
        description="The corner's running order — the part a director actually reuses")

    structure: list[str] = Field(
        default_factory=list,
        description="How a feature is built, in order — the opening device, the block "
                    "order, how it closes. One short line each.")
    block_timing: str = Field(default="", description="Roughly how long each block runs")
    narration_voice: list[str] = Field(
        default_factory=list,
        description="Sentence endings, sentence length, level of politeness, person")
    telop_conventions: list[str] = Field(
        default_factory=list,
        description="Characters per line, punctuation, how a name super is written")
    source_credit_format: str = Field(
        default="", description="How this programme words a source credit on screen, verbatim "
                                "pattern, e.g. 「出典：◯◯」 or 「（◯◯調べ）」")
    naming_conventions: list[str] = Field(
        default_factory=list, description="How people and companies are referred to")
    avoid: list[str] = Field(
        default_factory=list, description="Wordings this programme does not use")
    sample_lines: list[str] = Field(
        default_factory=list,
        description="At most 3 short narration lines that typify the voice. Form only — "
                    "no figures, no proper nouns, no facts from the broadcasts.")

    learned_from: int = 0
    notes: str = ""
    confirmed_by_director: bool = False
    created_at: str = Field(default_factory=now_iso)


_PROMPT = """You are reading past scripts of ONE RECURRING CORNER of a Japanese
television programme, so that a new edition of that corner can be drafted to
the same running order.

The most useful thing you can produce is `blocks`: the corner's running order,
because a recurring corner repeats its shape every week. A director reuses that
shape. Everything else is secondary.

Describe HOW this corner is built. Do NOT carry over WHAT it said.

Hard rules:
- Never repeat a figure, statistic, price, date, company name, product name or
  person's name from these scripts. They belong to past broadcasts.
- sample_lines must be short and generic enough to show the voice without
  reproducing content. If you cannot write one without naming something, leave
  it out.
- Describe only patterns you can actually see repeated across the scripts. If
  something appears once, it is not the house style — leave it out.
- Write the profile in Japanese, since the director will read and correct it.

Look for, in order of importance:
- blocks: the running order. One entry per block, with its role (掴み / 導入 /
  本題 / 転換 / 締め など), what it has to achieve, how long it usually runs in
  seconds, and what is usually on screen (interview / reaction / broll /
  exterior). Only include a block if it appears in MOST of the scripts — that is
  what makes it the corner's shape rather than one week's choice.
- corner_name and total_duration_seconds, if the scripts show them
- structure: what the opening does (a strong reaction? a question? a figure?),
  the order of blocks, how the piece lands at the end
- block_timing: roughly how long each block runs, if the scripts show timings
- narration_voice: sentence endings (です・ます / 体言止め), typical sentence
  length, how formal, whether the narrator addresses the viewer
- telop_conventions: characters per line, whether punctuation is used, how a
  name super is laid out (title above name? company then name?)
- source_credit_format: the exact wording pattern used when a figure is
  credited on screen. This one matters most — give the pattern with ◯◯ where
  the source name goes.
- naming_conventions: 「さん」「氏」, whether company types are spelled out
- avoid: wordings that are conspicuously absent or that the scripts replace

{scripts}

Return JSON."""


def _read_script(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("Word scripts need python-docx installed") from exc
        return "\n".join(p.text for p in Document(str(path)).paragraphs)
    if suffix == ".pdf":
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError("PDF scripts need PyMuPDF installed") from exc
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)
    raise RuntimeError(f"unsupported script format: {path.suffix}")


def learn(project_id: str, script_paths: list[str | Path]) -> HouseStyle:
    paths = [Path(p) for p in script_paths][:MAX_SCRIPTS]
    if not paths:
        raise RuntimeError("no scripts supplied")

    bodies = []
    for index, path in enumerate(paths, start=1):
        text = _read_script(path).strip()
        if not text:
            continue
        bodies.append(f"--- 台本 {index} ({path.name}) ---\n{text[:12000]}")
    if not bodies:
        raise RuntimeError("the uploaded scripts contained no readable text")

    if gemini.mock:
        style = _mock_style(bodies)
    else:
        try:
            style = gemini.structured(
                _PROMPT.format(scripts="\n\n".join(bodies)),
                HouseStyle, model=config.GEMINI_REASONING_MODEL)
        except Exception as exc:
            raise RuntimeError(f"could not read the scripts: {exc}") from exc

    style.project_id = project_id
    style.learned_from = len(bodies)
    style = _strip_content(style)
    store.put(project_id, "house_style", style)
    return style


# Figures and years are the clearest sign that content, not form, has been
# carried over from a past broadcast.
_FIGURE = re.compile(r"[0-9０-９]{2,}|[0-9０-９]+\s*[%％円人店万億]")


def _strip_content(style: HouseStyle) -> HouseStyle:
    """Belt and braces on rule 1: drop sample lines that carry figures."""
    kept, dropped = [], 0
    for line in style.sample_lines:
        if _FIGURE.search(line):
            dropped += 1
            continue
        kept.append(line)
    style.sample_lines = kept[:3]
    if dropped:
        note = f"{dropped}件の例文は過去放送の数字を含むため除外"
        style.notes = f"{style.notes}／{note}" if style.notes else note
    return style


def _mock_style(bodies: list[str]) -> HouseStyle:
    """Deterministic stand-in: read the shape without a model."""
    text = "\n".join(bodies)
    conventions = []
    if "。" not in text.split("テロップ")[-1][:400]:
        conventions.append("テロップに句読点を使わない")
    voice = []
    if text.count("です") + text.count("ます") > text.count("だ。"):
        voice.append("ナレーションは です・ます 調")
    if "体言止め" in text or text.count("──") > 2:
        voice.append("体言止めを混ぜる")
    credit = ""
    m = re.search(r"(出典[：:][^\n]{0,20})", text)
    if m:
        credit = m.group(1).replace(m.group(1).split("：")[-1], "◯◯") if "：" in m.group(1) else m.group(1)
    return HouseStyle(
        structure=["冒頭は現場の音や反応から入る", "中盤にインタビュー", "最後に問いかけで締める"],
        narration_voice=voice or ["ナレーションは です・ます 調"],
        telop_conventions=conventions or ["1行あたり13〜15文字"],
        source_credit_format=credit or "出典：◯◯",
        naming_conventions=["人物は「さん」付け"],
        notes="モデルを使わない簡易抽出",
    )


def load(project_id: str) -> HouseStyle | None:
    styles = store.list(project_id, "house_style", HouseStyle)
    return styles[-1] if styles else None


def as_prompt_block(style: HouseStyle | None) -> str:
    """The compact form injected into script and telop drafting."""
    if style is None:
        return ""
    parts = ["この番組の型（過去のOA台本から抽出・ディレクター確認済み"
             if style.confirmed_by_director else "この番組の型（過去のOA台本から抽出）"]
    if style.structure:
        parts.append("構成: " + " / ".join(style.structure))
    if style.block_timing:
        parts.append("尺配分: " + style.block_timing)
    if style.narration_voice:
        parts.append("ナレーション: " + " / ".join(style.narration_voice))
    if style.telop_conventions:
        parts.append("テロップ: " + " / ".join(style.telop_conventions))
    if style.source_credit_format:
        parts.append("出典表記: " + style.source_credit_format)
    if style.naming_conventions:
        parts.append("呼称: " + " / ".join(style.naming_conventions))
    if style.avoid:
        parts.append("使わない表現: " + " / ".join(style.avoid))
    if style.sample_lines:
        parts.append("語り口の例: " + " ／ ".join(style.sample_lines))
    parts.append("※これは書き方の型です。過去放送の事実・数字・固有名詞は持ち込まないこと。")
    return "\n".join(parts)
