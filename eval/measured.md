# Measured: 34 labelled claims, three consecutive passes

2026-08-05. `python scripts/run_eval.py`, real Gemini comparator, no cache,
against the labels in `labels.jsonl`. Three passes because the comparator is a
model and one pass is an anecdote.

| pass | false confirmations | missed | wrong source credited | correct |
|---|---:|---:|---:|---:|
| 1 | 1 | 7 | 1 | 25 |
| 2 | **0** | 7 | 0 | 27 |
| 3 | 1 | 7 | 1 | 25 |

**False confirmations: 0–1 of 34.** Reporting the best pass alone would be the
error this project keeps catching elsewhere, so the range stands.

## What the numbers are made of

**The one false confirmation is always the same claim.** 「AIスマート弁当箱は
中身の栄養バランスを自動で記録してくれる」 — a capability of a product that does
not exist. Two passes accepted a PubMed paper titled "When the Lunchbox Meets
the Algorithm" and a startup-idea generator's "smart lunchbox with integrated
meal tracking" as being about the same thing. The comparator is told not to
treat a product category as an entity, and it holds that line against a rival
*product*; a paper or a concept page about the category in general still gets
through. That is the open defect this set exists to keep visible.

**The three historical false confirmations are gone, in every pass.** The
comparator that shipped first confirmed a fictional lunchbox "priced at ¥1,980"
from a Fire TV Stick sale, "sold in 80 stores" from a sushi chain's store table,
and its nutrition tracking from a smart bath mat. All three are still in the
set, and all three are now rejected 3/3.

**The seven missed confirmations are identical in all three passes** — not
variance, a systematic gap. Six are the same fact in different words: 「コンビニ
エンスストアは全国に約5万6000店」.

An earlier version of this file blamed the approximation rule. That was wrong,
and reading the recorded verdicts back (`judged.jsonl`) is what showed it: the
comparator accepts 「5万5620店」 as a match for 「約5万6000」 — `supports_claim:
true` — in three of the six. The rounding rule works. What actually loses these
six is duller and harder to fix:

- **The retrieved excerpt usually contains no figure at all.** Across the six,
  between five and nine of the ten sources per claim came back with
  `source_value` empty — navigation, menus, article furniture. The comparator
  cannot confirm a number it was never shown.
- **The one figure that does support the claim is from 2019.** 「5万5620店」 is a
  2019 count, and a seven-year-old measurement does not establish a present-tense
  claim about a number that moves, so `STALE_EVIDENCE_YEARS` discards it. That is
  the rule working, not failing. In a seventh case the only support is a single
  non-primary source, which by the same stated rule is not enough.

So most of this gap is not a comparator that is too strict. It is retrieval that
never reaches a current, figure-bearing page for a Japanese industry statistic,
plus two rules doing what they were written to do. The honest next step is
better retrieval — name the publishing body, pull a longer excerpt — not a
looser tolerance. Loosening the tolerance would buy a nicer number here by
accepting evidence that does not establish the claim, which is the trade this
file exists to refuse.

One real defect did surface while reading the verdicts back, and it is fixed. A
source too old to confirm a claim could still **contradict** it, so a 2023 count
of 57,594 was putting 「この数字のまま出さない」 on a line that is true. Staleness
now applies to contradictions as well as to support. On this recorded set the
change moves no score — 2023 falls inside the three-year window, so nothing here
is suppressed by it — but it closes a route by which a true line could be
condemned by evidence too old to speak to it.

**Wrong source credited (0–1) is not the ranking rule.** In passes 1 and 3 the
credit for the federal minimum wage went to `webapps.dol.gov`, an application
host, rather than `www.dol.gov`. In those passes the comparator did not accept
`www.dol.gov`'s own history table as supporting, so the ranking never saw it.
Given the evidence it did have, it credited the right department.

## Reading this honestly

The headline is the number that reaches air, and it is the number to improve.
But a checker that confirms nothing scores a perfect zero, so it has to be read
against the misses: 34 claims, 0–1 wrongly confirmed, 7 wrongly withheld. This
system currently errs toward withholding, which is the right direction for
broadcast and still a cost — every miss is a figure a director has to check by
hand.

The set is 34 claims, not 50. The demo ships two shoots and re-running them
produces the same claims; it grows by putting new footage through the pipeline,
not by writing more labels. `eval/README.md` says how.
