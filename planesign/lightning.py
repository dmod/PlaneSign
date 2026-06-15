#!/usr/bin/python3
# -*- coding: utf-8 -*-

import random
import websocket
import json
import time
import os
import base64
import ssl
from multiprocessing import Process, Manager, Value
import numpy as np
import utilities
from rgbmatrix import graphics
import requests
import re
import PIL.ImageDraw as ImageDraw
import PIL.Image as Image
import _thread as thread
import os.path
import shared_config
import logging
import __main__
from modes import DisplayMode

USAlong = -96
USAlat = 38
USAscale = 55
global_map_ver = "V1"

@__main__.planesign_mode_handler(DisplayMode.LIGHTNING)
def lightning(sign):
    sign.canvas.Clear()

    LM = LightningManager(sign)

    sign.canvas.Clear()
    last_draw = None
    failed_connections = 0
    breakout = False
    while failed_connections < 3:
        if LM.connected.value == 0:
            LM.connect()

        if LM.connected.value == 1:
            failed_connections = 0

            while LM.connected.value:
                if last_draw is None or time.perf_counter() - last_draw > 2 or (LM.last_drawn_zoomind.value != shared_config.shared_lightning_zoomind.value) or (LM.last_drawn_mode.value != shared_config.shared_lightning_mode.value):
                    LM.draw()
                    last_draw = time.perf_counter()

                breakout = sign.wait_loop(0.1)
                if breakout:
                    break
            LM.close()
        elif LM.connected.value == 0:
            failed_connections += 1
            logging.error(f"Websocket failed to connect {failed_connections} times")

        if breakout:
            return

    shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value


def mercator_proj(lat, lon):
    x = np.radians(lon)
    y = np.log(np.tan(np.radians(lat)) + 1 / np.cos(np.radians(lat)))
    return x, y


def get_lightning_color(strike_time, now, format=False):

    max_bright = 150

    dt = now - strike_time

    b = max(min(round(max_bright * (1 - dt / 60)), max_bright), 0)  # min brightness at 1 min
    g = max(min(round(max_bright * (2 - dt / 60)), max_bright), 0)  # min brightness at 2 mins
    r = max(min(round(dt * (30 - max_bright) / 180 + (5 * max_bright - 60) / 3), max_bright), 30)  # min brightness at 5 mins

    color = (r, g, b)

    if format:
        return color
    else:
        return r, g, b


def draw_power(x, y, radius, sign):
    t1 = 900  # 650
    t2 = 1500  # 1200
    t3 = 2500  # 2000
    sign.canvas.SetPixel(x, y - 2, 0, 90, 0)
    if radius > t1:
        sign.canvas.SetPixel(x, y - 3, 140, 120, 10)
    if radius > t2:
        sign.canvas.SetPixel(x, y - 4, 140, 50, 10)
    if radius > t3:
        sign.canvas.SetPixel(x, y - 5, 120, 0, 0)


