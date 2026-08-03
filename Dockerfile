FROM python:3.11-slim

# ffmpeg cuts and renders; the CJK font is required for burned-in captions.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CURRENTCUT_FONT=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
    CURRENTCUT_DATA_DIR=/tmp/currentcut/data \
    CURRENTCUT_OUTPUT_DIR=/tmp/currentcut/output

WORKDIR /app

COPY services/agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY services/agent/app ./app
COPY demo-assets ./demo-assets

EXPOSE 8080
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
