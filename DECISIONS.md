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

## 2026-08-04 — D-026: The tool proposes an off-record boundary; a person sets it
Reverting D-025's sibling change from earlier the same day. A segment that was
only partly restricted was being split automatically, so the clean sentences
went into the script and the marked one did not.

That made the firewall **worse**, and the director on this team said so. Where an
off-record remark begins and ends is a judgment about subject matter, and the
spoken marker is not reliably at its edge:

    「オフレコですが、来月2号店を出します。まだ発表前なんです。」

The second sentence carries no marker and is plainly still off the record — the
automatic split put it on air. The reverse case is just as common:
「……という話でして。今のはオフレコで。」 marks the sentence *after* the material it
covers, so splitting on the marker releases the very thing being protected.

So the segment is held whole, as before, and the tool now:
- proposes where it thinks the restricted part starts, sentence by sentence,
  with timings apportioned by character count and flagged as estimates;
- raises it in the morning report as a decision waiting on the director, saying
  in as many words that nothing has been released;
- releases only through `POST /projects/{id}/segments/{sid}/release`, which
  requires a name — releasing someone's off-record remark is a person's decision
  and a person's responsibility.

The point is not to choose between losing the material and leaking it. It is to
turn the question into one click for the person entitled to answer it.

## 2026-08-04 — D-027: Nobody says "off the record" on cue
The rule layer knew the formal marker and almost nothing else, so it heard
「オフレコ」 and missed 「放送はしないでほしいんですけど」, 「今のはナシで」,
「表には出さないで」, "please don't use that", "keep that out", "scratch that",
"this stays between us".

