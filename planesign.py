#!/usr/bin/python3
# -*- coding: utf-8 -*-

# wget https://ourairports.com/data/airports.csv

import time
import math
import sys, traceback
import requests
import subprocess
from datetime import datetime

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value

from flask import Flask
from flask import Response
from flask import render_template

# <Config>
DEFAULT_BRIGHTNESS = 100
NUM_STEPS = 50
SENSOR_LOC = { "lat":39.288, "lon": -76.841 }
ALTITUDE_IGNORE_LIMIT = 100 # Ignore returns below this altitude in feet
ON_THE_MAP_RADIUS = 15.62 # Adds to the counter in scan mode in miles
ALERT_RADIUS = 12 # Will alert in miles
ENDPOINT = 'https://data-live.flightradar24.com/zones/fcgi/feed.js?bounds=40.1,38.1,-78.90,-75.10'
WEATHER_ENDPOINT = 'https://api.weather.gov/gridpoints/LWX/111,80/forecast/hourly'
# </Config>

code_to_airport = {}
app = Flask(__name__)

da_html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>D-Money Enterprises</title>
</head>

<script type="application/javascript">

  window.onload = function(){
    update_sign_status();
    update_brightness();

    document.getElementById("myRange").oninput = function() {
        console.log(this.value);
        document.getElementById("brightness_value").innerHTML = this.value;
        call_endpoint("/set_brightness/" + this.value);
    }
  }

  function call_endpoint(endpoint, callback) {
    var request = new XMLHttpRequest();
    request.onreadystatechange = function () {
        if (request.status == 200 && callback) {
            callback(request.responseText);
        }
    }
    request.open('GET', endpoint, true);
    request.send();
  }

  function update_brightness() {
    call_endpoint("/get_brightness", function(value) {
        console.log("I was told the brightness is: " + value);
        document.getElementById("myRange").value = value;
        document.getElementById("brightness_value").innerHTML = value;
    });
  }

  function update_sign_status() {
    console.log("In sign status update...");
    call_endpoint("/status", function(actual_text) {
        var html_to_send;
        if (actual_text === "1"){
            html_to_send = "<b style='color: green'>ON</b>";
        } else {
            html_to_send = "<b style='color: red'>LITERALLY NOT ON</b>";
        }
        document.getElementById("sign_status").innerHTML = html_to_send;
    });
  }
</script>

<style>
    button {
        background-color: #4CAF50;
        width: 100%;
        height: 20vh;
        color: white;
        font-size: xx-large;
        margin-top: 20px;
        text-shadow: 0 0 11px black;
        text-align: center;
        text-decoration: none;
    }
</style>

<body>
  <div style="text-align: center;">Current sign status: <div id="sign_status">Unknown?</div></div>
  <button onclick="call_endpoint('/turn_on'); update_sign_status();">Turn Sign On</button>
  <button onclick="call_endpoint('/turn_off'); update_sign_status();">Turn Sign Off</button>
  <div style="text-align: center;">
    Brightness: <div id="brightness_value"></div>
  </div>
  <div style="text-align: center;">
    <input id="myRange" type="range" min="1" max="100" value="100" class="slider">
  </div>
