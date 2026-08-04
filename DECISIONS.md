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

## 2026-08-04 — D-016: A claim is labelled by *who publishes it*, not by who says it
The demo kept finishing with no sourced line at all. The cause was that "うちも、
お持ち帰りは八パーセント" — the national reduced consumption-tax rate, stated in the
first person — was filed as the speaker's own private figure and therefore never
checked. That removed the one claim with a government source behind it, in three
runs out of three.

`Claim.verifiability` replaces the old `about_speakers_own_business` boolean with
three cases, because two of them are unverifiable for different reasons and the
caption a director writes differs:
- `public_record` — published somewhere public. **A statutory or nationally-set
  figure stays public even when spoken in the first person**: the speaker does
  not set the tax rate, so the subject is the rate, not their shop.
- `own_business` — only the speaker knows (their takings, their headcount).
- `unidentified_subject` — real but unnamed ("this shopping street"), so no
  source can ever be about the same entity.

Only `public_record` is searched. An unrecognised label falls back to
unsearchable: a claim wrongly held back costs the director one hand-written
caption, while a claim wrongly sent out puts an unrelated page on screen as
evidence. All three kinds are still extracted — an unverifiable claim was still
said on camera and still needs a caption.

## 2026-08-04 — D-017: Retrieval has to reach the page that states the number
Every judgment was honestly reporting "the source does not state the value", and
it was right: `basic` mode without a text budget returned 42–299 characters per
page. Two changes, both measured before adopting:
- `max_chars_total` set explicitly (~24,500 chars returned, 4 of 10 pages
  carrying the figure, including the industry association's own page).
- The extractor emits a second query aimed at **whoever publishes the fact**
  (国税庁, 日本フランチャイズチェーン協会), not just topic keywords.
`mode="advanced"` was tried and is *worse* here — shorter excerpts, fewer pages
with the figure. Kept `basic`.

Both queries pass the egress gate individually, and the `objective` field is
built from the gated queries alone. It is outbound text too, and building it
from the claim would have sent transcript wording out through a field nobody was
watching.

## 2026-08-04 — D-018: An outage is not a finding
A transient 503 from the comparator wiped a claim's evidence and reported it as
"nothing supports this" — indistinguishable, to a director, from a checked and
unsupported claim. Verification now retries, and a claim whose check never ran
carries `verification_error` and says so.

The same class of bug hid a worse one: batch verdicts were keyed on the
`source_index` the model echoes back, which Gemini routinely omits, so *every*
verdict in a batch was silently discarded. `_align()` now uses indices when they
are present and position only when no verdict is labelled and the counts agree
exactly. A short list of unlabelled verdicts says nothing about which sources it
describes, and attaching one to the wrong source puts the wrong citation on air.

## 2026-08-04 — D-019: A matching figure from years ago does not confirm "now"
"There are about 56,000 of them now" was being marked confirmed by a 2014 count
that rounds the same way. The match is genuine and the source is real; it simply
says nothing about air day. The comparator now reports `value_as_of_year` (the
year the *figure* describes, not the publication date), and a source further back
than `STALE_EVIDENCE_YEARS` can no longer make a claim confirmed. It stays on the
record with 「数字は合うが出典が古い」 so the director can go find the current
release. A source that states no year is **not** assumed stale — absence of a
date is not evidence of age.

The first version of this rule misfired on **statutory rates**: the 8% reduced
consumption-tax rate came back as a "2019 figure" and was held back as stale,
even from 国税庁's own page marked 「令和7年4月1日現在法令等」. A measurement and a
rule age differently. A store count is taken at a moment and goes out of date; a
rate holds until it is changed, so the year it came in says nothing about
whether it still applies. `value_as_of_year` is therefore for measured figures
only, and is 0 for a rule in force unless the source itself says it has changed
or is about to.

## 2026-08-04 — D-020: Speech is decided by whether anyone speaks
`audio_text` was populated only when the shot-type classifier said `interview` or
`reaction`. On footage it labels `other` — which is most footage it has not seen
before — every spoken line was dropped and the script came out with no narration
at all, while still looking structurally complete. It is now keyed on the segment
having a transcript. On-screen text goes to `visual_summary`, so a transcript
means someone spoke; shot type governs ordering only.

## 2026-08-04 — D-021: English first, because that is who is judging
The contest judges test in English. Until now a visitor pressed the one button
and got a Japanese script and a Japanese caption sheet — the output they were
being asked to evaluate was output they could not read.

Two shoots now ship, `en` (a US coffee shop) and `ja` (a Japanese one), telling
the same story. English is the default. The Japanese one stays, and not out of
sentiment: the caption order sheet answers a real Japanese newsroom's problem,
and it is the evidence that this is a tool rather than a demo. Dropping it would
drop the strongest thing about the idea.

Everything that differs by language now lives in `app/lang.py`, keyed by the
language of the footage — the shoot decides, not a setting somebody has to
remember. Caption limits (13 full-width characters vs about 32), the phrase
separator, punctuation rules, every note the director reads, the credit format,
and the examples given to the claim extractor.

## 2026-08-04 — D-022: The confidentiality gate was measuring the wrong thing
The egress gate rejects a query carrying a verbatim span of what someone said.
It measured that span as **12 characters**, which is a clause in Japanese —
「全国におよそ五万六千店」 is exactly 12. In English it is a word and a half:
"federal minim" is 13 characters, so every honest keyword query about what the
speaker had just said was refused. Three US public-record claims went unchecked
on the first English run, and the Egress Log recorded a transcript leak that had
not happened.

The unit now follows the language: characters where there are no word boundaries
to use, and **five consecutive words** where there are. Five words in a row is a
quotation; two or three is the subject matter. This loosens a security-relevant
rule, so the tests pin both directions — a quoted English sentence is still
refused, and the Japanese behaviour is unchanged.

Worth recording as a general lesson: a safety rule tuned on one language quietly
became a denial-of-service against the product's main feature on another, and it
reported itself as working correctly the whole time.

## 2026-08-04 — D-023: Prompt examples move with the shoot
The claim extractor's prompt carried Japanese examples throughout. On an English
shoot the model followed the examples rather than the instruction to match the
transcript, and the caption sheet came back with
「Harrow Bend Coffeeは1日に約200杯のコーヒーを販売している」. The examples are now
selected by language (`lang.CLAIM_EXAMPLES`). An instruction competing with a
page of counter-examples loses.

## 2026-08-04 — D-024: Failing to support is not contradicting
"The federal minimum wage has not changed since 2009" is true, and the
Department of Labor's own page states the history as "1938 - 2009". CONFLICTING
was inferred from "matched the subject and attribute but did not support",
which is the fallacy that absence of support is contradiction — so the sheet
carried "do not use this figure as spoken" against a correct line. Telling a
director to drop a true line is as damaging as letting a false one through. The
comparator is now asked directly whether a source makes the claim false, and
told to answer false when unsure.

## 2026-08-04 — D-025: The analysis cache must key on what produced the answer
It keyed on the media hash alone. In mock mode the reading comes from the
`.analysis.json` sidecar, so two clips with identical video and different
sidecars shared one entry — an English test shoot silently received the Japanese
shoot's transcripts, and the suite passed. The key now covers the sidecar in
mock mode and the video model in real mode, so a model change is not served the
previous model's reading either.
