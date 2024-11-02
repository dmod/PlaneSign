#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import logging
import logging.handlers
import sys
import json
import subprocess
import signal
import pytz
import os
import glob
import threading
import traceback
import weather
import planes
import santa
import requests
import snowfall
import countdown
from datetime import datetime

import gevent.pywsgi

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from timezonefinder import TimezoneFinder

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array, Queue
from flask import Flask, request, jsonify
from PIL import Image, ImageDraw
from flask_cors import CORS

import utilities
import shared_config
from modes import DisplayMode

app = Flask(__name__)
CORS(app)


@app.route("/get_config")
def get_config():
    shared_config.CONF.clear()
    utilities.read_config()
    sample = {}
    sample["DATATYPES"] = []

    with open("sign.conf.sample") as f:
        lines = f.readlines()
        lastline = None
        for line in lines:
            if line == '\n':
                continue
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

        utilities.read_config()
        shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/update")
def update_sign():
    p = subprocess.run(['sh', './install_and_update.sh', ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
    logging.info("Update sign output:")
    logging.info(p.stdout)
    subprocess.run(['reboot'])
    return ""


@app.route("/status")
def get_status():
    return str(shared_config.shared_mode.value)


@app.route("/turn_on")
def turn_on():
    shared_config.shared_mode.value = shared_config.shared_prev_mode.value
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/turn_off")
def turn_off():
    shared_config.shared_prev_mode.value = shared_config.shared_mode.value
    shared_config.shared_mode.value = DisplayMode.SIGN_OFF.value
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/set_color_mode/<color>")
def set_color_mode(color):
    shared_config.shared_color_mode.value = int(color)
    shared_config.shared_forced_sign_update.value = 1
    return ""

@app.route("/set_countdown/<datetimestr>/<countdownmsg>")
def set_countdown(datetimestr,countdownmsg):
    shared_config.data_dict["countdown_datetime"] = datetime.fromisoformat(datetimestr).astimezone(shared_config.local_timezone)
    shared_config.data_dict["countdown_message"] = countdownmsg[1:].strip()
    shared_config.shared_forced_sign_update.value = 1
    return ""

@app.route("/get_possible_flights/<query_string>")
def get_possible_flights(query_string):
    return requests.get(f'https://www.flightradar24.com/v1/search/web/find?query={query_string}&limit=50').json()


@app.route("/set_track_a_flight/<flight_num>")
def set_track_a_flight(flight_num):
    shared_config.data_dict["track_a_flight_num"] = flight_num
    shared_config.shared_mode.value = DisplayMode.TRACK_A_FLIGHT.value
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route('/set_mode')
def set_mode():
    try:
        new_mode = DisplayMode[request.args.get('mode')]
        shared_config.shared_mode.value = new_mode.value
        return jsonify({"success": True, "mode": new_mode.name})
    except KeyError:
        return jsonify({
            "success": False, 
            "error": f"Invalid mode. Valid modes are: {[m.name for m in DisplayMode]}"
        }), 400


@app.route("/get_mode")
def get_mode():
    return str(shared_config.shared_mode.value)


@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    shared_config.shared_current_brightness.value = int(brightness)
    #shared_config.shared_forced_sign_update.value = 1
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
    shared_config.shared_lighting_zoomind.value = int(zi)
    return ""


@app.route("/lightning_mode/<mode>")
def set_lightning_mode(mode):
    shared_config.shared_lighting_mode.value = int(mode)
    return ""

@app.route("/mandelbrot_color/<mode>")
def set_mandelbrot_color(mode):
    shared_config.shared_mandelbrot_color.value = int(mode)
    return ""

@app.route("/set_mandelbrot_colorscale/<mode>")
def set_mandelbrot_colorscale(mode):
    shared_config.shared_mandelbrot_colorscale.value = float(mode)
    return ""

@app.route("/satellite_mode/<mode>")
def set_satellite_mode(mode):
    shared_config.shared_satellite_mode.value = int(mode)
    return ""


@app.route("/is_audio_supported")
def is_audio_supported():
    p = subprocess.run("aplay -l | grep 'USB Audio'", shell=True)
    audio_supported = p.returncode == 0
    return jsonify(audio_supported)

@app.route("/play_audio", methods=['POST'])
def play_audio():
    logging.info(f"Audio content length: {request.content_length}")
    request_data = request.get_data()

    temp_audio_file = ".data/audio"

    with open(temp_audio_file, "wb") as f:
        f.write(request_data)

    my_env = {}
    my_env["SDL_AUDIODRIVER"] = "alsa"
    my_env["AUDIODEV"] = "hw:1,0"
    subprocess.run(["/usr/bin/ffplay", temp_audio_file, "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "error"], env=my_env)
    return ""

@app.route("/play_a_sound/<sound_id>")
def play_a_sound(sound_id):
    logging.info(f"Playing sound: {sound_id}")

    my_env = {}
    my_env["SDL_AUDIODRIVER"] = "alsa"
    my_env["AUDIODEV"] = "hw:1,0"
    subprocess.Popen(["/usr/bin/ffplay", f"{shared_config.sounds_dir}/{sound_id}", "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "error"], env=my_env)
    return ""

@app.route("/get_sounds")
def get_sounds():
    return jsonify(sorted(glob.glob(f"{shared_config.sounds_dir}/*.mp3"), key=str.casefold))


def api_server():
    app_server = gevent.pywsgi.WSGIServer(('0.0.0.0', 5000), app)
    app_server.serve_forever()



class PlaneSign:
    def __init__(self, defined_mode_handlers):

        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = int(shared_config.CONF["GPIO_SLOWDOWN"])
        options.chain_length = 2
        options.limit_refresh_rate_hz = 120
        options.hardware_mapping = shared_config.CONF["PINOUT_HARDWARE_MAPPING"]
        options.drop_privileges = False

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.defined_mode_handlers = defined_mode_handlers

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

        self.last_brightness = None

        shared_config.shared_current_brightness.value = int(shared_config.CONF["DEFAULT_BRIGHTNESS"])

        self.canvas.brightness = shared_config.shared_current_brightness.value

        self.matrix.brightness = shared_config.shared_current_brightness.value

    # Call this with a positive value to stay within the loop for that specificed amount of time
    # Call this with -1 to stay in the loop forever or until shared_forced_sign_update is set
    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds

        stay_in_loop = True
        forced_breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time or seconds == -1

            self.matrix.brightness = shared_config.shared_current_brightness.value

            if shared_config.shared_forced_sign_update.value == 1:
                logging.debug("Forcing breakout")
                stay_in_loop = False
                forced_breakout = True

        shared_config.shared_forced_sign_update.value = 0
        return forced_breakout

    def sign_loop(self):

        while not shared_config.shared_shutdown_event.is_set():
            try:

                try:
                    display_mode = DisplayMode(shared_config.shared_mode.value)  # Convert int to enum
                    if display_mode in self.defined_mode_handlers:
                        logging.info(f"Setting mode to {display_mode.name}")
                        self.defined_mode_handlers[display_mode](self)
                    else:
                        logging.error(f"Mode {display_mode.name} has no handler defined...")
                except ValueError:
                    logging.error(f"Invalid mode value: {mode}. Must be one of {[m.value for m in DisplayMode]}")

            except:
                logging.exception("General error in main loop, waiting...")
                time.sleep(3)
                shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value #Reset to default mode

        logging.info("--- END OF SIGN LOOP ---")
