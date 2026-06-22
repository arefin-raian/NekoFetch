# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# ffmpeg + mkvtoolnix for metadata/thumbnail/branding processing
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg mkvtoolnix \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install ".[speedups]"

COPY . .
RUN pip install --no-deps -e .

# Media + Pyrogram session persistence
VOLUME ["/data/storage", "/data/sessions"]

CMD ["python", "-m", "nekofetch"]
