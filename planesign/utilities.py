import logging
import math
import os
import random
import re
import subprocess
import time
import traceback
from datetime import datetime
from functools import cmp_to_key
from math import cos, pi, sin
from urllib.parse import urlparse

import favicon
import geopandas as gpd
import numpy as np
import pytz
import requests
import shared_config
from PIL import Image, ImageDraw, ImageFont
from rgbmatrix import graphics
from shapely.geometry import Point
from timezonefinder import TimezoneFinder

import __main__

NUM_STEPS = 40
DEG_2_RAD = pi / 180.0
KM_2_MI = 0.6214
CM_2_IN = 0.3937008

country_polys = []
state_polys = []
water_polys = []
geojsons_loaded = False

from modes import DisplayMode


def read_config():
    shared_config.CONF.clear()

    logging.info("Reading  config...")

    if not os.path.exists("sign.conf"):
        logging.warning("WARNING! No sign.conf found... using default values from sign.conf.sample")
    else:
        with open("sign.conf") as f:
            for line in f.readlines():
                if line.isspace() or line[0] == "#":
                    continue
                key, val = line.split("=")
                shared_config.CONF[key] = val.rstrip()

    with open("sign.conf.sample") as f:
        for line in f.readlines():
            if line.isspace() or line[0] == "#":
                continue
            key, val = line.split("=")
            if key not in shared_config.CONF.keys():
                logging.warning(f"WARNING! No setting for '{key}' found in sign.conf, using value '{val.rstrip()}' from sign.conf.sample")
                shared_config.CONF[key] = val.rstrip()

    logging.info("Config loaded: " + str(shared_config.CONF))

    tf = TimezoneFinder()
    local_tz = tf.timezone_at(lat=float(shared_config.CONF["SENSOR_LAT"]), lng=float(shared_config.CONF["SENSOR_LON"]))
    if local_tz is None:
        logging.warning("Cannot find given provided lat/lon! Using UTC...")
        shared_config.local_timezone = pytz.utc
    else:
        logging.info(f"Detected timezone to be {local_tz}")
        shared_config.local_timezone = pytz.timezone(local_tz)

    shared_config.airport_codes_to_ignore = set(shared_config.CONF["IGNORE_AIRPORT_CODES"].split(","))