</body>
</html>
"""

shared_flag_global = None
shared_current_brightness = 100

@app.route("/")
def da_index():
    return da_html

@app.route("/status")
def get_status():
    print("In get status...")
    return str(shared_flag_global.value)

@app.route("/turn_on")
def turn_on():
    print("TURNING ONNNNNNNNNN")
    shared_flag_global.value = 1
    return ""

@app.route("/turn_off")
def turn_off():
    print("TURNING OFFFFFFFFF")
    shared_flag_global.value = 0
    return ""

@app.route("/set_brightness/<brightness>")
def set_brightness(brightness):
    print("IN flask set_brightness")
    print("With: " + brightness)
    shared_current_brightness.value = int(brightness)
    return ""

@app.route("/get_brightness")
def get_brightness():
    print("IN flask get_brightness")
    print("shared_current_brightness: " + str(shared_current_brightness.value))
    return str(shared_current_brightness.value)

def server(shared_flag, shared_brightness):
    global shared_flag_global
    shared_flag_global = shared_flag

    global shared_current_brightness
    shared_current_brightness = shared_brightness

    app.run(host='0.0.0.0')

def get_data_worker(d, shared_flag):
    while True:
        try:
            if shared_flag.value is 0:
                print("off, skipping request...")
            else:
                stuff = get_data()
                stuff = sorted(stuff, key=(lambda x: x['distance']))
                d["allstuff"] = stuff
        except:
            print("FR24: HEY MAN BAD THING HAPPENED")
            traceback.print_exc()
        time.sleep(7.5)

def interpolate(num1, num2):
    if (num1 == 0):
        num1 = num2

    if num2 > num1:
        thing = float((num2 - num1)) / NUM_STEPS
        interpolated = [num1]
        for _ in range(NUM_STEPS):
            interpolated.append(interpolated[-1] + thing)
    else:
        thing = float((num1 - num2)) / NUM_STEPS
        interpolated = [num1]
        for _ in range(NUM_STEPS):
            interpolated.append(interpolated[-1] - thing)

    return interpolated

def get_weather_temp():
    try:
        weather_result = requests.get(WEATHER_ENDPOINT).json()
        return str(weather_result["properties"]["periods"][0]["temperature"])
    except:
        print("WEATHER ERROR")
        traceback.print_exc()
        return -1
    
def get_distance(coord1, coord2):
    R = 3958.8  # Earth radius in meters
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    
    phi1, phi2 = math.radians(lat1), math.radians(lat2) 
    dphi       = math.radians(lat2 - lat1)
    dlambda    = math.radians(lon2 - lon1)
    
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    
    return (2*R*math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def get_data():
    current_temp = get_weather_temp()
    print("The current temp is: " + current_temp)

    r = requests.get(ENDPOINT, headers={'user-agent': 'my-app/1.0.0'})

    if r.status_code is not 200:
        print("FR REQUEST WAS BAD")
        print("STATUS CODE: " + str(r.status_code))

    results = r.json()

    to_return = []

    for key in results:
        if key != "full_count" and key != "stats" and key != "version":
            result = results[key]
            #print result

            newguy = {}
            newguy["altitude"] = result[4]
            newguy["speed"] = result[5]
            newguy["flight"] = result[16] if result[16] else "UNK69"
            newguy["typecode"] = result[8]
            newguy["origin"] = result[11] if result[11] else "???"
            newguy["destination"] = result[12] if result[12] else "???"

            result_distance = get_distance((SENSOR_LOC["lat"], SENSOR_LOC["lon"]), (result[1], result[2]))
            newguy["distance"] = result_distance

            if (newguy["distance"] < ON_THE_MAP_RADIUS and newguy["altitude"] > ALTITUDE_IGNORE_LIMIT):
                to_return.append(newguy)

    return to_return

def read_airport_data():
    with open("airports.csv") as f:
        lines = f.readlines()
        for line in lines[1:]:
            parts = line.split(',')
            name = parts[3].strip("\"") # Get rid of the F'in quotes
            code = parts[13].strip("\"")
            code_to_airport[code] = name

    print(str(len(code_to_airport)) + " airports added.")

def sign_loop():

    options = RGBMatrixOptions()
    options.cols = 64
    options.gpio_slowdown = 2
    options.chain_length = 2

    matrix = RGBMatrix(options = options)

    canvas = matrix.CreateFrameCanvas()

    font57 = graphics.Font()
    font46 = graphics.Font()
    fontbig = graphics.Font()
    fontreallybig = graphics.Font()
    font57.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/5x7.bdf")
    font46.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/4x6.bdf")
    fontbig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/6x13.bdf")
    fontreallybig.LoadFont("/home/pi/rpi-rgb-led-matrix/fonts/9x18B.bdf")

    manager = Manager()
    d = manager.dict()

    shared_flag = Value('i', 1)
    shared_current_brightness = Value('i', DEFAULT_BRIGHTNESS)
    
    get_data_proc = Process(target=get_data_worker, args=(d,shared_flag, ))
    get_data_proc.start()

    pServer = Process(target=server, args=(shared_flag,shared_current_brightness,))
    pServer.start()

    prev_thing = {}
    prev_thing["distance"] = 0
    prev_thing["altitude"] = 0
    prev_thing["speed"] = 0
    prev_thing["flight"] = None

    # graphics.DrawText(canvas, fontbig, 4, 12, graphics.Color(140, 140, 140), "Welcome")
    # matrix.SwapOnVSync(canvas)
    # time.sleep(2)
    # graphics.DrawText(canvas, fontbig, 4, 26, graphics.Color(140, 140, 140), "to")
    # matrix.SwapOnVSync(canvas)
    # time.sleep(2)
    # graphics.DrawText(canvas, fontbig, 66, 10, graphics.Color(200, 10, 10), "The")
    # graphics.DrawText(canvas, fontbig, 66, 21, graphics.Color(200, 10, 10), "Sterners's")
    # graphics.DrawText(canvas, fontbig, 66, 32, graphics.Color(200, 10, 10), "Home")
    # matrix.SwapOnVSync(canvas)
    # time.sleep(2)

    while True:

        if shared_flag.value is 0:
            canvas.Clear()
            matrix.SwapOnVSync(canvas)
            time.sleep(0.5)
            continue

        if "allstuff" not in d:
            print("no data found, waiting...")
            time.sleep(3)
            continue
        
        allstuff = d["allstuff"]

        closest = allstuff[0] if len(allstuff) > 0 else None
        print("CLOSEST: " + str(closest))

        print("current shared brightness: " + str(shared_current_brightness.value))
        matrix.brightness = shared_current_brightness.value

        if closest and closest["distance"] <= ALERT_RADIUS:

            interpol_distance = interpolate(prev_thing["distance"], closest["distance"])
            interpol_alt = interpolate(prev_thing["altitude"], closest["altitude"])
            interpol_speed = interpolate(prev_thing["speed"], closest["speed"])

            code_to_resolve = closest["origin"] if closest["origin"] != "BWI" else closest["destination"] if closest["destination"] != "BWI" else ""

            friendly_name = code_to_airport.get(str(code_to_resolve), "")

            for i in range(NUM_STEPS):
                canvas.Clear()
                graphics.DrawText(canvas, fontreallybig, 1, 12, graphics.Color(20, 200, 20), closest["origin"] + "->" + closest["destination"])
                graphics.DrawText(canvas, font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
                graphics.DrawText(canvas, font57, 37, 30, graphics.Color(0, 0, 255), closest["flight"])
                graphics.DrawText(canvas, font57, 2, 30, graphics.Color(245, 245, 245), closest["typecode"])

                graphics.DrawText(canvas, font57, 79, 8, graphics.Color(255, 140, 140), "Dst: {0:.1f}".format(interpol_distance[i]))
                graphics.DrawText(canvas, font57, 79, 19, graphics.Color(255, 255, 0), "Alt: {0:.0f}".format(interpol_alt[i]))
                graphics.DrawText(canvas, font57, 79, 30, graphics.Color(140, 140, 140), "Vel: {0:.0f}".format(interpol_speed[i]))

                time.sleep(0.065)
                matrix.SwapOnVSync(canvas)

            prev_thing = closest
        else:
            # NOT ALERT RADIUS
            prev_thing = {}
            prev_thing["distance"] = 0
            prev_thing["altitude"] = 0
            prev_thing["speed"] = 0

            cur_temp = get_weather_temp()

            print_time = datetime.now().strftime('%I:%M%p')

            time_canvus = matrix.CreateFrameCanvas()

            graphics.DrawText(time_canvus, fontreallybig, 6, 21, graphics.Color(0, 150, 0), print_time)
            graphics.DrawText(time_canvus, fontreallybig, 84, 21, graphics.Color(20, 20, 240), cur_temp + "°F")
            
            matrix.SwapOnVSync(time_canvus)

        # Wait before doing anything
        time.sleep(3)

# Main function
if __name__ == "__main__":
    print('Starting......')
    print('Number of arguments:', len(sys.argv), 'arguments.')
    print('Argument List:', str(sys.argv))

    read_airport_data()

    sign_loop()
