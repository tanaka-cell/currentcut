"""Generate the demo shoot for the Quick Judge Demo — a small factual feature
about an independent coffee shop under pressure from convenience-store coffee.

Two shoots, the same story told in two places: `en` in the United States and
`ja` in Japan. English is what the contest judges will run, and a demo whose
output they cannot read proves nothing about the output; the Japanese one stays
because the telop order sheet is answering a real Japanese newsroom's problem,
and dropping it would drop the evidence that this is a tool rather than a demo.

Fully synthetic: the shop, the owner and the customer are invented, and no real
person or company is quoted. What is deliberately NOT invented is the public
record each owner cites. A fictional product cannot be fact-checked, because no
real evidence for it exists anywhere; that was the flaw in the first version of
this demo, where a real web search could only return unrelated pages that
happened to share a number.

Planted on purpose, one per capability:
  - a public statistic with a government publisher   → should verify and be credited
  - a public RULE stated in the first person         → verifies; must not be
      filed as the speaker's private figure, and its start year must not make
      it look stale
  - a real figure with no public-authority publisher → checked, but uncredited
  - shop-level numbers with no public data           → must stay unverified
  - an unnamed subject ("this street")               → cannot be checked at all
  - an explicit off-record remark                    → must never leave
  - B-roll and an exterior                           → structure for the cut

Audio uses Gemini TTS when GEMINI_API_KEY is present, otherwise a tone. Each
clip gets a `<name>.mp4.analysis.json` sidecar holding the ground truth, used
by mock mode and by the acceptance tests.

Usage: python scripts/make_demo_assets.py [en|ja ...]   (default: both)
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "demo-assets" / "generated"
FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
FONT = "C:/Windows/Fonts/meiryo.ttc" if os.name == "nt" else \
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"

GAP = 0.5  # seconds of silence between utterances

SHOOTS = {}

SHOOTS["ja"] = [
    {
        "name": "clip01_interview_owner",
        "color": "0x3b2f26",
        "label": "INTERVIEW - 青葉珈琲店 店主",
        "shot_type": "interview",
        "speaker": "青葉珈琲店 店主",
        "voice": "Charon",
        "visual": "喫茶店のカウンター越しに店主のインタビュー、胸から上のミディアムショット",
        "utterances": [
            # background — no factual claim to check
            "父の代からこの商店街で、四十年ちかく喫茶店をやっています。",
            # A remembered figure that is genuinely out of date. Public reporting
            # now puts the number higher, so this should come back as conflicting
            # with the current figure shown — the tool catching the director's
            # error before the structure is locked.
            "コンビニエンスストアは、いま全国におよそ五万六千店あります。どこでも手軽にコーヒーが飲める時代です。",
            # A correct, checkable rule with a government primary source.
            "うちも、お持ち帰りは八パーセント、店内でお召し上がりは十パーセントの消費税をいただいています。",
            # shop-level numbers — no public data exists, must stay unverified
            "うちは一日およそ百杯。この十年でお客さんは三割ほど減りました。",
            # off-record — must never reach search, script or cut
            "ここはオフレコですが、来月から二号店を出す話が進んでいます。まだ発表前なので放送では使わないでください。",
        ],
    },
    {
        "name": "clip02_interview_customer",
        "color": "0x4a3b2a",
        "label": "INTERVIEW - 常連客",
        "shot_type": "reaction",
        "speaker": "常連客(60代)",
        "voice": "Aoede",
        "visual": "カウンター席に座る常連客のインタビュー、手元にコーヒーカップ",
        "utterances": [
            "やっぱり、手で淹れたコーヒーは違いますよ。",
            "この商店街も、お店がずいぶん減りましたね。",
        ],
    },
    {
        "name": "clip03_broll_pour",
        "color": "0x2f3f36",
        "label": "B-ROLL - ハンドドリップ",
        "shot_type": "broll",
        "speaker": "",
        "voice": None,
        "visual": "ハンドドリップでコーヒーを淹れる手元のクローズアップ、湯気が立つ",
        "utterances": [],
        "duration": 8,
    },
    {
        "name": "clip04_exterior_shotengai",
        "color": "0x554433",
        "label": "EXTERIOR - 商店街の外観",
        "shot_type": "exterior",
        "speaker": "",
        "voice": None,
        "visual": "夕方の商店街、シャッターの下りた店舗が並ぶ",
        "utterances": [],
        "duration": 6,
    },
]

# The English shoot. Same five things planted, against United States public
# record instead of Japanese: the judges for this contest test in English, and a
# demo whose output they cannot read proves nothing about the output.
#
# The two figures that should verify are chosen for how firmly they are
# published, not for how interesting they are:
#   - the federal minimum wage, stated by the Department of Labor. It is also a
#     RULE IN FORCE since 2009, so it exercises the distinction between a figure
#     that ages and a rule that holds until changed — a 2009 date must not make
#     it stale.
#   - the share of the private workforce employed by small businesses, published
#     by the Small Business Administration. A measurement, so it carries an
#     as-of year and can go stale.
# The convenience-store count is planted deliberately WITHOUT a government
# publisher: the trade association that publishes it is not a primary source by
# the citation rule, so this line should come back checked but uncredited. That
# is the behaviour worth showing, not a failure.
SHOOTS["en"] = [
    {
        "name": "clip01_interview_owner",
        "color": "0x3b2f26",
        "label": "INTERVIEW - Owner, Harrow Bend Coffee",
        "shot_type": "interview",
        "speaker": "Owner, Harrow Bend Coffee",
        "voice": "Charon",
        "visual": "Interview with the owner across the counter, medium shot from the chest up",
        "utterances": [
            # background — nothing to check
            "My father opened this place in nineteen seventy-eight, and I have been "
            "behind this counter for twenty-two years.",
            # public statistic, published by a government body → should verify
            "Small businesses like this one employ almost half of the private "
            "workforce in this country.",
            # a public RULE stated in the first person. The speaker does not set
            # the federal minimum wage, so the subject is the wage, not the shop.
            "We pay the federal minimum wage here, seven dollars and twenty-five "
            "cents an hour. It has not changed since two thousand nine.",
            # a real figure whose publisher is a trade association, not a public
            # authority → checked, but nobody to credit on screen
            "There are more than a hundred and fifty thousand convenience stores "
            "in this country now, and nearly all of them sell coffee.",
            # shop-level numbers — nobody publishes these, must stay unverified
            "We do about two hundred cups a day. Ten years ago it was closer to "
            "three hundred.",
            # off record — must never reach search, script or cut
            "Off the record, we are signing a lease on a second location next "
            "month. It has not been announced, so please do not use that on air.",
        ],
    },
    {
        "name": "clip02_interview_customer",
        "color": "0x4a3b2a",
        "label": "INTERVIEW - Regular customer",
        "shot_type": "reaction",
        "speaker": "Regular customer",
        "voice": "Aoede",
        "visual": "Interview with a regular at the counter, coffee cup in frame",
        "utterances": [
            "You can taste the difference when somebody actually makes it by hand.",
            # real, but about an unnamed street — no source can ever match it
            "A lot of the shops along this street have closed up.",
        ],
    },
    {
        "name": "clip03_broll_pour",
        "color": "0x2f3f36",
        "label": "B-ROLL - Pour-over",
        "shot_type": "broll",
        "speaker": "",
        "voice": None,
        "visual": "Close-up of a pour-over being made by hand, steam rising",
        "utterances": [],
        "duration": 8,
    },
    {
        "name": "clip04_exterior_street",
        "color": "0x554433",
        "label": "EXTERIOR - Main street",
        "shot_type": "exterior",
        "speaker": "",
        "voice": None,
        "visual": "Late afternoon on the main street, several storefronts shuttered",
        "utterances": [],
        "duration": 6,
    },
]


def tts(text: str, voice: str, dst_wav: Path) -> bool:
    """Gemini TTS -> wav. Returns False on any failure (caller falls back)."""
    if not GEMINI_API_KEY:
        return False
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
            ),
        )
        pcm = response.candidates[0].content.parts[0].inline_data.data
        with wave.open(str(dst_wav), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
        return True
    except Exception as exc:
        print(f"  TTS failed ({exc}); falling back to tone")
        return False


def tone(duration: float, dst_wav: Path, freq: int = 440) -> None:
    rate = 24000
    n = int(duration * rate)
    with wave.open(str(dst_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = b"".join(
            struct.pack("<h", int(3000 * __import__("math").sin(2 * 3.14159 * freq * i / rate)))
            for i in range(n))
        w.writeframes(frames)


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def silence(duration: float, dst_wav: Path) -> None:
    rate = 24000
    with wave.open(str(dst_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(duration * rate))


def concat_wavs(parts: list[Path], dst: Path) -> None:
    with wave.open(str(dst), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        for p in parts:
            with wave.open(str(p), "rb") as w:
                out.writeframes(w.readframes(w.getnframes()))


def build_clip(clip: dict, tmp: Path, out_dir: Path) -> None:
    name = clip["name"]
    mp4 = out_dir / f"{name}.mp4"
    print(f"[{name}]")

    segments = []
    if clip["utterances"]:
        parts: list[Path] = []
        cursor = 0.0
        lead = tmp / f"{name}_lead.wav"
        silence(GAP, lead)
        parts.append(lead)
        cursor += GAP
        for i, text in enumerate(clip["utterances"]):
            piece = tmp / f"{name}_u{i}.wav"
            if not tts(text, clip["voice"], piece):
                tone(max(2.0, len(text) * 0.12), piece, freq=300 + 60 * i)
            d = wav_duration(piece)
            segments.append({
                "start_seconds": round(cursor, 2),
                "end_seconds": round(cursor + d, 2),
                "speaker": clip["speaker"],
                "transcript": text,
                "visual_summary": clip["visual"],
                "shot_type": clip["shot_type"],
                "usability_score": 0.85,
            })
            parts.append(piece)
            cursor += d
            gap = tmp / f"{name}_g{i}.wav"
            silence(GAP, gap)
            parts.append(gap)
            cursor += GAP
        audio = tmp / f"{name}_audio.wav"
        concat_wavs(parts, audio)
        duration = cursor
    else:
        duration = clip["duration"]
        audio = tmp / f"{name}_audio.wav"
        tone(duration, audio, freq=150)
        segments.append({
            "start_seconds": 0,
            "end_seconds": duration,
            "speaker": "",
            "transcript": "",
            "visual_summary": clip["visual"],
            "shot_type": clip["shot_type"],
            "usability_score": 0.75,
        })

    font_escaped = Path(FONT).as_posix().replace(":", "\\:")
    fontopt = f"fontfile='{font_escaped}':" if Path(FONT).exists() else ""
    label = clip["label"].replace(":", "\\:").replace(",", "\\,").replace("'", "\\'")
    vf = (f"drawtext={fontopt}text='{label}':fontsize=40:fontcolor=white:"
          f"x=(w-text_w)/2:y=60,"
          f"drawtext={fontopt}text='CurrentCut DEMO FOOTAGE (fictional)':fontsize=20:"
          f"fontcolor=gray:x=20:y=h-40")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", f"color=c={clip['color']}:s=1280x720:d={duration:.2f}:r=30",
         "-i", str(audio),
         "-vf", vf,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-ar", "48000", "-ac", "2", "-shortest",
         str(mp4)],
        check=True,
    )
    sidecar = mp4.with_suffix(mp4.suffix + ".analysis.json")
    sidecar.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"  -> {mp4.name} ({duration:.1f}s, {len(segments)} segments)")


def main() -> None:
    wanted = [a for a in sys.argv[1:] if not a.startswith("-")] or list(SHOOTS)
    unknown = [w for w in wanted if w not in SHOOTS]
    if unknown:
        print(f"Unknown shoot(s): {', '.join(unknown)}. Known: {', '.join(SHOOTS)}")
        return 1
    print(f"TTS: {'Gemini (' + TTS_MODEL + ')' if GEMINI_API_KEY else 'disabled -> tones'}")
    for language in wanted:
        out_dir = OUT / language
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / "_tmp"
        tmp.mkdir(exist_ok=True)
        print(f"\n=== {language} -> {out_dir}")
        for clip in SHOOTS[language]:
            build_clip(clip, tmp, out_dir)
        for f in tmp.glob("*"):
            f.unlink()
        tmp.rmdir()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
