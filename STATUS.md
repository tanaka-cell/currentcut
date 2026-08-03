# STATUS.md — honest state of the build

_Last update: 2026-08-03 (Phase 0 + Phase 1 complete)_

## Phase 0 — Research & design: ✅ DONE
- [x] Monorepo initialized (git, layout, docs, LICENSE, .env.example)
- [x] ADK current API confirmed (google-adk 2.6.1 installed; LlmAgent + Runner
      + InMemorySessionService verified working in this repo)
- [x] Gemini video understanding confirmed (real calls verified, see below)
- [x] Parallel Search API spec confirmed (POST /v1/search, x-api-key,
      objective + search_queries, source_policy.after_date; SDK `parallel-web`)

## Phase 1 — Vertical slice: ✅ DONE
- [x] Pydantic data model (Project/Asset/Segment/Claim/ResearchResult/
      ScriptLine/ChangeEvent/AgentRun/EgressLog)
- [x] Gemini client — real video analysis + deterministic mock (sidecar JSON)
- [x] Parallel client — real HTTP code + mock; egress gate; EgressLog before/after
- [x] Confidentiality: Gemini proposal + rule layer (stricter-only merge, fail closed)
- [x] Claim extraction + safe search queries (keyword-only, language-preserving)
- [x] Scriptwriter — source-linked ScriptLines, evidence statuses
- [x] Rough cut — FFmpeg EDL → MP4 (720p, burned captions) + SRT + edl.json
- [x] ADK orchestration — LlmAgent "overnight_director" with 6 tools drives the
      run end-to-end (verified with real Gemini)
- [x] Demo assets — 4 fictional clips (~50 s) with Gemini TTS speech + ground-truth sidecars
- [x] Acceptance tests 1–3 + 5(partial): **5 passed** (mock mode, deterministic)

### Real-API verification (2026-08-03, this machine)
| Provider | Key | Real call verified |
|---|---|---|
| Gemini video analysis | ✅ | ✅ 4 clips analyzed, JP transcripts accurate |
| Gemini text classification / claims | ✅ | ✅ |
| Gemini TTS (demo assets) | ✅ | ✅ |
| ADK orchestration (gemini-2.5-pro) | ✅ | ✅ "DONE 7 lines." — all 6 tools called in order |
| Parallel Search API | ❌ no key yet | ❌ real client code written, UNTESTED — mock verified. Get key from hackathon portal / platform.parallel.ai |
| Google Cloud TTS narration | — | not started (Phase 5) |
| Cloud Run deploy | — | not started (Phase 8) |

### Verified end-to-end behavior (real Gemini + mock Parallel)
- Off-record segment (Gemini even misheard 「オフレコ」→「オフエコ」) still caught
  by the rule layer via 「発表前」/「放送では使わないで」 → OFF_THE_RECORD,
  blocked from search/script/cut. Layered defense worked as designed.
- 「全国80店舗」 → safe query 「80店舗 全国 公式」 → PRIMARY_SOURCE_CONFIRMED,
  source linked into the script line caption.
- 「人気ですよね」 → popularity claim held for human approval (egress blocked, logged).

## Next (Phase 2–3)
- [ ] Async job execution (Overnight Run as background task + progress endpoint)
- [ ] Parallel real-key smoke test once key obtained
- [ ] Claim-vs-evidence comparison via Gemini (replace numeric overlap heuristic)
- [ ] Freshness Agent + ChangeEvent propagation (test 4)
- [ ] Next.js console skeleton (Morning Dashboard from /report)

## Known issues / risks
- google-adk 2.6.1 emits a deprecation-style warning when both GOOGLE_API_KEY
  and GEMINI_API_KEY are set (harmless; GOOGLE_API_KEY wins).
- Rough cut captions use Meiryo via drawtext; on non-Windows set CURRENTCUT_FONT.
- Analysis cache is keyed by (file hash, provider) — switching mock/real re-analyzes.
