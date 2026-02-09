#!/usr/bin/python3
# -*- coding: utf-8 -*-

import logging.handlers
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import urlparse
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont, GifImagePlugin
from bs4 import BeautifulSoup
import random
import shared_config
from math import ceil
import re
import time
from datetime import datetime, timedelta
from functools import cmp_to_key
import os
import json
from enum import Enum
from utilities import CM_2_IN, convert_c_to_f, getFavicon, weather_icon_decode, acquire_lock, release_lock
import __main__
from modes import DisplayMode


resortinfo_filename = f"{shared_config.datafiles_dir}/resortdata.json"
userresorts_filename = f"{shared_config.datafiles_dir}/resortlist.txt"

class SnowMode(Enum):
    STATIC = 0
    ROTATE = 1
    OVERVIEW = 2

def load_user_list():
    # Load the user's saved resorts
    resort_list = []
    if os.path.isfile(userresorts_filename):  

        acquire_lock(userresorts_filename)
        try:
            with open(userresorts_filename, "r") as file:
                resort_list = [line.rstrip() for line in file]
                logging.debug(f"Loaded user resort list: {resort_list}")
        except Exception as e:
            logging.error(f"Error reading {userresorts_filename}: {e}")
        finally:
            release_lock(userresorts_filename)
    else:
        logging.debug(f"No user resort list to read.")

    shared_config.data_dict["user_resorts"] = resort_list
    return

def save_current_resort():
    if (shared_config.shared_snow_mode.value != SnowMode.STATIC.value):
        return

    # Save the currently displayed resort
    uuid = shared_config.data_dict["displayed_resort"]
    if uuid == "" or uuid == None:
        return

    acquire_lock(userresorts_filename)
    try:
        with open(userresorts_filename, "a+") as file:
            resort_list = [line.rstrip() for line in file]
            if (uuid not in resort_list):
                file.write(uuid + "\n")
                logging.debug(f"Saving resort uuid: {uuid}")
    except Exception as e:
        logging.error(f"Error saving uuid {uuid} to {userresorts_filename}: {e}")
    finally:
        release_lock(userresorts_filename)
    return

def delete_user_resort(uuid):
    acquire_lock(userresorts_filename)
    try:
        with open(userresorts_filename, "r+") as file:
            resort_list = [line.rstrip() for line in file]
            if (uuid in resort_list):
                logging.debug(f"Deleting resort uuid: {uuid}")
                resort_list.remove(uuid)
                file.seek(0)
                for res in resort_list:
                    file.write(res + "\n")
                file.truncate()
    except Exception as e:
        logging.error(f"Error deleting uuid {uuid} from {userresorts_filename}: {e}")
    finally:
        release_lock(userresorts_filename)
    return

def populate_resort_lists():

    if "resort_info" in shared_config.data_dict and \
       "resorts" in shared_config.data_dict["resort_info"] and\
       len(shared_config.data_dict["resort_info"]["resorts"]) > 0 and \
       datetime.now() < datetime.fromtimestamp(shared_config.data_dict["resort_info"]["last_update"]) + timedelta(days=30):

        # No need to update 
        return

    # First check for locally saved data:
    if os.path.isfile(resortinfo_filename):

        success = False            
        try:
            with open(resortinfo_filename, 'r') as file:
                info = json.load(file)
                if "last_update" in info and datetime.now() <= datetime.fromtimestamp(info["last_update"]) + timedelta(days=30):
                    # Data is still valid
                    if "resorts" in info and len(info["resorts"]) > 0:
                        shared_config.data_dict["resort_info"] = info
                        success = True
                    else:
                        logging.error(f"Error in {resortinfo_filename} saved data.")
                else:
                    logging.debug(f"Data in {resortinfo_filename} no longer valid.")
        except Exception as e:
            logging.error(f"Error reading {resortinfo_filename}: {e}")

        if success:
            return

    # Need to get data from web. Start from scratch
    resort_info = {}

    logging.debug(f"Getting available ski resort list jsons from internet.")

    headers = {
        "Host": "www.onthesnow.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Referer": "https://www.onthesnow.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin"
    }

    session = requests.Session()
    session.headers.update(headers)

    allresorts_url = "https://www.onthesnow.com/index/resorts-en-US.json"
    allresorts_response = session.get(allresorts_url, timeout=10)
    if allresorts_response.status_code == requests.codes.ok:
        resort_info["resorts"] = json.loads(allresorts_response.text)
    else:
        resort_info["resorts"] = None
        logging.error(f"Error getting resort list from url: {allresorts_url}")

    altnames_url = "https://www.onthesnow.com/index/resorts-alt-en-US.json"
    altnames_response = session.get(altnames_url, timeout=10)
    if altnames_response.status_code == requests.codes.ok:
        resort_info["alt_names"] = json.loads(altnames_response.text)
    else:
        resort_info["alt_names"] = None
        logging.error(f"Error getting alternate names list from url: {altnames_url}")

    misspellings_url = "https://www.onthesnow.com/index/resorts-misspellings-en-US.json"
    misspellings_response = session.get(misspellings_url, timeout=10)
    if misspellings_response.status_code == requests.codes.ok:
        resort_info["misspellings"] = json.loads(misspellings_response.text)
    else:
        resort_info["misspellings"] = None
        logging.error(f"Error getting misspellings list from url: {misspellings_url}")

    if resort_info["resorts"] != None and len(resort_info["resorts"]) > 0:
        # Data is good enough

        resort_info["last_update"] = datetime.now().timestamp()
        shared_config.data_dict["resort_info"] = resort_info
        try:
            with open(resortinfo_filename, 'w', encoding='utf-8') as f:
                json.dump(resort_info, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"Error saving data to file {resortinfo_filename}: {e}")

    else:
        shared_config.data_dict["resort_info"] = {}
        logging.error("Problem getting ski resort list jsons from the internet.")    

