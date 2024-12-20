FROM ubuntu:24.04

RUN apt update && apt -y install \
  nginx=1.24.0-2ubuntu7.1 \
  git=1:2.43.0-1ubuntu7.1 \
  openssl=3.0.13-0ubuntu3.4 \
  python3=3.12.3-0ubuntu2 \
  python3-dev=3.12.3-0ubuntu2 \
  python3-setuptools=68.1.2-2ubuntu1.1 \
  python3-pip=24.0+dfsg-1ubuntu1.1 \
  python3-numpy=1:1.26.4+ds-6ubuntu1 \
  python3-scipy=1.11.4-6build1 \
  python3-pandas=2.1.4+dfsg-7 \
  python3-lxml=5.2.1-1 \
  python3-gevent=24.2.1-0.1ubuntu2 \
  python3-pil=10.2.0-1ubuntu1 \
  python3-shapely=2.0.3-1build2 \
  python3-tz=2024.1-2 \
  llvm-14=1:14.0.6-19build4 \
  ffmpeg=7:6.1.1-3ubuntu5 \
  cython3=3.0.8-1ubuntu3 \
  file=1:5.45-3build1 \
  make=4.3-4.1build2 \
  cmake=3.28.3-1build7 \
  g++=4:13.2.0-7ubuntu1 \
  && apt clean \
  && rm -rf /var/lib/apt/lists/*

RUN git init rpi-rgb-led-matrix \
    && cd rpi-rgb-led-matrix \
    && git remote add origin https://github.com/hzeller/rpi-rgb-led-matrix.git \
    && git fetch --depth 1 origin 0ff6a6973f95d14e3206bcef1201237097fa8edd \
    && git checkout FETCH_HEAD \
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