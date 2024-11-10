FROM ubuntu:24.04

RUN apt update && apt -y install \
  nginx \
  git \
  openssl \
  python3 \
  python3-dev \
  python3-setuptools \
  python3-pip \
  python3-numpy \
  python3-scipy \
  python3-pandas \
  python3-lxml \
  python3-gevent \
  python3-pillow \
  python3-shapely \
  python3-tz \
  llvm-14 \
  ffmpeg \
  cython3 \
  file \
  make \
  cmake \
  g++ \
  && apt clean \
  && rm -rf /var/lib/apt/lists/*

RUN git clone --depth=1 https://github.com/hzeller/rpi-rgb-led-matrix.git \
  && cd rpi-rgb-led-matrix \
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

RUN pip3 install --no-cache-dir --break-system-packages -v -r docker_requirements.txt

ARG BUILD_VERSION=argnotset
RUN echo ${BUILD_VERSION} > version.txt

CMD ["sh", "-c", "service nginx start && python3 planesign/"]