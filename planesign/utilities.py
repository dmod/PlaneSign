import math
import numpy as np
import random
import favicon
import logging
import time
import re
import pytz
import sys
import os
import __main__
import traceback
from multiprocessing import Process, Manager, Value, Array, Queue
import shared_config
import json
import requests
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from multiprocessing import Process, Manager, Value, Array, Queue
from requests import Session
from PIL import Image
from math import pi, cos, sin
from datetime import tzinfo, timedelta, datetime

NUM_STEPS = 40
DEG_2_RAD = pi/180.0
KM_2_MI = 0.6214

def random_angle():
    return random.randrange(0, 360)


def random_rgb_255_sum():
    _, r, g, b = next_color_rainbow_linear(random_angle())
    return r, g, b

def read_static_airport_data():
    with open("airports.csv") as f:
        lines = f.readlines()
        for line in lines:
            parts = line.strip().split(',')
            code = parts[0]
            name = parts[1]
            lat = float(parts[2])
            lon = float(parts[3])
            shared_config.code_to_airport[code] = (name, lat, lon)

    logging.info(f"{len(shared_config.code_to_airport)} static airport configs added")

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
    r = random.randrange(rmin, rmax+1)
    g = random.randrange(gmin, gmax+1)
    b = random.randrange(bmin, bmax+1)
    return r, g, b


def hsv_2_rgb(h, s, v):
    if s == 0.0:
        v *= 255
        return (v, v, v)
    i = int(h*6.)
    f = (h*6.)-i
    p, q, t = int(255*(v*(1.-s))), int(255*(v*(1.-s*f))), int(255*(v*(1.-s*(1.-f))))
    v *= 255
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


def next_color_rainbow_linear(angle, dangle=1, bright=255):
    bright %= 256
    angle += dangle
    angle %= 360

    if(angle <= 120):
        r = round(bright*(120-angle)/120)
        g = round(bright*angle/120)
        b = 0
    elif(angle <= 240):
        r = 0
        g = round(bright*(240-angle)/120)
        b = round(bright*(angle-120)/120)
    else:
        r = round(bright*(angle-240)/120)
        g = 0
        b = round(bright*(360-angle)/120)

    return angle, r, g, b


def next_color_rainbow_sine(angle, dangle=1, bright=255):
    bright %= 256
    angle += dangle
    angle %= 360

    if(angle <= 120):
        r = round(bright*(cos(angle*DEG_2_RAD*3/2)+1)/2)
        g = round(bright*(1-cos(angle*DEG_2_RAD*3/2))/2)
        b = 0
    elif(angle <= 240):
        r = 0
        g = round(bright*(1-cos(angle*DEG_2_RAD*3/2))/2)
        b = round(bright*(cos(angle*DEG_2_RAD*3/2)+1)/2)
    else:
        r = round(bright*(1-cos(angle*DEG_2_RAD*3/2))/2)
        g = 0
        b = round(bright*(cos(angle*DEG_2_RAD*3/2)+1)/2)

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

    while (r+dr) > rmax or (r+dr) < rmin or (g+dg) > gmax or (g+dg) < gmin or (b+db) > bmax or (b+db) < bmin:

        i = random.randrange(0, 3)
        j = (random.randrange(0, 2)*2-1)*step

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

    while (r+dr) > rmax or (r+dr) < rmin or (g+dg) > gmax or (g+dg) < gmin or (b+db) > bmax or (b+db) < bmin:

        theta = math.acos(2*random.random()-1)
        phi = 2*pi*random.random()

        dr = round(step*cos(phi)*sin(theta))
        dg = round(step*sin(phi)*sin(theta))
        db = round(step*cos(theta))

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

    while (r+dr > rmax or r+dr < rmin):
        dr = random.randrange(-step, step+1)
    while (g+dg > gmax or g+dg < gmin):
        dg = random.randrange(-step, step+1)
    while (b+db > bmax or b+db < bmin):
        db = random.randrange(-step, step+1)

    r += dr
    g += dg
    b += db

    return r, g, b


def next_color_andrew_weird(r, g, b, dr, dg, db):

    rtemp = r+dr
    gtemp = g+dg
    btemp = b+db

    if not (r > 230 and dr < 0) and not (r < 30 and dr > 0) and (rtemp <= 30 or rtemp >= 230):
        dr *= -1

    if not (g > 230 and dg > 0) and not (g < 30 and dg < 0) and (gtemp <= 30 or gtemp >= 230):
        dg *= -1

    if not (b > 230 and db > 0) and not (b < 30 and db < 0) and (btemp <= 30 or btemp >= 230):
        db *= -1

    r += dr
    g += dg
    b += db

    return r, g, b, dr, dg, db


def get_distance(coord1, coord2):
    R = 3958.8  # Earth radius in miles
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * \
        math.cos(phi2)*math.sin(dlambda/2)**2

    return (2*R*math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def direction_lookup(destination, origin):
    destination_y, destination_x = destination
    origin_y, origin_x = origin

    deltaX = destination_x - origin_x

    deltaY = destination_y - origin_y

    degrees = math.atan2(deltaX, deltaY)/math.pi*180

    if degrees < 0:
        degrees = 360 + degrees

    compass_brackets = ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]

    compass_lookup = round(degrees/45)

    return compass_brackets[compass_lookup]


def convert_unix_to_local_time(unix_timestamp):
    utc_time = datetime.fromtimestamp(unix_timestamp, tz=pytz.utc)
    local_time = utc_time.astimezone(shared_config.local_timezone)
    return local_time


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

@__main__.planesign_mode_handler(7)
def only_show_time(sign):
    while shared_config.shared_mode.value == 7:
        show_time(sign)
        breakout = sign.wait_loop(1)
        if breakout:
            return

def show_time(sign):
    if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
        print_time = convert_unix_to_local_time(time.time()).strftime('%-H:%M')
    else:
        print_time = convert_unix_to_local_time(time.time()).strftime('%-I:%M%p')

    if "weather" in shared_config.data_dict:
        temp = str(round(shared_config.data_dict["weather"].current.temperature()['temp']))
    else:
        temp = "--"

    sign.canvas.Clear()

    graphics.DrawText(sign.canvas, sign.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
    graphics.DrawText(sign.canvas, sign.fontreallybig, 86, 21, graphics.Color(20, 20, 240), temp + "°F")

    sign.matrix.SwapOnVSync(sign.canvas)

@__main__.planesign_mode_handler(0)
def clear_matrix(sign):
    sign.canvas.Clear()
    sign.matrix.SwapOnVSync(sign.canvas)
    sign.wait_loop(-1)