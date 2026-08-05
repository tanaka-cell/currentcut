"""CurrentCut data model — single source of truth (mirrors the master brief)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Confidentiality(str, Enum):
    PUBLIC = "PUBLIC"
    EDITORIAL_ONLY = "EDITORIAL_ONLY"
    CONFIDENTIAL = "CONFIDENTIAL"
    OFF_THE_RECORD = "OFF_THE_RECORD"
    PERSONAL_DATA = "PERSONAL_DATA"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


# Labels that may never leave the editorial system automatically.
RESTRICTED_LABELS = {
    Confidentiality.CONFIDENTIAL,
    Confidentiality.OFF_THE_RECORD,
    Confidentiality.PERSONAL_DATA,
    Confidentiality.NEEDS_HUMAN_REVIEW,
}


class EvidenceStatus(str, Enum):
    FOOTAGE_CONFIRMED = "FOOTAGE_CONFIRMED"
    PRIMARY_SOURCE_CONFIRMED = "PRIMARY_SOURCE_CONFIRMED"
    MULTIPLE_SOURCES_CONFIRMED = "MULTIPLE_SOURCES_CONFIRMED"
    EDITORIAL_LANGUAGE = "EDITORIAL_LANGUAGE"
    UNVERIFIED = "UNVERIFIED"
    CONFLICTING = "CONFLICTING"


class Project(BaseModel):
    id: str = Field(default_factory=lambda: new_id("prj"))
    title: str
    target_duration_seconds: int = 480
    air_date: str = ""
    genre: str = "trend_feature"
    audience: str = ""
    tone: str = ""
    editorial_rules: list[str] = []
    status: str = "created"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Asset(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ast"))
    project_id: str
    filename: str
    storage_uri: str
    duration_seconds: float = 0
    media_type: str = "video"
    hash: str = ""
    analysis_status: str = "pending"
    uploaded_at: str = Field(default_factory=now_iso)


class ProposedRelease(BaseModel):
    """One sentence of a held segment, with the tool's reading of it.

    A proposal, never an action. Where an off-record remark begins and ends is a
    judgment about subject matter, and the spoken marker is not reliably at its
    edge —「オフレコですが、来月2号店を出します。まだ発表前なんです。」 has no marker
    on the second sentence and is plainly still off the record. So the tool
    shows its reading and the director decides; nothing is released until they
    confirm it.
    """
    text: str
    start_seconds: float = 0
    end_seconds: float = 0
    proposed_label: "Confidentiality" = Confidentiality.PUBLIC
    # Sentence boundaries inside a segment have no timecode of their own, so
    # these are apportioned by character count. A director nudges them.
    timing_is_estimated: bool = True


class Segment(BaseModel):
    id: str = Field(default_factory=lambda: new_id("seg"))
    asset_id: str
    start_seconds: float = 0
    end_seconds: float = 0
    speaker: str = ""
    transcript: str = ""
    visual_summary: str = ""
    shot_type: str = ""  # interview | broll | exterior | reaction | other
    usability_score: float = 0
    confidentiality: Confidentiality = Confidentiality.NEEDS_HUMAN_REVIEW
    confidentiality_reason: str = ""
    allow_script_use: bool = False
    allow_external_search: bool = False
    # Only set on a held segment that looks partly usable: the tool's reading of
    # where the restricted part starts, for a director to confirm. Carries no
    # authority — see ProposedRelease.
    release_proposal: list[ProposedRelease] = []
    release_confirmed_by: str = ""  # who settled the boundary, if anyone has


class Verifiability(str, Enum):
    """Why a claim can — or can never — be settled against the public web.

    A claim no public source could ever settle must not be searched: the search
    comes back with pages that merely share a number, and the director is shown
    noise dressed as evidence. Which kind of unverifiable it is matters, because
    the caption the director has to write differs.
    """
    # Published somewhere public: national statistics, statutory rates, an
    # organisation's own official figures. First person or not.
    PUBLIC_RECORD = "public_record"
    # Only the speaker knows: their own takings, headcount, customer numbers.
    OWN_BUSINESS = "own_business"
    # Refers to something with no public name ("this shopping street"), so no
    # source can be about the same entity.
    UNIDENTIFIED_SUBJECT = "unidentified_subject"


class Claim(BaseModel):
    id: str = Field(default_factory=lambda: new_id("clm"))
    segment_id: str
    # What gets verified. Deliberately self-contained, and prefixed with its
    # subject when the sentence alone does not name one — a claim with no
    # subject verifies against any page carrying the same number.
    claim_text: str
    # What a viewer reads. The prefix earns its place in a search query, not on
    # screen: a caption went out reading "small businesses' employment share of
    # the private workforce in this country: Small businesses employ almost half
    # of the private workforce in this country." Empty on claims recorded before
    # the two were separated — read it through `on_screen`, never directly.
    display_text: str = ""
    claim_type: str = "other"  # store_count | price | release_date | stat | superlative | popularity | other
    volatility: str = "medium"  # high | medium | low
    verifiability: Verifiability = Verifiability.PUBLIC_RECORD
    safe_search_query: Optional[str] = None
    # More angles on the same claim. One keyword query rarely surfaces the page
    # that states the figure; naming the likely publisher usually does.
    extra_search_queries: list[str] = []
    allow_external_search: bool = False
    requires_human_approval: bool = False
    verification_status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    # Set only when the check could not be performed at all (API failure), so a
    # provider outage is never presented to the director as "nothing supports it".
    verification_error: str = ""
    last_checked_at: str = ""
    # Volatility flag: surfaced to the director before the structure is locked.
    # `volatility_note` is only set when a source states an actual expiry or
    # scheduled change — a generic "prices move" is not worth the director's time.
    volatility_note: str = ""
    recheck_before_lock: bool = False
    # Why the recheck flag was raised. Three different situations used to share
    # one flag, which made the morning alert say "may change before air" about a
    # tax rate *introduced* in 2019. Only the first two carry a note worth
    # putting in front of a director.
    recheck_reason: str = ""  # stale_evidence | source_states_a_date | volatile_kind

    @property
    def on_screen(self) -> str:
        """The wording to put in front of a person — caption, telop, sheet.

        Falls back to the verification text, so a claim stored before the two
        were separated still reads the way it always did.
        """
        return self.display_text or self.claim_text


class ResearchResult(BaseModel):
    id: str = Field(default_factory=lambda: new_id("res"))
    claim_id: str
    source_url: str
    source_title: str = ""
    source_domain: str = ""
    published_at: str = ""
    event_date: str = ""
    excerpt: str = ""
    # Decided from the URL by code. This, not the model's opinion, is what makes
    # a source creditable on screen — see evidence.citable_source.
    source_type: str = "web"  # official | government | news | web
    # The comparator's view, kept for the director and for calibration. It is
    # not allowed to change source_type: asked the same question it called a
    # newspaper and a legal-media site primary sources for a national statistic.
    model_calls_it_primary: bool = False
    supports_claim: Optional[bool] = None
    # Kept separately so "conflicting" can mean "same subject, different number"
    # rather than "some unrelated page also contained a number".
    entity_match: bool = False
    attribute_match: bool = False
    source_value: str = ""
    dated_qualifier: str = ""  # expiry / validity / scheduled change stated by the source
    # Year the figure describes, per the source. A 2014 store count is a real
    # figure and a true match, but it does not confirm what is true on air day.
    value_as_of_year: int = 0
    # The source makes the claim false — not merely "did not support it".
    # Inferring one from the other put a broadcast warning on a true line.
    contradicts_claim: bool = False
    # The claim fixes its own period ("unchanged since 2009"), so evidence from
    # that period is the right evidence and cannot be stale.
    claim_names_its_own_date: bool = False
    judgment_reason: str = ""
    confidence: float = 0
    retrieved_at: str = Field(default_factory=now_iso)


class ScriptLine(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scl"))
    project_id: str
    order: int = 0
    start_seconds: float = 0
    end_seconds: float = 0
    visual_instruction: str = ""
    audio_text: str = ""
    caption_text: str = ""
    asset_id: str = ""
    segment_id: str = ""
    source_in_seconds: float = 0
    source_out_seconds: float = 0
    claim_ids: list[str] = []
    evidence_status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    confidentiality: Confidentiality = Confidentiality.PUBLIC
    editorial_note: str = ""


class TelopEntry(BaseModel):
    """One row of a telop order sheet — what the station's telop operator types.

    Finished 5–15 minute features are usually completed at the broadcaster on
    the station's own telop system, so the deliverable from the director is the
    *text*, on the programme's own order sheet, not a rendered graphic.
    """
    id: str = Field(default_factory=lambda: new_id("tlp"))
    project_id: str
    order: int = 0
    script_line_id: str = ""
    in_seconds: float = 0
    out_seconds: float = 0
    telop_type: str = "comment"  # name | data | comment | place | title
    text_lines: list[str] = []   # one entry per displayed line
    source_note: str = ""        # 出典表記 — required on data telops
    evidence_status: EvidenceStatus = EvidenceStatus.EDITORIAL_LANGUAGE
    caution: str = ""            # 備考: what the director must still settle
    approved: bool = False


class ChangeEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("chg"))
    claim_id: str
    old_value: str = ""
    new_value: str = ""
    affected_script_line_ids: list[str] = []
    affected_graphics: list[str] = []
    duration_delta_seconds: float = 0
    approval_status: str = "pending"  # pending | applied | ignored
    detected_at: str = Field(default_factory=now_iso)


class ProgressEvent(BaseModel):
    """One line in the live run log — one clip watched, one segment labelled,
    one claim checked. AgentRun below is one row per pipeline step, which is
    too coarse to show what a step is actually doing while it runs; this is
    the finer-grained feed the Overnight Run screen polls."""
    id: str = Field(default_factory=lambda: new_id("evt"))
    project_id: str
    step: str  # matches demo.STEPS name, e.g. "parallel_research"
    state: str = "running"  # running | done | blocked
    text: str = ""
    created_at: str = Field(default_factory=now_iso)


class AgentRun(BaseModel):
    id: str = Field(default_factory=lambda: new_id("run"))
    project_id: str
    agent_name: str
    provider: str = ""  # gemini | parallel | ffmpeg | adk | mock
    model_or_tool: str = ""
    status: str = "running"  # running | completed | failed
    started_at: str = Field(default_factory=now_iso)
    completed_at: str = ""
    latency_ms: int = 0
    input_summary: str = ""
    output_summary: str = ""
    error: str = ""


class EgressLog(BaseModel):
    """Written before AND after every outbound Parallel call (or block)."""
    id: str = Field(default_factory=lambda: new_id("egr"))
    project_id: str
    claim_id: str = ""
    segment_id: str = ""
    classification: str = ""
    query_sent: str = ""
    raw_transcript_sent: bool = False
    provider: str = "parallel"
    timestamp: str = Field(default_factory=now_iso)
    status: str = ""  # blocked | sent | completed | failed
    reason: str = ""
    result_count: int = 0
    # Append-only audit trail: the attempt record and the outcome record are
    # separate rows, linked by attempt_id. Never overwrite an existing row.
    phase: str = "attempt"  # attempt | outcome
    attempt_id: str = ""
