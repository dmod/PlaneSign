#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import traceback
import requests
import random
from datetime import datetime
from utilities import *
from fish import *
from finance import *
from lightning import *
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array
from flask import Flask, request
from PIL import Image, ImageDraw
from flask_cors import CORS
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
shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)
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

@app.route("/set_track_a_flight/<flight_num>")
def set_track_a_flight(flight_num):
    data_dict["track_a_flight_num"] = flight_num
    shared_mode.value = 99
    shared_forced_sign_update.value = 1
    return ""

@app.route("/set_mode/<mode>")
def set_mode(mode):
    shared_mode.value = int(mode)
    if request.args:
        arg_dict.update(request.args)
    shared_forced_sign_update.value = 1
    return ""

@app.route("/get_mode")
def get_mode():
    return str(shared_mode.value)

@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    shared_current_brightness.value = int(brightness)
    return ""

@app.route("/set_pong_player_1/<spot>")
def set_pong_player1(spot):
    shared_pong_player1.value = int(spot)
    return ""

@app.route("/set_pong_player_2/<spot>")
def set_pong_player2(spot):
    shared_pong_player2.value = int(spot)
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

@app.route("/submit_ticker/", defaults={"ticker": ""})
@app.route("/submit_ticker/<ticker>")
def submit_ticker(ticker):
    data_dict["ticker"] = ticker
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
                        newguy["flight"] = result[16] if result[16] else ""
                        newguy["typecode"] = result[8]
                        newguy["origin"] = result[11]
                        newguy["destination"] = result[12]
                        newguy["distance"] = get_distance((float(CONF["SENSOR_LAT"]), float(CONF["SENSOR_LON"])), (result[1], result[2]))

                        # Filter out planes on the ground
                        if newguy["altitude"] < 100:
                            continue

                        if (closest is None or (newguy["distance"] < closest["distance"] and newguy["altitude"] < 10000)):
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

    CONF["ENDPOINT"] = f'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds={float(CONF["SENSOR_LAT"]) + 2},{float(CONF["SENSOR_LAT"]) - 2},{float(CONF["SENSOR_LON"]) - 2},{float(CONF["SENSOR_LON"]) + 2}'
    CONF["WEATHER_ENDPOINT"] = f'http://api.openweathermap.org/data/2.5/onecall?lat={CONF["SENSOR_LAT"]}&lon={CONF["SENSOR_LON"]}&appid=1615520156f27624562ceace6e3849f3&units=imperial'

    print("Plane Endpoint: " + CONF["ENDPOINT"])
    print("Weather Endpoint: " + CONF["WEATHER_ENDPOINT"])

def read_static_airport_data():
    with open("airports.csv") as f:
        lines = f.readlines()
        for line in lines:
            parts = line.strip().split(',')
            code = parts[0]
            name = parts[1]
            lat = float(parts[2])
            lon = float(parts[3])
            code_to_airport[code] = (name, lat, lon)

    print(f"{len(code_to_airport)} static airport configs added")


