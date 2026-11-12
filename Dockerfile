# syntax=docker/dockerfile:1
# ---- Build stage: compile native dependencies and build the venv ----
FROM ubuntu:26.04 AS builder

RUN apt update && apt -y install --no-install-recommends \
  git \
  ca-certificates \
  python3 \
  python3-dev \
  build-essential \
  cmake \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_COMPILE_BYTECODE=1

WORKDIR /planesign

# Only the dependency manifests, so source changes reuse the cached venv (and the rgbmatrix compile).
COPY pyproject.toml uv.lock .python-version ./

RUN uv sync --frozen --no-install-project --no-dev

# ---- Runtime stage: only what is needed to run the sign ----
FROM ubuntu:26.04

RUN apt update && apt -y install --no-install-recommends \
  nginx \
  openssl \
  ca-certificates \
  python3 \
  mpg123 \
  alsa-utils \
  && apt clean \
  && rm -rf /var/lib/apt/lists/* /usr/lib/python3.*/test

# Nginx setup comes before the app files so it stays cached across updates. The cache can keep the
# certificate for a long time, so it gets a long validity; a new key would also void browser exceptions.
ARG PLANESIGN_ROOT=/planesign
RUN unlink /etc/nginx/sites-enabled/default \
  && openssl req -x509 -nodes -days 3650 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"
COPY docker_nginx_planesign.conf /etc/nginx/conf.d/
RUN sed -i "s|\${PLANESIGN_ROOT}|${PLANESIGN_ROOT}|g" /etc/nginx/conf.d/docker_nginx_planesign.conf

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

# Any layer after a changed one gets a new digest, even with identical files, so the Pi downloads it
# again. Large layers that change rarely go first. datafiles/ and icons/ are not in the image: compose
# mounts the host's copies, which the installer seeds from the repository.
COPY sounds sounds
COPY --from=builder --exclude=**/tests /planesign/.venv /planesign/.venv
COPY fonts/4x6.* fonts/5x7.* fonts/6x13.* fonts/9x18B.* fonts/helvR12.* fonts/
# The app code changes most, but its bytecode is the largest part of a source update, so files that
# often change without it (web/, docs, scripts) come after it and do not recompile it.
COPY planesign planesign
# uv only compiles the venv (the project is not installed), so compile the app's own sources too.
RUN .venv/bin/python -m compileall -q planesign
COPY --exclude=fonts --exclude=sounds --exclude=planesign . .

ARG BUILD_VERSION=argnotset
RUN echo ${BUILD_VERSION} > version.txt

# exec makes Python PID 1, so it receives docker stop's SIGTERM and blanks the panel; sh would swallow it.
CMD ["sh", "-c", "service nginx start && exec .venv/bin/python planesign/"]