The pattern list is now deliberately broad in both languages, because the two
errors do not cost the same: a false positive costs one review click, and a miss
broadcasts something a person asked you not to. Tests cover both sides —
ten phrasings per language that must fire, and ordinary shop talk that must not
(「放送作家の仕事をしていました」, "the camera work was lovely", "we record
everything on tape").

Anything phrased in a way the list does not know still has to get past the Gemini
layer, which can only make a label stricter — and its prompt now says outright
that a polite request is still a request.

## 2026-08-05 — D-028: Which authority gets named, when several may be
Creditable sources were sorted by URL. Among equals that is fine; among
authorities it is not. The federal minimum wage was credited to
`dol.georgia.gov` — a state labour department, which does state the federal
rate truthfully but does not set it — because "d" sorts before "w" and
`www.dol.gov` was sitting in the same supporting evidence. The same sort put
`webapps.dol.gov`, an application server, under the same figure on the next
line. Both reached the sample served on the landing page, which is the first
thing a judge clicks.

Ranking now asks two questions before falling back to the alphabet:

1. **Does the authority match the scope of the claim?** A claim that says
   "federal" is not the state's to certify. Japan encodes the level in the
   suffix already (`.go.jp` national, `.lg.jp` local); the US does not, so the
   state registries are listed by name. A claim about that state credits that
   state's office — the demotion is about scope, not about states ranking below
   the union, and a state page that is the only public body to back a claim is
   still the source.
2. **Is the host the body's published estate?** `www.dol.gov` over
   `webapps.dol.gov`. Content subdomains are deliberately not penalised —
   `advocacy.sba.gov` and `data.bls.gov` are where those figures actually live.

Where the place cannot be read out of the claim at all — `city.yokohama.lg.jp`
against 「横浜市」, romaji domain against kanji text — the authority keeps its
standing. Demoting on a comparison that could not be made would quietly strip
every local office of credit for its own local story, which is the opposite of
the bug being fixed. Silence is not evidence.

The rule reads the claim only to decide scope. It can never make an
uncreditable source creditable: a company blog does not become citable by
naming the right state.

Measured against every stored run: two attributions changed, both the ones
above, and nothing else moved. The landing-page sample was rebuilt from the
recorded evidence of that same run rather than shot again — the claims, the
sources and the timings did not change, only the name the rule picks out of
them (`scripts/refresh_sample_credits.py`).

## 2026-08-05 — D-029: Count the checker's mistakes, then publish the count
"Every factual line carries the source it was checked against" is a claim about
a model's judgement, and it was never measured. `eval/` measures it.

The set is not written by hand. It is every claim any recorded run produced,
with the pages the search actually returned and the excerpt each verdict came
from, collected by `scripts/build_eval_set.py`. Labels are added separately:
does *this* evidence establish *this* claim, and which domain — if any — may be
printed on air. `citable: null` is a common and correct answer.

Two exclusions, both found by building it:

- **Mock runs invent their evidence** on a fixture domain. Fourteen of the 48
  collected claims were partly fixture, four of them marked confirmed. Scoring
  those would have been scoring the fixture, so they are dropped.
- **The stored `source_type` is whatever the classifier said that day.** The
  first harness replayed it and reported nine wrong attributions — all of them a
  retired classifier crediting a tax publisher for the national tax rate. The
  harness now classifies from the URL with today's code. Nine became zero, and
  the lesson is the general one: an evaluation that replays a stored decision
  measures the version that made it.

The harness calls `research.apply_judgments` and `evidence.citable_source`
directly, which is why `apply_judgments` was lifted out of the pipeline loop. An
evaluation that reimplements the rule measures the reimplementation.

**Measured, three consecutive passes: 0–1 false confirmations in 34 claims.**
Not the clean zero we wanted, and the range is published rather than the best
pass. The failure is always the same one — a capability of a product that does
not exist, matched to a research paper about that product *category*. The
comparator holds the line against a rival product and not against a survey of
the field. Three historical false confirmations (a Fire TV Stick's price, a
sushi chain's store table, a smart bath mat) are rejected 3/3 and stay in the
set as the regression they are.

Seven claims are withheld that should not be, identically in every pass — six of
them 「コンビニエンスストアは全国に約5万6000店」 against pages giving 55,979 and
55,620. 「約」 is a stated tolerance and the comparator ignores it. That number
is published next to the headline on purpose: a checker that confirms nothing
would score zero false confirmations, so the two only mean anything together.

## 2026-08-05 — D-030: A public recording shows invented pages, and says so
The contest organisers put the question to the Parallel team, whose guidance is
to use fictional sites in the public demo video and submission screenshots
rather than the real names, page titles and URLs a live search returns. That is
the right instinct independent of the rules: none of those organisations agreed
to appear in our film.

The obvious implementation — record with the mock — would have been dishonest in
a subtler way. The old mock returned one fixture page per keyword and a filler
result for everything else, so every claim found something. A viewer would have
learned that this product confirms whatever you say to it.

So `CURRENTCUT_SEARCH_CORPUS` serves a written corpus into the retrieval step
and changes nothing else. The pages still pass the egress gate, are still read
by the comparator, are still ranked by the attribution rule. Nothing in the
corpus declares its own standing: `.gov.example` is a public authority because
of its suffix, exactly as `.gov` and `.go.jp` are, and everything else comes
back `web` and cannot be credited. `.example` is reserved by RFC 2606 and can
never resolve, so admitting that suffix cannot admit a real site. A recording
therefore demonstrates the rule rather than a stand-in for it, and a test fails
if an entry ever tries to name its own type.

The corpus is shaped to keep the awkward outcomes. "More than 150,000
convenience stores" is backed only by a trade body, so it stays airable with no
attribution — a corpus that invented an authority for every claim would make the
film a lie about the product. A subject the corpus does not cover returns
nothing, as a live search that finds nothing does.

`provider` reads `demo-corpus` in the trace, on every Egress Log row, and in the
CLI banner before the run starts. Not `parallel`, not `mock`. The one thing a
recording must never do is pass for a live search, and that is one string in
three places rather than a promise in a README.

Measured on the English shoot: 12 claims, 4 confirmed, three captions carrying a
source, three off-record moments held, and every retrieved domain under
`.example`.

The hosted demo still calls Parallel for real, because the track asks us to
demonstrate that it does. Whether the organisers want the hosted app on the
corpus too is with them; the switch already exists either way.

## 2026-08-05 — D-031: What gets verified is not what gets read
A claim is prefixed with its subject when the sentence alone does not name one,
because a claim with no subject verifies against any page carrying the same
number. That guard is right and stays. What was wrong is that the prefixed
string then went on screen:

    small businesses' employment share of the private workforce in this
    country: Small businesses employ almost half of the private workforce in
    this country.

The guard is meant to skip claims that already name their subject, and it
decides by looking for the subject inside the sentence. That works when the
model returns a bare entity and fails when it returns a description of the
topic — "small businesses' employment share of the private workforce" is not a
substring of a sentence that says "Small businesses employ almost half". The
same test had already been widened once, for capitalisation. Widening it again
would only postpone the next paraphrase.

So the two strings are kept apart instead of being reconciled. `claim_text` is
what the comparator and the search query see; `display_text` is the sentence as
extracted, read through `Claim.on_screen`, which falls back to `claim_text` for
anything recorded before the split. Captions, telops, the caption sheet and the
progress log all read `on_screen`; evidence, attribution and de-duplication all
keep reading `claim_text`.

This is the older lesson in a new place. The prefix exists to make a machine
unambiguous, and a viewer is not a machine.

Measured on the English shoot, demo corpus: 2 of 12 claims carried a prefix,
both now read as spoken, and the sourced captions are unchanged otherwise.

## 2026-08-05 — D-031: The order sheet is written in the language of the shoot
The caption order sheet is the one deliverable a person works through line by
line, and it shipped only in Japanese. The column that carries the whole point
of the product was headed 裏付け, and the demo video points a judge at that
column while the narration says "was this checked, and against what". An
English-speaking judge would have been looking at a word they cannot read, in
the single shot carrying the "real understanding of a real problem" criterion.

The vocabulary moved into `app/lang.py` with everything else that changes by
language, and the endpoints decide from the segments — the same way the script
and the captions already decide it — so one project cannot produce a Japanese
sheet for an English cut.

The Japanese wording is unchanged and stays exact. It is the trade's own
vocabulary, not a translation back from the English: a Japanese edit house
wants 名前スーパー and 出典表記, and inventing tidier equivalents would make the
sheet worse for the people it was designed for.

Two things deliberately did not change:

- **Pouring into a broadcaster's uploaded form follows the form, not the
  shoot.** A Japanese template expects 名前スーパー in its type column whatever
  language the interview was in. That path keeps the Japanese table, now
  sharing one definition with the sheet CurrentCut writes itself.
- **The per-row notes are not translated.** Each was written when the telop was
  drafted, in the language of that shoot, and it is that shoot's content.
  Asking for an English sheet from a Japanese shoot gives English headings over
  Japanese notes, which is the honest outcome: the parameter says which shoot
  this is, not which language to translate into. A test says so in as many
  words, because the obvious reading of a failing assertion here is "leak".

## 2026-08-05 — D-032: The sample on the landing page is a corpus run
The film shows the landing page — the shoot ends at seven, the cursor goes to
the button — and the preview beside the hero is on screen while it does. That
preview was a live Parallel run, so the caption order sheet's SOURCE column
carried 106 real third-party hosts, and the frame burned into the hero read
`Source: www.dol.gov`. None of those organisations agreed to appear in our film.

So the published sample is now a `CURRENTCUT_SEARCH_CORPUS=en` run, and
`scripts/publish_sample.py` refuses to publish one that is not: it scans every
exported payload for a host that is not a reserved `.example` name and stops.
The guard is worth more than the discipline it replaces, because this file is
easy to regenerate and easy to forget.

Two things the work turned up that were not on the list:

- **The invented hosts were too long.** `www.labourstandards.gov.example` is
  thirty-one characters against `www.dol.gov`'s eleven, and the burned-in
  caption is capped at the width of the frame — so fitting the source in ate
  the claim, and the hero read "The federal minimum wage⋯". Measured, not
  guessed: the previous hero rendered to within 45px of both edges, which is
  what says the cap is calibrated and must not be raised for a demo's
  convenience. The corpus hosts were shortened instead. Real authorities have
  short names; the invented ones now do too.
- **Trimming stopped mid-word.** "the federal minimum wage hasn't change…"
  reads as a rendering fault rather than as an ellipsis. `_fit_caption` now
  clips at a word boundary where the script has them, and falls back to a
  straight cut for Japanese, which has none. It refuses the boundary when
  honouring it would throw away more than 40% of the line, so one long token
  cannot collapse the caption.

The preview note no longer says "one live run". It says the sources are
invented and everything else is the code that runs live, because the sample is
one click from a judge and the claim has to survive them reading it.

## 2026-08-05 — D-032: The sample a visitor clicks is a corpus run
The saved sample behind "View a sample" was a live Parallel run, so its script
table carried the full evidence trail — 106 distinct real third-party hosts,
trade press and state labour departments among them. That is the correct thing
for the product to show a director: every page it consulted, not only the one
it credited. It is the wrong thing to publish in a film, and the landing page
is on screen while the button is pressed.

So the sample is now taken from a corpus run. `scripts/publish_sample.py`
exports it and refuses outright if the run carries a real host, because the
guard is the point: this file gets filmed, and noticing afterwards is too late.

Two things the guard taught while being written:

- Its first version reported `advocacy.smallbusiness.gov.example` as a real
  `.gov`, because a word boundary sits between "gov" and the ".example" that
  makes it fictional. Anchoring on the public suffix is not enough; the host
  has to be matched to its last label.
- The numbers printed beside the hero are part of the sample, not decoration.
  The script prints what the page must say, so the two cannot drift — they had
  already drifted once.

Also fixed while looking at the frame this produces: a trimmed caption stopped
on the article — "the federal minimum wage is $7.25 an…" — leaving the reader
waiting for a noun. Word-boundary trimming was already there; what was missing
was dropping a word that only exists to introduce the next one. It now reads
"…is $7.25…", which stops on the figure the line was written for.

## 2026-08-08 — D-033: A failing conductor does not cost the director the night

Filming the demo turned up a failure nobody had seen because it is
intermittent: Gemini called a tool as `currentcut.analyze_footage` — the
Runner's `app_name` glued onto the tool name — and ADK refused to resolve the
qualified name. Every step stayed pending. The run ended before a single clip
was read.

That is the orchestrator failing, not the work. It would have happened to a
judge pressing the button, and there is nothing to see when it does.

Two layers, in that order:

- The agent is now told plainly which name shape ADK rejects, with the exact
  wrong string in the instruction. This is the fix.
- If the run fails anyway, the same seven steps run in the same fixed order
  from code. This is the net.

The fallback is honest because the product's claim survives it: the order was
never the agent's to choose. What changes is who calls the steps, and the trace
says so — `adk_orchestrator` stays in the record as failed, with its error, and
`fixed_order_fallback` appears beside it as the run that finished the work.
Falling back quietly would have turned a real failure into a clean-looking run,
which is the opposite of what this project is for.

## 2026-08-08 — D-034: The order sheet has to survive being printed

The caption order sheet is the deliverable a director emails to the edit house,
and it had never been looked at on paper. It printed across six pages, split by
column band: `Checked against` came out on a sheet of its own, a column of
verdicts with nothing to say which caption each one belonged to. The one column
CurrentCut adds was the one the printer threw away.

Fit-to-width, landscape, rows running on as far as they need. Six pages to two.

Two more defects were visible once the page could be read at all:

- Row height was computed from the caption's line count alone, so the rows with
  long notes were crushed and overlapped their neighbours. Those are exactly
  the rows that carry a reason to check something — the rows this sheet exists
  for. Height now follows the tallest wrapped cell across every wrapping
  column, and `Checked against` wraps too instead of spilling sideways.
- The programme name printed as "Programme: The corr", running into the air
  date. The header cells are merged now.
