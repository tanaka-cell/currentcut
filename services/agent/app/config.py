"""Central configuration. Model names and keys come from env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from service root (services/agent/.env) if present.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_SERVICE_ROOT / ".env")

REPO_ROOT = _SERVICE_ROOT.parents[1]

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
PARALLEL_API_KEY = os.getenv("PARALLEL_API_KEY") or ""

# ADK reads GOOGLE_API_KEY; mirror GEMINI_API_KEY into it so one key is enough.
if GEMINI_API_KEY and not os.getenv("GOOGLE_API_KEY"):
    os.environ["GOOGLE_API_KEY"] = GEMINI_API_KEY
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "FALSE"))

GEMINI_VIDEO_MODEL = os.getenv("GEMINI_VIDEO_MODEL", "gemini-2.5-flash")
GEMINI_REASONING_MODEL = os.getenv("GEMINI_REASONING_MODEL", "gemini-2.5-pro")
GEMINI_FAST_MODEL = os.getenv("GEMINI_FAST_MODEL", "gemini-2.5-flash")

_FORCED = {m.strip() for m in os.getenv("CURRENTCUT_FORCE_MOCK", "").split(",") if m.strip()}


def gemini_is_mock() -> bool:
    return "gemini" in _FORCED or not GEMINI_API_KEY


def parallel_is_mock() -> bool:
    return "parallel" in _FORCED or not PARALLEL_API_KEY


DATA_DIR = Path(os.getenv("CURRENTCUT_DATA_DIR", str(REPO_ROOT / "data"))).resolve()
OUTPUT_DIR = Path(os.getenv("CURRENTCUT_OUTPUT_DIR", str(_SERVICE_ROOT / "output"))).resolve()
DEMO_ASSETS_DIR = REPO_ROOT / "demo-assets" / "generated"

PARALLEL_BASE_URL = os.getenv("PARALLEL_BASE_URL", "https://api.parallel.ai")
PARALLEL_MAX_SEARCHES_PER_RUN = int(os.getenv("PARALLEL_MAX_SEARCHES_PER_RUN", "20"))
GEMINI_MAX_CLIP_SECONDS = int(os.getenv("GEMINI_MAX_CLIP_SECONDS", "600"))

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

# Font for burned-in captions (needed for CJK text in FFmpeg drawtext).
_default_font = "C:/Windows/Fonts/meiryo.ttc" if os.name == "nt" else \
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_FILE = os.getenv("CURRENTCUT_FONT", _default_font)


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, DEMO_ASSETS_DIR):
        d.mkdir(parents=True, exist_ok=True)
