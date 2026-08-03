"""Generate the fictional "AIスマート弁当箱" shoot for the Quick Judge Demo.

Fully synthetic — no real client footage. Each clip is FFmpeg-composed
(colored scene + burned-in scene label). Interview audio uses Gemini TTS when
GEMINI_API_KEY is present (Google TTS is contest-allowed), otherwise a tone.

Each clip gets a `<name>.mp4.analysis.json` sidecar: the ground truth used by
mock mode and by acceptance tests. Deliberately planted content (brief §11):
  - public product explanation
  - "全国80店舗" (verifiable claim)
  - "価格は1,980円" (will change before air)
  - "ここはオフレコですが…" (off-record, must be protected)
  - customer reaction with "人気" (needs human approval before search)
  - product B-roll + storefront exterior

Usage: python scripts/make_demo_assets.py  (from repo root or scripts/)
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

CLIPS = [
    {
        "name": "clip01_interview_ceo",
        "color": "0x2b3a55",
        "label": "INTERVIEW - スマートベントー社 社長",
        "shot_type": "interview",
        "speaker": "スマートベントー社 社長",
        "voice": "Charon",
        "visual": "オフィスでの社長インタビュー、胸から上のミディアムショット",
        "utterances": [
            "私たちのAIスマート弁当箱は、中身の栄養バランスを自動で記録してくれる新しい商品です。",
            "おかげさまで、現在、全国に80店舗で販売しています。",
            "価格は1,980円です。手に取りやすい値段にこだわりました。",
            "ここはオフレコですが、来月銀座に新店舗を出す予定なんです。まだ発表前なので放送では使わないでください。",
        ],
    },
    {
        "name": "clip02_interview_customer",
        "color": "0x4a3b2a",
        "label": "INTERVIEW - 利用客",
        "shot_type": "reaction",
        "speaker": "利用客(30代)",
        "voice": "Aoede",
        "visual": "店頭での利用客インタビュー、手にスマート弁当箱を持っている",
        "utterances": [
            "えっ、これすごい！お弁当がしゃべるなんて思わなかった！",
            "最近SNSでも人気ですよね。友達もみんな話題にしています。",
        ],
    },
    {
        "name": "clip03_broll_product",
        "color": "0x3a5540",
        "label": "B-ROLL - 商品アップ",
        "shot_type": "broll",
        "speaker": "",
        "voice": None,
        "visual": "白いテーブルの上のAIスマート弁当箱のクローズアップ、LED表示が点灯",
        "utterances": [],
        "duration": 8,
    },
    {
        "name": "clip04_exterior_store",
        "color": "0x554433",
        "label": "EXTERIOR - 店舗外観",
        "shot_type": "exterior",
        "speaker": "",
        "voice": None,
        "visual": "商業ビル1階の店舗外観、通行人が行き交う",
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


def build_clip(clip: dict, tmp: Path) -> None:
    name = clip["name"]
    mp4 = OUT / f"{name}.mp4"
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
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_tmp"
    tmp.mkdir(exist_ok=True)
    print(f"Output: {OUT}")
    print(f"TTS: {'Gemini (' + TTS_MODEL + ')' if GEMINI_API_KEY else 'disabled -> tones'}")
    for clip in CLIPS:
        build_clip(clip, tmp)
    for f in tmp.glob("*"):
        f.unlink()
    tmp.rmdir()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
