#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import logging
import logging.handlers
import sys
import subprocess
import os
import traceback
import requests
import datetime

import shared_config

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array, Queue
from flask import Flask, request
from PIL import Image, ImageDraw
from flask_cors import CORS

ALL_MODE_HANDLERS = {}

def planesign_mode_handler(mode_int):

    """
    Decorator
    """
    def handler(func):
        print(f"Mode {mode_int} will be set to: '{func.__name__}' in module '{func.__module__}'")
        ALL_MODE_HANDLERS[mode_int] = func

    return handler

# All defined mode handlers
from utilities import *
from fish import *
from finance import *
import weather
import firework
import lightning
import cgol
import cca
import custom_message
import pong
import planes
import shared_config
import satellite

app = Flask(__name__)
CORS(app)

@app.route("/get_config")
def get_config():
    shared_config.CONF.clear()
    read_config()
    sample = {}
    sample["DATATYPES"] = []

    with open("sign.conf.sample") as f:
        lines = f.readlines()
        lastline = None
        for line in lines:
            if line[0] == "#":
                lastline = line.rstrip()
                continue
            parts = line.split('=')
            sample[parts[0]] = parts[1].rstrip()
            if lastline:
                comment_parts = lastline[1:].split(' ')
                newdict = {}
                newdict["id"] = parts[0]
                newdict["type"] = comment_parts[0]
                for i in range(len(comment_parts)):
                    if comment_parts[i] == "min" and i+1 < len(comment_parts):
                        newdict["min"] = comment_parts[i+1]
                    if comment_parts[i] == "max" and i+1 < len(comment_parts):
                        newdict["max"] = comment_parts[i+1]
                sample["DATATYPES"].append(newdict)

    for key in sample.keys():
        if key in shared_config.CONF:
            sample[key] = shared_config.CONF[key]

    return json.dumps(sample)


@app.route('/write_config')
def write_config():
    if request.args:
        keys = list(request.args.keys())
        vals = list(request.args.values())
        f = open("sign.conf", "w+")
        for i in range(len(keys)):
            f.write(keys[i]+"="+vals[i]+"\n")
        f.flush()
        f.close()

        read_config()
        shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/update")
def update_sign():
    subprocess.call(['sh', './update.sh', ])
    return ""


@app.route("/status")
def get_status():
    return str(shared_config.shared_flag.value)


@app.route("/turn_on")
def turn_on():
    shared_config.shared_flag.value = 1
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/turn_off")
def turn_off():
    shared_config.shared_flag.value = 0
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/set_color_mode/<color>")
def set_color_mode(color):
    shared_config.shared_color_mode.value = int(color)
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/set_track_a_flight/<flight_num>")
def set_track_a_flight(flight_num):
    shared_config.data_dict["track_a_flight_num"] = flight_num
    shared_config.shared_mode.value = 99
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/set_mode/<mode>")
def set_mode(mode):
    shared_config.shared_mode.value = int(mode)
    if request.args:
        shared_config.arg_dict.update(request.args)
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/get_mode")
def get_mode():
    return str(shared_config.shared_mode.value)


@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    shared_config.shared_current_brightness.value = int(brightness)
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/set_pong_player_1/<spot>")
def set_pong_player1(spot):
    shared_config.shared_pong_player1.value = int(spot)
    return ""


@app.route("/set_pong_player_2/<spot>")
def set_pong_player2(spot):
    shared_config.shared_pong_player2.value = int(spot)
    return ""


@app.route("/get_brightness")
def get_brightness():
    return str(shared_config.shared_current_brightness.value)


@app.route("/set_custom_message/", defaults={"message": ""})
@app.route("/set_custom_message/<message>")
def set_custom_message(message):
    shared_config.data_dict["custom_message"] = message
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/submit_ticker/", defaults={"ticker": ""})
@app.route("/submit_ticker/<ticker>")
def submit_ticker(ticker):
    shared_config.data_dict["ticker"] = ticker
    return ""


@app.route("/lightning/<zi>")
def set_zoom(zi):
    lightning.LightningManager.zoomind.value = int(zi)
    return ""


