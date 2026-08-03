"""Gemini client — real video/text analysis with a deterministic mock fallback.

Mock mode reads a `<video>.analysis.json` sidecar (written by the demo asset
generator as ground truth). This keeps tests deterministic and lets the whole
pipeline run with zero credentials; provider is reported honestly either way.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config


class RawSegment(BaseModel):
    start_seconds: float
    end_seconds: float
    speaker: str = ""
    transcript: str = ""
    visual_summary: str = ""
    shot_type: str = "other"
    usability_score: float = Field(default=0.5, ge=0, le=1)


class VideoAnalysis(BaseModel):
    segments: list[RawSegment]


VIDEO_PROMPT = """You are a broadcast footage logger for a factual TV feature.
Analyze this footage and split it into segments (one per shot / utterance).
For each segment give:
- start_seconds / end_seconds (numbers, from the start of THIS file)
- speaker: name or role if identifiable from context, else ""
- transcript: verbatim words spoken (original language; "" if no speech)
- visual_summary: one sentence, what is on screen (include any on-screen text verbatim)
- shot_type: one of interview / broll / exterior / reaction / other
- usability_score: 0-1, how usable this is in a broadcast edit (focus, audio, framing)
Return ONLY JSON matching the schema."""


class GeminiClient:
    def __init__(self) -> None:
        self.mock = config.gemini_is_mock()
        self._client = None

    @property
    def provider(self) -> str:
        return "mock" if self.mock else "gemini"

    def _real(self):
        if self._client is None:
            from google import genai  # imported lazily so mock mode needs no SDK
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
        return self._client

    # ---------- video ----------
    def analyze_video(self, video_path: str | Path) -> VideoAnalysis:
        video_path = Path(video_path)
        if self.mock:
            return self._mock_analysis(video_path)
        return self._real_analysis(video_path)

    def _real_analysis(self, video_path: Path) -> VideoAnalysis:
        from google.genai import types

        client = self._real()
        uploaded = client.files.upload(file=str(video_path))
        while uploaded.state and uploaded.state.name == "PROCESSING":
            time.sleep(3)
            uploaded = client.files.get(name=uploaded.name)
        if uploaded.state and uploaded.state.name == "FAILED":
            raise RuntimeError(f"Gemini file processing failed for {video_path.name}")
        response = client.models.generate_content(
            model=config.GEMINI_VIDEO_MODEL,
            contents=[uploaded, VIDEO_PROMPT],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VideoAnalysis,
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, VideoAnalysis):
            return parsed
        return VideoAnalysis.model_validate(json.loads(response.text))

    def _mock_analysis(self, video_path: Path) -> VideoAnalysis:
        sidecar = video_path.with_suffix(video_path.suffix + ".analysis.json")
        if sidecar.exists():
            return VideoAnalysis.model_validate_json(sidecar.read_text(encoding="utf-8"))
        return VideoAnalysis(segments=[RawSegment(
            start_seconds=0, end_seconds=10,
            transcript="", visual_summary=f"Unlabeled footage ({video_path.name})",
            shot_type="other", usability_score=0.3,
        )])

    # ---------- text reasoning (classification, claims, script) ----------
    def structured(self, prompt: str, schema: type[BaseModel], model: str | None = None) -> BaseModel:
        """Run a text prompt with structured JSON output. Raises in mock mode —
        callers must branch to their own deterministic mock first."""
        if self.mock:
            raise RuntimeError("GeminiClient.structured called in mock mode")
        from google.genai import types

        client = self._real()
        response = client.models.generate_content(
            model=model or config.GEMINI_FAST_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )
        parsed = response.parsed
        if isinstance(parsed, schema):
            return parsed
        return schema.model_validate(json.loads(response.text))


gemini = GeminiClient()
