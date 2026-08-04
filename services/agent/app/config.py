"""Central configuration. Model names and keys come from env only."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from service root (services/agent/.env) if present.
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_SERVICE_ROOT / ".env")


def _find_upwards(name: str, start: Path) -> Path | None:
    """The container flattens the repo (app lives at /app), so the checkout
    layout cannot be assumed. Walk up instead of indexing into parents."""
    for candidate in [start, *start.parents]:
        if (candidate / name).is_dir():
            return candidate / name
    return None


REPO_ROOT = _SERVICE_ROOT.parents[1] if len(_SERVICE_ROOT.parents) > 1 else _SERVICE_ROOT

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""


def _parallel_key() -> str:
    """PARALLEL_API_KEY, or a key file pointed at by PARALLEL_API_KEY_FILE.

    On Cloud Run the key comes from Secret Manager as an env var; the file
    option exists so local development never puts a key in shell history.
    """
    if os.getenv("PARALLEL_API_KEY"):
        return os.environ["PARALLEL_API_KEY"]
    key_file = os.getenv("PARALLEL_API_KEY_FILE", "")
    if key_file:
        try:
            return Path(key_file).expanduser().read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


PARALLEL_API_KEY = _parallel_key()

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

_demo_env = os.getenv("CURRENTCUT_DEMO_DIR", "")
_demo_found = _find_upwards("demo-assets", _SERVICE_ROOT)
DEMO_ASSETS_DIR = (
    Path(_demo_env).resolve() if _demo_env
    else (_demo_found / "generated") if _demo_found
    else REPO_ROOT / "demo-assets" / "generated"
)

# The demo ships one shoot per language. English is the default because that is
# what a visitor to the hosted demo will be reading.
DEMO_SHOOTS = ("en", "ja")
DEFAULT_DEMO_SHOOT = os.getenv("CURRENTCUT_DEFAULT_SHOOT", "en")


def demo_dir(shoot: str = "") -> Path:
    """Footage for one shoot. Falls back to the flat directory so a checkout
    made before the shoots were split still runs."""
    shoot = shoot or DEFAULT_DEMO_SHOOT
    per_language = DEMO_ASSETS_DIR / shoot
    return per_language if per_language.is_dir() else DEMO_ASSETS_DIR

# "Your own footage" uploads on the hosted demo. The caps are cost armour, not
# product limits: the public instance runs on our Gemini key, so an unguarded
# upload form is an invitation to spend our quota. Sized for a short factual
# feature's selects, not a full rushes card.
UPLOAD_DIR = Path(os.getenv("CURRENTCUT_UPLOAD_DIR", str(DATA_DIR / "uploads"))).resolve()
# Caps for the public instance only — it runs on our keys and on one small
# Cloud Run machine whose filesystem is its memory. The pipeline itself is not
# built to these numbers: takes longer than the chunk size are split and read
# in parallel, so length is a question of how long you are willing to wait and
# how much disk the deployment has, not of what the code can hold. A private
# deployment raises them with environment variables and nothing else.
UPLOAD_MAX_FILES = int(os.getenv("CURRENTCUT_UPLOAD_MAX_FILES", "12"))
UPLOAD_MAX_FILE_MB = int(os.getenv("CURRENTCUT_UPLOAD_MAX_FILE_MB", "300"))
UPLOAD_MAX_TOTAL_MB = int(os.getenv("CURRENTCUT_UPLOAD_MAX_TOTAL_MB", "900"))
UPLOAD_MAX_TOTAL_MINUTES = int(os.getenv("CURRENTCUT_UPLOAD_MAX_TOTAL_MINUTES", "60"))
UPLOAD_RUNS_PER_DAY = int(os.getenv("CURRENTCUT_UPLOAD_RUNS_PER_DAY", "8"))
UPLOAD_ALLOWED_SUFFIXES = (".mp4", ".mov", ".m4v")

# How many provider calls are in flight at once. Every heavy step is one call
# per clip or per segment with nothing shared between them, so this is the
# single number that decides whether a night's rushes takes an hour or a day.
# Bounded by the provider's rate limit, not by the machine.
MAX_CONCURRENCY = int(os.getenv("CURRENTCUT_MAX_CONCURRENCY", "6"))
# Rushes arrive as long takes, not as eight-second clips. Anything longer than
# this is split before analysis: it keeps a single request inside the model's
# context window, and lets the pieces of one long take be read in parallel.
ANALYSIS_CHUNK_MINUTES = int(os.getenv("CURRENTCUT_ANALYSIS_CHUNK_MINUTES", "10"))

PARALLEL_BASE_URL = os.getenv("PARALLEL_BASE_URL", "https://api.parallel.ai")
PARALLEL_MAX_SEARCHES_PER_RUN = int(os.getenv("PARALLEL_MAX_SEARCHES_PER_RUN", "20"))
# Text budget per search. The default returns snippets far too short to contain
# the figure being checked, which makes every claim look unsupported.
PARALLEL_MAX_CHARS_TOTAL = int(os.getenv("PARALLEL_MAX_CHARS_TOTAL", "40000"))
# Kept per page, and how much of it the evidence comparator reads. The figure is
# often well past the first paragraph, so both are far above the old 500.
EXCERPT_STORE_CHARS = int(os.getenv("CURRENTCUT_EXCERPT_STORE_CHARS", "6000"))
EXCERPT_JUDGE_CHARS = int(os.getenv("CURRENTCUT_EXCERPT_JUDGE_CHARS", "6000"))
# How far back a source's own as-of year may be and still confirm a claim being
# spoken in the present tense on air.
STALE_EVIDENCE_YEARS = int(os.getenv("CURRENTCUT_STALE_EVIDENCE_YEARS", "3"))
GEMINI_MAX_CLIP_SECONDS = int(os.getenv("GEMINI_MAX_CLIP_SECONDS", "600"))

FFMPEG = os.getenv("FFMPEG_BIN", "ffmpeg")
FFPROBE = os.getenv("FFPROBE_BIN", "ffprobe")

# Font for burned-in captions (needed for CJK text in FFmpeg drawtext).
_default_font = "C:/Windows/Fonts/meiryo.ttc" if os.name == "nt" else \
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_FILE = os.getenv("CURRENTCUT_FONT", _default_font)


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, DEMO_ASSETS_DIR, UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)