@app.route("/lightning_mode/<mode>")
def set_lightning_mode(mode):
    lightning.LightningManager.mode.value = int(mode)
    return ""

@app.route("/satellite_mode/<mode>")
def set_satellite_mode(mode):
    shared_config.shared_satellite_mode.value = int(mode)
    return ""




def api_server():
    app.run(host='0.0.0.0')


def get_weather_data_worker(data_dict):
    while True:
        try:
            with requests.Session() as s:
                s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                response = s.get(shared_config.CONF["WEATHER_ENDPOINT"])
                data_dict["weather"] = response.json()
        except:
            logging.exception("Error getting weather data...")

        time.sleep(600)


def get_data_worker(data_dict):
    while True:
        try:
            if shared_config.shared_flag.value == 0:
                logging.info("off, skipping FR24 request...")
            else:

                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    response = s.get(shared_config.CONF["ENDPOINT"], headers={'user-agent': 'martian-law-v1.3'})
                    results = response.json()

                closest = None
                highest = None
                fastest = None
                slowest = None

                for key in results:

                    if key != "full_count" and key != "stats" and key != "version":
                        result = results[key]

                        newguy = {}
                        newguy["altitude"] = result[4]
                        newguy["speed"] = result[5]
                        newguy["flight"] = result[16] if result[16] else ""
                        newguy["typecode"] = result[8]
                        newguy["origin"] = result[11]
                        newguy["destination"] = result[12]
                        newguy["distance"] = get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (result[1], result[2]))

                        # Filter out planes on the ground
                        if newguy["altitude"] < 100:
                            continue

                        if (closest is None or (newguy["distance"] < closest["distance"] and newguy["altitude"] < float(shared_config.CONF["CLOSEST_HEIGHT_LIMIT"]))):
                            closest = newguy

                        # The rest of these are for fun, filter out the unknown planes
                        if not newguy["origin"]:
                            continue

                        if (highest is None or int(newguy["altitude"]) > int(highest["altitude"])):
                            highest = newguy

                        if (fastest is None or int(newguy["speed"]) > int(fastest["speed"])):
                            fastest = newguy

                        if (slowest is None or int(newguy["speed"]) < int(slowest["speed"])):
                            slowest = newguy

                logging.info(str(closest))

                data_dict["closest"] = closest
                data_dict["highest"] = highest
                data_dict["fastest"] = fastest
                data_dict["slowest"] = slowest

        except:
            logging.exception("Error getting FR24 data...")

        time.sleep(7)


def read_config():
    shared_config.CONF.clear()

    logging.info("reading  config...")

    with open("sign.conf") as f, open("sign.conf.sample") as s:
        lines = f.readlines()
        lines_s = s.readlines()

        temp = {}
        for line in lines:
            if line[0] == "#":
                continue
            parts = line.split('=')
            temp[parts[0]] = parts[1].rstrip()

        for line in lines_s:
            if line[0] == "#":
                continue
            parts = line.split('=')
            if parts[0] in temp.keys():
                shared_config.CONF[parts[0]] = temp[parts[0]]
            else:
                shared_config.CONF[parts[0]] = parts[1].rstrip()

    logging.info("Config loaded: " + str(shared_config.CONF))

    shared_config.CONF["ENDPOINT"] = f'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds={float(shared_config.CONF["SENSOR_LAT"]) + 2},{float(shared_config.CONF["SENSOR_LAT"]) - 2},{float(shared_config.CONF["SENSOR_LON"]) - 2},{float(shared_config.CONF["SENSOR_LON"]) + 2}'
    shared_config.CONF["WEATHER_ENDPOINT"] = f'http://api.openweathermap.org/data/2.5/onecall?lat={shared_config.CONF["SENSOR_LAT"]}&lon={shared_config.CONF["SENSOR_LON"]}&appid=1615520156f27624562ceace6e3849f3&units=imperial'

    logging.info("Plane Endpoint: " + shared_config.CONF["ENDPOINT"])
    logging.info("Weather Endpoint: " + shared_config.CONF["WEATHER_ENDPOINT"])


