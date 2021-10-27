#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import logging
import logging.handlers
import sys
import traceback
import requests
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
from utilities import *
from fish import *
from finance import *
import lightning
import cgol
import custom_message
import pong
import weather
import planes
import shared_config
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array, Queue
import subprocess
from flask import Flask, request
from PIL import Image, ImageDraw
from flask_cors import CORS

code_to_airport = {}

app = Flask(__name__)
CORS(app)

@app.route("/get_config")
def get_config():
    shared_config.CONF.clear()
    read_config()
    sample={}
    sample["DATATYPES"]=[]

    with open("sign.conf.sample") as f:
        lines = f.readlines()
        lastline = None
        for line in lines:
            if line[0]=="#":
                lastline = line.rstrip()
                continue
            parts = line.split('=')
            sample[parts[0]] = parts[1].rstrip()
            if lastline:
                comment_parts = lastline[1:].split(' ')
                newdict = {}
                newdict["id"]=parts[0]
                newdict["type"]=comment_parts[0]
                for i in range(len(comment_parts)):
                    if comment_parts[i]=="min" and i+1<len(comment_parts):
                        newdict["min"]=comment_parts[i+1]
                    if comment_parts[i]=="max" and i+1<len(comment_parts):
                        newdict["max"]=comment_parts[i+1]
                sample["DATATYPES"].append(newdict)

    for key in sample.keys():
        if key in shared_config.CONF:
            sample[key]=shared_config.CONF[key]

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
    subprocess.call(['sh', './update.sh',])
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

def log_listener_process(queue):
    root = logging.getLogger()
    log_filename = "logs/planesign.log"
    os.makedirs(os.path.dirname(log_filename), exist_ok=True)
    log_handler = logging.handlers.TimedRotatingFileHandler(log_filename, when="midnight")
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(processName)-10s %(name)s %(levelname)-8s %(message)s'))
    root.addHandler(log_handler)

    while True:
        try:
            record = queue.get()
            if record is None:
                break
            logger = logging.getLogger(record.name)
            logger.handle(record)
        except Exception:
            traceback.print_exc(file=sys.stderr)

def configure_logging():
    logging_queue = Queue(-1)
    listener = Process(target=log_listener_process, args=(logging_queue, ))
    listener.start()

    queue_handler = logging.handlers.QueueHandler(logging_queue)

    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
    console_handler.setFormatter(console_formatter)

    root = logging.getLogger()
    root.addHandler(queue_handler)
    root.addHandler(console_handler)
    root.setLevel(logging.DEBUG)
    logging.getLogger('PIL').setLevel(logging.WARNING)

def server():
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
            if shared_config.shared_flag.value is 0:
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

        temp={}
        for line in lines:
            if line[0]=="#":
                continue
            parts = line.split('=')
            temp[parts[0]] = parts[1].rstrip()

        for line in lines_s:
            if line[0]=="#":
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

    logging.info(f"{len(code_to_airport)} static airport configs added")