def draw_loading(sign):
   
    gif = Image.open(f"{shared_config.icons_dir}/snow/snow.gif")

    nf = gif.n_frames
    frame=0
    sign.canvas.Clear()
    # Potentially also pre-load user resort list data in a separate thread and check for that here also
    while not("resort_info" in shared_config.data_dict and \
              "resorts" in shared_config.data_dict["resort_info"] and\
              len(shared_config.data_dict["resort_info"]["resorts"]) > 0 and \
              datetime.now() < datetime.fromtimestamp(shared_config.data_dict["resort_info"]["last_update"]) + timedelta(days=30)):

        gif.seek(frame)

        image = Image.new("RGB", gif.size, (255, 255, 255))
        image.paste(gif, (0,0))

        sign.canvas.SetImage(image.resize((128, 64), Image.BICUBIC).convert('RGB'), 1, -15)
        for i in range(-1,2):
            for j in range(-1,2):
                graphics.DrawText(sign.canvas, sign.fontbig, 7+i, 12+j, graphics.Color(0,0,0), "Loading...")
        graphics.DrawText(sign.canvas, sign.fontbig, 7, 12, graphics.Color(255,255,255), "Loading...")

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        frame = (frame+1)%nf
        
        breakout = sign.wait_loop(1.0)

        if breakout:
            return breakout

    return False

def mapIcon(i):
    if (i == "PARTLY_CLOUDY") or (i == "SLIGHTLY_CLOUDY") or (i == "MOSTLY_SUNNY"):
        return "cloudpart"
    elif (i == "CLOUDY"):
        return "cloud"
    elif (i == "OVERCAS"):
        return "cloudheavy"
    elif (i == "LIGHT_RAI"):
        return "rainlight"
    elif (i == "RAIN"):
        return "rain"
    elif (i == "RAIN_SHOWERS"):
        return "rainheavy"
    elif (i == "SNOW") or (i == "SNOW_SHOWERS") or (i == "SLEET") or (i == "SLEET_SHOWERS"):
        return "snow"
    elif (i == "FOG"):
        return "haze"
    elif (i == "SUN") or (i == "SUNNY") or (i == "FAIR"):
        return "clear"
    elif (i == "LUNE"):
        return "lune"
    elif (i == "THUNDERSTORM"):
        return "thunder"
    else:
        return None

