import math
import random
import logging
import time
import pytz
import os
import __main__
import shared_config

from PIL import Image, ImageDraw, ImageFont
from timezonefinder import TimezoneFinder
from rgbmatrix import graphics
from math import pi, cos, sin
from datetime import datetime

NUM_STEPS = 40
DEG_2_RAD = pi/180.0
KM_2_MI = 0.6214


def read_config():
    shared_config.CONF.clear()

    logging.info("Reading  config...")

    if not os.path.exists("sign.conf"):
        logging.warn("WARNING! No sign.conf found... using default values from sign.conf.sample")
    else:
        with open("sign.conf") as f:
            for line in f.readlines():
                if line.isspace() or line[0] == "#":
                    continue
                key, val = line.split('=')
                shared_config.CONF[key] = val.rstrip()

    with open("sign.conf.sample") as f:
        for line in f.readlines():
            if line.isspace() or line[0] == "#":
                continue
            key, val = line.split('=')
            if key not in shared_config.CONF.keys():
                logging.warn(f"WARNING! No setting for '{key}' found in sign.conf, using value '{val.rstrip()}' from sign.conf.sample")
                shared_config.CONF[key] = val.rstrip()

    logging.info("Config loaded: " + str(shared_config.CONF))

    tf = TimezoneFinder()
    local_tz = tf.timezone_at(lat=float(shared_config.CONF["SENSOR_LAT"]), lng=float(shared_config.CONF["SENSOR_LON"]))
    if local_tz is None:
        logging.warn("Cannot find given provided lat/lon! Using UTC...")
        shared_config.local_timezone = pytz.utc
    else:
        logging.info(f"Detected timezone to be {local_tz}")
        shared_config.local_timezone = pytz.timezone(local_tz)


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
    def __init__(self,sign,x,y,color,boxdim,text=None,space=1,font="5x7",scrolldir='left',scrollspeed=5,holdtime=0,forcescroll=False):

        self.sign=sign
        self.x=x
        self.y=y

        self.text=text
        self.lasttext=None
        self.space=space
        self.fontname=font
        self.color=color
        self.scrolldir=scrolldir
        self.scrollspeed=scrollspeed
        self.forcescroll=forcescroll
        self.holdtime=holdtime
        self.holdtimer=0
        if holdtime==0:
            self.stopflag=False
        else:
            self.stopflag=True


        if self.fontname=="6x13" or self.fontname=="fontbig" or self.fontname=="big":
            self.fontname="6x13"
            bdffont=self.sign.fontbig
        elif self.fontname=="9x18B" or self.fontname=="fontreallybig" or self.fontname=="reallybig":
            self.fontname="9x18B"
            bdffont=self.sign.fontreallybig
        elif self.fontname=="helvR12" or self.fontname=="fontplanesign" or self.fontname=="planesign":
            self.fontname="helvR12"
            bdffont=self.sign.fontplanesign
        elif self.fontname=="4x6":
            bdffont=self.sign.font46
        else:
            self.fontname=="5x7"
            bdffont=self.sign.font57

        self.font = ImageFont.load("./fonts/"+font+".pil")
            
        self.cw=bdffont.CharacterWidth(0)
        self.ch=bdffont.height

        self.w,self.h=boxdim

        self.lastdrawtime=None
        self.offset = 0

        if text!=None:
            self.length=len(self.text)
        else:
            self.length=None

        self.image = Image.new("RGB", boxdim, (0, 0, 0))
        self.dr = ImageDraw.Draw(self.image)

    def draw(self):

        if self.text==None:
            return

        if self.text != self.lasttext:
            self.lasttext=self.text
            self.length=len(self.text)
            self.lastdrawtime=None
            self.offset = 0

        if self.text=="":
            return

        self.dr.rectangle([(0,0),self.image.size], fill = (0,0,0) )

        curtime = time.perf_counter()

        #Scroll Text
        if ((self.scrolldir == "left" or self.scrolldir == "right") and self.length*self.cw>self.w) or ((self.scrolldir == "up" or self.scrolldir == "down") and self.ch>self.h) or self.forcescroll:

            if self.lastdrawtime != None:

                if self.holdtime==0:
                    self.offset = self.offset+self.scrollspeed*(curtime-self.lastdrawtime)
                elif round(self.offset)==0 and self.stopflag:
                    self.holdtimer=self.holdtimer+(curtime-self.lastdrawtime)
                elif self.holdtimer<self.holdtime or not self.stopflag:

                    tempoffset = self.offset+self.scrollspeed*(curtime-self.lastdrawtime)
                    if round(tempoffset)*round(self.offset)<0:#make sure we don't skip over 0 by going too fast
                        self.offset = 0
                        self.stopflag = True
                        self.holdtimer=0
                    else:
                        self.offset = tempoffset
                        
                    if not self.stopflag and round(self.offset)!=0:
                        self.stopflag = True

                if self.holdtimer>=self.holdtime:
                    self.stopflag=False
                    self.holdtimer=0


            if self.scrolldir=="left" or self.scrolldir=="right":
                self.offset = self.offset%((self.length+self.space)*self.cw)
                for o in range(-round((self.length+self.space)*self.cw), self.w+round((self.length+self.space)*self.cw)+1, round((self.length+self.space)*self.cw)):
                    if self.scrolldir=="left":
                        self.dr.text((round(-self.offset+o), 0), self.text, font=self.font, fill=self.color)
                    elif self.scrolldir=="right":  
                        self.dr.text((round(self.offset+o), 0), self.text, font=self.font, fill=self.color)
            else:
                self.offset = self.offset%((1+self.space)*self.ch)
                for o in range(-round((1+self.space)*self.ch), self.h+round((1+self.space)*self.ch)+1, round((1+self.space)*self.ch)):
                    if self.scrolldir=="up":
                        self.dr.text((0, round(-self.offset+o)), self.text, font=self.font, fill=self.color)
                    elif self.scrolldir=="down":  
                        self.dr.text((0, round(self.offset+o)), self.text, font=self.font, fill=self.color)

        else:#Text will fit in box, don't need to scroll if we don't have to
            self.dr.text((0, 0), self.text, font=self.font, fill=self.color)

        self.sign.canvas.SetImage(self.image.convert('RGB'), self.x, self.y-self.h+1)

        self.lastdrawtime=curtime

