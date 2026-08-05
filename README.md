# CurrentCut

> **Rest after the shoot. Wake up to a first cut.**
> You shot the story. CurrentCut worked the night shift.

CurrentCut is an AI night-shift agent for directors of 5–15 minute factual TV
features. After the shoot, the director uploads raw footage, presses **Start
Overnight Run**, and rests. Overnight, a Google ADK workflow understands every
clip, holds restricted segments back from search, script and cut and lists
them for review, checks eligible claims against live sources — recording a
source or a no-source reason — writes a source-linked script, and renders a
rough cut. So the next morning the director makes editorial decisions instead
of scrubbing through hours of footage.

**What makes the cut different from an automatic rough cut.** Transcript-driven
editing already ships in several products. CurrentCut's first cut is different
in what comes attached to it:

- **Every factual line carries its source, or says why it has none.** A number
  reaches the script as checked only when a retrieved page matches it on
  entity, attribute and value. A page that merely contains the same digits is
  not evidence, and a line that nothing supported says so rather than going out
  unmarked.
- **Off-record material is held back, and what was held is shown to you.**
  Not greyed out for the director to notice — kept out of the search queries,
  the script and the cut, with the block recorded and listed for review.
- **Claims whose sources state an expiry or a scheduled change are flagged**
  before the structure is locked ("this is a campaign price, valid until Aug 31";
  "two more stores open this month"). The tool surfaces the candidate; the
  director decides whether it belongs in the script.

The window CurrentCut works in is between the shoot and the edit house — the
nights the director spends alone with the footage. Once the edit house starts,
a human editor is in the room and the tool steps back.

Built for Google Cloud **"Agentic Cinema: The Blockbuster Hackathon"** —
Parallel track.

**Live: https://currentcut-317408545495.asia-northeast1.run.app**
One button runs a real overnight pass on the bundled demo footage — Gemini
reads the clips, the Parallel Search API checks the claims that clear the
confidentiality gate, FFmpeg cuts the preview. Nothing on that page is
pre-generated; it takes a few minutes because the work actually happens.

## The problem

Directors of factual features (trend segments, business news, weekly shows)
spend the nights after a shoot doing three jobs at once: logging footage,
fact-checking numbers that may change before air, and drafting a cut. Facts
like prices and store counts go stale between shoot day and air day, and one
off-record remark accidentally left in a timeline is a career-level incident.

## Why 5–15 minute factual features

They are long enough that footage logging and fact-checking dominate the
director's night, short enough that an agent can produce a reviewable first
cut, and fact-dense enough that live web verification (Parallel) genuinely
matters. Breaking news, anonymous-source stories, and crime/politics are
explicitly out of scope — CurrentCut never makes the air/no-air decision.

## Runtime AI stack (contest-compliant)

| Capability | Service | Where in code |
|---|---|---|
| Video/audio understanding | **Gemini** (google-genai) | `services/agent/app/clients/gemini_client.py` |
| Agent orchestration | **Google ADK** (`LlmAgent` + tools) | `services/agent/app/adk_pipeline.py` |
| Live web verification | **Parallel Search API** | `services/agent/app/clients/parallel_client.py` |
| Temp narration (planned) | Google Cloud Text-to-Speech | Phase 5 |
| Cutting/rendering (non-AI) | FFmpeg | `services/agent/app/agents/rough_cut.py` |

No non-Google AI APIs at runtime. The only AI services this application calls
are Gemini, Google ADK, and the Parallel Search API.

## Confidentiality Firewall

The AI reads everything; what leaves the edit suite is controlled by **code,
not prompts**:

1. Every segment gets a label: `PUBLIC / EDITORIAL_ONLY / CONFIDENTIAL /
   OFF_THE_RECORD / PERSONAL_DATA / NEEDS_HUMAN_REVIEW`. Gemini proposes,
   a deterministic rule layer can only make labels *stricter*, and uncertainty
   fails closed.
2. All outbound search goes through one choke point
   (`parallel_client.search_for_claim`) whose **egress gate** refuses
   restricted labels, unapproved claims, and any query containing raw
   transcript text. Safe queries are keyword-only (`○○社 店舗数 公式 2026`).
3. Every attempt — allowed or blocked — is written to an **Egress Log**
   (`GET /projects/{id}/egress`).
4. Restricted segments are excluded from script and rough cut, and the rough
   cut renderer re-checks independently (defense in depth).

## Source-to-Cut Graph

Footage utterance → timecoded segment → verifiable claim → web evidence →
script line → caption → cut. Every `ScriptLine` stores `segment_id`,
`claim_ids`, source links and an evidence status
(`FOOTAGE_CONFIRMED / PRIMARY_SOURCE_CONFIRMED / MULTIPLE_SOURCES_CONFIRMED /
EDITORIAL_LANGUAGE / UNVERIFIED / CONFLICTING`). The director can move from any
line in the script to the footage timecode it came from and to the page that
backs it, and can see which claims are the kind that go stale.

## How support is decided

A retrieved page supports a claim only when the entity, the attribute and the
value all match (`app/agents/evidence.py`). Claims are required to be
self-contained for this reason: "the price is ¥1,980" would verify against any
page containing that number, so the extractor restores the subject —
"<product>'s price is ¥1,980". Verification failures never count as support,
and a single non-primary source is not enough to call a fact confirmed.

## Repo layout

