#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import traceback
import requests
import random
import json
from datetime import datetime
from utilities import *
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array
from flask import Flask
from PIL import Image
import ctypes
from flask_cors import CORS
from enum import Enum
from collections import namedtuple

RGB = namedtuple('RGB', 'r g b')

COLORS = {}
COLORS[0] = [RGB(3, 194, 255)] #Plain
COLORS[1] = [RGB(0, 0, 0)] #RAINBOW
COLORS[2] = [RGB(12, 169, 12), RGB(206, 13, 13)] #CHRISTMAS
COLORS[3] = [RGB(173, 0, 30), RGB(178, 178, 178), RGB(37, 120, 178)] #FOURTH_OF_JULY
COLORS[4] = [RGB(20, 20, 20), RGB(247, 95, 28)] #HALLOWEEN

code_to_airport = {}

app = Flask(__name__)
CORS(app)

shared_flag = Value('i', 1)
shared_current_brightness = Value('i', 80)
shared_mode = Value('i', 1)
shared_color_mode = Value('i', 0)
shared_forced_sign_update = Value('i', 0)

@app.route("/status")
def get_status():
    return str(shared_flag.value)

@app.route("/turn_on")
def turn_on():
    shared_flag.value = 1
    shared_forced_sign_update.value = 1
    return ""

@app.route("/turn_off")
def turn_off():
    shared_flag.value = 0
    shared_forced_sign_update.value = 1
    return ""

@app.route("/set_color_mode/<color>")
def set_color_mode(color):
    shared_color_mode.value = int(color)
    shared_forced_sign_update.value = 1
    return ""

@app.route("/set_mode/<mode>")
def set_mode(mode):
    data_dict["custom_message"] = ""
    shared_mode.value = int(mode)
    shared_forced_sign_update.value = 1
    return ""

@app.route("/get_mode")
def get_mode():
    return str(shared_mode.value)

@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    shared_current_brightness.value = int(brightness)
    return ""

@app.route("/get_brightness")
def get_brightness():
    return str(shared_current_brightness.value)

@app.route("/set_custom_message/", defaults={"message": ""})
@app.route("/set_custom_message/<message>")
def set_custom_message(message):
    data_dict["custom_message"] = message
    shared_forced_sign_update.value = 1
    return ""

def server():
    app.run(host='0.0.0.0')

def get_weather_data_worker(data_dict):
    while True:
        try:
            data_dict["weather"] = requests.get(CONF["WEATHER_ENDPOINT"]).json()
        except:
            print("Error getting weather data...")
            traceback.print_exc()
            time.sleep(5)
            data_dict["weather"] = requests.get(CONF["WEATHER_ENDPOINT"]).json()

        time.sleep(600)

def get_data_worker(data_dict):
    while True:
        try:
            if shared_flag.value is 0:
                print("off, skipping FR24 request...")
            else:

                r = requests.get(CONF["ENDPOINT"], headers={'user-agent': 'martian-law-v1.2'})

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
                        newguy["distance"] = get_distance((float(CONF["SENSOR_LAT"]), float(CONF["SENSOR_LON"])), (result[1], result[2]))

                        if newguy["altitude"] < 100:
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

                data_dict["closest"] = closest
                data_dict["highest"] = highest
                data_dict["fastest"] = fastest
                data_dict["slowest"] = slowest

        except:
            print("Error getting FR24 data...")
            traceback.print_exc()

        time.sleep(7)