def acquire_lock(filepath):
    while True:
        try:
            fd = os.open(filepath + ".lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break  # Lock acquired
        except FileExistsError:
            time.sleep(0.01)  # Wait and retry


def release_lock(filepath):
    try:
        os.remove(filepath + ".lock")
    except FileNotFoundError:
        pass  # Already removed


def safe_write(filepath, newdata):
    # Appends newdata to the end of a file safely
    acquire_lock(filepath)
    try:
        with open(filepath, "r+") as f:
            data = f.read()
            f.seek(0)
            f.write(data + f"{newdata}")
    finally:
        release_lock(filepath)


def random_angle():
    return random.randrange(0, 360)


def random_rgb_255_sum():
    _, r, g, b = next_color_rainbow_linear(random_angle())
    return r, g, b


def detect_usb_audio_device():
    result = subprocess.run(["aplay", "-l"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = result.stdout.splitlines()
    for line in lines:
        if "USB Audio" in line and "card" in line and "device" in line:
            # Example line: card 0: UACDemoV10 [UACDemoV1.0], device 0: USB Audio [USB Audio]
            parts = line.split()
            card_index = parts.index("card") + 1
            device_index = parts.index("device") + 1
            card_num = parts[card_index].replace(":", "")
            device_num = parts[device_index].replace(":", "")
            shared_config.audio_device = f"hw:{card_num},{device_num}"
            shared_config.audio_card = card_num
            shared_config.audio_mixer_control = find_usb_volume_control(card_num)
            logging.info(f"Detected USB Audio device: {shared_config.audio_device} (mixer control: {shared_config.audio_mixer_control})")
            return


def find_usb_volume_control(card_num):
    """Return the name of the best available playback volume control on a card, or None."""
    try:
        result = subprocess.run(["amixer", "-c", card_num, "controls"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to get controls for card {card_num}: {result.stderr}")
            return None

        for control in ["Master", "PCM", "Speaker", "Headphone", "Playback"]:
            for line in result.stdout.splitlines():
                if control in line:
                    return control

        logging.error(f"No suitable volume control found for card {card_num}")
        return None
    except Exception as e:
        logging.error(f"Error looking up USB audio volume control: {e}")
        return None


def get_usb_audio_volume():
    """Return the current USB audio volume as a 0-100 percentage, or None if unavailable."""
    if shared_config.audio_card is None or shared_config.audio_mixer_control is None:
        return None

    try:
        # -M uses the mapped (perceptual) scale so it round-trips with set_usb_audio_volume
        result = subprocess.run(["amixer", "-M", "-c", shared_config.audio_card, "sget", shared_config.audio_mixer_control], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to read volume: {result.stderr}")
            return None

        if re.search(r"\[off\]", result.stdout):
            return 0

        match = re.search(r"\[(\d{1,3})%\]", result.stdout)
        if not match:
            logging.error("Could not parse volume from amixer output")
            return None

        return min(100, int(match.group(1)))
    except Exception as e:
        logging.error(f"Error reading USB audio volume: {e}")
        return None


def set_usb_audio_volume(percent):
    """Set the USB audio volume to a 0-100 percentage. Returns True on success."""
    if shared_config.audio_card is None or shared_config.audio_mixer_control is None:
        logging.error("Cannot set volume, no USB audio device detected")
        return False

    percent = max(0, min(100, int(percent)))

    try:
        result = subprocess.run(["amixer", "-M", "-c", shared_config.audio_card, "set", shared_config.audio_mixer_control, f"{percent}%", "unmute"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to set volume: {result.stderr}")
            return False

        logging.info(f"Set USB audio volume to {percent}% using {shared_config.audio_mixer_control} control")
        return True
    except Exception as e:
        logging.error(f"Error setting USB audio volume: {e}")
        return False


def read_static_airport_data():
    with open("datafiles/airports.csv") as f:
        lines = f.readlines()
        for line in lines:
            parts = line.strip().split(",")
            code = parts[0]
            name = parts[1]
            lat = float(parts[2])
            lon = float(parts[3])
            shared_config.code_to_airport[code] = (name, lat, lon)

    logging.info(f"{len(shared_config.code_to_airport)} static airport configs added")


def read_geojsons():
    global country_polys
    global state_polys
    global water_polys
    global geojsons_loaded

    if geojsons_loaded:
        return

    # Load static geojson files for use in local reverse geocoding
    country_polys = gpd.read_file(f"{shared_config.datafiles_dir}/countries.geojson")
    state_polys = gpd.read_file(f"{shared_config.datafiles_dir}/states.geojson")
    water_polys = gpd.read_file(f"{shared_config.datafiles_dir}/water.geojson")
    geojsons_loaded = True


def reverse_geocode(lat, lon):
    """
    For a given lat/lon pair in degrees, returns a string representing the name
    of the state/country/body of water/point of interest, as well as the 'code'
    to display the region's flag or symbol via the icon saved in:
    f'{shared_config.icons_dir}/flags/{code}.png'
    """

    global country_polys
    global state_polys
    global water_polys

    read_geojsons()

    formatted_address = None
    code = None

    point = Point(lon, lat)

    # First check for point in countries (water is more probable but you'll miss small islands)
    result = country_polys[country_polys.contains(point)]

    if result.shape[0]:
        index = 0
        if result.shape[0] > 1:
            smallest_area = None
            for j in range(result.shape[0]):
                new_area = result["geometry"].iloc[j].area
                if smallest_area is None or (new_area < smallest_area):
                    smallest_area = new_area
                    index = j

        code = result["CODE"].iloc[index]
        formatted_address = result["NAME"].iloc[index]

        if code == "USA":
            # Check for specific state
            result = state_polys[state_polys.contains(point)]

            if result.shape[0]:
                code = "states/" + result["CODE"].iloc[0]
                formatted_address = result["NAME"].iloc[0]

    else:
        # We're in the water

        result = water_polys[water_polys.contains(point)]

        if result.shape[0]:
            code = "OCEAN"

            index = 0
            if result.shape[0] > 1:
                smallest_area = None
                for j in range(result.shape[0]):
                    new_area = result["geometry"].iloc[j].area
                    if smallest_area is None or (new_area < smallest_area):
                        smallest_area = new_area
                        index = j

            # Special case codes
            if result["CODE"].iloc[index] in ["IMAG", "NEMO", "TRASH", "TRIANG", "TRENCH", "REEF", "NEMO", "SHIP"]:
                code = result["CODE"].iloc[index]

            formatted_address = result["NAME"].iloc[index]

    if formatted_address is None:
        formatted_address = "Unknown"
        logging.debug(f"Couldn't find reverse geocoding for lat/lon: ({lat},{lon})")
    else:
        logging.info(f"Found location {formatted_address} for lat/lon ({lat},{lon}).")

    if code is None:
        code = "UNKNOWN"

    return formatted_address, code


class TextScroller:
    """
    Scrolling Textfield Object

    Arguments:
        (Required)
        sign: Planesign obj
        x: inteter - horiz. location on matrix (0 left)
        y: inteter - vert. location on matrix (0 top)
        color: rgb integer tuple (0-255, 0-255, 0-255)
        boxdim: (width, height) integer tuple - defines size of scrolling window display area in number of pixels

        (Default)
        text:   string - text to scroll. Setting to None or "" will display nothing.            Default: None
        space:  integer or float - number of equiv. space characters to add before wrapping.    Default: 1
        font:   string - font style. Available: "4x6","5x7","6x13"/"fontbig"/"big",             Default: "5x7"
                "9x18B"/"fontreallybig"/"reallybig","helvR12"/"fontplanesign"/"planesign"
        scrolldir:   string - scroll travel direction. Available: "Left", "Right", "Up", "Down" Default: "Left"
        scrollspeed: integer - scroll speed in pixels/second.                                   Default: 5
        holdtime:    integer - seconds to show (re)starting text before scrolling.              Default: 0
        forcescroll: boolean - if text will fit within display area without scrolling,          Default: False
                     should we force scrolling anyway?

    Functions:
        .draw() - draws text at the current scroll position to sign.canvas

    Use:
        object.text can be updated dynamically by user and scrolling will restart with new text

        DO NOT directly modify:
            object.holdtimer, object.stopflag, object.lasttext, object.lastdrawtime, object.offset
    """

    def __init__(self, sign, x, y, color, boxdim, text=None, space=1, font="5x7", scrolldir="left", scrollspeed=5, holdtime=0, forcescroll=False):

        self.sign = sign
        self.x = x
        self.y = y

        self.colortimer = time.perf_counter()
        self.coloroffset = 0
        self.color_mode_offset = 6
        self.tempcolor = random_rgb(rmin=10, gmin=10, bmin=10)

        self.text = text
        self.lasttext = None
        self.space = space
        self.fontname = font
        self.color = color
        self.scrolldir = scrolldir
        self.scrollspeed = scrollspeed
        self.forcescroll = forcescroll
        self.holdtime = holdtime
        self.holdtimer = 0
        if holdtime == 0:
            self.stopflag = False
        else:
            self.stopflag = True

        if self.fontname == "6x13" or self.fontname == "fontbig" or self.fontname == "big":
            self.fontname = "6x13"
            bdffont = self.sign.fontbig
            self.fontw = 6
        elif self.fontname == "9x18B" or self.fontname == "fontreallybig" or self.fontname == "reallybig":
            self.fontname = "9x18B"
            bdffont = self.sign.fontreallybig
            self.fontw = 9
        elif self.fontname == "helvR12" or self.fontname == "fontplanesign" or self.fontname == "planesign":
            self.fontname = "helvR12"
            bdffont = self.sign.fontplanesign
            self.fontw = 9
        elif self.fontname == "4x6":
            bdffont = self.sign.font46
            self.fontw = 4
        else:
            self.fontname == "5x7"
            bdffont = self.sign.font57
            self.fontw = 5

        self.font = ImageFont.load("./fonts/" + self.fontname + ".pil")

        self.cw = bdffont.CharacterWidth(0)
        self.ch = bdffont.height

        self.w, self.h = boxdim

        self.lastdrawtime = None
        self.offset = 0

        if text is not None:
            self.length = len(self.text)
        else:
            self.length = None

        self.image = Image.new("RGB", boxdim, (0, 0, 0))
        self.dr = ImageDraw.Draw(self.image)

    def set_text(self, dx, dy):

        if type(self.color) is tuple:
            self.dr.text((dx, dy), self.text, font=self.font, fill=self.color)
        else:
            if self.color == 0 or self.color == 5:
                self.dr.text((dx, dy), self.text, font=self.font, fill=(3, 194, 255))

            if self.color == 1:
                if self.colortimer + 0.1 < time.perf_counter():
                    self.colortimer = time.perf_counter()
                    self.tempcolor = random_rgb(rmin=10, gmin=10, bmin=10)
                self.dr.text((dx, dy), self.text, font=self.font, fill=self.tempcolor)

            if (self.color >= 2 and self.color <= 4) or self.color > 5:
                if self.color == 2:
                    colors = [(12, 169, 12), (206, 13, 13)]  # CHRISTMAS
                elif self.color == 3:
                    colors = [(173, 0, 30), (178, 178, 178), (37, 120, 178)]  # 4TH OF JULY
                elif self.color == 4:
                    colors = [(20, 20, 20), (247, 95, 28)]  # HALLOWEEN
                else:
                    colors = [(((self.color - self.color_mode_offset) >> 16) & 255, ((self.color - self.color_mode_offset) >> 8) & 255, (self.color - self.color_mode_offset) & 255)]

                if self.colortimer + 1.1 < time.perf_counter():
                    self.colortimer = time.perf_counter()
                    self.coloroffset = (self.coloroffset + 1) % len(colors)

                self.dr.text((dx, dy), self.text, font=self.font, fill=colors[(0 + self.coloroffset) % len(colors)])
                if len(colors) > 1:
                    for index, letter in enumerate(self.text):
                        if index % len(colors) == 1:
                            self.dr.text((dx + self.fontw * index, dy), letter, font=self.font, fill=colors[(1 + self.coloroffset) % len(colors)])
                        if len(colors) > 2 and index % len(colors) == 2:
                            self.dr.text((dx + self.fontw * index, dy), letter, font=self.font, fill=colors[(2 + self.coloroffset) % len(colors)])

    def draw(self):

        if self.text is None:
            return

        if self.text != self.lasttext:
            self.lasttext = self.text
            self.length = len(self.text)
            self.lastdrawtime = None
            self.offset = 0

        if self.text == "":
            return

        self.dr.rectangle([(0, 0), self.image.size], fill=(0, 0, 0))

        curtime = time.perf_counter()

        # Scroll Text
        if ((self.scrolldir == "left" or self.scrolldir == "right") and self.length * self.cw > self.w) or ((self.scrolldir == "up" or self.scrolldir == "down") and self.ch > self.h) or self.forcescroll:
            if self.lastdrawtime is not None:
                if self.holdtime == 0:
                    self.offset = self.offset + self.scrollspeed * (curtime - self.lastdrawtime)
                elif round(self.offset) == 0 and self.stopflag:
                    self.holdtimer = self.holdtimer + (curtime - self.lastdrawtime)
                elif self.holdtimer < self.holdtime or not self.stopflag:
                    tempoffset = self.offset + self.scrollspeed * (curtime - self.lastdrawtime)
                    if round(tempoffset) * round(self.offset) < 0:  # make sure we don't skip over 0 by going too fast
                        self.offset = 0
                        self.stopflag = True
                        self.holdtimer = 0
                    else:
                        self.offset = tempoffset

                    if not self.stopflag and round(self.offset) != 0:
                        self.stopflag = True

                if self.holdtimer >= self.holdtime:
                    self.stopflag = False
                    self.holdtimer = 0

            if self.scrolldir == "left" or self.scrolldir == "right":
                self.offset = self.offset % ((self.length + self.space) * self.cw)
                for o in range(-round((self.length + self.space) * self.cw), self.w + round((self.length + self.space) * self.cw) + 1, round((self.length + self.space) * self.cw)):
                    if self.scrolldir == "left":
                        r = -1
                    elif self.scrolldir == "right":
                        r = 1

                    self.set_text(round(r * self.offset + o), 0)
            else:
                self.offset = self.offset % ((1 + self.space) * self.ch)
                for o in range(-round((1 + self.space) * self.ch), self.h + round((1 + self.space) * self.ch) + 1, round((1 + self.space) * self.ch)):
                    if self.scrolldir == "up":
                        r = -1
                    elif self.scrolldir == "down":
                        r = 1

                    self.set_text(0, round(r * self.offset + o))

        else:  # Text will fit in box, don't need to scroll if we don't have to
            self.set_text(0, 0)

        self.sign.canvas.SetImage(self.image.convert("RGB"), self.x, self.y - self.h + 1)

        self.lastdrawtime = curtime


def fix_black(image):
    # brighten black
    rgb = np.array(image.convert("RGB"))
    mask = (rgb[:, :, 0] < 30) & (rgb[:, :, 1] < 30) & (rgb[:, :, 2] < 30)
    rgb[mask] = np.true_divide(rgb[mask], 2.0) + [15, 15, 15]
    image = Image.fromarray(rgb)

    return image


def colordista(c1, c2, bg):

    # Background must be RGB
    bgr = bg[0] / 255
    bgg = bg[1] / 255
    bgb = bg[2] / 255

    # C1 and C2 must be RGBA
    r1 = c1[0] / 255
    r2 = c2[0] / 255
    g1 = c1[1] / 255
    g2 = c2[1] / 255
    b1 = c1[2] / 255
    b2 = c2[2] / 255
    a1 = c1[3] / 255
    a2 = c2[3] / 255

    r1 = r1 * a1 + bgr * (1 - a1)
    r2 = r2 * a2 + bgr * (1 - a2)

    g1 = g1 * a1 + bgg * (1 - a1)
    g2 = g2 * a2 + bgg * (1 - a2)

    b1 = b1 * a1 + bgb * (1 - a1)
    b2 = b2 * a2 + bgb * (1 - a2)

    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2

    return np.sqrt(dr**2 + dg**2 + db**2) * 255


def flood(image, x, y, floodcolor, threshold):

    sizex, sizey = image.size

    if x >= sizex or y >= sizey or x < 0 or y < 0:
        return

    oldcolor = image.getpixel((x, y))

    done = []
    q = []
    q.append((x, y))
    while len(q) > 0:
        (x, y) = q.pop()

        image.putpixel((x, y), floodcolor)
        done.append((x, y))

        if x + 1 < sizex:
            rightcolor = image.getpixel((x + 1, y))
        else:
            rightcolor = None

        if y + 1 < sizey:
            downcolor = image.getpixel((x, y + 1))
        else:
            downcolor = None

        if x - 1 >= 0:
            leftcolor = image.getpixel((x - 1, y))
        else:
            leftcolor = None

        if y - 1 >= 0:
            upcolor = image.getpixel((x, y - 1))
        else:
            upcolor = None

        if rightcolor is not None and rightcolor != floodcolor and colordista(oldcolor, rightcolor, floodcolor) < threshold:
            q.append((x + 1, y))
        if downcolor is not None and downcolor != floodcolor and colordista(oldcolor, downcolor, floodcolor) < threshold:
            q.append((x, y + 1))
        if leftcolor is not None and leftcolor != floodcolor and colordista(oldcolor, leftcolor, floodcolor) < threshold:
            q.append((x - 1, y))
        if upcolor is not None and upcolor != floodcolor and colordista(oldcolor, upcolor, floodcolor) < threshold:
            q.append((x, y - 1))


def autocrop(image, bg):

    sizex, sizey = image.size

    flag = False
    for row in range(sizey):
        for col in range(sizex):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break
    top = row

    flag = False
    for row in range(sizey - 1, top + 1, -1):
        for col in range(sizex):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break
    bot = row

    flag = False
    for col in range(sizex):
        for row in range(top, bot + 1, 1):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break

    left = col

    flag = False
    for col in range(sizex - 1, left + 1, -1):
        for row in range(top, bot + 1, 1):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break

    right = col

    return image.crop((left, top, right + 1, bot + 1))


def getPixels(image, offset=0):
    width, height = image.size
    tl = image.getpixel((0 + offset, 0 + offset))
    tr = image.getpixel((width - 1 - offset, 0 + offset))
    bl = image.getpixel((0 + offset, height - 1 - offset))
    br = image.getpixel((width - 1 - offset, height - 1 - offset))
    return tl, tr, bl, br


def improcess(image, desired_size=20):

    white = (255, 255, 255, 255)
    black = (0, 0, 0, 255)

    width, height = image.size
    image = image.convert("RGBA")

    testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
    testimage.paste(image, (0, 0), image)
    testimage = testimage.convert("RGB")

    # Replace black parts of logo with dark grey if enough of the logo is black
    if np.count_nonzero(np.all(np.array(testimage) == (0, 0, 0), axis=-1)) / (width * height) > 0.05:
        rgba = np.array(image)
        mask = (rgba[:, :, 0] < 35) & (rgba[:, :, 1] < 35) & (rgba[:, :, 2] < 35) & (rgba[:, :, 3] > 200)
        rgba[mask] = [35, 35, 35, 255]
        image = Image.fromarray(rgba)

    floodcorners = False

    # Try and fix the background if it is transparent or white
    tl, tr, bl, br = getPixels(image)

    threshold = 50
    if max(tl[3], tr[3], bl[3], br[3]) <= threshold:
        # Corners are transparent

        # Try flooding with black to test
        transim = Image.new("RGBA", (image.width + 2, image.height + 2), (0, 0, 0, 0))
        transim.paste(image, (1, 1))
        blackflood = transim
        if tl[3] < threshold:
            flood(blackflood, 1, 1, black, 100)
            tl, tr, bl, br = getPixels(blackflood, 1)

        if tr[3] < threshold:
            flood(blackflood, width - 2, 1, black, 100)
            tl, tr, bl, br = getPixels(blackflood, 1)

        if bl[3] < threshold:
            flood(blackflood, 1, height - 2, black, 100)
            tl, tr, bl, br = getPixels(blackflood, 1)

        if br[3] < threshold:
            flood(blackflood, width - 2, height - 2, black, 100)

            blackflood = blackflood.crop((1, 1, width + 1, height + 1))

        if np.count_nonzero(np.array(blackflood)[:, :, 3] <= threshold) / (width * height) > 0.025:
            # After flooding the corners, we still have transparent regions which
            # likely should have a white background. Paste white behind the original image.
            whiteim = Image.new("RGBA", image.size, white)
            whiteim.paste(image, (0, 0), image)
            image = whiteim

            floodcorners = True

        else:
            # No large transparent holes, just paste black behind original image
            blackim = Image.new("RGBA", image.size, black)
            blackim.paste(image, (0, 0), image)
            image = blackim

    elif max(colordista(tl, white, white), colordista(tr, white, white), colordista(bl, white, white), colordista(br, white, white)) < threshold:
        # Corners are white
        floodcorners = True

    if floodcorners:
        tl, tr, bl, br = getPixels(image)

        if colordista(tl, white, white) < threshold:
            flood(image, 0, 0, black, 100)
            tl, tr, bl, br = getPixels(image)

        if colordista(tr, white, white) < threshold:
            flood(image, width - 1, 0, black, 100)
            tl, tr, bl, br = getPixels(image)

        if colordista(bl, white, white) < threshold:
            flood(image, 0, height - 1, black, 100)
            tl, tr, bl, br = getPixels(image)

        if colordista(br, white, white) < threshold:
            flood(image, width - 1, height - 1, black, 100)

    # Paste black behind as final "normalization"
    new_image = Image.new("RGBA", image.size, black)
    new_image.paste(image, (0, 0), image)

    image = new_image.convert("RGBA")

    # Crop out black background regions
    image = autocrop(image, black)

    width, height = image.size

    # Rescale final cropped image to desired_size max, preserving logo aspect ratio
    if width > height:
        image = image.resize((desired_size, int(desired_size * height / width)), Image.BICUBIC)
    elif height > width:
        image = image.resize((int(desired_size * width / height), desired_size), Image.BICUBIC)
    else:
        image = image.resize((desired_size, desired_size), Image.BICUBIC)

    # Tone-down brightness
    bg = (0, 0, 0, 30)
    new_image = Image.new("RGBA", image.size, bg)
    image.paste(new_image, (0, 0), new_image)

    return image.convert("RGB")


def getFavicon(website, headers=None):

    if headers is None:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/png,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.5", "Connection": "keep-alive"}
    try:
        logging.debug(f"getFavicon: fetching icons for {website}")
        icons = favicon.get(website, headers=headers, timeout=10)
        logging.debug(f"getFavicon: found {len(icons)} icons for {website}")
    except Exception as e:
        logging.warning(f"getFavicon: failed for {website}: {e}")
        logging.debug(traceback.format_exc())
        icons = []

    def compare(item1, item2):

        f = "favico"
        i = "icon"
        name1 = item1.url.split("/")[-1].split(".")[0]
        name2 = item2.url.split("/")[-1].split(".")[0]
        # Prioritize files starting with "favico"
        if (name1.startswith(f) or name1.startswith(i)) and not (name2.startswith(f) or name2.startswith(i)):
            return -1
        elif not (name1.startswith(f) or name1.startswith(i)) and (name2.startswith(f) or name2.startswith(i)):
            return 1
        else:
            # Deprioritize the "default" favicon (favicon library just guesses
            # this url and sometimes it is a janky placeholder image)
            domain = urlparse(website).netloc
            default = domain + "/favicon.ico"
            url1 = item1.url
            url2 = item2.url
            if url1.endswith(default) and not url2.endswith(default):
                return 1
            elif not url1.endswith(default) and url2.endswith(default):
                return -1
            else:
                # Prioritize files containing "favico" or "icon"
                if (f in name1 or i in name1) and not (f in name2 or i in name2):
                    return -1
                elif not (f in name1 or i in name1) and (f in name2 or i in name2):
                    return 1
                else:
                    # Prioritize ".ico" files
                    format1 = item1.url.split("/")[-1].split(".")
                    format2 = item2.url.split("/")[-1].split(".")
                    isIco1 = True if (item1.format == "ico" or (len(format1) > 1 and format1[1].startswith("ico"))) else False
                    isIco2 = True if (item2.format == "ico" or (len(format2) > 1 and format2[1].startswith("ico"))) else False
                    if isIco1 and not isIco2:
                        return -1
                    elif not isIco1 and isIco2:
                        return 1
                    else:
                        # All else being equal, use size to sort
                        size1 = item1.width * item1.height
                        size2 = item2.width * item2.height
                        large = 150 * 150 + 1

                        # Suppress images that are too large (usually random non-icon pics)
                        if size1 >= large and size2 < large:
                            # Prefer small over too large
                            return 1
                        elif size1 < large and size2 >= large:
                            # Prefer small over too large
                            return -1

                        # Prefer square images:
                        if item1.width > 0 and item1.height > 0 and item2.width > 0 and item2.height > 0:
                            if item1.width > item1.height:
                                ar1 = item1.height / item1.width
                            else:
                                ar1 = item1.width / item1.height

                            if item2.width > item2.height:
                                ar2 = item2.height / item2.width
                            else:
                                ar2 = item2.width / item2.height

                            if ar1 > ar2:
                                # Item 1 is more square
                                return -1
                            elif ar2 > ar1:
                                # Item 2 is more square
                                return 1

                        if size1 >= large and size2 >= large:
                            # Both are too large, prefer smaller
                            return size1 - size2
                        else:
                            # Both are small, prefer larger
                            return size2 - size1

    icons_sorted = sorted(icons, key=cmp_to_key(compare))
    image = None

    for icon in icons_sorted:
        try:
            logging.debug(f"getFavicon: downloading icon {icon.url} ({icon.width}x{icon.height}, {icon.format})")
            req = requests.get(icon.url, stream=True, headers=headers, timeout=5)
        except Exception as e:
            logging.warning(f"getFavicon: failed to download icon {icon.url}: {e}")
            logging.debug(traceback.format_exc())
            continue
        if req.status_code != requests.codes.ok:
            logging.debug(f"getFavicon: icon {icon.url} returned status {req.status_code}")
            continue
        if len(req.content) == 0:
            logging.debug(f"getFavicon: icon {icon.url} returned empty content")
            continue

        image = open(f"{shared_config.icons_dir}/favicon", "wb")
        image.write(req.content)
        image.close()

        try:
            image = Image.open(f"{shared_config.icons_dir}/favicon")
            if image.width > 500 or image.height > 500 or image.width <= 10 or image.height <= 10:
                # Actual image size is too big or too small
                logging.debug(f"getFavicon: icon {icon.url} size {image.width}x{image.height} out of range, skipping")
                image = None
                continue
            logging.debug(f"getFavicon: successfully loaded icon {icon.url} ({image.width}x{image.height})")
            break
        except Exception as e:
            logging.debug(f"getFavicon: failed to open downloaded icon {icon.url}: {e}")
            image = None
            continue

    if image is None:
        # Fallback to getting favicon from google
        google_url = f"https://www.google.com/s2/favicons?domain={urlparse(website).netloc}"
        logging.debug(f"getFavicon: trying Google fallback for {website}: {google_url}")
        try:
            req = requests.get(google_url, stream=True, timeout=5)
            if req.status_code == requests.codes.ok:
                image = open(f"{shared_config.icons_dir}/favicon", "wb")
                image.write(req.content)
                image.close()

                try:
                    image = Image.open(f"{shared_config.icons_dir}/favicon")
                    logging.debug(f"getFavicon: Google fallback succeeded for {website} ({image.width}x{image.height})")
                except Exception as e:
                    logging.debug(f"getFavicon: Google fallback image failed to open: {e}")
                    image = None
            else:
                logging.debug(f"getFavicon: Google fallback returned status {req.status_code}")
        except Exception as e:
            logging.warning(f"getFavicon: Google fallback failed for {website}: {e}")
            logging.debug(traceback.format_exc())

    if image:
        image = improcess(image)
        return image
    else:
        logging.debug(f"getFavicon: no usable favicon found for {website}")
        return None


def fix_chars(name):
    name = name.replace("–", "-")
    for ch in ["\u0100", "\u0102", "\u0104"]:
        name = name.replace(ch, "A")
    for ch in ["\u0101", "\u0103", "\u0105"]:
        name = name.replace(ch, "a")
    for ch in ["\u0106", "\u0108", "\u010a", "\u010c"]:
        name = name.replace(ch, "C")
    for ch in ["\u0107", "\u0109", "\u010b", "\u010d"]:
        name = name.replace(ch, "c")
    for ch in ["\u010e", "\u0110"]:
        name = name.replace(ch, "D")
    for ch in ["\u010f", "\u0111"]:
        name = name.replace(ch, "d")
    for ch in ["\u0112", "\u0114", "\u0116", "\u0118", "\u011a"]:
        name = name.replace(ch, "E")
    for ch in ["\u0113", "\u0115", "\u0117", "\u0119", "\u011b"]:
        name = name.replace(ch, "e")
    for ch in ["\u011c", "\u011e", "\u0120", "\u0122"]:
        name = name.replace(ch, "G")
    for ch in ["\u011d", "\u011f", "\u0121", "\u0123"]:
        name = name.replace(ch, "g")
    for ch in ["\u0124", "\u0126"]:
        name = name.replace(ch, "H")
    for ch in ["\u0125", "\u0127"]:
        name = name.replace(ch, "h")
    for ch in ["\u0128", "\u012a", "\u012c", "\u012e", "\u0130", "\u0132"]:
        name = name.replace(ch, "I")
    for ch in ["\u0129", "\u012b", "\u012d", "\u012f", "\u0131", "\u0133"]:
        name = name.replace(ch, "i")
    for ch in ["\u0134"]:
        name = name.replace(ch, "J")
    for ch in ["\u0135"]:
        name = name.replace(ch, "j")
    for ch in ["\u0136"]:
        name = name.replace(ch, "K")
    for ch in ["\u0137", "\u0138"]:
        name = name.replace(ch, "k")
    for ch in ["\u0139", "\u013b", "\u013d", "\u013f", "\u0141"]:
        name = name.replace(ch, "L")
    for ch in ["\u0140", "\u013c", "\u013e", "\u0140", "\u0142"]:
        name = name.replace(ch, "l")
    for ch in ["\u0143", "\u0145", "\u0147", "\u014a"]:
        name = name.replace(ch, "N")
    for ch in ["\u0144", "\u0146", "\u0148", "\u0149", "\u014b"]:
        name = name.replace(ch, "n")
    for ch in ["\u014c", "\u014e", "\u0150", "\u0152"]:
        name = name.replace(ch, "O")
    for ch in ["\u014d", "\u014f", "\u0151", "\u0153"]:
        name = name.replace(ch, "o")
    for ch in ["\u0154", "\u0156", "\u0158"]:
        name = name.replace(ch, "R")
    for ch in ["\u0155", "\u0157", "\u0159"]:
        name = name.replace(ch, "r")
    for ch in ["\u015a", "\u015c", "\u015e", "\u0160"]:
        name = name.replace(ch, "S")
    for ch in ["\u015b", "\u015d", "\u015f", "\u0161", "\u017f"]:
        name = name.replace(ch, "s")
    for ch in ["\u0162", "\u0164", "\u0166"]:
        name = name.replace(ch, "T")
    for ch in ["\u0163", "\u0165", "\u0167"]:
        name = name.replace(ch, "t")
    for ch in ["\u0168", "\u016a", "\u016c", "\u016e", "\u0170", "\u0172"]:
        name = name.replace(ch, "U")
    for ch in ["\u0169", "\u016b", "\u016d", "\u016f", "\u0171", "\u0173"]:
        name = name.replace(ch, "U")
    for ch in ["\u0174"]:
        name = name.replace(ch, "W")
    for ch in ["\u0175"]:
        name = name.replace(ch, "w")
    for ch in ["\u0176", "\u0178"]:
        name = name.replace(ch, "Y")
    for ch in ["\u0177"]:
        name = name.replace(ch, "y")
    for ch in ["\u0179", "\u017b", "\u017d"]:
        name = name.replace(ch, "Z")
    for ch in ["\u017a", "\u017c", "\u017e"]:
        name = name.replace(ch, "z")

    return name


def random_rgb(rmin=0, rmax=255, gmin=0, gmax=255, bmin=0, bmax=255):
    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256
    if rmax < rmin:
        rmin = rmax
    if gmax < gmin:
        gmin = gmax
    if bmax < bmin:
        bmin = bmax
    r = random.randrange(rmin, rmax + 1)
    g = random.randrange(gmin, gmax + 1)
    b = random.randrange(bmin, bmax + 1)
    return r, g, b


def hsv_2_rgb(h, s, v):
    if s == 0.0:
        v *= 255
        v = int(v)
        return (v, v, v)
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p, q, t = int(255 * (v * (1.0 - s))), int(255 * (v * (1.0 - s * f))), int(255 * (v * (1.0 - s * (1.0 - f))))
    v *= 255
    v = int(v)
    i %= 6
    if i == 0:
        return (v, t, p)
    if i == 1:
        return (q, v, p)
    if i == 2:
        return (p, v, t)
    if i == 3:
        return (p, q, v)
    if i == 4:
        return (t, p, v)
    if i == 5:
        return (v, p, q)


def rgb_2_hsv(r, g, b):
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx - mn
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g - b) / df) + 360) % 360
    elif mx == g:
        h = (60 * ((b - r) / df) + 120) % 360
    elif mx == b:
        h = (60 * ((r - g) / df) + 240) % 360
    if mx == 0:
        s = 0
    else:
        s = (df / mx) * 100
    v = mx * 100
    return h, s, v


def next_color_rainbow_linear(angle, dangle=1, bright=255):
    bright %= 256
    angle += dangle
    angle %= 360

    if angle <= 120:
        r = round(bright * (120 - angle) / 120)
        g = round(bright * angle / 120)
        b = 0
    elif angle <= 240:
        r = 0
        g = round(bright * (240 - angle) / 120)
        b = round(bright * (angle - 120) / 120)
    else:
        r = round(bright * (angle - 240) / 120)
        g = 0
        b = round(bright * (360 - angle) / 120)

    return angle, r, g, b


def next_color_rainbow_sine(angle, dangle=1, bright=255):
    bright %= 256
    angle += dangle
    angle %= 360

    if angle <= 120:
        r = round(bright * (cos(angle * DEG_2_RAD * 3 / 2) + 1) / 2)
        g = round(bright * (1 - cos(angle * DEG_2_RAD * 3 / 2)) / 2)
        b = 0
    elif angle <= 240:
        r = 0
        g = round(bright * (1 - cos(angle * DEG_2_RAD * 3 / 2)) / 2)
        b = round(bright * (cos(angle * DEG_2_RAD * 3 / 2) + 1) / 2)
    else:
        r = round(bright * (1 - cos(angle * DEG_2_RAD * 3 / 2)) / 2)
        g = 0
        b = round(bright * (cos(angle * DEG_2_RAD * 3 / 2) + 1) / 2)

    return angle, r, g, b


def next_color_random_walk_const_sum(r, g, b, step=1, rmin=0, rmax=255, gmin=0, gmax=255, bmin=0, bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax < rmin:
        rmin = rmax
    if gmax < gmin:
        gmin = gmax
    if bmax < bmin:
        bmin = bmax

    dr = 256
    dg = 256
    db = 256

    while (r + dr) > rmax or (r + dr) < rmin or (g + dg) > gmax or (g + dg) < gmin or (b + db) > bmax or (b + db) < bmin:
        i = random.randrange(0, 3)
        j = (random.randrange(0, 2) * 2 - 1) * step

        if i == 0:
            dr = j
            dg = -j
            db = 0
        elif i == 1:
            dr = j
            dg = 0
            db = -j
        else:
            dr = 0
            dg = j
            db = -j

    r += dr
    g += dg
    b += db

    return r, g, b


def next_color_random_walk_uniform_step(r, g, b, step=1, rmin=0, rmax=255, gmin=0, gmax=255, bmin=0, bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax < rmin:
        rmin = rmax
    if gmax < gmin:
        gmin = gmax
    if bmax < bmin:
        bmin = bmax

    dr = 256
    dg = 256
    db = 256

    while (r + dr) > rmax or (r + dr) < rmin or (g + dg) > gmax or (g + dg) < gmin or (b + db) > bmax or (b + db) < bmin:
        theta = math.acos(2 * random.random() - 1)
        phi = 2 * pi * random.random()

        dr = round(step * cos(phi) * sin(theta))
        dg = round(step * sin(phi) * sin(theta))
        db = round(step * cos(theta))

    r += dr
    g += dg
    b += db

    return r, g, b


def next_color_random_walk_nonuniform_step(r, g, b, step=1, rmin=0, rmax=255, gmin=0, gmax=255, bmin=0, bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax < rmin:
        rmin = rmax
    if gmax < gmin:
        gmin = gmax
    if bmax < bmin:
        bmin = bmax

    dr = 256
    dg = 256
    db = 256

    while r + dr > rmax or r + dr < rmin:
        dr = random.randrange(-step, step + 1)
    while g + dg > gmax or g + dg < gmin:
        dg = random.randrange(-step, step + 1)
    while b + db > bmax or b + db < bmin:
        db = random.randrange(-step, step + 1)

    r += dr
    g += dg
    b += db

    return r, g, b


def get_distance(coord1, coord2):
    R = 3958.8  # Earth radius in miles
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2

    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def direction_lookup(destination, origin=None):

    if origin is None and (type(destination) is float or type(destination) is np.float64 or type(destination) is int):
        degrees = destination

    else:
        destination_y, destination_x = destination
        origin_y, origin_x = origin

        deltaX = destination_x - origin_x

        deltaY = destination_y - origin_y

        degrees = math.atan2(deltaX, deltaY) / math.pi * 180

    degrees = degrees % 360

    compass_brackets = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]

    compass_lookup = round(degrees / 45)

    return compass_brackets[compass_lookup]


def convert_unix_to_local_time(unix_timestamp):
    utc_time = datetime.fromtimestamp(unix_timestamp, tz=pytz.utc)
    local_time = utc_time.astimezone(shared_config.local_timezone)
    return local_time


def convert_c_to_f(celcius):
    return (celcius * 1.8) + 32


def interpolate(num1, num2):
    if num1 == 0:
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

    return interpolated[1:]


def first(iter, pred):
    for element in iter:
        if pred(element):
            return element


def get_centered_text_x_offset_value(font_width, text):
    text_pixel_length = len(text) * font_width
    return 64 - (text_pixel_length / 2)


def check_matrix(x, y, matrix):
    if x == -1:
        x = 127

    if x == 128:
        x = 0

    if y == -1:
        y = 31

    if y == 32:
        y = 0

    return matrix[x][y]


def set_matrix(x, y, matrix, val):
    if x == -1:
        x = 127

    if x == 128:
        x = 0

    if y == -1:
        y = 31

    if y == 32:
        y = 0

    matrix[x][y] = val


@__main__.planesign_mode_handler(DisplayMode.TIME_ONLY)
def only_show_time(sign):
    while shared_config.shared_mode.value == DisplayMode.TIME_ONLY.value:
        show_time(sign)
        breakout = sign.wait_loop(1)
        if breakout:
            return


def show_time(sign):
    if shared_config.CONF["MILITARY_TIME"].lower() == "true":
        print_time = convert_unix_to_local_time(time.time()).strftime("%H:%M")
    else:
        print_time = convert_unix_to_local_time(time.time()).strftime("%-I:%M%p")

    xloc = 86
    weather = shared_config.data_dict.get("weather")
    current = weather.get("current") if weather else None
    if current and "temp" in current:
        tempval = round(current["temp"])
        if tempval < 0 or tempval > 99:
            xloc = 77
        temp = str(tempval)
    else:
        temp = "--"

    sign.canvas.Clear()

    tempstr = temp + "°F"

    graphics.DrawText(sign.canvas, sign.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
    graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, 21, graphics.Color(20, 20, 240), tempstr)

    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)


def weather_icon_decode(code, status, isNight=False):
    if code == 200:
        # thunderstorm with light rain
        icon = "thunderrain"
    elif code == 201:
        # thunderstorm with rain
        icon = "thunderrain"
    elif code == 202:
        # thunderstorm with heavy rain
        icon = "thunderrainheavy"
    elif code == 210:
        # light thunderstorm
        icon = "thunder"
    elif code == 211:
        # thunderstorm
        icon = "thunder"
    elif code == 212:
        # heavy thunderstorm
        icon = "thunderheavy"
    elif code == 221:
        # ragged thunderstorm
        icon = "thunder"
    elif code == 230:
        # thunderstorm with light drizzle
        icon = "thunderrain"
    elif code == 231:
        # thunderstorm with drizzle
        icon = "thunderrain"
    elif code == 232:
        # thunderstorm with heavy drizzle
        icon = "thunderrainheavy"
    elif code < 300:
        # generic fallback for "thunderstorm"
        icon = "thunder"
    elif code == 300:
        # light intensity drizzle
        icon = "rainlight"
    elif code == 301:
        # drizzle
        icon = "rainlight"
    elif code == 302:
        # heavy intensity drizzle
        icon = "rain"
    elif code == 310:
        # light intensity drizzle rain
        icon = "rainlight"
    elif code == 311:
        # drizzle rain
        icon = "rainlight"
    elif code == 312:
        # heavy intensity drizzle rain
        icon = "rain"
    elif code == 313:
        # shower rain and drizzle
        icon = "rain"
    elif code == 314:
        # heavy shower rain and drizzle
        icon = "rainheavy"
    elif code == 321:
        # shower drizzle
        icon = "rainlight"
    elif code < 500:
        # generic fallback for "drizzle"
        icon = "rainlight"
    elif code == 500:
        # light rain
        icon = "rainlight"
    elif code == 501:
        # moderate rain
        icon = "rain"
    elif code == 502:
        # heavy intensity rain
        icon = "rainheavy"
    elif code == 503:
        # very heavy rain
        icon = "rainheavy"
    elif code == 504:
        # extreme rain
        icon = "rainheavy"
    elif code == 511:
        # freezing rain
        icon = "snow"
        status = "FrzRain"
    elif code == 520:
        # light intensity shower rain
        icon = "rainlight"
    elif code == 521:
        # shower rain
        icon = "rain"
    elif code == 522:
        # heavy intensity shower rain
        icon = "rainheavy"
    elif code == 531:
        # ragged shower rain
        icon = "rainlight"
    elif code < 600:
        # generic fallback for "rain"
        icon = "rain"
    elif code == 600:
        # light snow
        icon = "snow"
    elif code == 601:
        # snow
        icon = "snow"
    elif code == 602:
        # heavy snow
        icon = "snow"
    elif code == 611:
        # sleet
        icon = "snow"
        status = "Sleet"
    elif code == 612:
        # light shower sleet
        icon = "snow"
        status = "Sleet"
    elif code == 613:
        # shower sleet
        icon = "snow"
        status = "Sleet"
    elif code == 615:
        # light rain and snow
        icon = "snow"
        status = "RainSno"
    elif code == 616:
        # rain and snow
        icon = "snow"
        status = "RainSno"
    elif code == 620:
        # light shower snow
        icon = "snow"
        status = "RainSno"
    elif code == 621:
        # shower snow
        icon = "snow"
        status = "RainSno"
    elif code == 622:
        # heavy shower snow
        icon = "snow"
        status = "RainSno"
    elif code < 700:
        # generic fallback for "snow"
        icon = "snow"
    elif code == 701:
        # mist
        icon = "haze"
    elif code == 711:
        # smoke
        icon = "haze"
    elif code == 721:
        # haze
        icon = "haze"
    elif code == 731:
        # sand/dust whirls
        icon = "haze"
    elif code == 741:
        # fog
        icon = "haze"
    elif code == 751:
        # sand
        icon = "haze"
    elif code == 761:
        # dust
        icon = "haze"
    elif code == 762:
        # volcanic ash
        icon = "haze"
    elif code == 771:
        # squalls
        icon = "tornado"
    elif code == 781:
        # tornado
        icon = "tornado"
    elif code < 800:
        # generic fallback for "haze"
        icon = "haze"
    elif code == 800:
        # clear sky
        icon = "clear"
    elif code == 801:
        # few clouds: 11-25%
        icon = "cloudpart"
    elif code == 802:
        # scattered clouds: 25-50%
        icon = "cloud"
    elif code == 803:
        # broken clouds: 51-84%
        icon = "cloudheavy"
    elif code == 804:
        # overcast clouds: 85-100%
        icon = "cloudheavy"
        status = "Overcst"
    else:
        # generic fallback for "clouds"
        icon = "cloud"

    if isNight and icon in ["clear", "cloudpart", "rainlight"]:
        icon += "_night"

    return icon, status


def get_mac_id(interface="wlan0"):
    try:
        mac_path = f"/sys/class/net/{interface}/address"
        if not os.path.exists(mac_path):
            return "UNKNOWN"

        with open(mac_path, "r", encoding="utf-8") as f:
            mac_address = f.read().strip()
        return mac_address.replace(":", "").upper()[-4:]
    except Exception:
        return "UNKNOWN"


# Degrees of hue advanced for each pixel painted with the free sketch rainbow pen.
# Must stay in sync with FREE_SKETCH_RAINBOW_STEP in web/index.js.
FREE_SKETCH_RAINBOW_STEP = 9


def rainbow_pen_color(angle):
    """Return the (r, g, b) rainbow pen color for a hue angle in degrees."""
    _, r, g, b = next_color_rainbow_linear(angle % 360, dangle=0)
    return r, g, b


def get_version():
    try:
        with open("version.txt", "r") as f:
            return f.read().strip()
    except Exception:
        return "unknown"


def bresenham_line(x0, y0, x1, y1):
    """Yield (x, y) for each point on the line from (x0,y0) to (x1,y1)."""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        yield (x0, y0)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def paint_brush(pixel_buffer, cx, cy, brush_size, color, brush_shape="square"):
    """Paint a brush stamp centered at (cx, cy) into pixel_buffer (no lock)."""
    pixels = get_brush_shape_pixels(cx, cy, brush_size, brush_shape)
    for px, py in pixels:
        if 0 <= px < 128 and 0 <= py < 32:
            index = (py * 128 + px) * 3
            pixel_buffer[index : index + 3] = color


def get_brush_shape_pixels(cx, cy, size, shape):
    """Get the list of (x, y) pixels for a brush stamp centered at (cx, cy)."""
    pixels = []
    half = size // 2

    if shape == "square":
        for dy in range(-half, size - half):
            for dx in range(-half, size - half):
                pixels.append((cx + dx, cy + dy))
    elif shape == "plus":
        # Vertical and horizontal lines
        for d in range(-half, size - half):
            pixels.append((cx, cy + d))  # vertical
            pixels.append((cx + d, cy))  # horizontal
    elif shape == "x":
        # Diagonal lines
        for d in range(-half, size - half):
            pixels.append((cx + d, cy + d))  # diagonal \
            pixels.append((cx + d, cy - d))  # diagonal /
    elif shape == "circle":
        # Circle approximation using distance formula
        radius_squared = (size / 2.0) * (size / 2.0)
        for dy in range(-half, size - half):
            for dx in range(-half, size - half):
                dist_squared = dx * dx + dy * dy
                if dist_squared <= radius_squared:
                    pixels.append((cx + dx, cy + dy))

    # Remove duplicates
    return list(set(pixels))


def stamp_sprite_on_buffer(pixel_buffer, sprite, cx, cy):
    """Composite an RGBA PIL sprite centered at (cx, cy) onto pixel_buffer (no lock).

    Only writes pixels where the sprite alpha is > 0.
    """
    w, h = sprite.size
    ox = cx - w // 2
    oy = cy - h // 2
    rgba = np.array(sprite)
    for sy in range(h):
        py = oy + sy
        if not 0 <= py < 32:
            continue
        for sx in range(w):
            px = ox + sx
            if not 0 <= px < 128:
                continue
            if rgba[sy, sx, 3] == 0:
                continue
            index = (py * 128 + px) * 3
            pixel_buffer[index] = rgba[sy, sx, 0]
            pixel_buffer[index + 1] = rgba[sy, sx, 1]
            pixel_buffer[index + 2] = rgba[sy, sx, 2]


def validate_sketch_filename(filename):
    if not filename or not re.match(r"^[a-zA-Z0-9_\-]+\.png$", filename):
        return False
    if ".." in filename or "/" in filename or "\\" in filename:
        return False
    return True


@__main__.planesign_mode_handler(DisplayMode.SIGN_OFF)
def clear_matrix(sign):
    sign.canvas.Clear()
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.wait_loop(-1)