def fix_chars(name):
    name = name.replace("–","-")
    for ch in [u'\u0100',u'\u0102',u'\u0104']:
        name = name.replace(ch,"A")
    for ch in [u'\u0101',u'\u0103',u'\u0105']:
        name = name.replace(ch,"a")
    for ch in [u'\u0106',u'\u0108',u'\u010A',u'\u010C']:
        name = name.replace(ch,"C")
    for ch in [u'\u0107',u'\u0109',u'\u010B',u'\u010D']:
        name = name.replace(ch,"c")
    for ch in [u'\u010E',u'\u0110']:
        name = name.replace(ch,"D")
    for ch in [u'\u010F',u'\u0111']:
        name = name.replace(ch,"d")
    for ch in [u'\u0112',u'\u0114',u'\u0116',u'\u0118',u'\u011A']:
        name = name.replace(ch,"E")
    for ch in [u'\u0113',u'\u0115',u'\u0117',u'\u0119',u'\u011B']:
        name = name.replace(ch,"e")
    for ch in [u'\u011C',u'\u011E',u'\u0120',u'\u0122']:
        name = name.replace(ch,"G")
    for ch in [u'\u011D',u'\u011F',u'\u0121',u'\u0123']:
        name = name.replace(ch,"g")
    for ch in [u'\u0124',u'\u0126']:
        name = name.replace(ch,"H")
    for ch in [u'\u0125',u'\u0127']:
        name = name.replace(ch,"h")
    for ch in [u'\u0128',u'\u012A',u'\u012C',u'\u012E',u'\u0130',u'\u0132']:
        name = name.replace(ch,"I")
    for ch in [u'\u0129',u'\u012B',u'\u012D',u'\u012F',u'\u0131',u'\u0133']:
        name = name.replace(ch,"i")
    for ch in [u'\u0134']:
        name = name.replace(ch,"J")
    for ch in [u'\u0135']:
        name = name.replace(ch,"j")
    for ch in [u'\u0136']:
        name = name.replace(ch,"K")
    for ch in [u'\u0137',u'\u0138']:
        name = name.replace(ch,"k")
    for ch in [u'\u0139',u'\u013B',u'\u013D',u'\u013F',u'\u0141']:
        name = name.replace(ch,"L")
    for ch in [u'\u0140',u'\u013C',u'\u013E',u'\u0140',u'\u0142']:
        name = name.replace(ch,"l")
    for ch in [u'\u0143',u'\u0145',u'\u0147',u'\u014A']:
        name = name.replace(ch,"N")
    for ch in [u'\u0144',u'\u0146',u'\u0148',u'\u0149',u'\u014B']:
        name = name.replace(ch,"n")
    for ch in [u'\u014C',u'\u014E',u'\u0150',u'\u0152']:
        name = name.replace(ch,"O")
    for ch in [u'\u014D',u'\u014F',u'\u0151',u'\u0153']:
        name = name.replace(ch,"o")
    for ch in [u'\u0154',u'\u0156',u'\u0158']:
        name = name.replace(ch,"R")
    for ch in [u'\u0155',u'\u0157',u'\u0159']:
        name = name.replace(ch,"r")
    for ch in [u'\u015A',u'\u015C',u'\u015E',u'\u0160']:
        name = name.replace(ch,"S")
    for ch in [u'\u015B',u'\u015D',u'\u015F',u'\u0161',u"\u017F"]:
        name = name.replace(ch,"s")       
    for ch in [u'\u0162',u'\u0164',u'\u0166']:
        name = name.replace(ch,"T")  
    for ch in [u'\u0163',u'\u0165',u'\u0167']:
        name = name.replace(ch,"t") 
    for ch in [u'\u0168',u'\u016A',u'\u016C',u'\u016E',u'\u0170',u'\u0172']:
        name = name.replace(ch,"U") 
    for ch in [u'\u0169',u'\u016B',u'\u016D',u'\u016F',u'\u0171',u'\u0173']:
        name = name.replace(ch,"U") 
    for ch in [u'\u0174']:
        name = name.replace(ch,"W") 
    for ch in [u'\u0175']:
        name = name.replace(ch,"w") 
    for ch in [u'\u0176',u'\u0178']:
        name = name.replace(ch,"Y") 
    for ch in [u'\u0177']:
        name = name.replace(ch,"y") 
    for ch in [u'\u0179',u'\u017B',u'\u017D']:
        name = name.replace(ch,"Z") 
    for ch in [u'\u017A',u'\u017C',u'\u017E']:
        name = name.replace(ch,"z") 

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

    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)


@__main__.planesign_mode_handler(0)
def clear_matrix(sign):
    sign.canvas.Clear()
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.wait_loop(-1)
