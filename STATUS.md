# STATUS.md — honest state of the build

_Last update: 2026-08-04 (verification reliability — the first cut now arrives sourced)_

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

The fictional demo product yielded **zero** confirmed claims. That was the
correct answer — a made-up product has no real evidence — and it is why the demo
subject was changed to a shoot that cites real public statistics.

## Verification reliability (2026-08-04): ✅ the sourced line now shows up

The headline gap — production runs finishing with **zero** confirmed claims, so
the "sourced first cut" was never on screen — was four separate faults, each
found by measuring rather than reasoning.

Confirmed claims per run, same footage, five consecutive runs:

| | before | after |
|---|---|---|
| Confirmed claims per run | 0, 0, 0 | **2, 3, 3, 2, 3** |
| Tax-rate claims confirmed | 0 (never searched) | **10 / 10** |
| Runs with no sourced line at all | all of them | none |

Sources are nta.go.jp, keisan.nta.go.jp, mof.go.jp, customs.go.jp, nikkei.com
and 7andi's IR pages.

The store-count claim still fails to confirm in 2 runs out of 5, and that is the
rule working: the only figures retrieved on those runs were counts from 2019 and
2021. "About 56,000 of them now" is not settled by a 2019 count, and the claim
carries 「数字は合うが出典が古い」 rather than a citation.

| Fault | What it did | Fix |
|---|---|---|
| A statutory rate was filed as the speaker's private figure | "we charge 8% on takeaway" is the national reduced rate; labelled own-business, it was never searched — losing the one claim with a government source behind it. 3 runs out of 3. | `Verifiability` on the claim: `public_record` / `own_business` / `unidentified_subject`. A nationally-set figure stays public even in the first person; unknown labels fail closed to unsearchable |
| One keyword query, and no text budget | Parallel returned 42–299 char snippets that never contained the number, so every judgment honestly read "the source does not state the value" | A second query aimed at the publisher (国税庁, 日本フランチャイズチェーン協会) plus `max_chars_total`; both queries pass the egress gate. Measured: ~24,500 chars, 4 pages carrying the figure, including the industry association's own page |
| Batch verdicts keyed on an index the model omits | Gemini rarely emits `source_index`, so every verdict in the batch was discarded and the run read as "nothing supports any of this" | `_align()`: indices win when present, position only when no verdict is labelled *and* the counts agree. Never guess a verdict onto a source |
| A transient API error looked identical to a finding | One 503 wiped a claim's evidence and reported it as unsupported | Retry, then say plainly that the check did not run (`Claim.verification_error`). An outage is not a finding |

Two further faults surfaced while verifying the above:
- **A 2014 figure was confirming a present-tense claim.** "About 56,000 of them
  now" matched a 2014 count that rounds the same way. The comparator now reports
  `value_as_of_year`, and a source more than `STALE_EVIDENCE_YEARS` behind can no
  longer make a claim confirmed — it stays on the record with
  「数字は合うが出典が古い」. A source that states no year is *not* assumed stale.
  The first cut of this rule then misfired the other way: it held back the 8% tax
  rate as a "2019 figure", rejecting 国税庁's own page marked 「令和7年4月1日現在
  法令等」. A measurement dates; a rule holds until changed. `value_as_of_year` is
  now for measured figures only (see D-019).
- **The script came out with no narration at all.** `audio_text` was gated on the
  shot-type guess being `interview`/`reaction`; on footage Gemini labels `other`
  every spoken line was silently dropped. It is now gated on whether anyone
  speaks — on-screen text lives in `visual_summary`, so a transcript means speech.

Also: judging is one call per claim instead of one per source (10× fewer round
trips), which is most of Next item 2 below.

Tests: **35 passed**. `tests/test_verifiability.py` pins each fault above.

### Verified in production (2026-08-04, revision `currentcut-00008-pvc`)

One click on the hosted demo, real pipeline, no pre-generated anything. The
telop order sheet came back with its citations filled in:

| Telop | 出典 | 備考 |
|---|---|---|
| 全国 コンビニ／5万6000店 | www.bengo4.com | 12月度 |
| 消費税 軽減税率／お持ち帰り 8% | **www.nta.go.jp** | 2027年4月から1%に引き下げ |
| 店内飲食　消費税10% | stripe.com | |
| 1日　約100杯　コーヒー | — | 自店の数字　公開データなし |
| 喫茶店客 10年で／3割減 | — | 自店の数字　公開データなし |
| この商店街　店減少 | — | 対象が特定できない　裏取り不可 |

8 claims checked, 1 confidential moment protected, 47.1s cut. The volatility
flag on the 8% line is the useful kind — the source itself says the rate drops
to 1% in April 2027.

Rough edge: the 10% line cites stripe.com. Supporting sources are sorted
official/government first, so no primary source backed that claim on this run
and a payments vendor's explainer led instead. It is a true citation but not one
to put on air; the data telop should probably require a primary source or else
carry no 出典 at all.

Deployment note: `gcloud` credentials live per-machine. `gcloud auth login` as
`fieldcasterjp@gmail.com` is a prerequisite; `deploy.sh` wraps the rest.

## Next
1. **Speed.** A cold run is still dominated by Gemini watching four clips. Ship
   the analysis cache in the image (hash-keyed, so it is caching rather than
   faking — search, script and cut still run live).
2. Volatility flags surfaced in the morning report UI
3. Browser upload (footage paths are currently restricted to the bundled clips)
4. English 3-minute demo video, submission package

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
