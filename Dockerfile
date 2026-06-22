# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg mkvtoolnix \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip \
    && pip install hatchling \
    && pip install ".[speedups]"

COPY . .
RUN pip install --no-deps -e .

VOLUME ["/data/storage", "/data/sessions"]

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import nekofetch; print('ok')" || exit 1

CMD ["python", "-m", "nekofetch"]
