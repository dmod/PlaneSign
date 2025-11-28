FROM ubuntu:24.04

RUN apt update && apt -y install \
  nginx \
  git \
  openssl \
  llvm-14 \
  ffmpeg \
  alsa-utils \
  cython3 \
  python3-setuptools \
  file \
  make \
  cmake \
  g++ \
  && apt clean \
  && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git \
  && cd rpi-rgb-led-matrix \
  && git checkout 9fbdeea555239daa19d2226f836b790387c0f2e6 \
  && make build-python \
  && make install-python

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

COPY . .

# Nginx Setup
RUN unlink /etc/nginx/sites-enabled/default
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"

# Define build argument with default value
ARG PLANESIGN_ROOT=/planesign

# Copy and substitute nginx config using the build arg directly
COPY docker_nginx_planesign.conf /etc/nginx/conf.d/
RUN sed -i "s|\${PLANESIGN_ROOT}|${PLANESIGN_ROOT}|g" /etc/nginx/conf.d/docker_nginx_planesign.conf

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN uv sync

ARG BUILD_VERSION=argnotset
RUN echo ${BUILD_VERSION} > version.txt

CMD ["sh", "-c", "service nginx start && uv run planesign/"]