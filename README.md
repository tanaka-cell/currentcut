# CurrentCut

> **Rest after the shoot. Wake up to a first cut.**
> You shot the story. CurrentCut worked the night shift.

CurrentCut is an AI night-shift agent for directors of 5–15 minute factual TV
features. After the shoot, the director uploads raw footage, presses **Start
Overnight Run**, and rests. Overnight, a Google ADK workflow understands every
clip, protects confidential moments, verifies claims against the live web,
writes a source-linked script, and renders a rough cut — so the next morning
the director makes editorial decisions instead of scrubbing through hours of
footage.

**What makes the cut different from an automatic rough cut.** Transcript-driven
editing already ships in several products. CurrentCut's first cut is different
in what comes attached to it:

- **Every factual line carries its source.** A number reaches the script only
  when a retrieved page matches it on entity, attribute and value. A page that
  merely contains the same digits is not evidence.
- **Off-record material is already gone.** Not greyed out for the director to
  notice — excluded from the search queries, the script and the cut, with the
  block recorded.
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
scripts/make_demo_assets.py   fictional demo shoot generator
demo-assets/generated/    synthetic footage (never real client material)
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

All demo footage is synthetic and fictional (「AI搭載型スマート弁当箱」 story),
generated by `scripts/make_demo_assets.py` with FFmpeg + Gemini TTS. It
deliberately plants: a verifiable claim (全国80店舗), a price that changes
before air (1,980円), an off-record remark, a "人気" claim requiring human
approval, B-roll and an exterior.

## Security limits (honest)

Confidentiality enforcement is at the application layer: content marked
restricted is excluded from egress, script, cut and logs by code paths in this
repo — but the underlying media still exists in storage, and Gemini processes
all footage under Google's API terms. No claim is made of absolute
non-leakage; the Egress Log exists precisely so humans can audit what left.

## Status / roadmap

See `STATUS.md` (honest, per-phase) and `PLAN.md`. Deploy target: Cloud Run +
Firestore + Cloud Storage + Secret Manager (Phase 8).

## License

Apache-2.0 — see `LICENSE`.
