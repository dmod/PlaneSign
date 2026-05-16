#!/usr/bin/python3
# -*- coding: utf-8 -*-

import json
import logging
import os
import glob
import subprocess
import re
import requests
from datetime import datetime

import gevent.pywsgi

from flask import Flask, request, jsonify, send_from_directory
from PIL import Image
from flask_cors import CORS

import utilities
import shared_config
from modes import DisplayMode
from finance import get_tickers
from snow import populate_resort_lists, load_user_list, save_current_resort, delete_user_resort, SnowMode

SKETCHES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sketches")
FREE_SKETCH_BRUSH_SIZES = {1, 2, 3, 4}

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
    try:
        keys = list(request.args.keys())
        vals = list(request.args.values())

        with open("sign.conf", "w", encoding="utf-8") as f:
            for i in range(len(keys)):
                f.write(keys[i] + "=" + vals[i] + "\n")
            f.flush()
            os.fsync(f.fileno())

        utilities.read_config()
        shared_config.shared_forced_sign_update.value = 1
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("Failed to write sign.conf")
        return jsonify({"ok": False, "error": str(e)}), 500


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
    shared_config.data_dict["countdown_datetime"] = datetime.fromisoformat(datetimestr)
    shared_config.data_dict["countdown_message"] = countdownmsg[1:].strip()
    shared_config.shared_forced_sign_update.value = 1
    return ""

@app.route("/get_possible_flights/<query_string>")
def get_possible_flights(query_string):
    query_result = requests.get(f'https://www.flightradar24.com/v1/search/web/find?query={query_string}&limit=50', headers = {'User-Agent': ''})
    return query_result.json()

