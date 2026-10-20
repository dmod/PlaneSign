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

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

# Least to most frequently changed, so a source-only update downloads just the last layer.
# Any layer after a changed one gets a new digest, even with identical files.
COPY --from=builder --exclude=**/tests /planesign/.venv /planesign/.venv
COPY datafiles datafiles
COPY fonts/4x6.* fonts/5x7.* fonts/6x13.* fonts/9x18B.* fonts/helvR12.* fonts/
COPY icons icons
COPY sounds sounds
COPY --exclude=datafiles --exclude=fonts --exclude=icons --exclude=sounds . .

# Nginx Setup
RUN unlink /etc/nginx/sites-enabled/default
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"

# Define build argument with default value
ARG PLANESIGN_ROOT=/planesign

# Copy and substitute nginx config using the build arg directly
COPY docker_nginx_planesign.conf /etc/nginx/conf.d/
RUN sed -i "s|\${PLANESIGN_ROOT}|${PLANESIGN_ROOT}|g" /etc/nginx/conf.d/docker_nginx_planesign.conf

ARG BUILD_VERSION=argnotset
RUN echo ${BUILD_VERSION} > version.txt

# exec makes Python PID 1, so it receives docker stop's SIGTERM and blanks the panel; sh would swallow it.
CMD ["sh", "-c", "service nginx start && exec .venv/bin/python planesign/"]
