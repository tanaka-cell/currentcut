# Does the claim checker actually check?

A director can only rest if the thing that ran overnight was right. The number
that matters is not how many claims were confirmed — it is how often a figure
was called confirmed when the evidence does not establish it. That is the
error that reaches air, so it is the one counted here.

```bash
python scripts/run_eval.py             # judge the evidence again, score it
python scripts/run_eval.py --offline   # score the recorded verdicts instead
```

**Measured 2026-08-05: 0–1 false confirmations in 34 claims, over three
consecutive passes** — [measured.md](measured.md) says what the numbers are made
of. [results.md](results.md) is the per-case detail of whichever pass ran last.

## Where the cases come from

`cases.jsonl` is not written by hand. It is every claim any recorded run has
produced, together with the pages the Parallel Search API actually returned for
it and the excerpt each verdict was reached from — collected by
`scripts/build_eval_set.py`. Real footage, real queries, real pages.

Two exclusions, both deliberate:

- **Mock runs.** A run with no key invents its evidence on a fixture domain.
  Scoring against those would be scoring the fixture, so any case whose sources
  include one is dropped. That removes 14 of 48 — including four the pipeline
  had marked confirmed.
- **Claims nothing was retrieved for.** There is no judgment to score.

That leaves **34 distinct claims and 200-odd retrieved pages**. It is smaller
than we would like, and the reason is honest: the demo ships two shoots, and
re-running the same footage produces the same claims. The set grows by running
the pipeline over new material, not by writing more labels.

## What a label says

`labels.jsonl` gives each case two judgements, made by reading the claim against
the excerpts that were actually retrieved for it:

- `supported` — does *this* evidence establish *this* claim?
- `citable` — which domain, if any, may be printed on screen as the source?

`citable: null` is a real answer and several cases have it. Japan's reduced
consumption-tax rate is true, and every page retrieved for it is a tax
publisher, an accountancy blog or a credit-card site. The rate is airable; the
attribution is not. A checker that credits one of those is wrong even though the
figure is right, which is why attribution is scored separately from support.

The labels take the claims at face value from the footage. "There is no AI smart
lunchbox" is not a judgement about the sources — it is why no source can support
the claim, and why a page about a bath mat matching on the digits is not
evidence.

## What the two modes measure

The system reaches a verdict in two layers: Gemini judges each retrieved page
against the claim, then deterministic code turns those verdicts into a status
and picks at most one source to credit.

- **Default** re-judges every page with the current comparator and then runs the
  current decision code. This is the end-to-end number. It needs `GEMINI_API_KEY`.
- **`--offline`** replays the verdicts exactly as they were recorded and runs
  only today's decision code over them. No key, same numbers on any machine —
  but the recorded verdicts include ones made by comparators that have since
  been replaced, so this mode measures the rules, not the model.

The gap between the two is the point. Three cases in this set were confirmed by
the numeric-overlap comparator that shipped first: a lunchbox that does not
exist "priced at 1,980 yen" (a Fire TV Stick sale), the same lunchbox sold in
"80 stores" (a sushi chain's store table), and its nutrition tracking (a bath
mat). They are kept in the set on purpose. `--offline` still shows them
confirmed, because no decision rule can rescue a wrong verdict about what a page
is about. The default mode is where the current comparator has to reject them.

## The number moves between runs

The comparator is a model, so the same evidence does not always get the same
verdict. Measuring once and printing the good number would be the same mistake
this project keeps finding elsewhere, so the headline is reported as a range
over consecutive passes, not as a single figure.

Two things move:

- **Which pages count as supporting.** One pass accepted `www.dol.gov`'s
  minimum-wage history table for "unchanged since 2009"; the next did not, and
  the credit fell to `webapps.dol.gov` — the same department, an application
  host. The ranking rule behaved correctly both times. What changed was the
  evidence it was ranking.
- **Whether a generic page is "the same subject".** The one false confirmation
  seen so far is a claim about a specific product matched to a research paper
  and a startup-idea page that are about smart lunchboxes in general. Digits are
  no longer enough to confirm a claim, but a category is still sometimes read as
  an entity.

## Scoring

| outcome | meaning |
|---|---|
| **false confirmation** | confirmed, but the evidence does not establish it |
| missed | the evidence establishes it, and the system did not confirm |
| wrong source credited | confirmed correctly, credited to the wrong domain |
| correct | everything above avoided |

Missed confirmations are counted because the headline is trivially gamed: a
checker that confirms nothing never confirms anything falsely. The two numbers
have to be read together.

The harness calls `research.apply_judgments` and `evidence.citable_source` — the
same functions the pipeline calls. An evaluation that reimplements the rule
measures the reimplementation.