class PlaneSign:
    def __init__(self):

        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = 5
        options.chain_length = 2
        #options.limit_refresh_rate_hz = 200

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

        self.canvas.brightness = shared_config.shared_current_brightness.value

        self.last_brightness = None

        manager = Manager()
        shared_config.data_dict = manager.dict()
        shared_config.arg_dict = manager.dict()
        shared_config.CONF = manager.dict()

        read_config()
        shared_config.shared_current_brightness.value = int(shared_config.CONF["DEFAULT_BRIGHTNESS"])

        read_static_airport_data()

        Process(target=get_data_worker, args=(shared_config.data_dict,)).start()
        Process(target=get_weather_data_worker, args=(shared_config.data_dict,)).start()
        Process(target=server).start()

    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds

        stay_in_loop = True
        forced_breakout = False

        while stay_in_loop:
            stay_in_loop = time.perf_counter() < exit_loop_time

            self.matrix.brightness = shared_config.shared_current_brightness.value

            if shared_config.shared_forced_sign_update.value == 1:
                stay_in_loop = False
                forced_breakout = True

        shared_config.shared_forced_sign_update.value = 0
        return forced_breakout

    def show_time(self):
        if shared_config.CONF["MILITARY_TIME"].lower()=='true':
            print_time = datetime.now().strftime('%-H:%M%p')
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
        shared_config.data_dict["ticker"] = None
        s = None

        while True:

            ddt = shared_config.data_dict["ticker"] 

            if(ddt != None and ddt != ""):

                raw_ticker = ddt.upper()

                if s == None:
                    s = Stock(self, raw_ticker, shared_config.CONF)
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

        lightning.draw_loading(self)
        LM=lightning.LightningManager(self,shared_config.CONF)
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


    def welcome(self):

        self.canvas.Clear()
        graphics.DrawText(self.canvas, self.fontplanesign, 34, 20, graphics.Color(46, 210, 255), "Plane Sign")
        self.matrix.SwapOnVSync(self.canvas)
        self.wait_loop(2)
        self.canvas.Clear()
        shared_config.shared_mode.value = 1

    def sign_loop(self):

        prev_thing = {}
        prev_thing["distance"] = 0
        prev_thing["altitude"] = 0
        prev_thing["speed"] = 0
        prev_thing["flight"] = None

        while True:
            try:

                mode = shared_config.shared_mode.value

                forced_breakout = False

                if shared_config.shared_flag.value is 0:
                    self.canvas.Clear()
                    self.matrix.SwapOnVSync(self.canvas)
                    self.wait_loop(0.5)
                    continue

                if not shared_config.data_dict or "closest" not in shared_config.data_dict:
                    logging.info("no data found, waiting...")
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
                    planes.track_a_flight(self)

                if mode == 6:
                    weather.show_weather(self)

                if mode == 7:
                    self.show_time()
                    self.wait_loop(0.5)
                    continue

                if mode == 8:
                    custom_message.show_custom_message(self)

                if mode == 9:
                    self.welcome()

                if mode == 10:
                    cgol.cgol(self)

                if mode == 11:
                    pong.pong(self)

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
                    if shared_config.data_dict["closest"] and shared_config.data_dict["closest"]["distance"] <= 2:
                        plane_to_show = shared_config.data_dict["closest"]

                if mode == 2:
                    plane_to_show = shared_config.data_dict["closest"]

                if mode == 3:
                    plane_to_show = shared_config.data_dict["highest"]

                if mode == 4:
                    plane_to_show = shared_config.data_dict["fastest"]

                if mode == 5:
                    plane_to_show = shared_config.data_dict["slowest"]

                if plane_to_show:
                    interpol_distance = interpolate(prev_thing["distance"], plane_to_show["distance"])
                    interpol_alt = interpolate(prev_thing["altitude"], plane_to_show["altitude"])
                    interpol_speed = interpolate(prev_thing["speed"], plane_to_show["speed"])

                    # We only have room to display one full airport name. So pick the one that is further away assuming
                    # the user probably hasn't heard of that one
                    origin_distance = 0
                    if plane_to_show["origin"]:
                        origin_config = code_to_airport.get(plane_to_show["origin"])
                        if origin_config:
                            origin_distance = get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (origin_config[1], origin_config[2]))
                            logging.info(f"Origin is {origin_distance:.2f} miles away")

                    destination_distance = 0
                    if plane_to_show["destination"]:
                        destination_config = code_to_airport.get(plane_to_show["destination"])
                        if destination_config:
                            destination_distance = get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (destination_config[1], destination_config[2]))
                            logging.info(f"Destination is {destination_distance:.2f} miles away")

                    if origin_distance != 0 and origin_distance > destination_distance:
                        friendly_name = origin_config[0]
                    elif destination_distance != 0:
                        friendly_name = destination_config[0]
                    else:
                        friendly_name = ""

                    logging.info("Full airport name from code: "  + friendly_name)

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
                logging.exception("General error in main loop, waiting...")
                time.sleep(3)
                shared_config.shared_mode.value = 1

# Main function
if __name__ == "__main__":
    configure_logging()
    
    PlaneSign().sign_loop()
