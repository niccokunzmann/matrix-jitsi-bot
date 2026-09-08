# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.12-alpine AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# git: hatch-vcs derives the package version from git history at build time.
# The rest is build tooling for dependencies without musllinux wheels (e.g.
# Rust-based packages pulled in by nio-bot/niquests) that would otherwise
# need to be compiled from source on Alpine.
RUN apk add --no-cache \
        git \
        build-base \
        cargo \
        rust \
        libffi-dev \
        jpeg-dev \
        zlib-dev \
        openssl-dev \
        file-dev

# Install dependencies first, cached separately from the application code.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    MJB_DB=/data/matrix-jitsi-bot.sqlite3

# file provides libmagic, which python-magic (a nio-bot dependency) loads at
# runtime to detect attachment mime types.
RUN apk add --no-cache file \
    && addgroup -S app \
    && adduser -S app -G app -h /data \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder --chown=app:app /app /app
COPY --chown=app:app --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data"]
USER app

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["run"]