def read_config():
    global CONF
    CONF = {}
    with open("sign.conf") as f:
        lines = f.readlines()
        print("reading  config...")
        for line in lines:
            parts = line.split('=')
            CONF[parts[0]] = parts[1].rstrip()

    print("Config loaded: " + str(CONF))

    CONF["ENDPOINT"] = 'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds=40.1,38.1,-78.90,-75.10'
    CONF["WEATHER_ENDPOINT"] = f'http://api.openweathermap.org/data/2.5/onecall?lat={CONF["SENSOR_LAT"]}&lon={CONF["SENSOR_LON"]}&appid=1615520156f27624562ceace6e3849f3&units=imperial'

    print("Using: " + CONF["WEATHER_ENDPOINT"])

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
        options.gpio_slowdown = 3
        options.chain_length = 2
        options.limit_refresh_rate_hz = 160

        self.matrix = RGBMatrix(options = options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.starting_color_index = 0

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

        self.canvas.brightness = shared_current_brightness.value

        manager = Manager()
        global data_dict
        data_dict = manager.dict()

        Process(target=get_data_worker, args=(data_dict,)).start()
        Process(target=get_weather_data_worker, args=(data_dict,)).start()
        Process(target=server).start()

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds
        original_mode = shared_mode.value

        stay_in_loop = True
        forced_breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time

            self.canvas.brightness = shared_current_brightness.value
            self.matrix.brightness = shared_current_brightness.value
            self.matrix.SwapOnVSync(self.canvas)

            if shared_forced_sign_update.value == 1:
                stay_in_loop = False
                forced_breakout = True

        shared_forced_sign_update.value = 0
        return forced_breakout

    def show_time(self):
        print_time = datetime.now().strftime('%-I:%M%p')

        temp = str(round(data_dict["weather"]["current"]["temp"]))

        self.canvas.Clear()

        graphics.DrawText(self.canvas, self.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
        graphics.DrawText(self.canvas, self.fontreallybig, 86, 21, graphics.Color(20, 20, 240), temp + "°F")
        
        self.matrix.SwapOnVSync(self.canvas)

    def show_custom_message(self):
        raw_message = data_dict["custom_message"]

        self.canvas.Clear()

        clean_message = raw_message.strip()

        line_1 = clean_message[0:14]
        line_2 = clean_message[14:]

        line_1 = line_1.strip()
        line_2 = line_2.strip()

        # Figure out odd/even # of chars spacing
        if len(line_1) % 2 == 0:
            starting_line_1_x_index = 64 - ((len(line_1) / 2) * 9)
        else:
            starting_line_1_x_index = 59 - (((len(line_1) - 1) / 2) * 9)

        if len(line_2) % 2 == 0:
            starting_line_2_x_index = 64 - ((len(line_2) / 2) * 9)
        else:
            starting_line_2_x_index = 59 - (((len(line_2) - 1) / 2) * 9)

        print_the_char_at_this_x_index = starting_line_1_x_index
        lines = line_1 + line_2

        if len(line_2) == 0:
            print_at_y_index = 21
        else:
            print_at_y_index = 14

        if shared_color_mode.value == 1:
            selected_color_list = [RGB(random.randrange(10, 255), random.randrange(10, 255), random.randrange(10, 255))]
        else:
            selected_color_list = COLORS[shared_color_mode.value]

        if self.starting_color_index >= len(selected_color_list):
            self.starting_color_index = 0

        color_index = self.starting_color_index

        for line_1_char in line_1:
            char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
            graphics.DrawText(self.canvas, self.fontreallybig, print_the_char_at_this_x_index, print_at_y_index, char_color, line_1_char)
            print_the_char_at_this_x_index += 9

            color_index = color_index + 1 if line_1_char is not  ' ' else color_index

            if color_index >= len(selected_color_list):
                color_index = 0

        print_the_char_at_this_x_index = starting_line_2_x_index

        for line_2_char in line_2:
            char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
            graphics.DrawText(self.canvas, self.fontreallybig, print_the_char_at_this_x_index, 28, char_color, line_2_char)
            print_the_char_at_this_x_index += 9

            color_index = color_index + 1 if line_2_char is not  ' ' else color_index

            if color_index >= len(selected_color_list):
                color_index = 0

        self.matrix.SwapOnVSync(self.canvas)

    def show_weather(self):
        self.canvas = self.matrix.CreateFrameCanvas()

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        image = Image.open(f"/home/pi/PlaneSign/icons/{data_dict['weather']['daily'][0]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_0_xoffset + 15, 5)

        image = Image.open(f"/home/pi/PlaneSign/icons/{data_dict['weather']['daily'][1]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_1_xoffset + 15, 5)

        image = Image.open(f"/home/pi/PlaneSign/icons/{data_dict['weather']['daily'][2]['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.ANTIALIAS)
        self.canvas.SetImage(image.convert('RGB'), day_2_xoffset + 15, 5)

        graphics.DrawText(self.canvas, self.font46, 0, 5, graphics.Color(20, 20, 210), CONF["WEATHER_CITY_NAME"])

        # Calculate and draw the horizontal boarder around the WEATHER_CITY_NAME
        num_horizontal_pixels = (len(CONF["WEATHER_CITY_NAME"]) * 4)
        for x in range(num_horizontal_pixels):
            self.canvas.SetPixel(x, 6, 140, 140, 140)

        # Draw the vertical boarder around the WEATHER_CITY_NAME
        for y in range(7):
            self.canvas.SetPixel(num_horizontal_pixels, y, 140, 140, 140)

        sunrise_sunset_start_x = num_horizontal_pixels + 20

        graphics.DrawText(self.canvas, self.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), convert_unix_to_local_time(data_dict['weather']['current']['sunrise']).strftime('%-I:%M'))
        graphics.DrawText(self.canvas, self.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), convert_unix_to_local_time(data_dict['weather']['current']['sunset']).strftime('%-I:%M'))

        daily = data_dict['weather']['daily']

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if (datetime.now().hour >= 18):
            start_index_day = 1

        # Day 0
        day = daily[start_index_day]
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(self.canvas, self.font57, day_0_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(self.canvas, self.font46, day_0_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 1 
        day = daily[start_index_day + 1]
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(self.canvas, self.font57, day_1_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(self.canvas, self.font46, day_1_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 2 
        day = daily[start_index_day + 2]
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
        graphics.DrawText(self.canvas, self.fontbig, 66, 21, graphics.Color(160, 160, 200), "Sterner's")
        graphics.DrawText(self.canvas, self.fontbig, 66, 32, graphics.Color(20, 160, 60), "Home")
        self.matrix.SwapOnVSync(self.canvas)
        shared_mode.value = 1
        self.wait_loop(3)

    def sign_loop(self):

        prev_thing = {}
        prev_thing["distance"] = 0
        prev_thing["altitude"] = 0
        prev_thing["speed"] = 0
        prev_thing["flight"] = None

        self.welcome()

        while True:
            try:
                mode = shared_mode.value

                forced_breakout = False

                if shared_flag.value is 0:
                    self.canvas.Clear()
                    self.matrix.SwapOnVSync(self.canvas)
                    self.wait_loop(0.5)
                    continue

                if not data_dict or "closest" not in data_dict:
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
                # 8 = custom message
                # 9 = welcome

                if mode == 6:
                    self.show_weather()
                    self.wait_loop(0.5)
                    continue

                if mode == 7:
                    self.show_time()
                    self.wait_loop(0.5)
                    continue

                if mode == 8:
                    self.show_custom_message()

                    self.starting_color_index += 1

                    if shared_color_mode.value == 1:
                        self.wait_loop(0.1)
                    else:
                        self.wait_loop(1.1)
                    
                    continue

                if mode == 9:
                    self.welcome()

                plane_to_show = None

                if mode == 1:
                    if data_dict["closest"] and data_dict["closest"]["distance"] <= 2:
                        plane_to_show = data_dict["closest"]

                if mode == 2:
                    plane_to_show = data_dict["closest"]

                if mode == 3:
                    plane_to_show = data_dict["highest"]

                if mode == 4:
                    plane_to_show = data_dict["fastest"]

                if mode == 5:
                    plane_to_show = data_dict["slowest"]

                if plane_to_show:
                    interpol_distance = interpolate(prev_thing["distance"], plane_to_show["distance"])
                    interpol_alt = interpolate(prev_thing["altitude"], plane_to_show["altitude"])
                    interpol_speed = interpolate(prev_thing["speed"], plane_to_show["speed"])

                    ignore_these_codes = ("BWI", "IAD", "DCA")

                    code_to_resolve = plane_to_show["origin"] if plane_to_show["origin"] not in ignore_these_codes else plane_to_show["destination"] if plane_to_show["destination"] not in ignore_these_codes else ""

                    print("Resolving code: "  + code_to_resolve)

                    friendly_name = code_to_airport.get(str(code_to_resolve), "")

                    print("Full airport name from code: "  + friendly_name)

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

                        forced_breakout = self.wait_loop(0.065)
                        if forced_breakout:
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

                if forced_breakout:
                    continue

                # Wait before doing anything
                self.wait_loop(1)
            except:
                print("General error in main loop, waiting...")
                traceback.print_exc()
                time.sleep(5)

# Main function
if __name__ == "__main__":

    read_config()
    read_static_airport_data()

    PlaneSign().sign_loop()