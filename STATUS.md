# STATUS.md — honest state of the build

_Last update: 2026-08-03 (after the 4-AI review and the trust fixes)_

## Positioning: SETTLED
Axis unchanged — "wake up to a first cut". The differentiator is that the cut
arrives **sourced and confidentiality-cleared**. The reviewers' proposed pivot
to "detect fact changes before air" was rejected on workflow grounds by the
director on this team (by then they are in the edit house with an editor).
See DECISIONS D-011/D-012.

## Phase 0 — Research & design: ✅ DONE
- [x] Monorepo, PLAN/DECISIONS/STATUS, LICENSE (Apache-2.0), .env.example
- [x] ADK confirmed (google-adk 2.6.1; LlmAgent + Runner + InMemorySessionService)
- [x] Gemini video understanding confirmed (real calls verified)
- [x] Parallel Search confirmed (official `parallel-web` SDK 1.1.0, real key)

## Phase 1 — Vertical slice: ✅ DONE
- [x] Pydantic data model
- [x] Gemini client (real + deterministic mock via ground-truth sidecars)
- [x] Parallel client, egress gate, **append-only** Egress Log
- [x] Confidentiality: Gemini proposal + rule layer, stricter-only merge, fail closed
- [x] Claim extraction — self-contained claims, deduplicated
- [x] **Evidence comparator** (entity + attribute + value) replacing numeric overlap
- [x] Scriptwriter — source-linked lines, only supporting sources may be cited
- [x] Rough cut — FFmpeg EDL → MP4 + SRT + edl.json
- [x] ADK orchestration (single LlmAgent + 6 tools; see honesty note below)
- [x] Demo assets — 4 fictional clips with Gemini TTS
- [x] Acceptance tests: **7 passed** (mock mode, deterministic)

### Real-API verification (2026-08-03, this machine)
| Provider | Key | Real call verified |
|---|---|---|
| Gemini video analysis | ✅ | ✅ 4 clips, accurate JP transcripts |
| Gemini text (labels / claims / evidence comparison) | ✅ | ✅ |
| Gemini TTS (demo assets) | ✅ | ✅ |
| ADK orchestration (gemini-2.5-pro) | ✅ | ✅ all 6 tools in order |
| Parallel Search (`parallel-web` SDK) | ✅ | ✅ safe queries only; off-record query blocked and logged |
| Google Cloud TTS narration | — | not started |
| Cloud Run deploy | ✅ | ✅ **https://currentcut-317408545495.asia-northeast1.run.app** — one-click demo runs the real pipeline in the container (Gemini → Parallel → FFmpeg), keys from Secret Manager |

### What the trust fixes changed (measured on the same demo footage)
| | Before | After |
|---|---|---|
| Sources judged to support the claims | ~all of 31 | 1 of 24 |
| Rough cut citations | `価格は1980円です。（出典: www.lovelive-anime.jp）` | no false citation; unverified claims carry no source |
| Claims falsely marked CONFIRMED | 3 | 0 |
| Egress Log rows with the pre-send state | 0 of 5 | every attempt kept, linked to its outcome |

The fictional demo product now yields **zero** confirmed claims. That is the
correct answer — a made-up product has no real evidence — and it is the reason
the demo subject has to change (below).

## Next
1. **Make the demo produce a confirmed claim reliably.** The tax-rate line
   (8% takeaway / 10% eat-in) verifies against a tax-publisher source locally,
   but extraction varies between runs and one production pass produced no
   confirmed claim at all — so the "sourced first cut" promise was not visible
   on screen. This is the single most important gap.
2. **Speed.** A cold run takes ~4 minutes because Gemini watches four clips and
   claim extraction is one call per segment. Batch the per-segment calls and
   ship the analysis cache in the image (hash-keyed, so it is caching rather
   than faking — the search, script and cut still run live).
3. Volatility flags surfaced in the morning report UI
4. Browser upload (footage paths are currently restricted to the bundled clips)
5. English 3-minute demo video, submission package

## Deployment notes
- Project `clearslate-demo-2026`, region `asia-northeast1`, service `currentcut`
- `--min-instances=1 --no-cpu-throttling` are required: the run continues on a
  worker thread after the starting request returns
- `/healthz` is registered but returns Google's own 404 through the edge; the
  app itself is reachable on `/`, `/docs` and every `/api` and `/projects` route

## Honesty notes
- The ADK layer is **one `LlmAgent` calling six tools in a fixed order**, not
  nine autonomous agents. Documentation and submission text must say so.
- Support judgments come from Gemini and are not infallible; the acceptance
  target is a claim-level evaluation set with zero false confirmations, which
  does not exist yet.
- Confidentiality enforcement is application-layer only. The media still exists
  in storage and Gemini processes all footage under Google's API terms.
