#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import traceback
import requests
from datetime import datetime
from utilities import *
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value
from flask import Flask
from PIL import Image
from flask_cors import CORS

# <Config>
DEFAULT_BRIGHTNESS = 80
SENSOR_LOC = { "lat":39.288, "lon": -76.841 }
ALTITUDE_IGNORE_LIMIT = 100 # Ignore returns below this altitude in feet
ALERT_RADIUS = 3 # Will alert in miles
ENDPOINT = 'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds=40.1,38.1,-78.90,-75.10'
WEATHER_ENDPOINT = f'http://api.openweathermap.org/data/2.5/onecall?lat={SENSOR_LOC["lat"]}&lon={SENSOR_LOC["lon"]}&appid=1615520156f27624562ceace6e3849f3&units=imperial'
# </Config>

print("Using: " + WEATHER_ENDPOINT)

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

def get_weather_data_worker(d):
    while True:
        try:
            d["weather"] = requests.get(WEATHER_ENDPOINT).json()
        except:
            print("Error getting weather data...")
            traceback.print_exc()

        time.sleep(600)

def get_data_worker(d, shared_flag):
    while True:
        try:
            if shared_flag.value is 0:
                print("off, skipping FR24 request...")
            else:

                r = requests.get(ENDPOINT, headers={'user-agent': 'your-app/1.4.2'})

                if r.status_code is not 200:
                    print("FR REQUEST WAS BAD")
                    print("STATUS CODE: " + str(r.status_code))

                results = r.json()

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
                        newguy["flight"] = result[16] if result[16] else "UNK69"
                        newguy["typecode"] = result[8]
                        newguy["origin"] = result[11] if result[11] else "???"
                        newguy["destination"] = result[12] if result[12] else "???"
                        newguy["distance"] = get_distance((SENSOR_LOC["lat"], SENSOR_LOC["lon"]), (result[1], result[2]))

                        if newguy["altitude"] < ALTITUDE_IGNORE_LIMIT:
                            continue

                        if (closest is None or int(newguy["distance"]) < int(closest["distance"])):
                            closest = newguy

                        # The rest of these are for fun, filter out ??? planes
                        if newguy["origin"] == "???":
                            continue

                        if (highest is None or int(newguy["altitude"]) > int(highest["altitude"])):
                            highest = newguy

                        if (fastest is None or int(newguy["speed"]) > int(fastest["speed"])):
                            fastest = newguy

                        if (slowest is None or int(newguy["speed"]) < int(slowest["speed"])):
                            slowest = newguy

                print(str(closest))

                d["closest"] = closest
                d["highest"] = highest
                d["fastest"] = fastest
                d["slowest"] = slowest

        except:
            print("Error getting FR24 data...")
            traceback.print_exc()

        time.sleep(7)

