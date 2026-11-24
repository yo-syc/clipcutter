# ClipCutter website (web + worker share this image). Works on x86 and ARM (Oracle Cloud free tier).
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg nodejs libfribidi0 fonts-dejavu-core fonts-noto-core fonts-noto-color-emoji ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV CLIPCUTTER_DATA=/data PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
CMD ["clipcutter", "site", "--host", "0.0.0.0", "--port", "8000"]