class PlaneSign:
    def __init__(self):

        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = 5
        options.chain_length = 2
        options.drop_privileges = False

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.font57 = graphics.Font()
        self.font46 = graphics.Font()
        self.fontbig = graphics.Font()
        self.fontreallybig = graphics.Font()
        self.fontplanesign = graphics.Font()
        self.font57.LoadFont(os.path.join(shared_config.font_dir, "5x7.bdf"))
        self.font46.LoadFont(os.path.join(shared_config.font_dir, "4x6.bdf"))
        self.fontbig.LoadFont(os.path.join(shared_config.font_dir, "6x13.bdf"))
        self.fontreallybig.LoadFont(os.path.join(shared_config.font_dir, "9x18B.bdf"))
        self.fontplanesign.LoadFont(os.path.join(shared_config.font_dir, "helvR12.bdf"))

        self.canvas.brightness = shared_config.shared_current_brightness.value

        self.last_brightness = None

        manager = Manager()
        shared_config.data_dict = manager.dict()
        shared_config.arg_dict = manager.dict()
        shared_config.CONF = manager.dict()

        read_config()
        shared_config.shared_current_brightness.value = int(shared_config.CONF["DEFAULT_BRIGHTNESS"])

        Process(target=get_data_worker, args=(shared_config.data_dict,), daemon=True).start()
        Process(target=get_weather_data_worker, args=(shared_config.data_dict,), daemon=True).start()
        Process(target=api_server, daemon=True).start()

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds

        stay_in_loop = True
        forced_breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time

            self.matrix.brightness = shared_config.shared_current_brightness.value

            if shared_config.shared_forced_sign_update.value == 1:
                logging.debug("Forcing breakout")
                stay_in_loop = False
                forced_breakout = True

        shared_config.shared_forced_sign_update.value = 0
        return forced_breakout

    def show_time(self):
        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            print_time = datetime.now().strftime('%-H:%M')
        else:
            print_time = datetime.now().strftime('%-I:%M%p')

        if "weather" in shared_config.data_dict and shared_config.data_dict["weather"] and shared_config.data_dict["weather"]["current"] and shared_config.data_dict["weather"]["current"]["temp"]:
            temp = str(round(shared_config.data_dict["weather"]["current"]["temp"]))
        else:
            temp = "--"

        self.canvas.Clear()

        graphics.DrawText(self.canvas, self.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
        graphics.DrawText(self.canvas, self.fontreallybig, 86, 21, graphics.Color(20, 20, 240), temp + "°F")

        self.matrix.SwapOnVSync(self.canvas)


    @planesign_mode_handler(9)
    def welcome(self):

        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontplanesign, 34, 20, graphics.Color(46, 210, 255), "Plane Sign")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        self.canvas.Clear()
        shared_config.shared_mode.value = 1

    def sign_loop(self):

        while True:
            try:

                mode = shared_config.shared_mode.value

                forced_breakout = False

                logging.info(f"Top of loop. Current mode is: {mode}")

                # Sign is off, clear canvas and wait
                if shared_config.shared_flag.value == 0:
                    self.canvas.Clear()
                    self.matrix.SwapOnVSync(self.canvas)
                    self.wait_loop(0.5)
                    continue

                if not shared_config.data_dict or "closest" not in shared_config.data_dict:
                    logging.info("No plane data found, waiting...")
                    self.wait_loop(3)
                    continue

                if mode in ALL_MODE_HANDLERS:
                    ALL_MODE_HANDLERS[mode](self)
                else:
                    logging.error(f"Mode currently set to {mode} but no handler exists...")

                if mode == 7:
                    self.show_time()
                    self.wait_loop(0.5)
                    continue

                if forced_breakout:
                    continue

                # Wait before doing anything
                self.wait_loop(1)
            except:
                logging.exception("General error in main loop, waiting...")
                time.sleep(3)
                shared_config.shared_mode.value = 1


# Main function
if __name__ == "__main__":
    configure_logging()
    read_static_airport_data()

    PlaneSign().sign_loop()