def compute_display_name (resdata, desired_length):

    nameopts = set()

    nameopts.add(resdata["title"])

    # Check short name from valid resorts info
    if "resorts" in shared_config.data_dict["resort_info"] and len(shared_config.data_dict["resort_info"]["resorts"]) > 0:

        info = next((res for res in shared_config.data_dict["resort_info"]["resorts"] if res['uuid'] == resdata['uuid']), None)
    
    if info != None and "title_short" in info and info["title_short"]:
        nameopts.add(info["title_short"])

    if info != None and "title_original" in info and info["title_original"]:
        nameopts.add(info["title_original"])

    # Check various subsitution combos
    optlist = list(nameopts)
    nopts = len(optlist)
    lastnopts = None

    def fixWhitespace(string):
        return string.replace("  "," ").strip()

    while (lastnopts == None or nopts != lastnopts):
        
        for name in optlist:
            nameopts.add(fixWhitespace(name.replace("Mountain", "Mtn.")))
            nameopts.add(fixWhitespace(name.replace("Mountain", "Mt.")))
            nameopts.add(fixWhitespace(name.replace("Mountain", "")))
            nameopts.add(fixWhitespace(name.replace("Resort", "Res.")))
            nameopts.add(fixWhitespace(name.replace("Resort", "")))
            nameopts.add(fixWhitespace(name.replace("Ski & Snowboard Area","")))
            
        lastnopts = nopts
        optlist = list(nameopts)
        nopts = len(optlist)

    def compare(item1, item2):
        l1 = len(item1)
        l2 = len(item2)
        d1 = l1 - desired_length
        d2 = l2 - desired_length
        if (d1 <= 0 and d2 > 0):
            # Prefer fitting over too long
            return -1
        elif (d1 > 0 and d2 <= 0):
            # Prefer fitting over too long
            return 1
        elif (d1 > 0 and d2 > 0):
            # Both too long, prefer less abbreviations
            c1 = item1[:desired_length].count(".")
            c2 = item2[:desired_length].count(".")
            return c1 - c2
        else:
            # Both are shorter than desired, prefer longer
            return l2 - l1

    optlist = list(nameopts)
    names_sorted = sorted(optlist, key=cmp_to_key(compare))

    return names_sorted[0]

def snowcolor(inches):

    if inches == "-" or inches == "--" or inches == "?":
        return graphics.Color(50, 50, 50)

    inches = float(inches)

    if inches < 1.0:
        color =  graphics.Color(150, 150, 150)
    elif inches >= 6.0:
        color = graphics.Color(229, 119, 0)
    else:
        color =  graphics.Color(66, 151, 213)
        
    return color

