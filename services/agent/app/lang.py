"""What changes when the shoot is not in Japanese.

CurrentCut was built against Japanese broadcast practice, and that practice is
baked into things that look neutral: a caption line is thirteen full-width
characters, a caption carries no 。 or 、, and the note a director reads is
written for the person who will set the telop. None of that survives contact
with an English-language newsroom, where a lower third runs to about thirty
characters and nobody is counting full-width anything.

Rather than scatter `if japanese:` through the agents, every convention that
differs lives here, keyed by language, and the agents ask for the one they need.
The language is read off the footage — the shoot decides, not a setting someone
has to remember to change.
"""
from __future__ import annotations

import re

from .models.schemas import Segment, Verifiability

JA = "ja"
EN = "en"

_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def detect(text: str) -> str:
    """Japanese if the text contains kana or han, English otherwise.

    Deliberately crude and deliberately one-directional: a Japanese shoot always
    contains kana, while an English one cannot accidentally acquire any. The
    failure mode is a Japanese shoot with no dialogue at all, which falls to
    English and produces English notes about footage nobody spoke over.
    """
    return JA if _CJK.search(text or "") else EN


def of_segments(segments: list[Segment]) -> str:
    """The language of a shoot, from everything anyone said in it."""
    return detect(" ".join(s.transcript for s in segments))


# --- captions -------------------------------------------------------------
# A Japanese telop is counted in full-width characters and never carries 。 or 、.
# An English lower third is counted in ordinary characters and simply runs
# longer; broadcast practice drops the terminal full stop but keeps commas.
CAPTION_LIMITS = {
    JA: {"max_chars": 13, "max_lines": 2},
    EN: {"max_chars": 32, "max_lines": 2},
}

CAPTION_RULES = {
    JA: ("- Never use 。 or 、. Separate phrases with a full-width space instead.\n"
         "- Count full-width characters, not bytes."),
    EN: ("- No full stop at the end of a line; commas are fine mid-line.\n"
         "- Title case is not used — sentence case, as a broadcast lower third."),
}

CAPTION_AUDIENCE = {
    JA: "Japanese factual television",
    EN: "English-language factual television",
}

CREDIT_FORMAT = {JA: "出典 ◯◯", EN: "Source: ◯◯"}


# --- what the director is told --------------------------------------------
# These land on the order sheet, so they are written in the language of the
# person who will read it, not translated from the other one.
UNCHECKABLE_NOTE = {
    JA: {
        Verifiability.OWN_BUSINESS: "自店の数字　公開データなし　話者の発言として表記",
        Verifiability.UNIDENTIFIED_SUBJECT: "対象が特定できない　裏取り不可　話者の発言として表記",
    },
    EN: {
        Verifiability.OWN_BUSINESS:
            "Their own figure — nobody publishes it. Attribute it to the speaker.",
        Verifiability.UNIDENTIFIED_SUBJECT:
            "No named subject — cannot be checked. Attribute it to the speaker.",
    },
}


def no_primary_source(language: str, backers: list[str]) -> str:
    """Checked, but with nobody worth crediting on screen."""
    if language == JA:
        who = f"（{'　'.join(backers)}）" if backers else ""
        return f"裏付けあり　一次情報なし{who}　公式発表を確認して出典表記"
    who = f" (backed by {', '.join(backers)})" if backers else ""
    return (f"Checked, but no primary source to credit{who}. "
            "Find the official release before adding a source line.")


def stale_evidence(language: str, year: int) -> str:
    """The figure matches, but only in a source describing an earlier year."""
    if language == JA:
        return f"数字は合うが出典が古い（{year}年の数値）　最新の公表値を確認"
    return (f"The figure matches, but only in {year} data. "
            "Check the current release before using it.")


def conflicting(language: str) -> str:
    if language == JA:
        return "⚠この数字のまま出さない　公開情報と食い違い　要確認"
    return "Do not use this figure as spoken — it conflicts with published data."


def unbacked(language: str) -> str:
    if language == JA:
        return "裏付けなし　話者の発言として出すか　数字を外す"
    return "Nothing backs this. Attribute it to the speaker, or drop the number."


def too_long(language: str, longest: int, limit: int) -> str:
    if language == JA:
        return f"{longest}字　1行{limit}字に収まらない　要short"
    return f"{longest} characters — over the {limit}-character line. Needs shortening."


# --- examples given to the claim extractor --------------------------------
# A prompt full of Japanese examples pulls the model into Japanese whatever the
# transcript is: an English shoot came back with 「Harrow Bend Coffeeは1日に約
# 200杯のコーヒーを販売している」 on the caption sheet. The instruction to match
# the transcript's language loses to the weight of the examples, so the examples
# move with the shoot.
CLAIM_EXAMPLES = {
    JA: {
        "subjectless": '価格は1,980円',
        "self_contained": '<subject>の価格は1,980円',
        "public_subject": '"消費税の軽減税率", "全国のコンビニエンスストア"',
        "first_person_rule": '「うちも持ち帰りは8%」は国が決めた軽減税率',
        "unnamed": '"この商店街", "向こうの駅", "うちの近所"',
        "publisher_queries": '"国税庁 軽減税率 8% 10%", "日本フランチャイズチェーン協会 統計調査 店舗数"',
    },
    EN: {
        "subjectless": 'the price is $19.80',
        "self_contained": "<subject>'s price is $19.80",
        "public_subject": '"the federal minimum wage", "convenience stores nationwide"',
        "first_person_rule": '"we pay the federal minimum, $7.25" is a nationally set wage',
        "unnamed": '"this street", "the station over there", "our neighbourhood"',
        "publisher_queries": ('"US Department of Labor federal minimum wage", '
                              '"Census Bureau convenience store count"'),
    },
}


# --- what counts as smuggling the transcript out --------------------------
# The egress gate stops a verbatim span of what someone said from leaving in a
# search query. The unit of "a span" is not the same in both languages, and
# getting it wrong is not a small error in either direction.
#
# Japanese has no word boundaries, so a character run is the only unit
# available, and twelve characters is a clause — "全国におよそ五万六千店" is 12.
#
# English does have boundaries, and twelve characters is a word and a half:
# "federal minim" is 13, so on an English shoot the twelve-character rule
# rejected every honest keyword query about what the speaker had just said, and
# three US public-record claims went unchecked with the gate reporting a
# transcript leak that had not happened. Consecutive words are the right unit
# there — five in a row is a quotation, two or three is just the subject matter.
_MIN_QUOTED_CHARS = 12
_MIN_QUOTED_WORDS = 5

_WORD = re.compile(r"[0-9a-z$%'’.-]+")


def quotes_transcript(query: str, transcript: str, language: str = "") -> bool:
    """True when the query carries a verbatim span of the transcript."""
    language = language or detect(transcript)
    if language == JA:
        nq = re.sub(r"\s+", "", query.lower())
        nt = re.sub(r"\s+", "", transcript.lower())
        if len(nt) < _MIN_QUOTED_CHARS:
            return False
        return any(nt[i:i + _MIN_QUOTED_CHARS] in nq
                   for i in range(len(nt) - _MIN_QUOTED_CHARS + 1))

    said = _WORD.findall(transcript.lower())
    asked = " ".join(_WORD.findall(query.lower()))
    if len(said) < _MIN_QUOTED_WORDS:
        return False
    return any(" ".join(said[i:i + _MIN_QUOTED_WORDS]) in asked
               for i in range(len(said) - _MIN_QUOTED_WORDS + 1))


def name_super_check(language: str) -> str:
    if language == JA:
        return "屋号・肩書の表記を本人に確認"
    return "Confirm the spelling of the name and title with the speaker."
