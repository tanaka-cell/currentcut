"""Score the claim checker against hand-written labels.

The number this exists to produce is the false-confirmation rate: how often the
system tells a director a figure is confirmed when the evidence does not
establish it. That is the failure that reaches air, so it is the one worth
counting. Missed confirmations and wrong attributions are counted alongside it,
because a checker that confirms nothing would score perfectly on the headline.

Every case is a real claim from a real run, with the pages that were actually
retrieved for it. Only the judging is redone, so a run costs a few text calls
rather than a video pass and a search budget.

    python scripts/run_eval.py                 # judge with Gemini, score, write results
    python scripts/run_eval.py --offline       # score the recorded verdicts instead
    python scripts/run_eval.py --limit 5       # a quick pass over the first few

Needs GEMINI_API_KEY unless --offline. Results land in eval/results.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "agent"))

from app import lang  # noqa: E402
from app.agents import evidence, research  # noqa: E402
from app.clients.parallel_client import ParallelClient  # noqa: E402
from app.models.schemas import Claim, EvidenceStatus, ResearchResult  # noqa: E402

CASES = REPO / "eval" / "cases.jsonl"
LABELS = REPO / "eval" / "labels.jsonl"
RESULTS = REPO / "eval" / "results.md"
# Verdicts from the last live pass, so a change to the decision rules can be
# scored against the same judgements instead of paying for them again.
CACHE = REPO / "eval" / "judged.jsonl"

CONFIRMED = (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
             EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)
# Sources a mock run invented. They are not retrieved evidence and scoring
# against them would be scoring the fixture.
MOCK_DOMAINS = ("demo.currentcut.example",)


def _is_real(case: dict) -> bool:
    return all(s["domain"] and not any(m in s["domain"] for m in MOCK_DOMAINS)
               for s in case["sources"])


def load() -> tuple[list[dict], dict[str, dict]]:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = {}
    for line in LABELS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "case_id" in row:
            labels[row["case_id"]] = row
    return [c for c in cases if _is_real(c)], labels


def rebuild(case: dict) -> tuple[Claim, list[ResearchResult]]:
    claim = Claim(id=case["case_id"], segment_id="seg_eval",
                  claim_text=case["claim_text"],
                  claim_type=case.get("claim_type") or "other",
                  verifiability=case.get("verifiability") or "public_record")
    results = [ResearchResult(
        claim_id=claim.id, source_url=s["url"], source_title=s["title"],
        source_domain=s["domain"],
        # Classified from the URL now, not read back from the run. The stored
        # value is whatever the classifier said on the day, and older runs
        # predate the rules that stopped crediting press-release distributors
        # and company explainers. Replaying it would score a retired classifier.
        source_type=ParallelClient._source_type(s["url"]),
        excerpt=s["excerpt"],
    ) for s in case["sources"]]
    return claim, results


JUDGED_FIELDS = ("supports_claim", "entity_match", "attribute_match", "source_value",
                 "value_as_of_year", "contradicts_claim", "claim_names_its_own_date",
                 "dated_qualifier")


def _replay(claim: Claim, results: list[ResearchResult], verdicts: list[dict]) -> None:
    """Apply verdicts made earlier, then today's decision code over them."""
    for r, v in zip(results, verdicts):
        for field in JUDGED_FIELDS:
            if field in v:
                setattr(r, field, v[field])
    supporting = [r for r in results if r.supports_claim]
    current = [r for r in supporting if not research._is_stale(r)]
    primary = [r for r in current if r.source_type in ("official", "government")]
    claim.verification_status = (
        EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED if len(current) >= 2
        else EvidenceStatus.PRIMARY_SOURCE_CONFIRMED if primary
        else EvidenceStatus.CONFLICTING if research._conflicting(claim, results)
        else EvidenceStatus.UNVERIFIED)


