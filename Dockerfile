FROM arm64v8/alpine:3.19.0

RUN apk update && apk add \
  nginx \
  git \
  python3 \
  python3-dev \
  py3-pip \
  py3-numpy \
  py3-scipy \
  py3-pandas \
  llvm14 \
  llvm14-dev \
  make \
  cmake \
  g++

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && make build-python PYTHON=$(which python3) && make install-python PYTHON=$(which python3)

WORKDIR /planesign

EXPOSE 80/tcp
EXPOSE 5000/tcp

COPY . .

RUN rm /etc/nginx/http.d/default.conf

COPY docker_nginx_planesign.conf /etc/nginx/http.d/

ENV LLVM_CONFIG=/usr/lib/llvm14/bin/llvm-config

RUN pip3 install --break-system-packages -r docker_requirements.txt

ENTRYPOINT /usr/sbin/nginx && python3 planesign/
