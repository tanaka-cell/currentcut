# DECISIONS.md — Architecture & Product Decisions

Format: date / decision / why / alternatives considered.

## 2026-08-03 — D-001: Repo location outside OneDrive
`C:\Users\PC_USER\dev\currentcut`. OneDrive sync churns on `node_modules`/`.venv`/video
files and can corrupt git. Backed up via GitHub remote instead.

## 2026-08-03 — D-002: Python 3.11 + requirements.txt (no poetry/uv lock for now)
Local machine has Python 3.11.9. Keep dependency management boring; Cloud Run
build uses the same requirements.txt. Revisit if dependency conflicts appear.

## 2026-08-03 — D-003: Core agent logic as plain functions, ADK as the orchestration layer
Each agent's business logic (Gemini calls, confidentiality rules, Parallel client,
FFmpeg) lives in importable modules; ADK agents wrap them as tools/sub-agents.
Why: testable without an LLM in the loop, mock mode stays trivial, and the ADK
workflow (`SequentialAgent` pipeline) still genuinely controls execution at runtime
— satisfying the contest's "ADK actually runs" requirement without making business
logic untestable.

## 2026-08-03 — D-004: Storage = local JSON store behind a repository interface; Firestore adapter in Phase 8
Phase 1 needs replayable, diffable state (great for demos and tests). The
`Store` interface (get/put/query by project) is Firestore-shaped so the swap is
mechanical.

## 2026-08-03 — D-005: Mock mode is per-provider and auto-detected
`GEMINI_API_KEY` present → real Gemini; missing → deterministic mock with a loud
banner in logs/UI + `AgentRun.provider="mock"`. Same for `PARALLEL_API_KEY`.
Never silently fake: STATUS.md and the Agent Trace UI both show which providers
were real. Env overrides: `CURRENTCUT_FORCE_MOCK=gemini,parallel`.

## 2026-08-03 — D-006: Confidentiality decisions are deterministic code, not only LLM output
Gemini proposes labels per segment; a rule layer enforces hard guarantees:
anything labeled `OFF_THE_RECORD`/`CONFIDENTIAL`/`PERSONAL_DATA` is stripped
before any Parallel call by the egress gate (code, not prompt). LLMs classify;
code enforces. Uncertain → `NEEDS_HUMAN_REVIEW` (fail closed).

## 2026-08-03 — D-007: Egress gate is a single choke point
All outbound Parallel calls go through `clients/parallel.py::search()`, which
(1) refuses non-PUBLIC-derived queries, (2) refuses queries containing raw
transcript sentences (similarity check), (3) writes an EgressLog record before
and after every call. No other module imports the HTTP client.

## 2026-08-03 — D-008: Demo footage is synthesized, speech via Gemini TTS when key present
No real client footage. `scripts/make_demo_assets.py` builds the fictional
"AIスマート弁当箱" shoot with FFmpeg (color scenes + burned-in labels) and
Gemini TTS speech for interview audio (falls back to text-on-screen + tone when
no key). Google TTS is contest-allowed.

## 2026-08-03 — D-009: Phase 1 skips the Next.js UI
The brief prioritizes the real-API vertical slice over UI. Phase 1 exposes the
pipeline via FastAPI endpoints + CLI (`python -m app.cli run demo`); the web app
lands in Phase 4/7. A JSON "morning report" endpoint already returns the numbers
the Morning Dashboard will render.

## 2026-08-03 — D-010: Model names only via env vars
`GEMINI_VIDEO_MODEL` / `GEMINI_REASONING_MODEL` / `GEMINI_FAST_MODEL` with
defaults set in `config.py` after checking availability (research pending —
see STATUS). No model IDs hardcoded elsewhere.

## 2026-08-03 — D-011: Main axis stays "wake up to a first cut"; the differentiator is that the cut is sourced and confidentiality-cleared
A 4-AI review unanimously proposed reframing the product around "facts change
before air → propagate to script/caption/cut". The director on this team
rejected it from workflow experience: by the eve of air they are already in the
edit house with a professional editor, so an AI has no seat there — and the
rough cut CurrentCut generates has been discarded by then anyway.

That objection is decisive, and the reviewers' proposal would have cost us the
"Quality of the Idea — do they understand a real problem?" criterion it was
meant to win. The AI window is between the shoot and the edit house, which is
exactly where the original positioning sits.

The reviewers were right about one thing: transcript → rough cut already ships
(Trint Story Builder, Descript Underlord, Avid PhraseFind/ScriptSync AI,
Premiere text-based editing, DaVinci Resolve, Axle AI). Our answer is not a
different workflow position but a different output:
**a first cut that arrives with sources attached and off-record material
already removed.** Across the broadcast tools surveyed, none documents
fact-checking or off-record handling. Parallel stays central — it is what puts
the sources on the numbers.

## 2026-08-03 — D-012: Freshness demoted to a volatility flag, and moved before the edit house
Not "detect that a fact changed and re-render", but "before you lock the
structure, here are the claims whose sources state an expiry or a scheduled
change". Raised only when a source actually says so (`dated_qualifier`); a
generic "prices move" is not worth a director's attention. The director decides
whether it reaches the script — the tool only surfaces candidates.

## 2026-08-03 — D-013: Support is entity + attribute + value, never numeric overlap
The old heuristic confirmed a bento-box price from an anime fan site because
both contained "1980", and the rough cut burned that citation into the picture.
Two distinct defects, both fixed:
1. `_judge_support` counted any shared number as support → replaced by the
   Gemini evidence comparator (`agents/evidence.py`), which requires entity,
   attribute and value to all match and fails closed on error.
2. `_caption_for` cited `results[0]` without checking `supports_claim` → now
   only a supporting source may be cited, primary sources first.
Claims are also required to be self-contained: "価格は1,980円" verifies against
anything, so the extractor must produce "<subject>の価格は1,980円".

## 2026-08-03 — D-014: Egress Log is append-only
The attempt record and the outcome record were being written under the same id,
so the store replaced the first with the second and the "what we were about to
send" row never survived. Each write is now its own row, linked by
`attempt_id`. An audit trail that overwrites itself is not an audit trail.

## 2026-08-03 — D-015: EDITORIAL_ONLY may not leave the building
Briefly relaxed so that verification would fire at all; the real cause was the
LLM over-labeling ordinary on-camera statements, since fixed in the prompt.
External search is PUBLIC-only again. Fail-closed is the product's claim, and
loosening it to make a demo work is the wrong trade.