@app.route("/set_track_a_flight/<flight_num>")
def set_track_a_flight(flight_num):
    shared_config.data_dict["track_a_flight_num"] = flight_num
    shared_config.shared_mode.value = DisplayMode.TRACK_A_FLIGHT.value
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/free_sketch/pixel", methods=["POST"])
def set_free_sketch_pixel():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Expected JSON object"}), 400

    try:
        x = int(data["x"])
        y = int(data["y"])
        r = int(data["r"])
        g = int(data["g"])
        b = int(data["b"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Expected integer x, y, r, g, b"}), 400

    try:
        brush_size = int(data.get("brush_size", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Brush size must be 1, 2, 3, or 4"}), 400

    if not 0 <= x < 128 or not 0 <= y < 32:
        return jsonify({"ok": False, "error": "Coordinates must be in range x=0-127, y=0-31"}), 400
    if not 0 <= r <= 255 or not 0 <= g <= 255 or not 0 <= b <= 255:
        return jsonify({"ok": False, "error": "RGB values must be in range 0-255"}), 400
    if brush_size not in FREE_SKETCH_BRUSH_SIZES:
        return jsonify({"ok": False, "error": "Brush size must be 1, 2, 3, or 4"}), 400

    color = bytes((r, g, b))
    pixel_buffer = shared_config.free_sketch_pixels.get_obj()
    with shared_config.free_sketch_pixels.get_lock():
        utilities.paint_brush(pixel_buffer, x, y, brush_size, color)

    return jsonify({"ok": True})


@app.route("/free_sketch/line", methods=["POST"])
def set_free_sketch_line():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"ok": False, "error": "Expected JSON object"}), 400

    try:
        x0 = int(data["x0"])
        y0 = int(data["y0"])
        x1 = int(data["x1"])
        y1 = int(data["y1"])
        r = int(data["r"])
        g = int(data["g"])
        b = int(data["b"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "Expected integer x0, y0, x1, y1, r, g, b"}), 400

    try:
        brush_size = int(data.get("brush_size", 1))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Brush size must be 1, 2, 3, or 4"}), 400

    if not 0 <= x0 < 128 or not 0 <= y0 < 32 or not 0 <= x1 < 128 or not 0 <= y1 < 32:
        return jsonify({"ok": False, "error": "Coordinates must be in range x=0-127, y=0-31"}), 400
    if not 0 <= r <= 255 or not 0 <= g <= 255 or not 0 <= b <= 255:
        return jsonify({"ok": False, "error": "RGB values must be in range 0-255"}), 400
    if brush_size not in FREE_SKETCH_BRUSH_SIZES:
        return jsonify({"ok": False, "error": "Brush size must be 1, 2, 3, or 4"}), 400

    color = bytes((r, g, b))
    pixel_buffer = shared_config.free_sketch_pixels.get_obj()
    with shared_config.free_sketch_pixels.get_lock():
        for px, py in utilities.bresenham_line(x0, y0, x1, y1):
            utilities.paint_brush(pixel_buffer, px, py, brush_size, color)

    return jsonify({"ok": True})


@app.route("/free_sketch/clear", methods=["POST"])
def clear_free_sketch():
    pixel_buffer = shared_config.free_sketch_pixels.get_obj()
    with shared_config.free_sketch_pixels.get_lock():
        pixel_buffer[:] = b"\x00" * len(pixel_buffer)
    return jsonify({"ok": True})


@app.route("/free_sketch/save", methods=["POST"])
def save_free_sketch():
    os.makedirs(SKETCHES_DIR, exist_ok=True)
    pixel_buffer = shared_config.free_sketch_pixels.get_obj()
    with shared_config.free_sketch_pixels.get_lock():
        pixels = bytes(pixel_buffer)
    img = Image.frombytes("RGB", (128, 32), pixels)
    filename = "sketch_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
    img.save(os.path.join(SKETCHES_DIR, filename))
    return jsonify({"ok": True, "filename": filename})


@app.route("/free_sketch/list")
def list_free_sketches():
    os.makedirs(SKETCHES_DIR, exist_ok=True)
    files = sorted(glob.glob(os.path.join(SKETCHES_DIR, "*.png")), reverse=True)
    sketches = []
    for f in files:
        name = os.path.basename(f)
        sketches.append({"filename": name, "url": "/api/free_sketch/image/" + name})
    return jsonify({"ok": True, "sketches": sketches})


@app.route("/free_sketch/load/<filename>", methods=["POST"])
def load_free_sketch(filename):
    if not utilities.validate_sketch_filename(filename):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400
    filepath = os.path.join(SKETCHES_DIR, filename)
    if not os.path.isfile(filepath):
        return jsonify({"ok": False, "error": "Sketch not found"}), 404
    img = Image.open(filepath).convert("RGB")
    if img.size != (128, 32):
        return jsonify({"ok": False, "error": "Invalid sketch dimensions"}), 400
    pixels = img.tobytes()
    pixel_buffer = shared_config.free_sketch_pixels.get_obj()
    with shared_config.free_sketch_pixels.get_lock():
        pixel_buffer[:] = pixels
    return jsonify({"ok": True})


@app.route("/free_sketch/delete/<filename>", methods=["POST"])
def delete_free_sketch(filename):
    if not utilities.validate_sketch_filename(filename):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400
    filepath = os.path.join(SKETCHES_DIR, filename)
    if not os.path.isfile(filepath):
        return jsonify({"ok": False, "error": "Sketch not found"}), 404
    os.remove(filepath)
    return jsonify({"ok": True})


@app.route("/free_sketch/image/<filename>")
def serve_free_sketch_image(filename):
    if not utilities.validate_sketch_filename(filename):
        return jsonify({"ok": False, "error": "Invalid filename"}), 400
    return send_from_directory(SKETCHES_DIR, filename, mimetype="image/png")


@app.route('/set_mode/<mode>')
def set_mode(mode):
    shared_config.shared_mode.value = DisplayMode[mode].value
    if request.args:
        shared_config.arg_dict.update(request.args)
    shared_config.shared_forced_sign_update.value = 1
    return ""


@app.route("/get_mode")
def get_mode():
    return DisplayMode(shared_config.shared_mode.value).name


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

@app.route("/get_resort_opts")
def get_resort_opts():
    populate_resort_lists()
    return jsonify(shared_config.data_dict["resort_info"])

@app.route("/snow_mode/<mode>")
def set_snow_mode(mode):
    shared_config.shared_snow_mode.value = int(mode)
    return ""

@app.route("/display_resort/", defaults={"uuid": ""})
@app.route("/display_resort/<uuid>")
def display_resort(uuid):
    if (uuid != ""):
        shared_config.data_dict["displayed_resort"] = uuid
        shared_config.shared_snow_mode.value = SnowMode.STATIC.value
    return ""

@app.route("/save_current_resort")
def save_resort():
    save_current_resort()
    return ""

@app.route("/delete_saved_resort/", defaults={"uuid": ""})
@app.route("/delete_saved_resort/<uuid>")
def delete_resort(uuid):
    if (uuid != ""):
        delete_user_resort(uuid)
    return ""
    
@app.route("/get_saved_resorts")
def get_resorts():
    load_user_list()
    if "user_resorts" in shared_config.data_dict:
        data = shared_config.data_dict["user_resorts"]
    else:
        data = ""
    return '\n'.join(data)

@app.route("/get_ticker_opts")
def get_ticker_opts():
    options = get_tickers()
    return jsonify(options)

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

@app.route("/play_mic_audio", methods=['POST'])
def play_mic_audio():
    logging.info(f"Mic audio content length: {request.content_length}")
    request_data = request.get_data()

    temp_audio_file = ".data/audio"

    with open(temp_audio_file, "wb") as f:
        f.write(request_data)

    my_env = {}
    my_env["SDL_AUDIODRIVER"] = "alsa"
    my_env["AUDIODEV"] = shared_config.audio_device
    subprocess.run(["/usr/bin/ffplay", temp_audio_file, "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "error"], env=my_env)
    return ""

@app.route("/play_a_sound/<sound_id>")
def play_a_sound(sound_id):
    logging.info(f"Playing sound: {sound_id}")

    my_env = {}
    my_env["SDL_AUDIODRIVER"] = "alsa"
    my_env["AUDIODEV"] = shared_config.audio_device
    subprocess.Popen(["/usr/bin/ffplay", f"{shared_config.sounds_dir}/{sound_id}", "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "error"], env=my_env)
    return ""

@app.route("/get_sounds")
def get_sounds():
    return jsonify(sorted(glob.glob(f"{shared_config.sounds_dir}/*.mp3"), key=str.casefold))

@app.route("/version")
def get_version():
    return utilities.get_version()

@app.route("/device_info")
def get_device_info():
    import shutil
    import socket
    info = {}

    # Hostname
    info["hostname"] = socket.gethostname()

    # IP address
    try:
        result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
        addrs = result.stdout.strip().split()
        info["ip_address"] = addrs[0] if addrs else "N/A"
    except Exception:
        info["ip_address"] = "N/A"

    # CPU temperature
    try:
        with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
            temp_millideg = int(f.read().strip())
            temp_c = temp_millideg / 1000.0
            info["cpu_temp_c"] = round(temp_c, 1)
    except Exception:
        info["cpu_temp_c"] = None

    # Disk usage
    try:
        total, used, free = shutil.disk_usage("/")
        info["disk_total_gb"] = round(total / (1024 ** 3), 1)
        info["disk_used_gb"] = round(used / (1024 ** 3), 1)
        info["disk_free_gb"] = round(free / (1024 ** 3), 1)
        info["disk_usage_percent"] = round(used / total * 100, 1)
    except Exception:
        info["disk_total_gb"] = None
        info["disk_used_gb"] = None
        info["disk_free_gb"] = None
        info["disk_usage_percent"] = None

    # Uptime
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.read().split()[0])
            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)
            info["uptime"] = f"{days}d {hours}h {minutes}m"
    except Exception:
        info["uptime"] = "N/A"

    # Memory usage
    try:
        with open("/proc/meminfo", "r") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
            total_mb = meminfo["MemTotal"] / 1024
            available_mb = meminfo["MemAvailable"] / 1024
            used_mb = total_mb - available_mb
            info["mem_total_mb"] = round(total_mb, 0)
            info["mem_used_mb"] = round(used_mb, 0)
            info["mem_usage_percent"] = round(used_mb / total_mb * 100, 1)
    except Exception:
        info["mem_total_mb"] = None
        info["mem_used_mb"] = None
        info["mem_usage_percent"] = None

    return jsonify(info)

def api_server():
    app_server = gevent.pywsgi.WSGIServer(('0.0.0.0', 5000), app)
    app_server.serve_forever()