class SnowReport:
    def __init__(self,sign):
        self.sign = sign
        self.resorts = []

    def drawresort(self, res_id):

        resort = self.update(res_id)

        if resort != None:
            if resort['isOpen']:
                color = graphics.Color(10, 150, 10)
            else:
                color = graphics.Color(100, 10, 10)

            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 46-round(len(resort['displayName'][:15])*3), 10, color, resort['displayName'][:15])

            if "logo" in resort and resort["logo"] != None:
                sizex, sizey = resort['logo'].size
                x = 12-round(sizex/2)
                y = 22-round(sizey/2)
                self.sign.canvas.SetImage(resort['logo'], x, y)
            
            graphics.DrawText(self.sign.canvas, self.sign.font57, 24, 20, graphics.Color(100, 10, 10), "New:")

            snownew = resort['new']
            if snownew == None:
                snownew = "?"
            else:
                snownew = str(round(snownew))
            graphics.DrawText(self.sign.canvas, self.sign.font57, 45, 20, snowcolor(snownew), snownew+'"')

            weather = resort["weather"]

            currtemp = "?°F"
            if "currTemp" in weather and weather["currTemp"] != None:
                currtemp = f"{round(weather['currTemp'])}°F"

            graphics.DrawText(self.sign.canvas, self.sign.font57, 40-round(len(currtemp)*5/2), 30, graphics.Color(60, 60, 200), currtemp)
            
            if "currWeatherIcon" in weather and weather["currWeatherIcon"]:
                image = weather["currWeatherIcon"]

                width, height = image.size
                if width > height:
                    image = image.resize((10, int(10*height/width)), Image.BICUBIC)
                elif height > width:
                    image = image.resize((int(10*width/height), 10), Image.BICUBIC)
                else:
                    image = image.resize((10, 10), Image.BICUBIC)

                sizex, sizey = image.size
                x = 40+round(len(currtemp)*5/2)+1
                y = 26-round(sizey/2)
                self.sign.canvas.SetImage(image, x, y)

            snow4d = None
            snow8d = None

            graphx = 66
            graphy = 30
            graphw = 6
            num_bars = 8
            offset = 0

            graphend = graphx+num_bars*(graphw+1)
            graphics.DrawLine(self.sign.canvas, graphx-1, graphy+1, graphend+1, graphy+1, graphics.Color(13, 13, 25))
            for i in range(num_bars):
                # Daily forecast
                forecast = resort['forecast'][i+7]
                if "snowfall" in forecast:
                    snowfall = forecast["snowfall"] * CM_2_IN
                else:
                    snowfall = None

                if snowfall != None:
                    if i < round(num_bars/2):
                        if snow4d == None:
                            snow4d = snowfall
                        else:
                            snow4d += snowfall
                    else:
                        if snow8d == None:
                            snow8d = snowfall
                        else:
                            snow8d += snowfall
                
                if i== 4:
                    offset = 2

                if snowfall and snowfall > 0.0:
                    barheight = ceil(snowfall/2)
                    for j in range(barheight):
                        if j >= 10:
                            break
                        startx = offset+graphx+i*(graphw+1)
                        graphics.DrawLine(self.sign.canvas, startx, graphy-j, startx+graphw-1, graphy-j, snowcolor(snowfall))

            if snow4d != None:
                snow4d = str(round(snow4d))
            else:
                snow4d = "?"

            if snow8d != None:
                snow8d = str(round(snow8d))
            else:
                snow8d = "?"

            liney = 17
            x4d = graphx-1 + round((num_bars/4)*(graphw+1) + 0.5 - (len(snow4d)+1)*5/2)
            x8d = graphx-1 + round((3*num_bars/4)*(graphw+1)+2 + 0.5 - (len(snow8d)+1)*5/2)
            middlex = round(graphx-1 + num_bars/2*(graphw+1) + 1)
            graphics.DrawLine(self.sign.canvas, graphx-2, liney, x4d-2, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x4d+1+(len(snow4d)+1)*5, liney, x8d-2, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x8d+1+(len(snow8d)+1)*5, liney, graphend+1, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, graphx-2, liney-3, graphx-2, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, middlex, liney-3, middlex, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, graphend+2, liney-3, graphend+2, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawText(self.sign.canvas, self.sign.font57, x4d, liney+3, snowcolor(snow4d), snow4d+'"')
            graphics.DrawText(self.sign.canvas, self.sign.font57, x8d, liney+3, snowcolor(snow8d), snow8d+'"')

            # Draw small Sun icon
            sunx=93
            suny=1

            self.sign.canvas.SetPixel(sunx+1, suny+1, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx+2, suny+1, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx+3, suny+1, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx+1, suny+2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx+2, suny+2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx+3, suny+2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx+1, suny+3, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx+2, suny+3, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx+3, suny+3, 185, 120, 0)

            self.sign.canvas.SetPixel(sunx, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx+2, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx+4, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx, suny+2, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx+4, suny+2, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx, suny+4, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx+2, suny+4, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx+4, suny+4, 180, 65, 0)

            minTemp = "?"
            maxTemp = "?"
            if "dayLow" in weather and weather["dayLow"] != None:
                minTemp = round(weather["dayLow"])
            if "dayHigh" in weather and weather["dayHigh"] != None:
                maxTemp = round(weather["dayHigh"])

            graphics.DrawText(self.sign.canvas, self.sign.font46, sunx+7, suny+5, graphics.Color(95, 95, 105), f"{minTemp}-{maxTemp}°F")

            # Draw small Moon icon
            moonx = 93
            moony = 7

            self.sign.canvas.SetPixel(moonx+1, moony, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx+2, moony, 103, 111, 116)
            self.sign.canvas.SetPixel(moonx+3, moony, 31, 33, 34)
            self.sign.canvas.SetPixel(moonx, moony+1, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx+1, moony+1, 113, 122, 116)
            self.sign.canvas.SetPixel(moonx+2, moony+1, 31, 33, 35)
            self.sign.canvas.SetPixel(moonx, moony+2, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx+1, moony+2, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx+2, moony+2, 18, 19, 20)
            self.sign.canvas.SetPixel(moonx, moony+3, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx+1, moony+3, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx+2, moony+3, 81, 87, 91)
            self.sign.canvas.SetPixel(moonx+1, moony+4, 92, 100, 104)
            self.sign.canvas.SetPixel(moonx+2, moony+4, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx+3, moony+4, 92, 100, 104)

            minTemp = "?"
            maxTemp = "?"
            if "nightLow" in weather and weather["nightLow"] != None:
                minTemp = round(weather["nightLow"])
            if "nightHigh" in weather and weather["nightHigh"] != None:
                maxTemp = round(weather["nightHigh"])

            graphics.DrawText(self.sign.canvas, self.sign.font46, moonx+7, moony+5, graphics.Color(95, 95, 105), f"{minTemp}-{maxTemp}°F")

    def drawoverview(self, res_id, user_list):

        n = len(user_list)
        currently_displayed = res_id

        start_index = -1
        found = False
        for uuid in user_list:
            start_index += 1
            if currently_displayed == uuid:
                found = True
                break

        if not found:
            if n > 0:
                start_index = random.randint(0, n)
            else:
                # Do not want to be in this mode if we have no saved user resorts
                shared_config.shared_snow_mode.value = SnowMode.STATIC.value
                drawresort(currently_displayed)
                return

        numdisplay = min(4, n)
        display_ids = []
        index = start_index
        for i in range(numdisplay):
            display_ids.append(user_list[index])
            index = (index+1)%n

        offset = 0
        for res_id in display_ids:

            resort = self.update(res_id)

            if resort != None:

                if resort["isOpen"]:
                    color = graphics.Color(40, 167, 69)
                else:
                    color = graphics.Color(115, 18, 15)

                graphics.DrawText(self.sign.canvas, self.sign.font57, 1, 7+offset, color, resort['displayName'][:15])
                
                graphics.DrawLine(self.sign.canvas, 94, 0, 94, 31, graphics.Color(13, 13, 25))

                snownew = resort['new']
                if snownew == None:
                    snownew = "?"
                else:
                    snownew = str(round(snownew))

                snow4d = None
                snow8d = None
                for i in range(8):
                    # Daily forecast
                    forecast = resort['forecast'][i+7]
                    if "snowfall" in forecast:
                        snowfall = forecast["snowfall"] * CM_2_IN
                    else:
                        snowfall = None

                    if snowfall != None:
                        if i < 4:
                            if snow4d == None:
                                snow4d = snowfall
                            else:
                                snow4d += snowfall
                        else:
                            if snow8d == None:
                                snow8d = snowfall
                            else:
                                snow8d += snowfall
                if snow4d != None:
                    snow4d = str(round(snow4d))
                else:
                    snow4d = "?"

                if snow8d != None:
                    snow8d = str(round(snow8d))
                else:
                    snow8d = "?"
                
                graphics.DrawText(self.sign.canvas, self.sign.font57, 86-round((len(snownew)+1)*5/2), 7+offset, snowcolor(snownew), snownew+'"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 104-round((len(snow4d)+1)*5/2), 7+offset, snowcolor(snow4d), snow4d+'"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 121-round((len(snow8d)+1)*5/2), 7+offset, snowcolor(snow8d), snow8d+'"')

                offset += 8

    def update(self, res_id):

        if not res_id:
            return None

        data_update_interval = timedelta(minutes=20)

        # Do we already have data stored?
        resort = next((res for res in self.resorts if res['uuid'] == res_id), None)

        if resort == None:
            # Need to add resort to list
            resort = {}

            # Need to construct the report url using the resort's region and slug.
            # Find the resort with the matching uuid in the global json list

            # Make sure our lists are up to date
            populate_resort_lists()

            info = None
            if "resorts" in shared_config.data_dict["resort_info"] and len(shared_config.data_dict["resort_info"]["resorts"]) > 0:

                info = next((res for res in shared_config.data_dict["resort_info"]["resorts"] if res['uuid'] == res_id), None)
            
            if info == None:
                # Updating the resort list failed or the specified uuid is not listed. Give up!
                logging.error(f"Error getting resort with uuid={res_id} from resort list.")
                return None

            reporturl = f"https://www.onthesnow.com/{info['region']}/{info['slug']}/skireport"

            resort["url"]   = reporturl
            resort["uuid"]  = res_id

            logging.debug(f"Creating new data for uuid: {res_id}")

            # Save this data for recall later
            self.resorts.append(resort)
        else:
            # Found resort in list.
            if "last_update" in resort and datetime.now() < datetime.fromtimestamp(resort["last_update"]) + data_update_interval:
                # Data is still valid
                return resort

            # Need to update the data
            reporturl = resort["url"]

        logging.debug(f"Updating data for uuid: {res_id} using url: {reporturl}")

        report_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
            "Host": "www.onthesnow.com",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-GPC": "1"
            }

        with requests.Session() as s:
            response = s.get(reporturl, headers = report_headers, timeout=10)
            if response and response.status_code == requests.codes.ok:
                
                soup = BeautifulSoup(response.content, "html.parser")
                datatxt = soup.find('script', {'id':'__NEXT_DATA__'}).text
                data = json.loads(datatxt)

                buildID = data["buildId"]
                resortdata = data["props"]["pageProps"]["fullResort"]
                neardata = data["props"]["pageProps"]["nearbyResorts"]
                
                # Workaround
                for res in neardata:
                    if (resort["uuid"] == res["uuid"]):
                        resortdata = res
                        break

                resort["name"]      = resortdata["title"]

                resort["displayName"] = compute_display_name(resortdata, 15)

                resort["slug"]      = resortdata["slug"]
                resort["isOpen"]    = resortdata["status"]["openFlag"]
                resort["runsOpen"]  = resortdata["runs"]["open"]
                resort["runsTotal"] = resortdata["runs"]["total"]

                snowbase = None
                if "base" in resortdata["snow"] and resortdata["snow"]["base"] != None:
                    snowbase = resortdata["snow"]["base"] * CM_2_IN

                snowmid = None
                if "middle" in resortdata["snow"] and resortdata["snow"]["middle"] != None:
                    snowmid = resortdata["snow"]["middle"] * CM_2_IN

                snowpeak = None
                if "summit" in resortdata["snow"] and resortdata["snow"]["summit"] != None:
                    snowpeak = resortdata["snow"]["summit"] * CM_2_IN

                snownew = None
                if "last24" in resortdata["snow"] and resortdata["snow"]["last24"] != None:
                    snownew = resortdata["snow"]["last24"] * CM_2_IN

                resort["snowBase"]  = snowbase
                resort["snowMid"]   = snowmid
                resort["snowPeak"]  = snowpeak
                resort["new"]       = snownew
                resort["forecast"]  = resortdata["weather"]

                weather = {}
                weather["currTemp"] = None
                weather["currWeatherIcon"] = None
                weather["dayLow"] = None
                weather["dayHigh"] = None
                weather["nightLow"] = None
                weather["nightHigh"] = None
        
                weather_url = f"https://www.onthesnow.com/_next/data/{buildID}/{resortdata['region']['slug']}/{resortdata['slug']}/weather.json"
                
                weather_headers = report_headers
                weather_headers["Referer"] = reporturl[:-9]+"weather"
                    
                session = requests.Session()
                session.headers.update(weather_headers)
                
                fallback = False
                try:
                    weather_response = session.get(weather_url, timeout=10)
                    if weather_response.status_code == requests.codes.ok:
                        weather_data = json.loads(weather_response.text)
                        weather_data = weather_data["pageProps"]

                        hourly = weather_data["weatherInfoHourly"]["weatherItems"]
                        current = hourly[0]

                        icon = None
                        if "mid" in current and "type" in current["mid"]:
                            icon = mapIcon(current["mid"]["type"])
                        elif "base" in current and "type" in current["base"]:
                            icon = mapIcon(current["base"]["type"])

                        if icon:
                            image = Image.open(f"{shared_config.icons_dir}/weather/{icon}.png").convert("RGB")
                            weather["currWeatherIcon"] = image

                        temp = None
                        if "mid" in current and "temp" in current["mid"]:
                            temp = current["mid"]["temp"]
                        elif "base" in current and "temp" in current["base"]:
                            temp = current["base"]["temp"]
                        
                        if temp:
                            mean = convert_c_to_f((temp["min"] + temp["max"])/2)
                            weather["currTemp"] = mean

                        for hour in hourly:
                            if "datetime" in hour and hour["datetime"] != None:
                                h = datetime.fromisoformat(hour["datetime"]).hour
                                temp = None

                                if "mid" in hour and "temp" in hour["mid"]:
                                    temp = hour["mid"]["temp"]
                                elif "base" in hour and "temp" in hour["base"]:
                                    temp = hour["base"]["temp"]

                                templow = None
                                temphigh = None
                                if temp:
                                    templow = temp["min"]
                                    temphigh = temp["max"]

                                if templow != None and temphigh != None:
                                    if (h <= 6 or h >=18):
                                        # Night 6pm - 7am
                                        if (weather["nightLow"] == None or templow < weather["nightLow"]):
                                            weather["nightLow"] = templow

                                        if (weather["nightHigh"] == None or temphigh > weather["nightHigh"]):
                                            weather["nightHigh"] = temphigh
                                    else:
                                        # Day
                                        if (weather["dayLow"] == None or templow < weather["dayLow"]):
                                            weather["dayLow"] = templow

                                        if (weather["dayHigh"] == None or temphigh > weather["dayHigh"]):
                                            weather["dayHigh"] = temphigh

                        if weather["dayHigh"] != None:
                            weather["dayHigh"] = convert_c_to_f(weather["dayHigh"])
                        if weather["nightHigh"] != None:
                            weather["nightHigh"] = convert_c_to_f(weather["nightHigh"])
                        if weather["dayLow"] != None:
                            weather["dayLow"] = convert_c_to_f(weather["dayLow"])
                        if weather["nightLow"] != None:
                            weather["nightLow"] = convert_c_to_f(weather["nightLow"])
                        
                    else:
                        fallback = True

                except Exception as e:
                    logging.json(f"Error getting resort weather data for {resort['name']} from url {weather_url}: {e}")
                    fallback = True

                if fallback:
                    # Fallback to openweathermap data
                    logging.debug(f"There was a problem getting weather data from {urlparse(weather_url).netloc}, attempting fallback back to openweathermap data.")
                    weather_data = None
                    if "OPENWEATHER_API_KEY" in shared_config.CONF:
                        try:
                            weather_data = requests.get(f"https://api.openweathermap.org/data/3.0/onecall?lat={resortdata['latitude']}&lon={resortdata['longitude']}&appid={shared_config.CONF['OPENWEATHER_API_KEY']}&exclude=minutely,hourly&units=imperial").json()
                        except:
                            logging.debug(f"Could not get weather data for resort {resort['name']} at: {resortdata['latitude']}°, {resortdata['longitude']}°.")
                    else:
                        logging.debug(f"No OPENWEATHER_API_KEY!")

                    if weather_data:

                        if "current" in weather_data:
                            if "temp" in weather_data["current"]:
                                weather["currTemp"] = weather_data['current']['temp']

                            if "weather" in weather_data["current"]:
                                try:
                                    icon,_ = weather_icon_decode(weather_data['daily'][0]['weather'][0]['id'],weather_data['daily'][0]['weather'][0]['main'])
                                    
                                    if (icon == "clear") and (weather_data["current"]["dt"] < weather_data["current"]["sunrise"] or weather_data["current"]["dt"] > weather_data["current"]["sunset"]):
                                        icon = "lune"

                                    image = Image.open(f"{shared_config.icons_dir}/weather/{icon}.png")

                                    weather["currWeatherIcon"] = image
                                except:
                                    pass

                        if "daily" in weather_data:

                            daily = weather_data["daily"]

                            for day in daily:
                                if "temp" in day and day["temp"] != None:
                                    
                                    daytemp = None
                                    morntemp = None
                                    nighttemp = None
                                    evetemp = None

                                    if "day" in day["temp"]:
                                        daytemp = day["temp"]["day"]

                                    if "morn" in day["temp"]:
                                        morntemp = day["temp"]["morn"]

                                    if "night" in day["temp"]:
                                        nighttemp = day["temp"]["night"]

                                    if "eve" in day["temp"]:
                                        evetemp = day["temp"]["eve"]

                                    if nighttemp:
                                        if (weather["nightLow"] == None or nighttemp < weather["nightLow"]):
                                            weather["nightLow"] = nighttemp
                                        if (weather["nightHigh"] == None or nighttemp > weather["nightHigh"]):
                                            weather["nightHigh"] = nighttemp

                                    if evetemp:
                                        if (weather["nightLow"] == None or evetemp < weather["nightLow"]):
                                            weather["nightLow"] = evetemp
                                        if (weather["nightHigh"] == None or evetemp > weather["nightHigh"]):
                                            weather["nightHigh"] = evetemp

                                    if daytemp:
                                        if (weather["dayLow"] == None or daytemp < weather["dayLow"]):
                                            weather["dayLow"] = daytemp
                                        if (weather["dayHigh"] == None or daytemp > weather["dayHigh"]):
                                            weather["dayHigh"] = daytemp

                                    if morntemp:
                                        if (weather["dayLow"] == None or morntemp < weather["dayLow"]):
                                            weather["dayLow"] = morntemp
                                        if (weather["dayHigh"] == None or morntemp > weather["dayHigh"]):
                                            weather["dayHigh"] = morntemp
                    else:
                        logging.error("Fallback to openweathermap failed.")

                resort["weather"] = weather
                
                if ("logo" not in resort or resort["logo"] == None):

                    logo = None

                    # First try to get saved logo
                    try:
                        logo = Image.open(f"{shared_config.icons_dir}/snow/logos/{resort['slug']}.png")
                    except:
                        logo = None

                    if (logo == None):

                        # List of websites to try getting favicon from (in preference order)
                        website_list = [resortdata["website"], resortdata["liftsUrl"], resortdata["rentalUrl"], resortdata["lessonsUrl"], resortdata["mobileWebsite"]]
                        
                        if (len(website_list) == 0):
                            logging.debug(f"No websites listed for {resort['name']}.")

                        checked = []
                        
                        for website in website_list:
                            if (website == None):
                                continue
                            if website in checked:
                                continue
                            
                            logging.debug(f"Attempting to get favicon for {resort['name']} from: {website}.")

                            logo = getFavicon(website)
                            if logo != None:
                                logging.debug(f"Successfully got logo for resort {resort['name']} from: {website}.")
                                break

                            if len(checked) == 0:
                                # First website, also try url version without "www."
                                p = urlparse(website)
                                baseurl = p.netloc
                                scheme = p.scheme
                                if baseurl.startswith("www."):
                                    website = scheme + "://" + baseurl[4:]

                                    logging.debug(f"Attempting to get favicon for {resort['name']} from: {website}.")

                                    logo = getFavicon(website)
                                    if logo != None:
                                        logging.debug(f"Successfully got logo for resort {resort['name']} from: {website}.")
                                        break

                            checked.append(website)

                    if (logo == None):
                        # Give up and use the default image
                        logo = Image.open(f'{shared_config.icons_dir}/snow/logos/DEFAULT.png').convert("RGB")
                        logging.debug(f"Could not get logo for resort {resort['name']}.")
                    else:
                        # Save logo to disk so we don't need to get it from the web again
                        logo.convert("RGB").save(f"{shared_config.icons_dir}/snow/logos/{resort['slug']}.png")                    

                    resort["logo"] = logo

                resort["last_update"] = datetime.now().timestamp()

                return resort
            else:
                logging.error(f"Could not update data for resort: {resort['name']} using url: {reporturl}")
        return None

@__main__.planesign_mode_handler(DisplayMode.SNOW)
def snow_forecast(sign):
    release_lock(userresorts_filename)
    sign.canvas.Clear()

    breakout = draw_loading(sign)
    if breakout:
        return

    sr = SnowReport(sign)

    load_user_list()
    user_list = shared_config.data_dict["user_resorts"]
    n = len(user_list)
    if n > 0:
        shared_config.data_dict["displayed_resort"] = user_list[random.randint(0, n-1)]

    gif = Image.open(f"{shared_config.icons_dir}/snow/snow.gif")
    nf = gif.n_frames
    frame=0

    last_rotate = time.perf_counter()
    while shared_config.shared_mode.value == DisplayMode.SNOW.value:

        if ("displayed_resort" in shared_config.data_dict and shared_config.data_dict["displayed_resort"]):
            current_resort = shared_config.data_dict["displayed_resort"]
        else:
            current_resort = None

        if (current_resort == None):
            # Nothing to display - draw the background gif
            gif.seek(frame)
            frame = (frame+1)%nf
            
            image = Image.new("RGB", gif.size, (255, 255, 255))
            image.paste(gif, (0,0))
            sign.canvas.SetImage(image.resize((128, 64), Image.BICUBIC).convert('RGB'), 1, -15)

        elif (shared_config.shared_snow_mode.value == SnowMode.STATIC.value or n == 0):

            sr.drawresort(current_resort)

        elif (shared_config.shared_snow_mode.value == SnowMode.ROTATE.value):
            if (time.perf_counter()-last_rotate > 30):
                load_user_list()
                user_list = shared_config.data_dict["user_resorts"]
                n = len(user_list)
                index = -1
                found = False
                for uuid in user_list:
                    index += 1
                    if current_resort == uuid:
                        found = True
                        break
                
                if found:
                    index = (index+1)%n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()

            sr.drawresort(current_resort)

        elif (shared_config.shared_snow_mode.value == SnowMode.OVERVIEW.value):
            
            if (time.perf_counter()-last_rotate > 15):
                load_user_list()
                user_list = shared_config.data_dict["user_resorts"]
                n = len(user_list)
                index = -1
                found = False
                for uuid in user_list:
                    index += 1
                    if current_resort == uuid:
                        found = True
                        break
                
                if found and n >= 8:
                    index = (index+4)%n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                elif found and n >= 4:
                    index = (index+1)%n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                elif found and n > 0:
                    index = 0
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                    
            sr.drawoverview(current_resort, user_list)

        else:
            logging.error(f"Invalid snow mode: {shared_config.shared_snow_mode.value}.")
            shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value
            return

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
            
        breakout = sign.wait_loop(1.0)

        if breakout:
            return