class LightningManager:
    def __init__(self, sign):
        self.host = ""
        self.ws = None
        self.thread = None
        self.ws_server = None
        self.ws_key = None
        self.header = None
        self.floc = f"{shared_config.icons_dir}/lightning/"
        self.connected = Value("i", 0)
        self.strikes = Manager().list()
        self.sign = sign
        self.bgwidth = 64
        self.bgheight = 32
        self.minzoom = 500
        self.maxzoom = 3200
        self.zoomstep = 300
        self.numzooms = ((self.maxzoom - self.minzoom) // self.zoomstep) + 1
        self.zooms = np.linspace(self.minzoom, self.maxzoom, self.numzooms)
        self.background = None
        self.backgrounds = [None] * self.numzooms
        self.x0 = None
        self.y0 = None
        self.x1 = None
        self.y1 = None
        self.usa = None
        self.last_drawn_zoomind = Value("i", 6)
        self.last_drawn_mode = Value("i", 1)
        self.county_polygons = []
        self.state_polygons = []
        self._closest_bg_cache = None
        self._closest_bg_center = None
        self._closest_bg_scale = None
        self.genBackgrounds()

    def draw_loading(self):
        self.sign.canvas.Clear()
        image = Image.open(f"{shared_config.icons_dir}/11d.png")
        image = image.resize((35, 35), Image.BICUBIC)
        self.sign.canvas.SetImage(image.convert("RGB"), 93, -1)

        graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 7, 15, graphics.Color(180, 180, 40), "Storm Sign")

    def genBackgrounds(self):
        self.x0, self.y0 = mercator_proj(USAlat, USAlong)
        self.x1, self.y1 = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))

        countyfile = f"{shared_config.datafiles_dir}/geoBoundaries-USA-ADM2_simplified.geojson"
        usafile = f"{shared_config.datafiles_dir}/geoBoundaries-USA-ADM1_simplified.geojson"

        self.draw_loading()

        genmaps = (not os.path.exists(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png")) or len(Image.open(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png").getcolors()) == 1

        if not genmaps:
            for scale in self.zooms:
                if (not os.path.exists(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png")) or len(Image.open(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png").getcolors()) == 1:
                    genmaps = True
                    break

        # Load static state and county map data from geojson files
        with open(countyfile, "r") as f:
            try:
                countydata = json.load(f)
            except:
                countydata = None
        
        with open(usafile, "r") as f:
            try:
                usadata = json.load(f)
            except:
                usadata = None

        if (usadata == None or countydata == None):
            logging.error("Error loading map data, cannot generate maps")
            raise ValueError("Map data error")
            return

        if genmaps:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 10, 26, graphics.Color(180, 180, 40), "Drawing Maps...")
            for i in range(self.numzooms + 1):
                self.sign.canvas.SetPixel(15 + i, 28, 180, 20, 0)

        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 10, 26, graphics.Color(180, 180, 40), "Loading...")

        self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)

        # Extract verticies from datafiles and convert to mercator projection coordinates, then store in lists for drawing later
        usapoints = []
        for feature in usadata["features"]:
            shape = feature["geometry"]
            if feature["properties"]["shapeISO"] not in ["US-AS", "US-AK", "US-VI", "US-GU", "US-HI", "US-MP", "US-PR"]:
                if shape["type"] == "Polygon":
                    points = []
                    for coord in shape["coordinates"][0]:
                        x, y = mercator_proj(coord[1], coord[0])
                        points.append((x, y))
                    usapoints.append(points)
                elif shape["type"] == "MultiPolygon":
                    for subshape in shape["coordinates"]:
                        points = []
                        for coord in subshape[0]:
                            x, y = mercator_proj(coord[1], coord[0])
                            points.append((x, y))
                        usapoints.append(points)

        countypoints = []
        for feature in countydata["features"]:
            shape = feature["geometry"]
            if shape["type"] == "Polygon":
                points = []
                for coord in shape["coordinates"][0]:
                    x, y = mercator_proj(coord[1], coord[0])
                    points.append((x, y))
                countypoints.append(points)
            elif shape["type"] == "MultiPolygon":
                for subshape in shape["coordinates"]:
                    points = []
                    for coord in subshape[0]:
                        x, y = mercator_proj(coord[1], coord[0])
                        points.append((x, y))
                    countypoints.append(points)

        self.state_polygons = usapoints
        self.county_polygons = countypoints

        if (not os.path.exists(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png")) or len(Image.open(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png").getcolors()) == 1:
            self.usa = Image.new("RGB", (self.bgwidth, self.bgheight))

            # Draw and save new USA map centered on the middle of the country with state lines only
            usadraw = ImageDraw.Draw(self.usa)

            for polygon in usapoints:
                temp = []
                for p in polygon:
                    temp.append((self.bgwidth / 2 + (p[0] - self.x0) * USAscale, self.bgheight / 2 - (p[1] - self.y0) * USAscale))
                usadraw.polygon((temp), outline=(40, 40, 40))

            self.usa.save(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png")

        else:
            # Load USA map
            self.usa = Image.open(self.floc + f"usa_{USAlat}_{USAlong}_{USAscale}_{global_map_ver}.png")

        if genmaps:
            # Finished loading USA map
            loadingind = 0
            self.sign.matrix.SetPixel(15 + loadingind, 28, 20, 180, 0)
            loadingind += 1

        for i, scale in enumerate(self.zooms):
            if (not os.path.exists(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png")) or len(Image.open(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png").getcolors()) == 1:
                self.backgrounds[i] = Image.new("RGB", (self.bgwidth, self.bgheight))
                draw = ImageDraw.Draw(self.backgrounds[i])

                for polygon in countypoints:
                    temp = []
                    for p in polygon:
                        temp.append((self.bgwidth / 2 + (p[0] - self.x1) * scale, self.bgheight / 2 - (p[1] - self.y1) * scale))
                    draw.polygon((temp), outline=(30, 30, 30))

                for polygon in usapoints:
                    temp = []
                    for p in polygon:
                        temp.append((self.bgwidth / 2 + (p[0] - self.x1) * scale, self.bgheight / 2 - (p[1] - self.y1) * scale))
                    draw.polygon((temp), outline=(80, 80, 80))

                self.backgrounds[i].save(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png")

            else:
                self.backgrounds[i] = Image.open(self.floc + f"local_{shared_config.CONF['SENSOR_LAT']}_{shared_config.CONF['SENSOR_LON']}_{scale}_{global_map_ver}.png")

            if genmaps:
                # Finished loading this local map
                self.sign.matrix.SetPixel(15 + loadingind, 28, 20, 180, 0)
                loadingind += 1

    def genDynamicBackground(self, x_merc, y_merc, zoomind):

        zoom_scale = self.zooms[zoomind]

        if self._closest_bg_cache is not None and self._closest_bg_scale == zoom_scale and self._closest_bg_center is not None:
            dx = abs((x_merc - self._closest_bg_center[0]) * zoom_scale)
            dy = abs((y_merc - self._closest_bg_center[1]) * zoom_scale)
            if dx < 1 and dy < 1:
                # Cached background is close enough to the current strike location that we can keep using it without redrawing
                return self._closest_bg_cache, self._closest_bg_center[0], self._closest_bg_center[1]

        # Need to draw a new map centered on the current strike location -
        # first check if the strike is within the drawable area around the USA.

        testx = abs(x_merc - self.x0) * USAscale <= self.bgwidth / 2
        testy = abs(y_merc - self.y0) * USAscale <= self.bgheight / 2
        if not (testx and testy):
            # Point is outside of the drawable USA, do not generate a
            # new background centered on this location as it will not
            # have any of the state or county lines to orient us!
            if self._closest_bg_cache is not None and self._closest_bg_scale == zoom_scale and self._closest_bg_center is not None:
                # Keep the previous cached background if we have one
                return self._closest_bg_cache, self._closest_bg_center[0], self._closest_bg_center[1]
            else:
                # Show the local map background if we don't have a cached background to show
                x, y = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
                return self.backgrounds[zoomind], x, y

        # Draw a new background centered on the current strike location
        bg = Image.new("RGB", (self.bgwidth, self.bgheight))
        draw = ImageDraw.Draw(bg)

        for polygon in self.county_polygons:
            temp = []
            for p in polygon:
                temp.append((self.bgwidth / 2 + (p[0] - x_merc) * zoom_scale, self.bgheight / 2 - (p[1] - y_merc) * zoom_scale))
            draw.polygon(temp, outline=(30, 30, 30))

        for polygon in self.state_polygons:
            temp = []
            for p in polygon:
                temp.append((self.bgwidth / 2 + (p[0] - x_merc) * zoom_scale, self.bgheight / 2 - (p[1] - y_merc) * zoom_scale))
            draw.polygon(temp, outline=(80, 80, 80))

        self._closest_bg_cache = bg
        self._closest_bg_center = (x_merc, y_merc)
        self._closest_bg_scale = zoom_scale
        return bg, x_merc, y_merc

    def decode(self, b):
        e = {}
        g = []
        d = list(b)
        c = d[0]
        f = c
        g.append(c)
        h = 256
        o = h
        for b in range(1, len(d)):
            a = ord(d[b])
            if h > a:
                a = d[b]
            elif a in e:
                a = e[a]
            else:
                a = f + c
            g.append(a)
            c = a[0]
            e[o] = f + c
            o += 1
            f = a
        return "".join(g)

    def onMessage(self, ws, message):
        strike_js = json.loads(self.decode(message))

        dets = []
        for det in strike_js["sig"]:
            dets.append(utilities.get_distance((det["lat"], det["lon"]), (strike_js["lat"], strike_js["lon"])))
        dets.sort()
        # Median detector distance - use dets[floor(len(dets)/2.0)]
        # Second farthest detector distance - user dets[len(dets)-2]

        strike = {"time": strike_js["time"] / 1e9, "lat": strike_js["lat"], "lon": strike_js["lon"], "dist": utilities.get_distance((strike_js["lat"], strike_js["lon"]), (float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))), "radius": dets[len(dets) - 2]}
        # print(strike)
        self.strikes.append(strike)

    def onError(self, ws, err):
        logging.error(f"Websocket Error: {err}")
        self.connected.value = 0
        # self.close()

    def onClose(self, ws, close_status_code="", close_msg=""):
        logging.debug(f"Websocket Closed: {close_status_code} : {close_msg}")
        self.connected.value = 0
        # self.close()

    def onOpen(self, ws):

        logging.debug("Opening Websocket connection to the server ... ")

        # detect connect info

        # Fetch the JavaScript file from the URL
        url = "https://www.blitzortung.org/en/JS/live_lightning_maps.js"
        response = requests.get(url)

        heartbeatmode = None
        heartbeatkey = None
        heartbeatinterval = None
        modestrings = None
        keyvalues = None

        if response and response.status_code == requests.codes.ok:
            js_code = response.text

            # Define regular expressions to match the patterns
            onopen_pattern = re.compile(r"ws\.onopen\s*=\s*function\s*\(\s*evt\s*\)\s*{(.*?)};", re.DOTALL)
            variable_assignment_pattern = re.compile(r"var\s+([\w\d]+)\s*=\s*(.*?);", re.DOTALL)
            setInterval_pattern = re.compile(r"setInterval\(\s*function\s*\(\)\s*{(.*?)\s*ws\.send\((.*?)\);\s*}\s*,\s*(\d+)\s*\);", re.DOTALL)

            # Find the onopen function and its contents
            onopen_match = onopen_pattern.search(js_code)
            if onopen_match:
                onopen_contents = onopen_match.group(1)

                # Check if setInterval is used within onopen as a heartbeat function
                setInterval_matches = setInterval_pattern.findall(onopen_contents)

                variable_matches = variable_assignment_pattern.findall(js_code)
                variable_values = {}
                for var_name, var_value in variable_matches:
                    variable_values[var_name] = var_value

                if setInterval_matches:
                    for setInterval_match in setInterval_matches:
                        heartbeat_contents = setInterval_match[1]
                        heartbeatinterval = int(int(setInterval_match[2]) / 1000)

                        # Replace variable instances in heartbeatkey
                        for var_name, var_value in variable_values.items():
                            heartbeat_contents = re.sub(r"(?<=[^a-zA-Z0-9_])" + var_name + r"(?![a-zA-Z0-9_])", str(var_value), heartbeat_contents)

                        heartbeatmode = re.findall(r"\{\"(.*?)\"\:", re.sub(r"\'", "", heartbeat_contents))[0]
                        heartbeatkey = re.findall(r"\:\"(.*?)\"\}", re.sub(r"\'", "", heartbeat_contents))[0]

                        heartbeatkey = re.sub(r"['+]", "", heartbeatkey)

                        # Convert ints to int and strip extra chars from strings
                        if '"' not in heartbeatkey:
                            try:
                                heartbeatkey = int(heartbeatkey)
                            except:
                                heartbeatkey = re.sub(r"\w*(ws|server)\w*", self.ws_server, heartbeatkey, flags=re.IGNORECASE)
                        else:
                            heartbeatkey = re.sub(r"\"", "", heartbeatkey)

                # Replace variable instances in onopen_contents
                for var_name, var_value in variable_values.items():
                    onopen_contents = re.sub(r"(?<=[^a-zA-Z0-9_])" + var_name + r"(?![a-zA-Z0-9_])", str(var_value), onopen_contents)

                # Find modestrings based on ws.send calls
                modestrings = re.findall(r"ws\.send\(.*?\"(.*?)\".*?\);(?![^{]*\})", onopen_contents)
                keyvalues = re.findall(r"ws\.send\(.*?\:(.*?)\}.*?\);(?![^{]*\})", onopen_contents)

                # Replace ws_server variable with the selected server url
                keyvalues = [re.sub(r"\+\w*(ws|server)\w*\+", self.ws_server, k) for k in keyvalues]

                modestrings = [re.sub(r"['+]", "", m) for m in modestrings]
                keyvalues = [re.sub(r"['+]", "", k) for k in keyvalues]

                # Convert ints to int and strip extra chars from strings
                keyvalues = [int(k) if '"' not in k else re.sub(r"\"", "", k) for k in keyvalues]

        if modestrings:
            for m, k in zip(modestrings, keyvalues):
                tmp = {}
                tmp[m] = k
                logging.debug(f"Connect string found: {tmp}")
                json_data = json.dumps(tmp)
                ws.send(json_data)
            self.connected.value = 1
        else:
            logging.debug("Problem finding connect info")
            self.connected.value = 0

        if heartbeatmode and heartbeatinterval:

            def heartbeat(*args):
                tmp = {}
                tmp[heartbeatmode] = heartbeatkey
                while True:
                    json_data = json.dumps(tmp)
                    time.sleep(heartbeatinterval)
                    ws.send(json_data)

            thread.start_new_thread(heartbeat, ())

    def close(self):
        # if self.connected.value == 1:
        #    self.ws.close()
        if self.thread and self.thread.is_alive():
            self.thread.terminate()

    def draw(self):

        mode = shared_config.shared_lightning_mode.value
        if mode == 2:
            local = True
            closest_mode = False
        elif mode == 3:
            local = False
            closest_mode = True
        else:
            local = False
            closest_mode = False

        now = time.time()

        # print(self.strikes)
        x = []
        y = []
        c = np.empty((0, 3), int)

        strikescopy = sorted(self.strikes, key=lambda k: k["dist"])
        closest = strikescopy

        closest1 = None
        closest2 = None
        closest3 = None

        for strike in closest:
            if closest3 != None:
                break
            if strike["time"] + 60 <= now:  # too old to show in close list
                continue
            if local and strike["dist"] > 250:  # too far to show for local mode
                break
            if closest1 == None or strike["dist"] <= closest1["dist"]:
                closest3 = closest2
                closest2 = closest1
                closest1 = strike
            elif closest2 == None or strike["dist"] <= closest2["dist"]:
                closest3 = closest2
                closest2 = strike
            elif closest3 == None or strike["dist"] <= closest3["dist"]:
                closest3 = strike

        if local:
            # Local mode only considers strikes within 250 miles
            strikescopy = sorted(filter(lambda n: n["dist"] < 250, strikescopy), key=lambda k: k["time"], reverse=True)
        else:
            # USA and Closest mode list all strikes, not just nearby strikes
            strikescopy = sorted(strikescopy, key=lambda k: k["time"], reverse=True)

        recent = strikescopy
        oldest = recent.copy()
        oldest.reverse()

        numstrikes = 0
        for strike in recent:
            if strike["time"] + 300 > now:  # strike within last 5 mins
                numstrikes += 1
            else:
                break

        lightningmap = None
        center_x_merc = None
        center_y_merc = None

        zoomind = shared_config.shared_lightning_zoomind.value

        if local:
            self.background = self.backgrounds[zoomind]
        elif closest_mode:
            if closest1:
                x_merc, y_merc = mercator_proj(closest1["lat"], closest1["lon"])
                bg, center_x, center_y = self.genDynamicBackground(x_merc, y_merc, zoomind)
                self.background = bg
            else:
                # No closest strike - just show the local map
                center_x, center_y = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
                self.background = self.backgrounds[zoomind]
        else:
            self.background = self.usa

        if self.background:
            lightningmap = self.background.copy()
            draw = ImageDraw.Draw(lightningmap)

        if lightningmap:
            # Draw our home location in blue
            if local:
                # Map is centered on us
                x = self.bgwidth / 2
                y = self.bgheight / 2
            elif closest_mode:
                # Map is centered on a dynamically generated map point (which may not
                # be the current closest strike due to caching)
                x, y = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
                zoom_scale = self.zooms[zoomind]
                x = self.bgwidth / 2 + (x - center_x) * zoom_scale
                y = self.bgheight / 2 - (y - center_y) * zoom_scale
            else:
                x, y = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
                x = self.bgwidth / 2 + (x - self.x0) * USAscale
                y = self.bgheight / 2 - (y - self.y0) * USAscale
            draw.point([x, y], fill=(0, 0, 255))

        if oldest:
            for strike in oldest:
                strike_time = strike["time"]

                if strike_time > now:  # desync in server and local clock
                    continue
                elif strike_time + 600 <= now:
                    self.strikes.remove(strike)  # strike hit more than 10 mins ago
                    continue
                else:
                    color = get_lightning_color(strike_time, now, True)

                if lightningmap:
                    x, y = mercator_proj(strike["lat"], strike["lon"])
                    if local:
                        x = self.bgwidth / 2 + (x - self.x1) * self.zooms[zoomind]
                        y = self.bgheight / 2 - (y - self.y1) * self.zooms[zoomind]
                    elif closest_mode:
                        zoom_scale = self.zooms[zoomind]
                        x = self.bgwidth / 2 + (x - center_x) * zoom_scale
                        y = self.bgheight / 2 - (y - center_y) * zoom_scale
                    else:
                        x = self.bgwidth / 2 + (x - self.x0) * USAscale
                        y = self.bgheight / 2 - (y - self.y0) * USAscale
                    draw.point([x, y], fill=color)

        if lightningmap:
            self.sign.canvas.SetImage(lightningmap.convert("RGB"), 64, 0)

        for i in range(32):
            self.sign.canvas.SetPixel(64, i, 50, 50, 200)
        # 110, 170, 45   110, 45, 170   70, 70, 215  100,100,100

        graphics.DrawText(self.sign.canvas, self.sign.font46, 1, 6, graphics.Color(20, 20, 210), "Closest")
        if closest1:
            r, g, b = get_lightning_color(closest1["time"], now, False)
            closest1_dist_str = "{0:.1f}".format(closest1["dist"])
            if len(closest1_dist_str) > 4:
                closest1_dist_str = "{0:.0f}".format(closest1["dist"])
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(r, g, b), closest1_dist_str)
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2 + len(closest1_dist_str) * 5, 14, graphics.Color(110, 170, 45), utilities.direction_lookup((closest1["lat"], closest1["lon"]), (float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))))
            draw_power(0, 14, closest1["radius"], self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(70, 70, 215), "----")

        if closest2:
            r, g, b = get_lightning_color(closest2["time"], now, False)
            closest2_dist_str = "{0:.1f}".format(closest2["dist"])
            if len(closest2_dist_str) > 4:
                closest2_dist_str = "{0:.0f}".format(closest2["dist"])
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(r, g, b), closest2_dist_str)
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2 + len(closest2_dist_str) * 5, 22, graphics.Color(110, 170, 45), utilities.direction_lookup((closest2["lat"], closest2["lon"]), (float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))))
            draw_power(0, 22, closest2["radius"], self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(70, 70, 215), "----")

        if closest3:
            r, g, b = get_lightning_color(closest3["time"], now, False)
            closest3_dist_str = "{0:.1f}".format(closest3["dist"])
            if len(closest3_dist_str) > 4:
                closest3_dist_str = "{0:.0f}".format(closest3["dist"])
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(r, g, b), closest3_dist_str)
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2 + len(closest3_dist_str) * 5, 30, graphics.Color(110, 170, 45), utilities.direction_lookup((closest3["lat"], closest3["lon"]), (float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))))
            draw_power(0, 30, closest3["radius"], self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(70, 70, 215), "----")

        graphics.DrawText(self.sign.canvas, self.sign.font46, 34, 6, graphics.Color(20, 20, 210), "Recent")
        if recent:
            recent_dist_str = "{0:.1f}".format(recent[0]["dist"])
            if len(recent_dist_str) > 6:
                recent_dist_str = f"{round(recent[0]['dist'] / 1000)}k"
            elif len(recent_dist_str) > 4:
                recent_dist_str = "{0:.0f}".format(recent[0]["dist"])
            # 180,180,40
            graphics.DrawText(self.sign.canvas, self.sign.font57, 34, 14, graphics.Color(180, 180, 40), recent_dist_str)
            graphics.DrawText(self.sign.canvas, self.sign.font57, 34 + len(recent_dist_str) * 5, 14, graphics.Color(110, 170, 45), utilities.direction_lookup((recent[0]["lat"], recent[0]["lon"]), (float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))))
            draw_power(32, 14, recent[0]["radius"], self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 34, 14, graphics.Color(70, 70, 215), "----")

        if local:
            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 22, graphics.Color(20, 20, 210), "#")
            graphics.DrawText(self.sign.canvas, self.sign.font46, 39, 22, graphics.Color(20, 20, 210), "Near")
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 22, graphics.Color(20, 20, 210), "#")
            graphics.DrawText(self.sign.canvas, self.sign.font46, 39, 22, graphics.Color(20, 20, 210), "Global")
        self.sign.canvas.SetPixel(32, 18, 20, 20, 210)  # fix the janky looking # symbol
        self.sign.canvas.SetPixel(32, 20, 20, 20, 210)  # fix the janky looking # symbol

        graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 30, graphics.Color(180, 180, 40), str(numstrikes))

        if closest1 and closest1["dist"] < 2 and closest1["time"] + 30 > now and ("warned" not in closest1):
            logging.info(f"LIGHTNING STRIKE DANGER: Strike detected {closest1['dist']} miles away!")
            self.strikes[self.strikes.index(closest1)]["warned"] = True
            old = self.sign.matrix.SwapOnVSync(self.sign.canvas)
            for j in range(6):
                if j % 2 == 0:
                    for i in range(32):
                        self.sign.canvas.SetPixel(64, i, 200, 0, 0)
                        self.sign.canvas.SetPixel(127, i, 200, 0, 0)
                    for i in range(65, 127):
                        self.sign.canvas.SetPixel(i, 0, 200, 0, 0)
                        self.sign.canvas.SetPixel(i, 31, 200, 0, 0)
                else:
                    for i in range(32):
                        self.sign.canvas.SetPixel(64, i, 50, 50, 200)
                        self.sign.canvas.SetPixel(127, i, 0, 0, 0)
                    for i in range(65, 127):
                        self.sign.canvas.SetPixel(i, 0, 0, 0, 0)
                        self.sign.canvas.SetPixel(i, 31, 0, 0, 0)

                self.sign.wait_loop(0.2)

            self.sign.canvas = old

        else:
            self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)

        self.sign.canvas.Clear()

        self.last_drawn_zoomind.value = zoomind
        self.last_drawn_mode.value = mode

    def connect(self):

        if not self.connected.value:
            self.connected.value = 2
            try:
                ws_servers = ["ws1.blitzortung.org", "ws7.blitzortung.org", "ws8.blitzortung.org"]

                self.ws_server = ws_servers[random.randint(0, len(ws_servers) - 1)]

                self.ws_key = base64.b64encode(os.urandom(16)).decode("ascii")

                self.host = "wss://" + self.ws_server  #'wss://' + self.ws_server + ':3000'

                self.header = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:99.0) Gecko/20100101 Firefox/99.0",
                    "Accept": "*/*",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Extensions": "permessage-deflate",
                    "Sec-WebSocket-Key": self.ws_key,
                    "Connection": "keep-alive, Upgrade",
                    "Sec-Fetch-Dest": "websocket",
                    "Sec-Fetch-Mode": "websocket",
                    "Sec-Fetch-Site": "same-site",
                    "Pragma": "no-cache",
                    "Cache-Control": "no-cache",
                    "Upgrade": "websocket",
                }

                websocket.enableTrace(False)

                self.ws = websocket.WebSocketApp(self.host, on_message=lambda ws, message: self.onMessage(ws, message), on_error=self.onError, on_close=self.onClose, on_open=self.onOpen, header=self.header)

                # self.ws.on_open = self.onOpen

                logging.debug(f"Connecting to blitzortung server: {self.ws_server}...")

                self.thread = Process(target=self.ws.run_forever, kwargs={"host": self.ws_server, "origin": "https://map.blitzortung.org", "sslopt": {"cert_reqs": ssl.CERT_NONE}})
                self.thread.daemon = True
                self.thread.start()

                logging.debug("Websocket thread started.")

            except Exception as e:
                logging.error(f"Websocket Exception: {e}")
                self.connected.value = 0
