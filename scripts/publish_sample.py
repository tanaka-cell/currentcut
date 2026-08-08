"""Publish one run as the landing page's "View a sample".

The sample is a real run, saved. It is also the first thing a visitor clicks,
so it has to hold two properties at once: the numbers printed beside it on the
page must be that run's own numbers, and — since the film shows this page —
every source, page title and URL in it must be invented.

The queries are deliberately left alone. A query that goes looking for who
publishes a figure names that body, and that is the search the product really
makes. The organisers' guidance is about names, titles and URLs *returned by*
live Search; what we ask it is ours. The guard below checks hosts for that
reason, and the page says so rather than claiming more than the corpus does.

    python scripts/publish_sample.py <project_id> --hero-at 29.2 --write

Without --write it reports what the page would have to say and touches nothing.
Refuses to publish a run that carries real third-party hosts unless you pass
--allow-real-domains, because the whole reason the demo corpus exists is that
this file gets filmed.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVICE = REPO / "services" / "agent"
sys.path.insert(0, str(SERVICE))

STATIC = SERVICE / "app" / "static"
SAMPLE = STATIC / "sample"

# Anything that is not a reserved, unresolvable name is somebody's real site.
# The host is matched whole, to the last label: anchoring on the public suffix
# instead reported advocacy.smallbusiness.gov.example as a real .gov, because a
# word boundary sits between "gov" and the ".example" that makes it fictional.
_HOST = re.compile(r"\b(?:[a-z0-9][a-z0-9-]*\.)+[a-z]{2,}\b")
_REAL_TLDS = {"gov", "com", "org", "net", "jp", "co", "edu", "int", "mil",
              "us", "uk", "eu", "ai", "io", "info", "biz"}


def real_hosts(text: str) -> set[str]:
    hosts = set()
    for host in _HOST.findall(text.lower()):
        if host.endswith(".example"):
            continue
        if host.rsplit(".", 1)[-1] in _REAL_TLDS:
            hosts.add(host)
    return hosts


def export(project_id: str, write: bool) -> dict:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    payloads: dict[str, str] = {}
    for name, url in (("report", f"/projects/{project_id}/report"),
                      ("script", f"/projects/{project_id}/script"),
                      ("egress", f"/projects/{project_id}/egress"),
                      ("trace", f"/projects/{project_id}/trace"),
                      ("telops", f"/projects/{project_id}/telops")):
        res = client.get(url)
        res.raise_for_status()
        # Compact, as the shipped sample already was: these are served to every
        # visitor, and a whitespace-only rewrite buries the real change.
        payloads[name] = json.dumps(res.json(), ensure_ascii=False, separators=(",", ":"))

    binaries: dict[str, bytes] = {}
    for filename, url in (("telops.csv", f"/projects/{project_id}/telops.csv"),
                          ("telop-manuscript.xlsx",
                           f"/projects/{project_id}/telop-manuscript.xlsx")):
        res = client.get(url)
        res.raise_for_status()
        binaries[filename] = res.content

    report = json.loads(payloads["report"])
    found = set()
    for name, body in payloads.items():
        found |= real_hosts(body)

    if write:
        SAMPLE.mkdir(parents=True, exist_ok=True)
        for name, body in payloads.items():
            (SAMPLE / f"{name}.json").write_text(body, encoding="utf-8", newline="\n")
        for filename, blob in binaries.items():
            (SAMPLE / filename).write_bytes(blob)
        shutil.copyfile(report["rough_cut"]["mp4"], SAMPLE / "rough_cut.mp4")

    return {"report": report, "telops": json.loads(payloads["telops"]),
            "real_hosts": sorted(found)}


def page_numbers(report: dict, telops: list[dict]) -> dict:
    """Exactly what the preview beside the hero has to claim, from the run."""
    sourced = [(i, t) for i, t in enumerate(telops, start=1) if t.get("source_note")]
    unsourced = [(i, t) for i, t in enumerate(telops, start=1)
                 if t.get("telop_type") == "data" and not t.get("source_note")]
    return {
        "claims_checked": report["claims_checked"],
        "confidential_moments_protected": report["confidential_moments_protected"],
        "cut_seconds": round(report["rough_cut"]["duration_seconds"]),
        "recheck_before_lock": len(report["claims_to_recheck_before_lock"]),
        "sourced_telops": [(i, t["source_note"], " ".join(t["text_lines"])[:44])
                           for i, t in sourced],
        "unsourced_data_telops": [(i, " ".join(t["text_lines"])[:44]) for i, t in unsourced][:3],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--hero-at", type=float, default=None)
    ap.add_argument("--allow-real-domains", action="store_true")
    args = ap.parse_args()

    result = export(args.project_id, write=False)
    if result["real_hosts"] and not args.allow_real_domains:
        print(f"REFUSED: {len(result['real_hosts'])} real hosts in this run's output.")
        for h in result["real_hosts"][:12]:
            print("   ", h)
        print("\nThis file is filmed. Re-run with CURRENTCUT_SEARCH_CORPUS=en,")
        print("or pass --allow-real-domains if you know why you want them.")
        return 1

    numbers = page_numbers(result["report"], result["telops"])
    print("The preview beside the hero must say:")
    print(f"  {numbers['claims_checked']} claims checked")
    print(f"  {numbers['confidential_moments_protected']} confidential moments protected")
    print(f"  {numbers['cut_seconds']}-second first cut assembled")
    print(f"  {numbers['recheck_before_lock']} figures to re-check before lock")
    print("\n  caption order sheet rows to quote:")
    for index, note, text in numbers["sourced_telops"]:
        print(f"    No.{index}  {text}   [{note}]")
    for index, text in numbers["unsourced_data_telops"]:
        print(f"    No.{index}  {text}   [no source — attributed to the speaker]")

    if not args.write:
        print("\n(dry run - pass --write to publish)")
        return 0

    export(args.project_id, write=True)
    print("\npublished to app/static/sample/")

    if args.hero_at is not None:
        subprocess.run(["ffmpeg", "-y", "-ss", str(args.hero_at),
                        "-i", str(SAMPLE / "rough_cut.mp4"),
                        "-frames:v", "1", "-q:v", "2", str(STATIC / "hero_frame.jpg")],
                       check=True, capture_output=True)
        print(f"hero_frame.jpg taken at {args.hero_at}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
