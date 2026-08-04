"""Re-apply the attribution rule to a recorded run and rebuild the landing sample.

The sample served on the landing page came from a real run. When the rule for
*which* authority may be credited changed, that run's evidence did not — only
the name the rule picks out of it. So the artefacts are rebuilt from the stored
evidence rather than by shooting again: the same claims, the same sources, the
same timings, re-decided by the corrected rule.

Only the fields the rule actually feeds are recomputed:
  script line  caption_text  (burned into the cut)
  telop        source_note, caution
Everything the model produced — the condensed telop wording, the segmentation,
the timings — is left exactly as it was recorded.

    python scripts/refresh_sample_credits.py <project_id> [--write]

Without --write it reports what would change and touches nothing.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1] / "services" / "agent"
sys.path.insert(0, str(SERVICE))

from app import config, lang  # noqa: E402
from app.agents import evidence  # noqa: E402
from app.agents.rough_cut import render_rough_cut  # noqa: E402
from app.models.schemas import (  # noqa: E402
    Asset, Claim, EvidenceStatus, ResearchResult, ScriptLine, TelopEntry,
)
from app.storage import store  # noqa: E402

AIRABLE = (EvidenceStatus.PRIMARY_SOURCE_CONFIRMED,
           EvidenceStatus.MULTIPLE_SOURCES_CONFIRMED)
SAMPLE_DIR = SERVICE / "app" / "static" / "sample"


def recompute(project_id: str) -> tuple[list, list, list[str]]:
    claims = {c.id: c for c in store.list(project_id, "claims", Claim)}
    research: dict[str, list[ResearchResult]] = {}
    for r in store.list(project_id, "research_results", ResearchResult):
        research.setdefault(r.claim_id, []).append(r)

    lines = store.list(project_id, "script_lines", ScriptLine)
    telops = store.list(project_id, "telops", TelopEntry)
    changes: list[str] = []

    credited: dict[str, str | None] = {}
    for cid, claim in claims.items():
        src = evidence.citable_source(research.get(cid, []), claim.claim_text)
        credited[cid] = src.source_domain if src else None

    for line in lines:
        for cid in line.claim_ids:
            claim = claims.get(cid)
            if claim is None or claim.verification_status not in AIRABLE:
                continue
            domain = credited[cid]
            language = lang.detect(claim.claim_text)
            want = (lang.cited(language, claim.claim_text, domain) if domain
                    else claim.claim_text)
            if line.caption_text != want:
                changes.append(f"caption  {line.caption_text!r}\n      -> {want!r}")
                line.caption_text = want

    for telop in telops:
        if telop.telop_type != "data":
            continue
        # The sheet stores no claim id, so match the line it belongs to. A line
        # carrying one claim is the only case the data telop is built for.
        line = next((l for l in lines if l.id == telop.script_line_id), None)
        if line is None:
            continue
        airable = [c for c in (claims.get(i) for i in line.claim_ids)
                   if c is not None and c.verification_status in AIRABLE]
        if len(airable) != 1:
            continue
        claim = airable[0]
        language = lang.detect(claim.claim_text)
        domain = credited[claim.id]
        if domain:
            note = lang.CREDIT_FORMAT[language].replace("◯◯", domain)
            caution = claim.volatility_note
        else:
            backers = evidence.supporting_domains(research.get(claim.id, []))
            note = ""
            caution = lang.no_primary_source(language, backers)
            if claim.volatility_note:
                caution = f"{caution}／{claim.volatility_note}"
        if telop.source_note != note or telop.caution != caution:
            changes.append(f"telop    {telop.source_note!r} / {telop.caution!r}\n"
                           f"      -> {note!r} / {caution!r}")
            telop.source_note, telop.caution = note, caution

    return lines, telops, changes


def export_sample(project_id: str, cut_path: str) -> None:
    """Mirror the endpoints the landing page reads, into the static sample."""
    from app.main import app  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    client = TestClient(app)
    for name, url in (
        ("report", f"/projects/{project_id}/report"),
        ("script", f"/projects/{project_id}/script"),
        ("egress", f"/projects/{project_id}/egress"),
        ("trace", f"/projects/{project_id}/trace"),
        ("telops", f"/projects/{project_id}/telops"),
    ):
        res = client.get(url)
        res.raise_for_status()
        # Compact, matching what the sample already shipped: these are served to
        # every visitor, and a whitespace-only rewrite would bury the one line
        # that actually changed under a few thousand that did not.
        (SAMPLE_DIR / f"{name}.json").write_text(
            json.dumps(res.json(), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8", newline="\n")
        print(f"  wrote {name}.json")

    for filename, url in (("telops.csv", f"/projects/{project_id}/telops.csv"),
                          ("telop-manuscript.xlsx",
                           f"/projects/{project_id}/telop-manuscript.xlsx")):
        res = client.get(url)
        res.raise_for_status()
        (SAMPLE_DIR / filename).write_bytes(res.content)
        print(f"  wrote {filename}")

    shutil.copyfile(cut_path, SAMPLE_DIR / "rough_cut.mp4")
    print("  wrote rough_cut.mp4")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--hero-at", type=float, default=None,
                    help="seconds; also refresh static/hero_frame.jpg from the cut")
    args = ap.parse_args()

    lines, telops, changes = recompute(args.project_id)
    print(f"{len(changes)} field(s) would change\n")
    for c in changes:
        print("  " + c)
    if not args.write:
        print("\n(dry run - pass --write to apply)")
        return 0

    for line in lines:
        store.put(args.project_id, "script_lines", line)
    for telop in telops:
        store.put(args.project_id, "telops", telop)
    print("\nstored.")

    assets = store.list(args.project_id, "assets", Asset)
    cut = render_rough_cut(args.project_id, lines, assets)
    print(f"re-rendered cut: {cut['mp4']} "
          f"({cut['duration_seconds']}s, {cut['lines_used']} lines, "
          f"{cut['lines_excluded_confidential']} held back)")

    export_sample(args.project_id, cut["mp4"])

    if args.hero_at is not None:
        hero = SERVICE / "app" / "static" / "hero_frame.jpg"
        subprocess.run(["ffmpeg", "-y", "-ss", str(args.hero_at), "-i", cut["mp4"],
                        "-frames:v", "1", "-q:v", "2", str(hero)],
                       check=True, capture_output=True)
        print(f"  wrote hero_frame.jpg at {args.hero_at}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