def judge(case: dict, offline: bool, cache: dict | None = None
          ) -> tuple[Claim, list[ResearchResult]]:
    claim, results = rebuild(case)
    if cache is not None and case["case_id"] in cache:
        _replay(claim, results, cache[case["case_id"]])
        return claim, results
    if offline:
        # Replay the verdicts as recorded, then run today's decision code over
        # them. This measures the rules without measuring the model.
        _replay(claim, results, case["sources"])
        return claim, results
    judgments = evidence.judge_all(claim, results)
    research.apply_judgments(claim, results, judgments, lang.detect(claim.claim_text))
    return claim, results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--use-cache", action="store_true",
                    help="re-score the last live pass without calling the model")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    cases, labels = load()
    if args.limit:
        cases = cases[:args.limit]
    cache = None
    if args.use_cache:
        if not CACHE.exists():
            print(f"no cached verdicts at {CACHE.relative_to(REPO)} — run once without --use-cache")
            return 1
        cache = {row["case_id"]: row["verdicts"]
                 for row in map(json.loads, CACHE.read_text(encoding="utf-8").splitlines())}
    print(f"{len(cases)} labelled cases with real retrieved evidence\n")

    rows, tally, judged = [], Counter(), []
    for i, case in enumerate(cases, 1):
        label = labels.get(case["case_id"])
        if label is None:
            print(f"  [{i}/{len(cases)}] no label for {case['case_id']} — skipped")
            continue
        claim, results = judge(case, args.offline, cache)
        if not args.offline and cache is None:
            judged.append({"case_id": case["case_id"], "verdicts": [
                {f: getattr(r, f) for f in JUDGED_FIELDS} for r in results]})
        confirmed = claim.verification_status in CONFIRMED
        credited = evidence.citable_source(results, claim.claim_text)
        credited = credited.source_domain if credited else None

        if confirmed and not label["supported"]:
            verdict = "FALSE CONFIRMATION"
        elif not confirmed and label["supported"]:
            verdict = "missed"
        elif confirmed and credited != label["citable"]:
            verdict = "wrong source credited"
        else:
            verdict = "ok"
        tally[verdict] += 1
        rows.append({"case": case["case_id"], "group": label["group"],
                     "claim": case["claim_text"], "verdict": verdict,
                     "status": claim.verification_status.value,
                     "credited": credited, "should_credit": label["citable"],
                     "should_be_supported": label["supported"]})
        print(f"  [{i}/{len(cases)}] {verdict:22} {claim.verification_status.value:26} "
              f"{case['claim_text'][:44]}")

    total = sum(tally.values())
    false_conf = tally["FALSE CONFIRMATION"]
    print(f"\n{'='*64}")
    print(f"  false confirmations : {false_conf}/{total}")
    print(f"  missed              : {tally['missed']}/{total}")
    print(f"  wrong source        : {tally['wrong source credited']}/{total}")
    print(f"  correct             : {tally['ok']}/{total}")

    if judged:
        with CACHE.open("w", encoding="utf-8", newline="\n") as fh:
            for row in judged:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"cached {len(judged)} judgements in {CACHE.relative_to(REPO)}")

    mode = ("recorded verdicts, today's rules" if args.offline
            else "verdicts from the last live pass, today's rules" if args.use_cache
            else "judged fresh by Gemini")
    lines = [f"# Claim-checker evaluation\n",
             f"{total} labelled claims, {mode}.\n",
             f"| outcome | count |", "|---|---:|",
             f"| false confirmations | **{false_conf}** |",
             f"| missed confirmations | {tally['missed']} |",
             f"| wrong source credited | {tally['wrong source credited']} |",
             f"| correct | {tally['ok']} |", "",
             "A false confirmation is the one that reaches air: the system called a",
             "figure confirmed when the retrieved pages do not establish it.\n",
             "| case | group | verdict | status reached | credited | should credit |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['claim'][:48]} | {r['group']} | {r['verdict']} | "
                     f"{r['status']} | {r['credited'] or '—'} | {r['should_credit'] or '—'} |")
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"\nwrote {RESULTS.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
