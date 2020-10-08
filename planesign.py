#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import traceback
import requests
from datetime import datetime
from utilities import *
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value
from flask import Flask, request
from flask_cors import CORS

# <Config>
DEFAULT_BRIGHTNESS = 100
SENSOR_LOC = { "lat":39.288, "lon": -76.841 }
ALTITUDE_IGNORE_LIMIT = 100 # Ignore returns below this altitude in feet
ALERT_RADIUS = 3 # Will alert in miles
ENDPOINT = 'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds=40.1,38.1,-78.90,-75.10'
WEATHER_ENDPOINT = 'https://api.weather.gov/gridpoints/LWX/111,80/forecast/hourly'
# </Config>

code_to_airport = {}

app = Flask(__name__)
CORS(app)

shared_flag_global = None
shared_current_brightness = 100
shared_current_sign_mode = 1

@app.route("/status")
def get_status():
    return str(shared_flag_global.value)

@app.route("/turn_on")
def turn_on():
    shared_flag_global.value = 1
    return ""

@app.route("/turn_off")
def turn_off():
    shared_flag_global.value = 0
    return ""

@app.route("/set_mode/<mode>")
def set_mode(mode):
    shared_current_sign_mode.value = int(mode)
    return ""

@app.route("/get_mode")
def get_mode():
    return str(shared_current_sign_mode.value)

@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    shared_current_brightness.value = int(brightness)
    return ""

@app.route("/get_brightness")
def get_brightness():
    return str(shared_current_brightness.value)

def server(shared_flag, shared_brightness, shared_mode):
    global shared_flag_global
    shared_flag_global = shared_flag

    global shared_current_brightness
    shared_current_brightness = shared_brightness

    global shared_current_sign_mode
    shared_current_sign_mode = shared_mode

    app.run(host='0.0.0.0')

def get_data_worker(d, shared_flag):
    while True:
        try:
            if shared_flag.value is 0:
                print("off, skipping request...")
            else:
                closest = get_data()
                d["closest"] = closest
        except:
            print("FR24: HEY MAN BAD THING HAPPENED")
            traceback.print_exc()
        time.sleep(7.5)

def get_weather_temp():
    try:
        weather_result = requests.get(WEATHER_ENDPOINT).json()
        return str(weather_result["properties"]["periods"][0]["temperature"])
    except:
        print("WEATHER ERROR")
        traceback.print_exc()
        return ":("

def get_data():
    current_temp = get_weather_temp()
    print("The current temp is: " + str(current_temp))

    r = requests.get(ENDPOINT, headers={'user-agent': 'my-app/1.0.0'})

    if r.status_code is not 200:
        print("FR REQUEST WAS BAD")
        print("STATUS CODE: " + str(r.status_code))

    results = r.json()

    closest = None

    for key in results:

        if key != "full_count" and key != "stats" and key != "version":
            result = results[key]

            newguy = {}
            newguy["altitude"] = result[4]
            newguy["speed"] = result[5]
            newguy["flight"] = result[16] if result[16] else "UNK69"
            newguy["typecode"] = result[8]
            newguy["origin"] = result[11] if result[11] else "???"
            newguy["destination"] = result[12] if result[12] else "???"
            newguy["distance"] = get_distance((SENSOR_LOC["lat"], SENSOR_LOC["lon"]), (result[1], result[2]))

            if (newguy["altitude"] > ALTITUDE_IGNORE_LIMIT and (closest is None or int(newguy["distance"]) < int(closest["distance"]))):
                closest = newguy

    print(str(closest))
    return closest

def read_airport_data():
    with open("airports.csv") as f:
        lines = f.readlines()
        for line in lines[1:]:
            parts = line.split(',')
            name = parts[3].strip("\"")
            code = parts[13].strip("\"")
            code_to_airport[code] = name

    print(str(len(code_to_airport)) + " airports added.")