def read_static_airport_data():
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
        options.limit_refresh_rate_hz = 160

        self.matrix = RGBMatrix(options = options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.font57 = graphics.Font()
        self.font46 = graphics.Font()
        self.fontbig = graphics.Font()
        self.fontreallybig = graphics.Font()
        self.fontplanesign = graphics.Font()
        self.font57.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/5x7.bdf")
        self.font46.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/4x6.bdf")
        self.fontbig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/6x13.bdf")
        self.fontreallybig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/9x18B.bdf")
        self.fontplanesign.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/helvR12.bdf")

        manager = Manager()

        self.shared_data = manager.dict()

        self.shared_flag = Value('i', 1)
        global shared_current_brightness
        shared_current_brightness = Value('i', DEFAULT_BRIGHTNESS)

        get_data_proc = Process(target=get_data_worker, args=(self.shared_data,self.shared_flag))
        get_data_proc.start()

        get_weather_data_proc = Process(target=get_weather_data_worker, args=(self.shared_data,))
        get_weather_data_proc.start()

        self.shared_mode = Value('i', 1)

        pServer = Process(target=server, args=(self.shared_flag,shared_current_brightness,self.shared_mode,))
        pServer.start()

        self.canvas.brightness = shared_current_brightness.value

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds
        original_mode = self.shared_mode.value

        stay_in_loop = True
        breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time

            self.canvas.brightness = shared_current_brightness.value
            self.matrix.brightness = shared_current_brightness.value
            self.matrix.SwapOnVSync(self.canvas)

            if self.shared_flag.value is 0:
                self.canvas.Clear()
                self.matrix.SwapOnVSync(self.canvas)
                stay_in_loop = False

            if self.shared_mode.value != original_mode:
                stay_in_loop = False
                breakout = True

        return breakout

    def show_time(self):
        print_time = datetime.now().strftime('%-I:%M%p')
        temp = str(round(self.shared_data["weather"]["current"]["temp"]))

        self.canvas.Clear()

        graphics.DrawText(self.canvas, self.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
        graphics.DrawText(self.canvas, self.fontreallybig, 86, 21, graphics.Color(20, 20, 240), temp + "°F")
        
        self.matrix.SwapOnVSync(self.canvas)

    def show_weather(self):
        self.canvas = self.matrix.CreateFrameCanvas()

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        image = Image.open(f"/home/pi/PlaneSign/icons/{self.shared_data['weather']['daily'][0]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_0_xoffset + 15, 5)

        image = Image.open(f"/home/pi/PlaneSign/icons/{self.shared_data['weather']['daily'][1]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_1_xoffset + 15, 5)

        image = Image.open(f"/home/pi/PlaneSign/icons/{self.shared_data['weather']['daily'][2]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_2_xoffset + 15, 5)

        graphics.DrawText(self.canvas, self.font46, 0, 5, graphics.Color(20, 20, 210), "Ellicott City")

        for x in range(52):
            self.canvas.SetPixel(x, 6, 140, 140, 140)

        for y in range(7):
            self.canvas.SetPixel(52, y, 140, 140, 140)

        graphics.DrawText(self.canvas, self.font57, 66, 6, graphics.Color(210, 190, 0), convert_unix_to_local_time(self.shared_data['weather']['current']['sunrise']).strftime('%-I:%M'))
        graphics.DrawText(self.canvas, self.font57, 97, 6, graphics.Color(255, 158, 31), convert_unix_to_local_time(self.shared_data['weather']['current']['sunset']).strftime('%-I:%M'))

        daily = self.shared_data['weather']['daily']

        # Day 0
        day = daily[0]
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(self.canvas, self.font46, day_0_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 1 
        day = daily[1]
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(self.canvas, self.font46, day_1_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 2 
        day = daily[2]
        graphics.DrawText(self.canvas, self.font57, day_2_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(self.canvas, self.font57, day_2_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(self.canvas, self.font57, day_2_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(self.canvas, self.font46, day_2_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        self.matrix.SwapOnVSync(self.canvas)

    def welcome(self):
        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontplanesign, 34, 20, graphics.Color(46, 210, 255), "Plane Sign")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontbig, 4, 12, graphics.Color(140, 140, 140), "Welcome")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        graphics.DrawText(self.canvas, self.fontbig, 4, 26, graphics.Color(140, 140, 140), "to")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        graphics.DrawText(self.canvas, self.fontbig, 66, 10, graphics.Color(60, 60, 160), "The")
        graphics.DrawText(self.canvas, self.fontbig, 66, 21, graphics.Color(160, 160, 200), "Sterners's")
        graphics.DrawText(self.canvas, self.fontbig, 66, 32, graphics.Color(20, 160, 60), "Home")
        self.matrix.SwapOnVSync(self.canvas)
        self.shared_mode.value = 1
        self.wait_loop(3)

    def sign_loop(self):

        prev_thing = {}
        prev_thing["distance"] = 0
        prev_thing["altitude"] = 0
        prev_thing["speed"] = 0
        prev_thing["flight"] = None

        self.welcome()

        while True:
            mode = self.shared_mode.value
            breakout = False

            if self.shared_flag.value is 0:
                self.canvas.Clear()
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(0.5)
                continue

            if not self.shared_data:
                print("no data found, waiting...")
                self.wait_loop(3)
                continue

            # 1 = default
            # 2 = always alert closest
            # 3 = always alert highest
            # 4 = always alert fastest
            # 5 = always alert slowest
            # 6 = weather
            # 7 = clock
            # 8 = welcome

            if mode == 6:
                self.show_weather()
                self.wait_loop(0.5)
                continue

            if mode == 7:
                self.show_time()
                self.wait_loop(0.5)
                continue

            if mode == 8:
                self.welcome()

            plane_to_show = None

            if mode == 1:
                if self.shared_data["closest"]["distance"] <= ALERT_RADIUS:
                    plane_to_show = self.shared_data["closest"]

            if mode == 2:
                plane_to_show = self.shared_data["closest"]

            if mode == 3:
                plane_to_show = self.shared_data["highest"]

            if mode == 4:
                plane_to_show = self.shared_data["fastest"]

            if mode == 5:
                plane_to_show = self.shared_data["slowest"]

            if plane_to_show:
                interpol_distance = interpolate(prev_thing["distance"], plane_to_show["distance"])
                interpol_alt = interpolate(prev_thing["altitude"], plane_to_show["altitude"])
                interpol_speed = interpolate(prev_thing["speed"], plane_to_show["speed"])

                code_to_resolve = plane_to_show["origin"] if plane_to_show["origin"] != "BWI" else plane_to_show["destination"] if plane_to_show["destination"] != "BWI" else ""

                friendly_name = code_to_airport.get(str(code_to_resolve), "")

                # Front pad the flight number to a max of 7 for spacing
                formatted_flight = plane_to_show["flight"].rjust(7, ' ')

                for i in range(NUM_STEPS):
                    self.canvas.Clear()
                    graphics.DrawText(self.canvas, self.fontreallybig, 1, 12, graphics.Color(20, 200, 20), plane_to_show["origin"] + "->" + plane_to_show["destination"])
                    graphics.DrawText(self.canvas, self.font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
                    graphics.DrawText(self.canvas, self.font57, 37, 30, graphics.Color(0, 0, 200), formatted_flight)
                    graphics.DrawText(self.canvas, self.font57, 2, 30, graphics.Color(180, 180, 180), plane_to_show["typecode"])

                    graphics.DrawText(self.canvas, self.font57, 79, 8, graphics.Color(60, 60, 160), "Dst: {0:.1f}".format(interpol_distance[i]))
                    graphics.DrawText(self.canvas, self.font57, 79, 19, graphics.Color(160, 160, 200), "Alt: {0:.0f}".format(interpol_alt[i]))
                    graphics.DrawText(self.canvas, self.font57, 79, 30, graphics.Color(20, 160, 60), "Vel: {0:.0f}".format(interpol_speed[i]))

                    breakout = self.wait_loop(0.065)
                    if breakout:
                        break

                    self.matrix.SwapOnVSync(self.canvas)

                prev_thing = plane_to_show
            else:
                # NOT ALERT RADIUS
                prev_thing = {}
                prev_thing["distance"] = 0
                prev_thing["altitude"] = 0
                prev_thing["speed"] = 0

                self.show_time()

            if breakout:
                continue

            # Wait before doing anything
            self.wait_loop(1)

# Main function
if __name__ == "__main__":
    read_static_airport_data()
    PlaneSign().sign_loop()
