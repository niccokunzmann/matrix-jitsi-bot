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
# runtime to detect attachment mime types. bash/bash-completion are for the
# CLI's tab completion, for anyone who `docker exec`s in with bash.
RUN apk add --no-cache file bash bash-completion \
    && mkdir -p /data

WORKDIR /app
COPY --from=builder /app /app
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# _TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION forces --show-completion to
# take an explicit shell name instead of auto-detecting one from the
# calling process, which is unreliable in a minimal build container.
RUN _TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1 \
    matrix-jitsi-bot --show-completion bash > /etc/bash_completion.d/matrix-jitsi-bot

VOLUME ["/data"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["run"]