class PlaneSign:
    def __init__(self):

        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = 2
        options.chain_length = 2

        self.matrix = RGBMatrix(options = options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.font57 = graphics.Font()
        self.font46 = graphics.Font()
        self.fontbig = graphics.Font()
        self.fontreallybig = graphics.Font()
        self.font57.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/5x7.bdf")
        self.font46.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/4x6.bdf")
        self.fontbig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/6x13.bdf")
        self.fontreallybig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/9x18B.bdf")

        manager = Manager()

        self.closest = manager.dict()

        self.shared_flag = Value('i', 1)
        global shared_current_brightness
        shared_current_brightness = Value('i', DEFAULT_BRIGHTNESS)

        get_data_proc = Process(target=get_data_worker, args=(self.closest,self.shared_flag, ))
        get_data_proc.start()

        self.shared_mode = Value('i', 1)

        pServer = Process(target=server, args=(self.shared_flag,shared_current_brightness,self.shared_mode,))
        pServer.start()

        self.canvas.brightness = shared_current_brightness.value

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds
        while time.perf_counter() < exit_loop_time:
            if self.shared_flag.value is 0:
                self.canvas.Clear()
                self.matrix.SwapOnVSync(self.canvas)
                while self.shared_flag.value is 0:
                    pass
                return

            self.canvas.brightness = shared_current_brightness.value
            self.matrix.SwapOnVSync(self.canvas)

    def welcome(self):
        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontbig, 4, 12, graphics.Color(140, 140, 140), "Welcome")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        graphics.DrawText(self.canvas, self.fontbig, 4, 26, graphics.Color(140, 140, 140), "to")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        graphics.DrawText(self.canvas, self.fontbig, 66, 10, graphics.Color(200, 10, 10), "The")
        graphics.DrawText(self.canvas, self.fontbig, 66, 21, graphics.Color(200, 10, 10), "Sterners's")
        graphics.DrawText(self.canvas, self.fontbig, 66, 32, graphics.Color(200, 10, 10), "Home")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)

    def sign_loop(self):

        prev_thing = {}
        prev_thing["distance"] = 0
        prev_thing["altitude"] = 0
        prev_thing["speed"] = 0
        prev_thing["flight"] = None

        self.welcome()

        while True:
            mode = self.shared_mode.value

            if self.shared_flag.value is 0:
                self.canvas.Clear()
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(0.5)
                continue

            if not self.closest:
                print("no data found, waiting...")
                self.wait_loop(3)
                continue

            closest = self.closest["closest"]

            if mode == 4:
                self.welcome()
                self.shared_mode.value = 1

            if closest and (mode == 2 or (mode != 3 and closest["distance"] <= ALERT_RADIUS)):

                interpol_distance = interpolate(prev_thing["distance"], closest["distance"])
                interpol_alt = interpolate(prev_thing["altitude"], closest["altitude"])
                interpol_speed = interpolate(prev_thing["speed"], closest["speed"])

                code_to_resolve = closest["origin"] if closest["origin"] != "BWI" else closest["destination"] if closest["destination"] != "BWI" else ""

                friendly_name = code_to_airport.get(str(code_to_resolve), "")

                for i in range(NUM_STEPS):
                    self.canvas.Clear()
                    graphics.DrawText(self.canvas, self.fontreallybig, 1, 12, graphics.Color(20, 200, 20), closest["origin"] + "->" + closest["destination"])
                    graphics.DrawText(self.canvas, self.font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
                    graphics.DrawText(self.canvas, self.font57, 37, 30, graphics.Color(0, 0, 255), closest["flight"])
                    graphics.DrawText(self.canvas, self.font57, 2, 30, graphics.Color(245, 245, 245), closest["typecode"])

                    graphics.DrawText(self.canvas, self.font57, 79, 8, graphics.Color(255, 165, 0), "Dst: {0:.1f}".format(interpol_distance[i]))
                    graphics.DrawText(self.canvas, self.font57, 79, 19, graphics.Color(255, 255, 0), "Alt: {0:.0f}".format(interpol_alt[i]))
                    graphics.DrawText(self.canvas, self.font57, 79, 30, graphics.Color(255, 0, 255), "Vel: {0:.0f}".format(interpol_speed[i]))

                    self.wait_loop(0.065)
                    self.matrix.SwapOnVSync(self.canvas)

                prev_thing = closest
            else:
                # NOT ALERT RADIUS
                prev_thing = {}
                prev_thing["distance"] = 0
                prev_thing["altitude"] = 0
                prev_thing["speed"] = 0

                cur_temp = get_weather_temp()

                print_time = datetime.now().strftime('%I:%M%p')

                self.canvas.Clear()

                graphics.DrawText(self.canvas, self.fontreallybig, 6, 21, graphics.Color(0, 150, 0), print_time)
                graphics.DrawText(self.canvas, self.fontreallybig, 84, 21, graphics.Color(20, 20, 240), cur_temp + "°F")
                
                self.matrix.SwapOnVSync(self.canvas)

            # Wait before doing anything
            self.wait_loop(0.1)

# Main function
if __name__ == "__main__":
    read_airport_data()
    PlaneSign().sign_loop()
