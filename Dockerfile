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

FROM arm32v7/ubuntu:latest

RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

RUN apt-get update && apt-get install -y \
  build-essential \
  nginx \
  git \
  cmake \
  libffi-dev \
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

WORKDIR /planesign

COPY . .

RUN pip3 install -r requirements.txt

ENTRYPOINT python3 planesign/