class PlaneSign:
    def __init__(self):

        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = 5
        options.chain_length = 2
        #options.limit_refresh_rate_hz = 200

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

        self.last_brightness = None

        manager = Manager()
        global data_dict
        global arg_dict
        data_dict = manager.dict()
        arg_dict = manager.dict()

        Process(target=get_data_worker, args=(data_dict,)).start()
        Process(target=get_weather_data_worker, args=(data_dict,)).start()
        Process(target=server).start()

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds

        stay_in_loop = True
        forced_breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time

            if (self.last_brightness != shared_current_brightness.value):
                self.last_brightness = shared_current_brightness.value
                self.canvas.brightness = shared_current_brightness.value
                self.matrix.brightness = shared_current_brightness.value
                self.matrix.SwapOnVSync(self.canvas) #slow, want to avoid redrawing

            if shared_forced_sign_update.value == 1:
                stay_in_loop = False
                forced_breakout = True

        shared_forced_sign_update.value = 0
        return forced_breakout

    def show_time(self):
        print_time = datetime.now().strftime('%-I:%M%p')

        if data_dict["weather"] and data_dict["weather"]["current"] and data_dict["weather"]["current"]["temp"]:
            temp = str(round(data_dict["weather"]["current"]["temp"]))
        else:
            temp = "--"

        self.canvas.Clear()

        graphics.DrawText(self.canvas, self.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
        graphics.DrawText(self.canvas, self.fontreallybig, 86, 21, graphics.Color(20, 20, 240), temp + "°F")
        
        self.matrix.SwapOnVSync(self.canvas)

    def track_a_flight(self):

        if "track_a_flight_num" not in data_dict:
            self.canvas.Clear()
            self.matrix.SwapOnVSync(self.canvas)
            return

        requests_limiter = 0
        blip_count = 0

        while True:

            flight_num_to_track = data_dict["track_a_flight_num"]

            if (requests_limiter % 22 == 0):
                parse_this_to_get_hex = requests.get(f"https://www.flightradar24.com/v1/search/web/find?query={flight_num_to_track}&limit=10").json()

                live_flight_info = first(parse_this_to_get_hex["results"], lambda x: x["type"] == "live")
                print(live_flight_info)

                flight_data = requests.get(f"https://data-live.flightradar24.com/clickhandler/?version=1.5&flight={live_flight_info['id']}").json()
                current_location = flight_data['trail'][0]
                reverse_geocode = requests.get(f"https://maps.googleapis.com/maps/api/geocode/json?latlng={current_location['lat']},{current_location['lng']}&result_type=country|administrative_area_level_1|natural_feature&key=AIzaSyD65DETlTi-o5ymfcSp2Gl8JxBS7fwOl5g").json()

                if len(reverse_geocode['results']) != 0:
                    formatted_address = reverse_geocode['results'][0]['formatted_address']
                else:
                    formatted_address = 'Somewhere'

                print(current_location)
                print(formatted_address)

            requests_limiter = requests_limiter + 1

            self.canvas.Clear()

            flight_number_header = f"- {flight_data['identification']['callsign']} -"

            graphics.DrawText(self.canvas, self.font57, get_centered_text_x_offset_value(5, flight_number_header), 6, graphics.Color(200, 10, 10), flight_number_header)

            graphics.DrawText(self.canvas, self.fontreallybig, 1, 14, graphics.Color(20, 200, 20), flight_data['airport']['origin']['code']['iata'])
            graphics.DrawText(self.canvas, self.fontreallybig, 100, 14, graphics.Color(20, 200, 20), flight_data['airport']['destination']['code']['iata'])

            scheduled_start_time = flight_data['time']['scheduled']['departure']
            real_start_time = flight_data['time']['real']['departure']
            estimated_start_time = flight_data['time']['estimated']['departure']

            scheduled_end_time = flight_data['time']['scheduled']['arrival']
            real_end_time = flight_data['time']['real']['arrival']
            estimated_end_time = flight_data['time']['estimated']['arrival']

            if real_start_time is not None:
                start_time = real_start_time
            elif estimated_start_time is not None:
                start_time = estimated_start_time
            else:
                start_time = scheduled_start_time

            if real_end_time is not None:
                end_time = real_end_time
            elif estimated_end_time is not None:
                end_time = estimated_end_time
            else:
                end_time = scheduled_end_time

            # current progress divited by total
            current_time = int(time.time())
            duration = end_time - start_time
            current_progress = current_time - start_time 

            percent_complete = current_progress / duration

            line_x_start = 30
            line_x_end = 98
            line_y = 9

            line_distance = line_x_end - line_x_start

            for x in range(line_x_start, line_x_end):
                self.canvas.SetPixel(x, line_y, 120, 120, 120)

            # Left Bar
            for y in range(line_y - 2, line_y + 3):
                self.canvas.SetPixel(line_x_start, y, 255, 255, 255)

            # Right Bar
            for y in range(line_y - 2, line_y + 3):
                self.canvas.SetPixel(line_x_end, y, 255, 255, 255)

            progress_box_start_offset = int(line_distance * percent_complete) + line_x_start

            if blip_count == 0:
                self.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)
            elif blip_count == 1:
                for x in range(progress_box_start_offset - 1, progress_box_start_offset + 2):
                    for y in range(line_y - 1, line_y + 2):
                        self.canvas.SetPixel(x, y, 255, 0, 0)

                self.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)
            elif blip_count == 2:
                self.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)


            graphics.DrawText(self.canvas, self.font46, 2, 22, graphics.Color(40, 40, 255), f"{time.strftime('%I:%M%p', time.localtime(start_time))}")
            graphics.DrawText(self.canvas, self.font46, 99, 22, graphics.Color(40, 40, 255), f"{time.strftime('%I:%M%p', time.localtime(end_time))}")

            #graphics.DrawText(self.canvas, self.font46, 31, 17, graphics.Color(200, 200, 10), flight_data['aircraft']['model']['text'])

            graphics.DrawText(self.canvas, self.font46, 32, 19, graphics.Color(160, 160, 200), f"Alt:{current_location['alt']}")
            graphics.DrawText(self.canvas, self.font46, 70, 19, graphics.Color(20, 160, 60), f"Spd:{current_location['spd']}")

            graphics.DrawText(self.canvas, self.font57, get_centered_text_x_offset_value(5, formatted_address), 30, graphics.Color(246, 242, 116), formatted_address)

            self.matrix.SwapOnVSync(self.canvas)

            blip_count = blip_count + 1
            if blip_count == 3:
                blip_count = 0

            breakout = self.wait_loop(0.8)
            if breakout:
                return

    def show_custom_message(self):

        raw_message = ""
        if "custom_message" in data_dict:
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

        if len(line_2) == 0:
            print_at_y_index = 21
        else:
            print_at_y_index = 14

        if shared_color_mode.value == 1:
            selected_color_list = [RGB(random.randrange(10, 255), random.randrange(10, 255), random.randrange(10, 255))]
        elif shared_color_mode.value >= 5:
            selected_color_list = [RGB(((shared_color_mode.value-5) >> 16) & 255, ((shared_color_mode.value-5) >> 8) & 255, (shared_color_mode.value-5) & 255)]
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

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if (datetime.now().hour >= 18):
            start_index_day = 1

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        daily = data_dict['weather']['daily']

        day = daily[start_index_day]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        self.canvas.SetImage(image.convert('RGB'), day_0_xoffset + 15, 5)

        day = daily[start_index_day+1]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        self.canvas.SetImage(image.convert('RGB'), day_1_xoffset + 15, 5)
        
        day = daily[start_index_day+2]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
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

    def aquarium(self):
        self.canvas.Clear()

        tank = Tank(self)

        clown = Fish(tank,"Clownfish",2,0.01)
        hippo = Fish(tank,"Hippotang",2,0.01)
        queentrigger = Fish(tank,"Queentrigger",1,0.005)
        grouper = Fish(tank,"Coralgrouper",1,0.005)
        anthias = Fish(tank,"Anthias",2,0.02)
        puffer = Fish(tank,"Pufferfish",1.5,0.005)
        regal = Fish(tank,"Regalangel",1,0.005)
        bicolor = Fish(tank,"Bicolorpseudochromis",3,0.01)
        flame = Fish(tank,"Flameangel",1.5,0.01)
        cardinal = Fish(tank,"Cardinal",1.5,0.01)
        copper = Fish(tank,"Copperbanded",1.5,0.01)
        wrasse = Fish(tank,"Wrasse",3,0.01)

        while True:
            tank.swim()
            tank.draw()
            breakout = self.wait_loop(0.1)
            if breakout:
                return


    def finance(self):
        self.canvas.Clear()
        data_dict["ticker"] = None
        s = None

        while True:

            ddt = data_dict["ticker"] 

            if(ddt != None and ddt != ""):

                raw_ticker = ddt.upper()

                if s == None:
                    s = Stock(self, raw_ticker)
                else:
                    s.setticker(raw_ticker)

                s.drawfullpage()

            else:

                graphics.DrawText(self.canvas, self.fontreallybig, 7, 12, graphics.Color(50, 150, 0), "Finance")
                graphics.DrawText(self.canvas, self.fontreallybig, 34, 26, graphics.Color(50, 150, 0), "Sign")

                image = Image.open("/home/pi/PlaneSign/icons/finance/money.png")
                image = image.resize((20, 20), Image.BICUBIC)
                self.canvas.SetImage(image.convert('RGB'), 10, 14)

                image = Image.open("/home/pi/PlaneSign/icons/finance/increase.png")
                self.canvas.SetImage(image.convert('RGB'), 75, -5)  

            breakout = self.wait_loop(0.1)
            if breakout:
                return
            self.matrix.SwapOnVSync(self.canvas)
            self.canvas = self.matrix.CreateFrameCanvas()

    def lightning(self):
        self.canvas.Clear()
        #LM=LightningManager(self,47.34045883887302,-94.23635732086981)
        LM=LightningManager(self,float(CONF["SENSOR_LAT"]),float(CONF["SENSOR_LON"]))
        #LM.draw_loading()
        LM.connect()

        last_draw = time.perf_counter()

        self.canvas.Clear()
        while LM.connected.value:
            if time.perf_counter()-last_draw > 2:
                LM.draw()
                last_draw = time.perf_counter()

            breakout = self.wait_loop(0.1)
            if breakout:
                LM.close()
                return


    def cca(self):
        self.canvas.Clear()

        generation_time = 0.15

        current_state = [[0 for j in range(32)] for i in range(128)]
        next_state = [[0 for j in range(32)] for i in range(128)]
        
        numstates = 12 #number of states/colors possible
        threshold = 1 #set from 1 to numstates to adjust behavior
        
        
        for i in range(128):
            for j in range(32):
                current_state[i][j]=random.randrange(0,numstates)

        tstart = time.perf_counter()        
        while True:
    
            for col in range(0, 128):
                for row in range(0, 32):
        
                    cs=self.check_matrix(col,row,current_state)
                    ns = (cs+1)%numstates
                    curr = 0
        
                    #if self.check_matrix(col-1,row-1,current_state) == ns:
                    #    curr += 1
                    if self.check_matrix(col,row-1,current_state) == ns:
                        curr += 1
                    #if self.check_matrix(col+1,row-1,current_state) == ns:
                    #    curr += 1
        
                    if self.check_matrix(col-1,row,current_state) == ns:
                        curr += 1
                    if self.check_matrix(col+1,row,current_state) == ns:
                        curr += 1
        
                    #if self.check_matrix(col-1,row+1,current_state) == ns:
                    #    curr += 1
                    if self.check_matrix(col,row+1,current_state) == ns:
                        curr += 1
                    #if self.check_matrix(col+1,row+1,current_state) == ns:
                    #    curr += 1
                    
                    if curr >= threshold:
                        self.set_matrix(col,row,next_state,ns)
                        r,g,b=hsv_2_rgb(ns/numstates,1,1)
                    else:
                        self.set_matrix(col,row,next_state,cs)
                        r,g,b=hsv_2_rgb(cs/numstates,1,1)
                    
                    self.canvas.SetPixel(col, row, r, g, b)

            for col in range(0, 128):
                for row in range(0, 32):
                    current_state[col][row] = next_state[col][row]

            tend = time.perf_counter()
            if( tend < tstart + generation_time):
                breakout=self.wait_loop(tstart + generation_time-tend)
            else:
                breakout=self.wait_loop(0)

            self.matrix.SwapOnVSync(self.canvas)

            tstart = time.perf_counter()
            if breakout:
                return

    def cgol(self):
        self.canvas.Clear()

        generation_time = 0.15

        if arg_dict["style"]=="2":
            cgol_cellcolor = False
        else:
            cgol_cellcolor = True

        current_state = [[False for j in range(32)] for i in range(128)]
        next_state = [[False for j in range(32)] for i in range(128)]
        if cgol_cellcolor:
            hmatrix = [[0 for j in range(32)] for i in range(128)]
            next_hmatrix = [[0 for j in range(32)] for i in range(128)]

        for i in range(0, 128):
            for j in range(0, 32):
                if (random.random() < 0.3):
                    current_state[i][j]=True
                else:
                    current_state[i][j]=False
                if cgol_cellcolor:
                        #hmatrix[i][j]=random_angle()
                        hmatrix[i][j]=round(359*i/127+359*j/31)%360

        firstgen = True

        gen_index = 0

        angle = random_angle() 
        #r,g,b = random_rgb()

        tstart = time.perf_counter()
        while True:
        
            detect2cycle = True
            gen_index += 1

            if not cgol_cellcolor:
                #angle, r, g, b = next_color_rainbow_linear(angle)
                angle, r, g, b = next_color_rainbow_sine(angle)
                #r,g,b = next_color_random_walk_uniform_step(r,g,b,10)
                #r,g,b = next_color_random_walk_const_sum(r,g,b,10)

            next_state = [[False for j in range(32)] for i in range(128)]

            for col in range(0, 128):
                for row in range(0, 32):

                    if cgol_cellcolor:
                        candidate, r, g, b = self.check_life_color(col, row, current_state, hmatrix, next_hmatrix)
                    else:
                        candidate = self.check_life(col, row, current_state)

                    next_state[col][row] = candidate

                    if detect2cycle and not firstgen and candidate != prev_state[col][row]:
                        detect2cycle = False
                    if candidate:
                        self.canvas.SetPixel(col, row, r, g, b)
                    else:
                        self.canvas.SetPixel(col, row, 0, 0, 0)

            if firstgen:
                detect2cycle = False
                firstgen = False
             
            if detect2cycle:
                for i in range(0, 128):
                    for j in range(0, 32):
                        if (random.random() < 0.3):
                            next_state[i][j]=True
                            if cgol_cellcolor:
                                hmatrix[i][j]=random_angle()
                        else:
                            next_state[i][j]=False

            prev_state = current_state
            current_state = next_state

            tend = time.perf_counter()
            if( tend < tstart + generation_time):
                breakout=self.wait_loop(tstart + generation_time-tend)
            else:
                breakout=self.wait_loop(0)

            self.matrix.SwapOnVSync(self.canvas)

            tstart = time.perf_counter()

            if breakout:
                return

    def check_life(self, x, y, matrix):
        num_neighbors_alive = 0


        # Check neighbors above
        if self.check_matrix(x-1, y-1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x, y-1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y-1, matrix): num_neighbors_alive += 1
    
        # Check neighbors aside
        if self.check_matrix(x-1, y, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y, matrix): num_neighbors_alive += 1

        # Check neighbors below
        if self.check_matrix(x-1, y+1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x, y+1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y+1, matrix): num_neighbors_alive += 1

        # Any live cell with fewer than two live neighbours dies, as if by underpopulation.
        # Any live cell with two or three live neighbours lives on to the next generation.
        # Any live cell with more than three live neighbours dies, as if by overpopulation.
        # Any dead cell with exactly three live neighbours becomes a live cell, as if by reproduction.

        if matrix[x][y] and (num_neighbors_alive == 2 or num_neighbors_alive == 3):
            return True
        
        if not matrix[x][y] and num_neighbors_alive == 3:
            return True

        return False

    def check_life_color(self, x, y, matrix, hm, nhm):

        num_neighbors_alive = 0

        cx=0
        cy=0

        # Check neighbors above
        if self.check_matrix(x-1, y-1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x, y-1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y-1, matrix): num_neighbors_alive += 1

        # Check neighbors aside
        if self.check_matrix(x-1, y, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y, matrix): num_neighbors_alive += 1

        # Check neighbors below
        if self.check_matrix(x-1, y+1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x, y+1, matrix): num_neighbors_alive += 1
        if self.check_matrix(x+1, y+1, matrix): num_neighbors_alive += 1

        # Any live cell with fewer than two live neighbours dies, as if by underpopulation.
        # Any live cell with two or three live neighbours lives on to the next generation.
        # Any live cell with more than three live neighbours dies, as if by overpopulation.
        # Any dead cell with exactly three live neighbours becomes a live cell, as if by reproduction.

        if matrix[x][y] and (num_neighbors_alive == 2 or num_neighbors_alive == 3):
            h=self.check_matrix(x, y, hm)
            self.set_matrix(x,y,nhm,h)
            r,g,b=hsv_2_rgb(h/360.0,1,1)
            return True, r, g, b
        
        if not matrix[x][y] and num_neighbors_alive == 3:

            #Find the mean color of the 3 neighbors

            # Check neighbors above
            if self.check_matrix(x-1, y-1, matrix):
                h=self.check_matrix(x-1, y-1, hm)
                cx += cos(h)
                cy += sin(h)
            if self.check_matrix(x, y-1, matrix):
                h=self.check_matrix(x, y-1, hm)
                cx += cos(h)
                cy += sin(h)
            if self.check_matrix(x+1, y-1, matrix):
                h=self.check_matrix(x+1, y-1, hm)
                cx += cos(h)
                cy += sin(h)

            # Check neighbors aside
            if self.check_matrix(x-1, y, matrix):
                h=self.check_matrix(x-1, y, hm)
                cx += cos(h)
                cy += sin(h)
            if self.check_matrix(x+1, y, matrix):
                h=self.check_matrix(x+1, y, hm)
                cx += cos(h)
                cy += sin(h)

            # Check neighbors below
            if self.check_matrix(x-1, y+1, matrix):
                h=self.check_matrix(x-1, y+1, hm)
                cx += cos(h)
                cy += sin(h)
            if self.check_matrix(x, y+1, matrix):
                h=self.check_matrix(x, y+1, hm)
                cx += cos(h)
                cy += sin(h)
            if self.check_matrix(x+1, y+1, matrix):
                h=self.check_matrix(x+1, y+1, hm)
                cx += cos(h)
                cy += sin(h)

            h=round(math.atan2(cy,cx)/DEG_2_RAD)%360
            self.set_matrix(x,y,nhm,h)
            
            #h=self.check_matrix(x, y, hm)
            #self.set_matrix(x,y,nhm,h)

            r,g,b=hsv_2_rgb(h/360.0,1,1)

            return True, r, g, b

        return False, 0, 0, 0

    def check_matrix(self, x, y, matrix):
        if x == -1:
            x = 127
        
        if x == 128:
            x = 0

        if y == -1:
            y = 31

        if y == 32:
            y = 0

        return matrix[x][y]

    def set_matrix(self, x, y, matrix, val):
        if x == -1:
            x = 127
        
        if x == 128:
            x = 0

        if y == -1:
            y = 31

        if y == 32:
            y = 0

        matrix[x][y] = val

    def pong(self):

        xball = 64
        yball = 16

        xvel = random.randint(0,1)*2-1
        yvel = random.randint(0,1)*2-1

        framecount = 0

        player1_score = 0
        player2_score = 0

        starting_y_value = shared_pong_player1.value
        starting_y_value_2 = shared_pong_player2.value

        #player 1 paddle
        for width in range(0, 3):
            for height in range(starting_y_value, starting_y_value + 6):
                self.canvas.SetPixel(width, height, 255, 20, 20)

        #player 2 paddle
        for width in range(125, 128):
            for height in range(starting_y_value_2, starting_y_value_2 + 6):
                self.canvas.SetPixel(width, height, 20, 20, 255)

        while True:
            framecount += 1
            self.canvas.Clear()

            setyval = shared_pong_player1.value
            setyval2 = shared_pong_player2.value


            if framecount % 20 == 0 and self.wait_loop(0):
                return

            #starting_y_value = shared_pong_player1.value
            #starting_y_value_2 = shared_pong_player2.value

            #limit paddle move speed to 1 per frame - continuous motion, no teleporting
            if framecount == 1:
                starting_y_value = setyval
                starting_y_value_2 = setyval2
            else:
                if framecount % 3 == 0: #limit paddle update (move speed)
                    if starting_y_value < setyval:
                        starting_y_value += 1
                    if starting_y_value > setyval:
                        starting_y_value -= 1
                    if starting_y_value_2 < setyval2:
                        starting_y_value_2 += 1
                    if starting_y_value_2 > setyval2:
                        starting_y_value_2 -= 1

            ##paddle face reflection
            #if (starting_y_value <= yball and starting_y_value+6 >= yball and xball <= 4 and xvel < 0) or (starting_y_value_2 <= yball and starting_y_value_2+6 >= yball and xball >= 123 and xvel > 0):
            #    xvel *= -1
            #    yvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '1' for default gameplay

            ##paddle top and bottom reflection
            #if (yball >= starting_y_value and yball <= starting_y_value+6+2 and yvel < 0 and xball <= 3) or (yball >= starting_y_value-2 and yball <= starting_y_value+6 and yvel > 0 and xball <= 3) or (yball >= starting_y_value_2 and yball <= starting_y_value_2+6+2 and yvel < 0 and xball >= 124) or (yball >= starting_y_value_2-2 and yball <= starting_y_value_2+6 and yvel > 0 and xball >= 124):
            #    xvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '-1' for default gameplay
            #    yvel *= -1

            #left paddle face reflection
            if (starting_y_value-1 <= yball and starting_y_value+6 >= yball and xball <= 4 and xvel < 0):
                xvel = 1
                if (starting_y_value-1 <= yball and starting_y_value+1 >= yball):
                    yvel = -1
                elif (starting_y_value+2 <= yball and starting_y_value+3 >= yball):
                    yvel = 0
                    #xvel = 2
                else:
                    yvel = 1

            #right paddle face reflection
            if (starting_y_value_2-1 <= yball and starting_y_value_2+6 >= yball and xball >= 123 and xvel > 0):
                xvel = -1
                if (starting_y_value_2-1 <= yball and starting_y_value_2+1 >= yball):
                    yvel = -1
                elif (starting_y_value_2+2 <= yball and starting_y_value_2+3 >= yball):
                    yvel = 0
                    #xvel = 2
                else:
                    yvel = 1        

            #paddle top and bottom reflection
            if (yball >= starting_y_value and yball <= starting_y_value+5+2 and yvel < 0 and xball <= 3) or (yball >= starting_y_value-2 and yball <= starting_y_value+5 and yvel > 0 and xball <= 3) or (yball >= starting_y_value_2 and yball <= starting_y_value_2+5+2 and yvel < 0 and xball >= 124) or (yball >= starting_y_value_2-2 and yball <= starting_y_value_2+5 and yvel > 0 and xball >= 124):
                xvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '-1' for default gameplay
                yvel *= -1

            #top and bottom bounce
            if (yball <= 0 and yvel <0) or (yball >= 31 and yvel >0):
                yvel *= -1

            if xball <= 0:
                graphics.DrawText(self.canvas, self.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
                graphics.DrawText(self.canvas, self.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(0.5)
                self.canvas.Clear()
                player2_score += 1
                graphics.DrawText(self.canvas, self.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
                graphics.DrawText(self.canvas, self.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(3)
                self.canvas.Clear()
                xball = 64
                yball = random.randint(2,30)
                xvel = random.randint(0,1)*2-1
                yvel = random.randint(0,1)*2-1

            if xball >= 127:
                graphics.DrawText(self.canvas, self.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
                graphics.DrawText(self.canvas, self.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(0.5)
                self.canvas.Clear()
                player1_score += 1
                graphics.DrawText(self.canvas, self.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
                graphics.DrawText(self.canvas, self.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
                self.matrix.SwapOnVSync(self.canvas)
                self.wait_loop(3)
                self.canvas.Clear()
                xball = 64
                yball = random.randint(2,30)
                xvel = random.randint(0,1)*2-1
                yvel = random.randint(0,1)*2-1

            if framecount % 5 == 0:
                xball += xvel
                yball += yvel

            #player 1 paddle
            for width in range(0, 3):
                for height in range(starting_y_value, starting_y_value + 6):
                    self.canvas.SetPixel(width, height, 255, 20, 20)

            #player 2 paddle
            for width in range(125, 128):
                for height in range(starting_y_value_2, starting_y_value_2 + 6):
                    self.canvas.SetPixel(width, height, 20, 20, 255)

            for width in range(xball-1, xball+2):
                for height in range(yball-1, yball+2):
                    self.canvas.SetPixel(width, height, 255, 255, 255)

            self.matrix.SwapOnVSync(self.canvas)
            


    def welcome(self):

        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontplanesign, 34, 20, graphics.Color(46, 210, 255), "Plane Sign")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        self.canvas.Clear()
        shared_mode.value = 1

    def sign_loop(self):

        prev_thing = {}
        prev_thing["distance"] = 0
        prev_thing["altitude"] = 0
        prev_thing["speed"] = 0
        prev_thing["flight"] = None

        while True:
            try:

                self.wait_loop(0.5)

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
                # 10 = CGOL
                # 11 = PONG

                if mode == 99:
                    self.track_a_flight()

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
                    elif shared_color_mode.value >= 5:
                        self.wait_loop(0.1)
                    else:
                        self.wait_loop(1.1)
                    
                    continue

                if mode == 9:
                    self.welcome()

                if mode == 10:
                    self.cgol()

                if mode == 11:
                    self.pong()

                if mode == 12:
                    self.cca()

                if mode == 13:
                    self.finance()
                
                if mode == 14:
                    self.aquarium()

                if mode == 15:
                    self.lightning()

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

                    # We only have room to display one full airport name. So pick the one that is further away assuming
                    # the user probably hasn't heard of that one
                    origin_distance = 0
                    if plane_to_show["origin"]:
                        origin_config = code_to_airport.get(plane_to_show["origin"])
                        origin_distance = get_distance((float(CONF["SENSOR_LAT"]), float(CONF["SENSOR_LON"])), (origin_config[1], origin_config[2]))
                        print(f"Origin is {origin_distance:.2f} miles away")

                    destination_distance = 0
                    if plane_to_show["destination"]:
                        destination_config = code_to_airport.get(plane_to_show["destination"])
                        destination_distance = get_distance((float(CONF["SENSOR_LAT"]), float(CONF["SENSOR_LON"])), (destination_config[1], destination_config[2]))
                        print(f"Destination is {destination_distance:.2f} miles away")

                    if origin_distance != 0 and origin_distance > destination_distance:
                        friendly_name = origin_config[0]
                    elif destination_distance != 0:
                        friendly_name = destination_config[0]
                    else:
                        friendly_name = ""

                    print("Full airport name from code: "  + friendly_name)

                    # Front pad the flight number to a max of 7 for spacing
                    formatted_flight = plane_to_show["flight"].rjust(7, ' ')

                    if not plane_to_show["origin"]:
                        plane_to_show["origin"] = "???"

                    if not plane_to_show["destination"]:
                        plane_to_show["destination"] = "???"

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
                time.sleep(3)
                shared_mode.value = 1

# Main function
if __name__ == "__main__":
    read_config()
    read_static_airport_data()

    PlaneSign().sign_loop()
