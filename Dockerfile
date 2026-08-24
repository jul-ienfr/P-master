# syntax=docker/dockerfile:1.6
# Phase 1.6 — pin déterministe + multi-stage (repro, pas d'`apt upgrade -y`)
# Digest ubuntu:22.04 au 2026-08-24 (manifest list) — repinner via `docker buildx imagetools inspect ubuntu:22.04`
FROM ubuntu:22.04@sha256:2edbbc5dc405e9612ba3584ce95480277e3eb374407b5505fe26f17df77c7dbc AS base
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/srv/app
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        software-properties-common ca-certificates curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3-pip \
        ffmpeg libsm6 libxext6 tesseract-ocr libtesseract-dev libleptonica-dev \
        libxcb1-dev libx11-xcb-dev libglu1-mesa-dev libxrender-dev libxi-dev \
        libxkbcommon-dev libxkbcommon-x11-dev libegl1 && \
    rm -rf /var/lib/apt/lists/*

# --- deps stage: install Python deps via uv (locké) ---
FROM base AS deps
RUN pip3 install --no-cache-dir "uv==0.8.4"
WORKDIR /srv/app
COPY pyproject.toml uv.lock README.md ./
# `uv sync --frozen` installe exactement uv.lock (Windows wheels émulés — Linux repull au runtime si besoin)
# On installe sans sources pour cacher la couche deps
RUN uv sync --frozen --no-install-project --python 3.11 || pip3 install --no-cache-dir -e .

# --- app stage ---
FROM deps AS app
COPY . /srv/app
# Réinstalle le projet (src/) par-dessus les deps cachées
RUN uv sync --frozen --python 3.11 || pip3 install --no-cache-dir -e .
WORKDIR /srv/app/poker
