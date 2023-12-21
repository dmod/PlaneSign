# THIS IS A BIG TIME WIP

# Build:
# docker build -t planesign:latest .

# Pull:
# docker pull dmod/planesign:latest

# Lifecycle:
# docker run --privileged --rm --name planesign -p 80:80/tcp dmod/planesign:latest
# docker run --privileged --rm --name planesign -p 80:80/tcp planesign:latest
# docker kill planesign

# Tips:
# docker info
# docker image ls
# docker container ls
# docker ps --all
# docker logs planesign
# docker stats

FROM arm64v8/alpine:3.19.0

RUN apk update && apk add \
  nginx \
  git \
  python3 \
  python3-dev \
  py3-pip \
  py3-cmake-build-extension \
  py3-pkgconfig \
  make \
  cmake \
  g++ \
  openblas \
  linux-headers \
  openblas-dev \
  libffi \
  libffi-dev \
  gfortran

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && make build-python PYTHON=$(which python3) && make install-python PYTHON=$(which python3)

WORKDIR /planesign

COPY . .

RUN python3 -m venv .venv && source .venv/bin/activate && pip3 install -r requirements.txt

ENTRYPOINT python3 planesign/
