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
| Cloud Run deploy | — | **not started — this is the top Stage-1 risk** |

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
1. **Cloud Run deploy** (Stage-1 blocker: a hosted URL is required)
2. **Swap the demo subject** from the fictional bento box to a real, publicly
   verifiable one. Measured 2026-08-03: a query for the national average
   gasoline price returns the Agency for Natural Resources and Energy statistics
   page as a primary source, and `after_date` filtering surfaces genuinely newer
   figures — so sourcing and volatility flags can both be shown for real.
3. Volatility flags surfaced in the morning report (`dated_qualifier` is already
   captured by the comparator)
4. Browser upload + async job execution (currently local paths, synchronous —
   also a security problem once hosted)
5. Next.js console: Morning Dashboard / Source-to-Cut Review / Confidentiality
6. English 3-minute demo video, submission package

## Honesty notes
- The ADK layer is **one `LlmAgent` calling six tools in a fixed order**, not
  nine autonomous agents. Documentation and submission text must say so.
- Support judgments come from Gemini and are not infallible; the acceptance
  target is a claim-level evaluation set with zero false confirmations, which
  does not exist yet.
- Confidentiality enforcement is application-layer only. The media still exists
  in storage and Gemini processes all footage under Google's API terms.
