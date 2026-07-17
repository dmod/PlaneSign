# ---- Build stage: compile native dependencies and build the venv ----
FROM ubuntu:24.04 AS builder

RUN apt update && apt -y install --no-install-recommends \
  git \
  ca-certificates \
  python3 \
  python3-dev \
  python3-pil \
  build-essential \
  cmake \
  && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/
ENV CFLAGS="-I/usr/include/python3.12"

WORKDIR /planesign

COPY . .
RUN uv sync --frozen --no-install-project --no-dev

# ---- Runtime stage: only what is needed to run the sign ----
FROM ubuntu:24.04

RUN apt update && apt -y install --no-install-recommends \
  nginx \
  openssl \
  ca-certificates \
  python3 \
  libpython3.12t64 \
  ffmpeg \
  alsa-utils \
  && apt clean \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

# Application source and the pre-built virtual environment
COPY . .
COPY --from=builder /planesign/.venv /planesign/.venv

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

CMD ["sh", "-c", "service nginx start && .venv/bin/python planesign/"]
