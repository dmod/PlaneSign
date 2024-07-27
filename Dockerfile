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
  llvm-14-dev \
  cython3 \
  file \
  musl-dev \
  libffi-dev \
  make \
  cmake \
  g++

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && make build-python && make install-python

WORKDIR /planesign

EXPOSE 80/tcp 443/tcp

COPY . .

# Nginx Setup
RUN unlink /etc/nginx/sites-enabled/default
RUN openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout /etc/ssl/private/planesign-selfsigned.key -out /etc/ssl/certs/planesign-selfsigned.crt -subj "/C=US"
COPY docker_nginx_planesign.conf /etc/nginx/conf.d/

#ENV LLVM_CONFIG=/usr/lib/llvm14/bin/llvm-config

RUN pip3 install --break-system-packages -v -r docker_requirements.txt

ENTRYPOINT /usr/sbin/nginx && python3 planesign/
