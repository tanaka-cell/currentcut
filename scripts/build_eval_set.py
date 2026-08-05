"""Collect the claims of every recorded run into one worksheet for labelling.

The eval set is drawn from real runs rather than written by hand: every claim
here was spoken in the demo footage, searched for real, and judged by the real
comparator. Because each run stores the per-source verdict alongside the excerpt
it was judged from, the whole decision can be replayed and scored offline — no
key, no network, and the same numbers on anyone's machine.

    python scripts/build_eval_set.py            # refresh the worksheet
    python scripts/build_eval_set.py --stats    # just say what is in it

Labels are added by hand in eval/labels.jsonl, keyed by `case_id`, and are never
overwritten by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
OUT = REPO / "eval" / "cases.jsonl"

CONFIRMED = ("PRIMARY_SOURCE_CONFIRMED", "MULTIPLE_SOURCES_CONFIRMED")
# Enough of the page to judge the claim against, centred on the figures rather
# than the masthead. Whole excerpts run to thousands of characters of nav bar.
WINDOW = 320


def _case_id(claim_text: str) -> str:
    return "case_" + hashlib.sha1(claim_text.strip().encode()).hexdigest()[:10]


def _digits(text: str) -> list[str]:
    return re.findall(r"\d[\d,.]*", text)


def _relevant(excerpt: str, claim_text: str) -> str:
    """The part of the page a person would look at to check this claim."""
    excerpt = re.sub(r"\s+", " ", excerpt or "").strip()
    if len(excerpt) <= WINDOW:
        return excerpt
    wanted = _digits(claim_text)
    best, best_score = 0, -1
    for m in re.finditer(r"\d[\d,.]*", excerpt):
        window = excerpt[max(0, m.start() - WINDOW // 2): m.start() + WINDOW // 2]
        score = sum(1 for d in wanted if d in window)
        if score > best_score:
            best, best_score = max(0, m.start() - WINDOW // 2), score
    if best_score <= 0:
        return excerpt[:WINDOW] + " …"
    return ("… " if best else "") + excerpt[best:best + WINDOW] + " …"


def collect() -> list[dict]:
    by_case: dict[str, dict] = {}
    for project in sorted(DATA.glob("prj_*")):
        claims_file = project / "claims.json"
        research_file = project / "research_results.json"
        if not claims_file.exists():
            continue
        try:
            claims = json.loads(claims_file.read_text(encoding="utf-8"))
            research = (json.loads(research_file.read_text(encoding="utf-8"))
                        if research_file.exists() else [])
        except (json.JSONDecodeError, OSError):
            continue

        by_claim: dict[str, list[dict]] = {}
        for r in research:
            by_claim.setdefault(r["claim_id"], []).append(r)

        for claim in claims:
            sources = by_claim.get(claim["id"], [])
            if not sources:
                continue  # nothing was retrieved; there is no judgment to score
            case_id = _case_id(claim["claim_text"])
            case = {
                "case_id": case_id,
                "claim_text": claim["claim_text"].strip(),
                "claim_type": claim.get("claim_type", ""),
                "verifiability": claim.get("verifiability", ""),
                "system_status": claim.get("verification_status", ""),
                "run": project.name,
                "sources": [{
                    "domain": s.get("source_domain", ""),
                    "url": s.get("source_url", ""),
                    "title": (s.get("source_title") or "")[:140],
                    "source_type": s.get("source_type", "web"),
                    "supports_claim": s.get("supports_claim"),
                    "entity_match": s.get("entity_match", False),
                    "attribute_match": s.get("attribute_match", False),
                    "source_value": s.get("source_value", ""),
                    "value_as_of_year": s.get("value_as_of_year", 0),
                    "contradicts_claim": s.get("contradicts_claim", False),
                    "excerpt": _relevant(s.get("excerpt", ""), claim["claim_text"]),
                } for s in sources],
            }
            # The same line is spoken in every re-run of a shoot. Keep the
            # instance that retrieved the most evidence: it is the hardest one
            # to get right, and the one where a wrong confirmation can hide.
            kept = by_case.get(case_id)
            if kept is None or len(case["sources"]) > len(kept["sources"]):
                by_case[case_id] = case
    return sorted(by_case.values(), key=lambda c: (c["system_status"], c["case_id"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    cases = collect()
    status = Counter(c["system_status"] for c in cases)
    sources = sum(len(c["sources"]) for c in cases)
    supported = sum(1 for c in cases for s in c["sources"] if s["supports_claim"])

    print(f"{len(cases)} distinct claims with retrieved evidence")
    print(f"{sources} retrieved sources, {supported} judged as supporting")
    for name, count in status.most_common():
        print(f"  {count:3}  {name}")

    if args.stats:
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
    print(f"\nwrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
