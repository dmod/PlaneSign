# THIS IS A BIG TIME WIP

# Build:
# sudo docker build -t planesign:latest .

# Lifecycle:
# sudo docker run --privileged --rm --name planesign -p 8080:80/tcp planesign:latest
# sudo docker kill planesign

# Tips:
# sudo docker info
# sudo docker ps --all
# sudo docker logs planesign
# sudo docker stats


FROM ubuntu:20.04

RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

RUN apt-get update && apt-get install -y \
  build-essential \
  nginx \
  git \
  libxml2-dev \
  libxslt-dev \
  python3 \
  python3-venv \
  python3-pip \
  python3-dev \
  python3-pillow \
  libatlas-base-dev \
  gfortran

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && make build-python PYTHON=$(which python3) && make install-python PYTHON=$(which python3)

RUN pip3 install \
  pytz \
  flask \
  flask_cors \
  numpy \
  scipy \
  yfinance \
  favicon \
  country_converter \
  websocket-client \
  country_converter

WORKDIR /planesign

COPY . .

ENTRYPOINT ./planesign.py
