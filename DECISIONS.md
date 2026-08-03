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