```
apps/web/                 Next.js director console (Phase 4/7)
services/agent/           Python 3.11 + FastAPI + Google ADK
  app/agents/             footage_logger, confidentiality, claims, research,
                          scriptwriter, rough_cut
  app/clients/            gemini_client, parallel_client (egress gate)
  app/adk_pipeline.py     ADK LlmAgent that drives the overnight run
  app/pipeline.py         pipeline steps + deterministic fallback
  tests/                  acceptance tests (brief §13)
eval/                     labelled claims + how often the checker is wrong
scripts/make_demo_assets.py   fictional demo shoot generator
demo-assets/generated/    synthetic footage (never real client material)
```

## Is the checking any good?

`eval/` holds 34 claims taken from real runs, each with the pages actually
retrieved for it and a hand-written judgement of whether that evidence
establishes the claim. Measured over three consecutive passes: **0–1 false
confirmations in 34**, alongside 7 claims wrongly withheld in every pass. The
failures are named in [eval/measured.md](eval/measured.md) rather than averaged
away — a checker that confirms nothing would score a perfect zero, so the two
numbers only mean anything together.

```bash
python scripts/run_eval.py             # judge again and score; needs GEMINI_API_KEY
python scripts/run_eval.py --offline   # score recorded verdicts, no key needed
```

## Deploy

```bash
gcloud run deploy currentcut --source . --region=asia-northeast1 \
  --allow-unauthenticated --memory=2Gi --cpu=2 --timeout=900 \
  --min-instances=1 --no-cpu-throttling \
  --set-secrets=GEMINI_API_KEY=currentcut-gemini-key:latest,PARALLEL_API_KEY=currentcut-parallel-key:latest
```

Keys come from Secret Manager. `--no-cpu-throttling` and `--min-instances=1`
matter: the overnight run continues on a worker thread after the HTTP request
that started it has returned.

## Local quickstart

```bash
cd services/agent
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows
cp ../../.env.example .env    # fill GEMINI_API_KEY / PARALLEL_API_KEY if you have them

# 1. generate the fictional demo shoot (uses Gemini TTS when key present)
.venv/Scripts/python ../../scripts/make_demo_assets.py

# 2. overnight run (deterministic orchestration)
.venv/Scripts/python -m app.cli demo
# 2b. overnight run driven by the ADK agent
.venv/Scripts/python -m app.cli demo --adk

# 3. API server
.venv/Scripts/uvicorn app.main:app --reload
# POST /projects, POST /projects/{id}/assets, POST /projects/{id}/run,
# GET /projects/{id}/report /script /segments /egress /trace

# 4. tests (mock mode, no keys needed)
.venv/Scripts/python -m pytest tests/
```

**Mock mode:** missing `GEMINI_API_KEY` / `PARALLEL_API_KEY` switches that
provider to a deterministic mock, reported honestly in `/healthz` and the
agent trace (`provider: "mock"`). Real-API code paths are always compiled in;
adding keys switches them on with no code change.

## Demo material

All demo footage is synthetic and fictional — a fictional independent coffee
shop owner interviewed about competing with convenience-store coffee, shot in
two versions of the same story (English: a US coffee shop; Japanese: 「街の喫茶
店」). It deliberately plants claims a director would actually have to check:
public statistics the owner cites (US small-business employment share / the
federal minimum wage; convenience-store counts / Japan's reduced consumption
tax rate), a number about the speaker's own business that has no public source
to check it against, and an off-record remark. Generated by
`scripts/make_demo_assets.py` (Veo for video, Gemini TTS for the voice track).

## Security limits (honest)

Confidentiality enforcement is at the application layer: content marked
restricted is excluded from egress, script, cut and logs by code paths in this
repo — but the underlying media still exists in storage, and Gemini processes
all footage under Google's API terms. No claim is made of absolute
non-leakage; the Egress Log exists precisely so humans can audit what left.

## Footage volume (honest)

A ten-minute factual feature is cut from hours of rushes, not from a handful of
short clips. What that costs, measured rather than assumed:

- **Watching is the cheap part.** Rushes are logged by what is said, so video
  goes to Gemini at low media resolution: roughly 100 tokens per second of
  footage, and a file up to three hours fits a single request. Three hours is
  on the order of a million input tokens.
- **Long takes are split, not refused.** Anything longer than
  `CURRENTCUT_ANALYSIS_CHUNK_MINUTES` is cut at keyframes and the pieces are
  read in parallel, then the clock is put back. Boundaries land on keyframes so
  a piece's first frame is byte-identical to the source at that timestamp — the
  timecode in the caption sheet is the one that finds the moment on the tape.
  Pieces exist only while being read and are deleted immediately after.
- **Concurrency is the wall-clock lever.** Every heavy step is one call per clip
  or per segment with nothing shared between them, so they run
  `CURRENTCUT_MAX_CONCURRENCY` at a time. Done one after another, a night's
  rushes becomes a day's wait.
- **Storage is the real constraint, and it is a deployment choice.** Cloud Run's
  filesystem is memory, so every uploaded clip counts against the instance's
  RAM. The public instance is small, and its upload caps are sized to it. A
  deployment ingesting real rush volumes wants a Cloud Storage volume mount
  rather than a larger memory number.
- **Not built yet:** ingest that runs while the director sleeps (a watch folder
  or resumable upload, rather than a browser holding several gigabytes), and a
  cheap first pass that locates speech so the detailed read only covers the
  parts that matter. Both are the obvious next steps; neither is pretended to
  exist.

The caps on the landing page are served from `/api/limits`, which reports this
instance's own configuration. They are demo policy on shared API keys, not
limits of the pipeline.

## Status / roadmap

See `STATUS.md` (honest, per-phase) and `PLAN.md`. Deploy target: Cloud Run +
Firestore + Cloud Storage + Secret Manager (Phase 8).

## License

Apache-2.0 — see `LICENSE`.
