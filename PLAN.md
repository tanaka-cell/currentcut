# CurrentCut — Implementation Plan

> Rest after the shoot. Wake up to a first cut.

Target: Google Cloud "Agentic Cinema: The Blockbuster Hackathon" — **Parallel track**.
Deadline: 2026-09-08 06:00 JST.

## Positioning (settled 2026-08-03, see DECISIONS D-011)

Axis: **"Rest after the shoot. Wake up to a first cut."**
Differentiator: **the first cut arrives sourced and confidentiality-cleared.**
Working window: **after the shoot, before the edit house** — the nights the
director is alone with the footage. Once the edit house starts, a human editor
is in the room; the tool steps back and does not try to follow the edit.

## What we are building

An AI agent for directors of 5–15 min factual TV features. After the shoot, the
director uploads raw footage and presses **Start Overnight Run**. While they rest,
a Google ADK workflow:

1. Understands all footage (Gemini video understanding)
2. Produces timecoded transcripts, usable soundbites, B-roll classification
3. Detects confidential / off-record / personal-data segments (**Confidentiality Firewall**)
4. Extracts verifiable, self-contained claims and generates *safe* search queries
5. Verifies claims against the live web (**Parallel Search API**) — never sending raw
   footage text, and counting a page as support only on entity + attribute + value
6. Writes a source-linked TV script (every line tied to footage TC + sources)
7. Renders a rough cut MP4 with temp captions (FFmpeg) + temp narration (Google Cloud TTS)
8. Flags the claims whose sources state an expiry or a scheduled change, so the
   director can settle the wording before locking the structure

## Runtime AI stack (contest-compliant)

| Capability | Service |
|---|---|
| Video/audio/text understanding | Gemini (google-genai SDK) |
| Agent orchestration | Google Agent Development Kit (ADK) |
| Live web verification | Parallel Search API |
| Temp narration | Google Cloud Text-to-Speech |
| Everything else | FFmpeg, FastAPI, Next.js, Firestore/local JSON, Cloud Run |

No Anthropic/OpenAI/AWS/other AI APIs at runtime. Claude Code is used for
development only.

## Phases

- **Phase 0** — Research current ADK / Gemini video / Parallel APIs; monorepo; docs. ✅ then →
- **Phase 1** — Vertical slice: 1 short video → Gemini analysis → confidentiality →
  claims → Parallel search → 1-page script → FFmpeg rough cut. Real APIs wired,
  mock mode for missing creds.
- **Phase 2** — Multi-clip, hash-based analysis cache, merged transcript.
- **Phase 3** — Confidentiality Firewall hardening: labels, egress control, Egress Log, human unlock.
- **Phase 4** — Source-linked Script UI (ScriptLine ↔ footage ↔ sources ↔ status).
- **Phase 5** — Rough Cut: EDL JSON, FFmpeg render, SRT, player page.
- **Phase 6** — Volatility flags: surface claims whose sources state an expiry or
  scheduled change, before the structure is locked. (Replaces the former
  "Freshness / re-render before air" scope — see DECISIONS D-012.)
- **Phase 7** — UI polish: Morning Dashboard, Overnight Run, Confidentiality Review,
  Final Air Check, Agent Trace.
- **Phase 8** — Deploy: Cloud Run (web + agent), Firestore, Cloud Storage, Secret Manager.
- **Phase 9** — Submission: public repo, OSS license, README, architecture diagram,
  3-min demo script, Quick Judge Demo.

## Repo layout

```
currentcut/
├── apps/web/                 Next.js + TypeScript (director console)
├── services/agent/           Python + FastAPI + Google ADK
│   ├── app/
│   │   ├── agents/           ADK agents (footage_logger, confidentiality, claims,
│   │   │                     research, story_editor, scriptwriter, rough_cut,
│   │   │                     freshness, review)
│   │   ├── clients/          gemini.py / parallel.py / tts.py (+ mock fallbacks)
│   │   ├── models/           Pydantic schemas (single source of truth)
│   │   ├── pipeline.py       Overnight Run orchestration (ADK)
│   │   └── main.py           FastAPI
│   └── tests/                Acceptance tests 1–6
├── packages/shared-schemas/  JSON Schema exported from Pydantic
├── scripts/                  make_demo_assets.py etc.
├── demo-assets/              Fictional "AI smart bento box" shoot
├── infra/terraform/
└── docs/
```

## Quick Judge Demo (fictional, no client footage)

Topic: 「AI搭載型スマート弁当箱が話題」 — 3–5 clips, 2–5 min total, containing:
public product talk, "全国80店舗" (verifiable), "価格1,980円" (changes later),
an off-record line, customer reactions, B-roll, storefront. Judges get a
60–90 s rough cut + full agent trace in ~5 minutes of wall time.
