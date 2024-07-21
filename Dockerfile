FROM alpine:3.19.0

RUN apk update && apk add \
  nginx \
  git \
  openssl \
  python3 \
  python3-dev \
  py3-pip \
  py3-numpy \
  py3-scipy \
  py3-pandas \
  py3-lxml \
  py3-gevent \
  py3-pillow \
  py3-tz \
  gdal \
  gdal-dev \
  proj \
  proj-util \
  ffplay \
  zlib \
  zlib-dev \
  llvm14 \
  llvm14-dev \
  file \
  musl-dev \
  libffi-dev \
  make \
  cmake \
  g++

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && git reset --hard 87a9caba561bf94ac15f6fe7e492ed7bcbcb58a2 && make build-python PYTHON=$(which python3) && make install-python PYTHON=$(which python3)

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

COPY . .

# Nginx Setup
RUN rm /etc/nginx/http.d/default.conf
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"
COPY docker_nginx_planesign.conf /etc/nginx/http.d/

ENV LLVM_CONFIG=/usr/lib/llvm14/bin/llvm-config

RUN pip3 install --break-system-packages -v -r docker_requirements.txt

ENTRYPOINT /usr/sbin/nginx && python3 planesign/
