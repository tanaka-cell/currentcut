"""Guards that belong on the corridor rather than on each door.

The endpoints of this service were each given their own caps as they were
written, which is how a public instance ends up with a carefully bounded upload
form next to a `POST /projects` that accepts a five-megabyte title and writes it
to disk. Everything here applies to every request, so a route added tomorrow is
covered by the same rules as the ones written today.

None of it is authentication. The hosted instance is a public demo that a judge
has to be able to open and run in one click, and a login would make the thing it
is demonstrating unreachable. What these guards do is make the demo survive
being found: they bound what one visitor can spend of our disk, our memory and
our API budget, and they stop the service being used as a filesystem.

The numbers are set far above anything a person clicking through the demo will
reach. They are there for a script, not for a visitor.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections import deque

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

# Bodies. The upload route streams and checks its own (much larger) caps, so it
# is exempt here and guarded in upload.py; everything else is JSON or a small
# form and has no business being megabytes.
MAX_BODY_BYTES = int(os.getenv("CURRENTCUT_MAX_BODY_BYTES", str(2 * 1024 * 1024)))
_BODY_EXEMPT = ("/api/upload/start", "/telop-template", "/house-style")

# Requests per window per client. A visitor running the demo makes a handful of
# calls plus one status poll a second; 240 in a minute leaves room for several
# people on one office address and still stops a script enumerating ids.
RATE_LIMIT = int(os.getenv("CURRENTCUT_RATE_LIMIT", "240"))
RATE_WINDOW_SECONDS = int(os.getenv("CURRENTCUT_RATE_WINDOW_SECONDS", "60"))

# Text fields that reach the disk. Long enough for a real programme title or a
# real editorial note, short enough that nobody stores a video in one.
MAX_TITLE_CHARS = int(os.getenv("CURRENTCUT_MAX_TITLE_CHARS", "300"))
MAX_RULES = int(os.getenv("CURRENTCUT_MAX_RULES", "50"))
MAX_RULE_CHARS = int(os.getenv("CURRENTCUT_MAX_RULE_CHARS", "500"))
MAX_NAME_CHARS = int(os.getenv("CURRENTCUT_MAX_NAME_CHARS", "120"))

# The interactive API map. Useful while building, and a menu of every route and
# body shape for anyone else. Off unless asked for.
EXPOSE_API_DOCS = os.getenv("CURRENTCUT_EXPOSE_API_DOCS", "").lower() in ("1", "true", "yes")

_hits: dict[str, deque[float]] = {}
_hits_lock = threading.Lock()
# Above this many distinct clients we forget the quietest rather than grow.
_MAX_TRACKED_CLIENTS = 5000


def _client(request: Request) -> str:
    """Who to count this against.

    Behind Cloud Run the peer address is Google's front end, so the client is
    the first hop in X-Forwarded-For. That header is caller-controlled on a
    naked deployment, which makes this a speed bump rather than a lock — which
    is all a demo needs, and it is honest about being that.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _over_rate_limit(key: str) -> bool:
    now = time.monotonic()
    cutoff = now - RATE_WINDOW_SECONDS
    with _hits_lock:
        if len(_hits) > _MAX_TRACKED_CLIENTS:
            for stale in [k for k, v in _hits.items() if not v or v[-1] < cutoff]:
                _hits.pop(stale, None)
        seen = _hits.setdefault(key, deque())
        while seen and seen[0] < cutoff:
            seen.popleft()
        if len(seen) >= RATE_LIMIT:
            return True
        seen.append(now)
        return False


_HEADERS = {
    # The page is one file that carries its own script and style inline, so
    # 'unsafe-inline' is required for it to run at all. Saying so plainly is
    # better than a policy that looks stricter than it is: what this buys is the
    # rest of the list — no other origin may be loaded, framed or connected to.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # A project id is a capability: anyone holding the URL can read the run. The
    # referrer policy above stops it leaking to sites the director clicks
    # through to from the source list.
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


async def guard_request(request: Request, call_next):
    """Rate, size, and the headers on the way back out."""
    if _over_rate_limit(_client(request)):
        return JSONResponse(
            {"detail": "too many requests — slow down and try again in a minute"},
            status_code=429, headers={"Retry-After": str(RATE_WINDOW_SECONDS)})

    path = request.url.path
    if not any(part in path for part in _BODY_EXEMPT):
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return JSONResponse(
                {"detail": f"request body is over the {MAX_BODY_BYTES // 1024} KB limit"},
                status_code=413)

    response = await call_next(request)
    for key, value in _HEADERS.items():
        response.headers.setdefault(key, value)
    return response


# Small uploads: a programme's order form, and past scripts to learn the shape
# of a corner. Footage has its own much larger caps in upload.py.
MAX_TEMPLATE_BYTES = int(os.getenv("CURRENTCUT_MAX_TEMPLATE_BYTES", str(20 * 1024 * 1024)))
MAX_SCRIPT_BYTES = int(os.getenv("CURRENTCUT_MAX_SCRIPT_BYTES", str(5 * 1024 * 1024)))


def safe_filename(filename: str | None) -> str:
    """A caller's filename reduced to something that can only be a name.

    `Path(name).name` drops a directory prefix on the machine whose separator it
    is written with, and keeps it on the other — so a Windows deployment stores
    "..\\..\\x.txt" happily. Strip both separators first, then allow only
    characters that cannot mean anything to a filesystem.
    """
    raw = (filename or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^\w.\-]", "_", raw).lstrip(".")[:120]
    return name or "file"


async def read_capped(upload, limit: int, what: str) -> bytes:
    """Read an uploaded file, refusing it the moment it goes over.

    `await file.read()` with no argument decides how much memory the request
    uses by asking the caller. Reading in pieces and stopping at the cap means
    an oversized file costs one chunk, not the whole file.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(1 << 20):
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, f"{what} is over the {limit // (1024 * 1024)} MB limit")
        chunks.append(chunk)
    return b"".join(chunks)


def clip(text: str, limit: int, field: str) -> str:
    """A field that reaches the disk, cut to size — loudly.

    Silently truncating a director's title would be worse than refusing it: they
    would find out on the caption sheet.
    """
    text = (text or "").strip()
    if len(text) > limit:
        raise HTTPException(400, f"{field} is over {limit} characters")
    return text
