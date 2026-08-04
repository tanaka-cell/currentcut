# -*- coding: utf-8 -*-
"""Generate the demo shoot as footage, using Veo, instead of colour cards.

Why this replaced the colour cards
----------------------------------
The first version of the demo drew each line of dialogue as white text on a
coloured background and spoke it with Gemini TTS. It was honest and it was
cheap, and reviewing the entry three separate ways produced the same verdict:
in a contest about film and media, a rough cut made of colour cards does not
read as a cut. It also gave Gemini's video understanding nothing to understand.

Veo is Google's, so nothing about the contest's AI restriction changes: the
demo assets are made with Google AI, as the narration already was.

How the ground truth is decided
-------------------------------
Not by us. We ask Veo for a shot with a line of dialogue in it; Veo speaks the
line, and then Gemini watches the result and writes what it sees and hears into
the `.mp4.analysis.json` sidecar. So the sidecar is a record of what the footage
actually contains, not what we intended it to contain — which is the only way it
can be ground truth for mock mode and the tests.

Consistency
-----------
Every interview shot is generated from one reference frame, so it is the same
person, the same apron, the same espresso machine, the same window. That is not
a workaround: it is how an interview is shot — locked-off camera, one setup,
different answers.

What is planted, and why
------------------------
  - a figure a government body publishes            → should verify and be credited
  - a public RULE stated in the first person        → must not be filed as the
      speaker's private figure; its start year must not make it look stale
  - a real figure only a trade body publishes       → checked, but uncredited
  - the speaker's own numbers                       → nobody publishes them
  - an unnamed subject ("this street")              → cannot be checked at all
  - an explicit off-record remark                   → must never leave
  - B-roll and an exterior                          → structure for the cut

Usage:
    python scripts/make_veo_shoot.py            # generate + analyse everything
    python scripts/make_veo_shoot.py --analyse  # re-analyse existing clips only
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Built somewhere else and swapped in only when the whole shoot is there: a
# half-generated folder is a broken demo, and generation stops for reasons
# outside this script (it ran out of prepaid credit once, mid-shoot).
OUT = Path(os.getenv("VEO_OUT", REPO / "demo-assets" / "generated" / "_veo_wip"))
REFERENCE = OUT / "_reference_owner.png"
MODEL = os.getenv("VEO_MODEL", "veo-3.1-generate-preview")

# The look every shot shares, so the rushes belong to one shoot.
LOOK = ("Documentary factual-television footage. Filmic 24fps look, shallow "
        "depth of field, warm natural afternoon light. No captions, no text on "
        "screen, no music, no on-screen graphics.")

OWNER = ("A coffee shop owner in his fifties in a beige polo shirt and denim "
         "apron, standing behind a wooden counter, a lavalier microphone "
         "clipped to his apron. He looks slightly off camera at an unseen "
         "interviewer and speaks naturally, with small pauses.")

SHOTS = [
    {
        "name": "clip01_owner_intro",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He says: "
                  "\"My father opened this place in nineteen seventy-eight. "
                  "I have been behind this counter for twenty-two years.\"",
    },
    {
        # Published by a government body → should verify and carry a credit.
        "name": "clip02_owner_smallbiz",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He says: "
                  "\"Small businesses like this one employ almost half of the "
                  "private workforce in this country.\"",
    },
    {
        # A public RULE in the first person. He does not set the federal wage.
        "name": "clip03_owner_wage",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He says: "
                  "\"We pay the federal minimum wage here. Seven dollars and "
                  "twenty-five cents an hour. It hasn't changed since two "
                  "thousand nine.\"",
    },
    {
        # Real, but only a trade association publishes it → uncredited.
        "name": "clip04_owner_stores",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He says: "
                  "\"There are more than a hundred and fifty thousand "
                  "convenience stores in this country now. Nearly all of them "
                  "sell coffee.\"",
    },
    {
        # Nobody publishes a single shop's takings.
        "name": "clip05_owner_cups",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He says: "
                  "\"We do about two hundred cups a day. Ten years ago it was "
                  "closer to three hundred.\"",
    },
    {
        # Must never reach the search API, the script or the cut.
        "name": "clip06_owner_offrecord",
        "reference": True,
        "prompt": f"{LOOK} {OWNER} Mid shot from the chest up. He leans in "
                  "slightly and lowers his voice. He says: \"Off the record, "
                  "we're signing a lease on a second location next month. It "
                  "hasn't been announced, so please don't use that.\"",
    },
    {
        # A different person, and an unnamed subject nothing can verify.
        "name": "clip07_customer",
        "reference": False,
        "prompt": f"{LOOK} A regular customer in her sixties sitting at the "
                  "counter of the same coffee shop, a cup in front of her, "
                  "speaking to an unseen interviewer. Mid shot. She says: "
                  "\"You can taste the difference when somebody actually makes "
                  "it by hand. A lot of the shops along this street have "
                  "closed up.\"",
    },
    {
        "name": "clip08_broll_pour",
        "reference": False,
        "prompt": f"{LOOK} Close-up insert shot, no dialogue and no speech: "
                  "hands making a pour-over coffee, steam rising from the "
                  "filter, water spiralling slowly. Only the ambient sound of "
                  "pouring water.",
    },
    {
        "name": "clip09_exterior_street",
        "reference": False,
        "prompt": f"{LOOK} Establishing exterior shot, no dialogue and no "
                  "speech: a quiet main street in late afternoon, several "
                  "shuttered storefronts, one lit coffee shop window. Only "
                  "faint ambient street sound.",
    },
]


def client():
    from google import genai
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=key)


def generate(shot: dict, c) -> Path:
    from google.genai import types

    mp4 = OUT / f"{shot['name']}.mp4"
    if mp4.exists():
        print(f"[{shot['name']}] already generated")
        return mp4

    kwargs = {"model": MODEL, "prompt": shot["prompt"],
              "config": types.GenerateVideosConfig(aspect_ratio="16:9")}
    if shot["reference"] and REFERENCE.exists():
        # One setup, one person, one wardrobe — the way an interview is shot.
        kwargs["image"] = types.Image.from_file(location=str(REFERENCE))

    print(f"[{shot['name']}] generating...", flush=True)
    # A generation takes about a minute and the connection sometimes drops in
    # the middle of one. Losing the whole shoot to a disconnect on clip eight is
    # not a failure worth accepting.
    for attempt in range(3):
        try:
            op = c.models.generate_videos(**kwargs)
            waited = 0
            while not op.done:
                time.sleep(10)
                waited += 10
                op = c.operations.get(op)
                print(f"  ...{waited}s", flush=True)
            break
        except Exception as exc:
            if attempt == 2:
                raise
            print(f"  {type(exc).__name__}: {exc}; retrying", flush=True)
            time.sleep(15)

    if not getattr(op, "response", None) or not op.response.generated_videos:
        raise RuntimeError(f"{shot['name']}: no video returned ({op})")
    video = op.response.generated_videos[0].video
    c.files.download(file=video)
    video.save(str(mp4))
    print(f"  -> {mp4.name} ({mp4.stat().st_size // 1024} KB)", flush=True)
    return mp4


def analyse(mp4: Path) -> None:
    """Ground truth is what Gemini reads out of the finished clip, not what we
    asked Veo for. Anything else would be a sidecar describing footage that does
    not exist."""
    sys.path.insert(0, str(REPO / "services" / "agent"))
    from app.clients.gemini_client import gemini

    analysis = gemini.analyze_video(mp4)
    sidecar = mp4.with_suffix(mp4.suffix + ".analysis.json")
    sidecar.write_text(
        json.dumps(json.loads(analysis.model_dump_json()), ensure_ascii=False, indent=1),
        encoding="utf-8")
    speech = [s for s in analysis.segments if s.transcript.strip()]
    print(f"  {len(analysis.segments)} segments, {len(speech)} with speech")
    for s in analysis.segments:
        if s.transcript.strip():
            print(f"    [{s.start_seconds:.1f}-{s.end_seconds:.1f}] "
                  f"{s.speaker}: {s.transcript}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    analyse_only = "--analyse" in sys.argv
    if not REFERENCE.exists() and not analyse_only:
        sys.exit(f"Reference frame missing: {REFERENCE}\n"
                 "Extract one from a first generation and save it there, so "
                 "every interview shot is the same person.")

    c = None if analyse_only else client()
    for shot in SHOTS:
        mp4 = OUT / f"{shot['name']}.mp4"
        if not analyse_only:
            mp4 = generate(shot, c)
        if not mp4.exists():
            print(f"[{shot['name']}] no clip; skipping analysis")
            continue
        print(f"[{shot['name']}] analysing...", flush=True)
        analyse(mp4)
    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
