# THIS IS A BIG TIME WIP
# sudo docker build -t planesign:latest /home/pi/PlaneSign/
# sudo docker run --privileged planesign:latest

FROM ubuntu:20.04

RUN echo 'debconf debconf/frontend select Noninteractive' | debconf-set-selections

RUN apt-get update && apt-get install -y --no-install-recommends git build-essential nginx libxml2-dev libxslt-dev python3-venv python3-pip python3-dev python3-pillow libatlas-base-dev gfortran

RUN git clone https://github.com/hzeller/rpi-rgb-led-matrix.git && cd rpi-rgb-led-matrix && make build-python PYTHON=$(which python3) && make install-python PYTHON=$(which python3)

RUN pip3 install pytz flask flask_cors numpy scipy yfinance favicon websocket-client country_converter

ENTRYPOINT rpi-rgb-led-matrix/examples-api-use/demo --led-slowdown-gpio=4 --led-cols=64 --led-chain=2 -D4