import math
import random
import logging
import time
import pytz
import os
import __main__
import shared_config
import numpy as np
import subprocess

from PIL import Image, ImageDraw, ImageFont
from timezonefinder import TimezoneFinder
from rgbmatrix import graphics
from math import pi, cos, sin
from datetime import datetime

NUM_STEPS = 40
DEG_2_RAD = pi/180.0
KM_2_MI = 0.6214    

from modes import DisplayMode

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

    shared_config.airport_codes_to_ignore = set(shared_config.CONF["IGNORE_AIRPORT_CODES"].split(","))


def random_angle():
    return random.randrange(0, 360)


def random_rgb_255_sum():
    _, r, g, b = next_color_rainbow_linear(random_angle())
    return r, g, b


def detect_usb_audio_device():
    result = subprocess.run(['aplay', '-l'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    lines = result.stdout.splitlines()
    for line in lines:
        if 'USB Audio' in line and 'card' in line and 'device' in line:
            # Example line: card 0: UACDemoV10 [UACDemoV1.0], device 0: USB Audio [USB Audio]
            parts = line.split()
            card_index = parts.index('card') + 1
            device_index = parts.index('device') + 1
            card_num = parts[card_index].replace(':', '')
            device_num = parts[device_index].replace(':', '')
            shared_config.audio_device = f"hw:{card_num},{device_num}"
            logging.info(f"Detected USB Audio device: {shared_config.audio_device}")
            set_usb_audio_volume(card_num)
            return

def set_usb_audio_volume(card_num):
    try:
        # First, get list of available controls
        result = subprocess.run(['amixer', '-c', card_num, 'controls'], 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to get controls: {result.stderr}")
            return

        # Look for common volume control names
        volume_controls = ['Master', 'PCM', 'Speaker', 'Headphone', 'Playback']
        found_control = None
        
        for line in result.stdout.splitlines():
            for control in volume_controls:
                if control in line:
                    found_control = control
                    break
            if found_control:
                break

        if not found_control:
            logging.error("No suitable volume control found")
            return

        volume_percent = "90%"
        result = subprocess.run(['amixer', '-c', card_num, 'set', found_control, volume_percent], 
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            logging.info(f"Successfully set USB audio volume to {volume_percent} using {found_control} control")
        else:
            logging.error(f"Failed to set volume: {result.stderr}")
    except Exception as e:
        logging.error(f"Error setting USB audio volume: {e}")

def read_static_airport_data():
    with open("datafiles/airports.csv") as f:
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

        self.colortimer = time.perf_counter()
        self.coloroffset = 0
        self.color_mode_offset = 6
        self.tempcolor = random_rgb(rmin=10,gmin=10,bmin=10)

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
            self.fontw = 6
        elif self.fontname=="9x18B" or self.fontname=="fontreallybig" or self.fontname=="reallybig":
            self.fontname="9x18B"
            bdffont=self.sign.fontreallybig
            self.fontw = 9
        elif self.fontname=="helvR12" or self.fontname=="fontplanesign" or self.fontname=="planesign":
            self.fontname="helvR12"
            bdffont=self.sign.fontplanesign
            self.fontw = 9
        elif self.fontname=="4x6":
            bdffont=self.sign.font46
            self.fontw = 4
        else:
            self.fontname=="5x7"
            bdffont=self.sign.font57
            self.fontw = 5

        self.font = ImageFont.load("./fonts/"+self.fontname+".pil")
            
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

    def set_text(self,dx,dy):

        if type(self.color) is tuple:
            self.dr.text((dx, dy), self.text, font=self.font, fill=self.color)
        else:
            if self.color==0 or self.color==5:

                self.dr.text((dx, dy), self.text, font=self.font, fill=(3, 194, 255))

            if self.color==1:

                if self.colortimer+0.1<time.perf_counter():
                    self.colortimer = time.perf_counter()
                    self.tempcolor = random_rgb(rmin=10,gmin=10,bmin=10)
                self.dr.text((dx, dy), self.text, font=self.font, fill=self.tempcolor)

            if (self.color>=2 and self.color <=4) or self.color>5:

                if self.color == 2:
                    colors = [(12, 169, 12),(206, 13, 13)] #CHRISTMAS
                elif self.color == 3:
                    colors = [(173, 0, 30),(178, 178, 178),(37, 120, 178)] #4TH OF JULY
                elif self.color == 4:
                    colors = [(20, 20, 20),(247, 95, 28)] #HALLOWEEN
                else:
                    colors = [(((self.color-self.color_mode_offset) >> 16) & 255, ((self.color-self.color_mode_offset) >> 8) & 255, (self.color-self.color_mode_offset) & 255)]


                if self.colortimer+1.1<time.perf_counter():
                    self.colortimer = time.perf_counter()
                    self.coloroffset = (self.coloroffset+1)%len(colors)

                self.dr.text((dx, dy), self.text, font=self.font, fill=colors[(0+self.coloroffset)%len(colors)])
                if len(colors)>1:
                    for index, letter in enumerate(self.text):
                        if index % len(colors) == 1:
                            self.dr.text((dx+self.fontw*index, dy), letter, font=self.font, fill=colors[(1+self.coloroffset)%len(colors)])
                        if len(colors)>2 and index % len(colors) == 2:
                            self.dr.text((dx+self.fontw*index, dy), letter, font=self.font, fill=colors[(2+self.coloroffset)%len(colors)])

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
                        r=-1
                    elif self.scrolldir=="right":  
                        r=1

                    self.set_text(round(r*self.offset+o), 0)
            else:
                self.offset = self.offset%((1+self.space)*self.ch)
                for o in range(-round((1+self.space)*self.ch), self.h+round((1+self.space)*self.ch)+1, round((1+self.space)*self.ch)):
                    if self.scrolldir=="up":
                        r=-1
                    elif self.scrolldir=="down":
                        r=1
                    
                    self.set_text(0, round(r*self.offset+o))

        else:#Text will fit in box, don't need to scroll if we don't have to

            self.set_text(0, 0)

        self.sign.canvas.SetImage(self.image.convert('RGB'), self.x, self.y-self.h+1)

        self.lastdrawtime=curtime

def fix_black(image):
    #brighten black
    rgb = np.array(image.convert('RGB'))
    mask = (rgb[:,:,0] < 30) & (rgb[:,:,1] < 30) & (rgb[:,:,2] < 30)
    rgb[mask] = np.true_divide(rgb[mask],2.0)+[15,15,15]
    image = Image.fromarray(rgb)    

    return image

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
    for row in range(sizey-1, top+2, -1):
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
        for row in range(top+1, bot, 1):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break

    left = col

    flag = False
    for col in range(sizex-1, left+2, -1):
        for row in range(top+1, bot, 1):
            if image.getpixel((col, row)) != bg:
                flag = True
            if flag:
                break
        if flag:
            break

    right = col

    return image.crop((left, top, right, bot))


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
        v = int(v)
        return (v, v, v)
    i = int(h*6.)
    f = (h*6.)-i
    p, q, t = int(255*(v*(1.-s))), int(255*(v*(1.-s*f))), int(255*(v*(1.-s*(1.-f))))
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
    r, g, b = r/255.0, g/255.0, b/255.0
    mx = max(r, g, b)
    mn = min(r, g, b)
    df = mx-mn
    if mx == mn:
        h = 0
    elif mx == r:
        h = (60 * ((g-b)/df) + 360) % 360
    elif mx == g:
        h = (60 * ((b-r)/df) + 120) % 360
    elif mx == b:
        h = (60 * ((r-g)/df) + 240) % 360
    if mx == 0:
        s = 0
    else:
        s = (df/mx)*100
    v = mx*100
    return h, s, v


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


def direction_lookup(destination, origin=None):
    
    if origin==None and (type(destination) is float or type(destination) is np.float64 or type(destination) is int):

        degrees = destination

    else:
        destination_y, destination_x = destination
        origin_y, origin_x = origin

        deltaX = destination_x - origin_x

        deltaY = destination_y - origin_y

        degrees = math.atan2(deltaX, deltaY)/math.pi*180

    degrees = degrees%360

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


@__main__.planesign_mode_handler(DisplayMode.TIME_ONLY)
def only_show_time(sign):
    while shared_config.shared_mode.value == DisplayMode.TIME_ONLY.value:
        show_time(sign)
        breakout = sign.wait_loop(1)
        if breakout:
            return


def show_time(sign):
    if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
        print_time = convert_unix_to_local_time(time.time()).strftime('%H:%M')
    else:
        print_time = convert_unix_to_local_time(time.time()).strftime('%-I:%M%p')

    xloc = 86
    if "weather" in shared_config.data_dict:
        tempval = round(shared_config.data_dict['weather']['current']['temp'])
        if tempval<0 or tempval>99:
            xloc = 77
        temp = str(tempval)
    else:
        temp = "--"

    sign.canvas.Clear()

    tempstr = temp + "°F"

    graphics.DrawText(sign.canvas, sign.fontreallybig, 7, 21, graphics.Color(0, 150, 0), print_time)
    graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, 21, graphics.Color(20, 20, 240), tempstr)

    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

def weather_icon_decode(code,status):
    if code==200:
        icon="thunderrain"
    elif code==201:
        icon="thunderrain"
    elif code==202:
        icon="thunderrainheavy"
    elif code==210:
        icon="thunder"
    elif code==211:
        icon="thunder"
    elif code==212:
        icon="thunderheavy"
    elif code==221:
        icon="thunder"
    elif code==230:
        icon="thunderrain"
    elif code==231:
        icon="thunderrain"
    elif code==232:
        icon="thunderrainheavy"
    elif code <300:
        icon="thunder"
    elif code==300:
        icon="rainlight"
    elif code==301:
        icon="rain"
    elif code==302:
        icon="rainheavy"
    elif code==310:
        icon="rainlight"
    elif code==311:
        icon="rain"
    elif code==312:
        icon="rain"
    elif code==313:
        icon="rain"
    elif code==314:
        icon="rainheavy"
    elif code==321:
        icon="rain"
    elif code <500:
        icon="rain"
    elif code==500:
        icon="rainlight"
    elif code==501:
        icon="rainlight"
    elif code==502:
        icon="rain"
    elif code==503:
        icon="rainheavy"
    elif code==504:
        icon="rainheavy"
    elif code==511:
        icon="snow"
        status="FrzRain"
    elif code==520:
        icon="rainlight"
    elif code==521:
        icon="rain"
    elif code==522:
        icon="rainheavy"
    elif code==531:
        icon="rainlight"
    elif code <600:
        icon="rain"
    elif code==600:
        icon="snow"
    elif code==601:
        icon="snow"
    elif code==602:
        icon="snow"
    elif code==611:
        icon="snow"
        status="Sleet"
    elif code==612:
        icon="snow"
        status="Sleet"
    elif code==613:
        icon="snow"
        status="Sleet"
    elif code==615:
        icon="snow"
        status="RainSno"
    elif code==616:
        icon="snow"
        status="RainSno"
    elif code==620:
        icon="snow"
    elif code==621:
        icon="snow"
    elif code==622:
        icon="snow"
    elif code <700:
        icon="snow"
    elif code==701:
        icon="haze"
    elif code==711:
        icon="haze"
    elif code==721:
        icon="haze"
    elif code==731:
        icon="haze"
    elif code==741:
        icon="haze"
    elif code==751:
        icon="haze"
    elif code==761:
        icon="haze"
    elif code==762:
        icon="haze"
    elif code==781:
        icon="tornado"
    elif code <800:
        icon="haze"
    elif code==800:
        icon="clear"
    elif code==801:
        icon="cloudpart"
    elif code==802:
        icon="cloud"
    elif code==803:
        icon="cloudheavy"
    elif code==804:
        icon="cloudheavy"
        status="Overcst"
    else:
        icon="cloud"

    return icon,status

@__main__.planesign_mode_handler(DisplayMode.SIGN_OFF)
def clear_matrix(sign):
    sign.canvas.Clear()
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.wait_loop(-1)
