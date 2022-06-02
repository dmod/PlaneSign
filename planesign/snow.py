#!/usr/bin/python3
# -*- coding: utf-8 -*-

import logging.handlers
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from PIL import Image, ImageDraw, ImageFont, GifImagePlugin
import threading
from multiprocessing import Process, Manager, Value
from bs4 import BeautifulSoup
import shared_config
import numpy as np
import math
import re
import time
import utilities
import __main__

import timeit


def snowcolor(inches):

    if inches == "-":
        return graphics.Color(50, 50, 50)

    inches = int(inches)

    if inches == 0:
        color =  graphics.Color(150, 150, 150)
    elif inches>=6:
        color = graphics.Color(229, 119, 0)
    else:
        color =  graphics.Color(66, 151, 213)
        
    return color

def fixicon(image):

    image = image.convert('RGB')
    rgb = np.array(image)

    width, height = image.size

    if np.count_nonzero((rgb[:, :, 0] < 5) & (rgb[:, :, 1] < 5) & (rgb[:, :, 2] < 5))/(width*height) > 0.33:

        mask = (rgb[:, :, 0] >= 200) & (rgb[:, :, 1] >= 200) & (rgb[:, :, 2] >= 200)
        rgb[mask, 0:3] = np.ones_like(rgb[mask, 0:3])*255

        image = Image.fromarray(rgb)

        image = utilities.autocrop(image, (255,255,255))

        rgb = np.array(image)
        
        #lighten dark colors
        mask = (rgb[:, :, 0] < 30) & (rgb[:, :, 1] < 30) & (rgb[:, :, 2] < 30)
        rgb[mask, 0:3] = np.true_divide(rgb[mask, 0:3], 2.0)+[15, 15, 15]

        image = Image.fromarray(rgb)

    else:

        #lighten dark colors
        mask = (rgb[:, :, 0] < 50) & (rgb[:, :, 1] < 50) & (rgb[:, :, 2] < 50)
        rgb[mask, 0:3] = np.true_divide(rgb[mask, 0:3], 2.0)+[35, 35, 35]

        #remove white background
        mask = (rgb[:, :, 0] >= 200) & (rgb[:, :, 1] >= 200) & (rgb[:, :, 2] >= 200)
        rgb[mask, 0:3] = np.zeros_like(rgb[mask, 0:3])

        image = Image.fromarray(rgb)

        image = utilities.autocrop(image, (0,0,0))

    width, height = image.size

    # rescale to 20px max, preserving logo aspect ratio
    if width > height:
        image = image.resize((20, int(20*height/width)), Image.BICUBIC)
    elif height > width:
        image = image.resize((int(20*width/height), 20), Image.BICUBIC)
    else:
        image = image.resize((20, 20), Image.BICUBIC)

    # tone down brightness
    bg = (0, 0, 0, 50)
    new_image = Image.new("RGBA", image.size, bg)
    image.paste(new_image, (0, 0), new_image)

    return image.convert('RGB')


class SnowReport:
    def __init__(self,sign):
        self.sign = sign
        self.last_snow_mode = None
        self.resorts = Manager().list()
        self.lastupdate = Value('d',0)
        self.lastdisp = -1
        self.lastresort = None

        self.draw_loading()

    def draw_loading(self):

        thread = Process(target=self.getdata, name="SnowDataWorker")
        thread.start()
        
        image = Image.open("./icons/snow1.gif")

        nf = image.n_frames
        frame=0
        
        while thread.is_alive():

            image.seek(frame)

            self.sign.canvas.SetImage(image.resize((128, 64), Image.BICUBIC).convert('RGB'), 1, -15)
            for i in range(-1,2):
                for j in range(-1,2):
                    graphics.DrawText(self.sign.canvas, self.sign.fontbig, 7+i, 12+j, graphics.Color(0,0,0), "Loading...")
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 7, 12, graphics.Color(255,255,255), "Loading...")
            self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)
            self.sign.canvas.Clear()
            

            frame = (frame+1)%nf
            
            self.sign.wait_loop(0.5)

        thread.join()

    def drawresort(self):

        if time.perf_counter()-self.lastupdate.value > 1300:
            self.getdata()

        if self.resorts:
            #openresorts = list(filter(lambda resort: resort['open'], self.resorts))

            ind = -1 
            if self.lastresort != None:                
                for resort in self.resorts:#openresorts:
                    ind+=1
                    if resort['name']==self.lastresort:
                        break
            ind = (ind+1)%len(self.resorts)#len(openresorts)

            resort = self.resorts[ind]#openresorts[ind]
            self.lastresort = resort['name']

            if resort['open']:
                graphics.DrawText(self.sign.canvas, self.sign.fontbig, 46-round(len(resort['name'][:15])*3), 10, graphics.Color(10, 150, 10), resort['name'][:15])
            else:
                graphics.DrawText(self.sign.canvas, self.sign.fontbig, 46-round(len(resort['name'][:15])*3), 10, graphics.Color(100, 10, 10), resort['name'][:15]) 

            sizex, sizey = resort['icon'].size
            self.sign.canvas.SetImage(resort['icon'], 12-round(sizex/2), 22-round(sizey/2))
            
            graphics.DrawText(self.sign.canvas, self.sign.font57, 24, 21, graphics.Color(100, 10, 10), "New:")#150, 7, 7
            graphics.DrawText(self.sign.canvas, self.sign.font57, 45, 21, snowcolor(resort['new']), resort['new']+'"')


            graphics.DrawText(self.sign.canvas, self.sign.font57, 40-round(len(resort['curtemp'])*5/2), 30, graphics.Color(60, 60, 200), resort['curtemp'])
            
            graphx = 64
            graphy = 30
            graphw = 4
            offset = 0
            graphics.DrawLine(self.sign.canvas, graphx-1, graphy+1, 125, graphy+1, graphics.Color(13, 13, 25))
            for i in range(len(resort['forcast'])):
                if i== 5:
                    offset = 2
                if resort['forcast'][i]>0:
                    barheight = math.ceil(resort['forcast'][i]/2)
                    for j in range(barheight):
                        if j >= 10:
                            break
                        graphics.DrawLine(self.sign.canvas, offset+graphx+i*(graphw+2), graphy-j, offset+graphx+graphw+i*(graphw+2), graphy-j,  snowcolor(resort['forcast'][i]))

            liney = 18
            x5d = 79-round((len(resort['5d'])+1)*5/2)
            x10d = 111-round((len(resort['10d'])+1)*5/2)
            graphics.DrawLine(self.sign.canvas, 62, liney, x5d-3, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x5d+1+(len(resort['5d'])+1)*5, liney, x10d-3, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x10d+1+(len(resort['10d'])+1)*5, liney, 125, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, 62, liney-3, 62, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, 94, liney-3, 94, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, 126, liney-3, 126, liney+3, graphics.Color(13, 13, 25))
            graphics.DrawText(self.sign.canvas, self.sign.font57, x5d, liney+3, snowcolor(resort['5d']), resort['5d']+'"')
            graphics.DrawText(self.sign.canvas, self.sign.font57, x10d, liney+3, snowcolor(resort['10d']), resort['10d']+'"')

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
            graphics.DrawText(self.sign.canvas, self.sign.font46, sunx+7, suny+5, graphics.Color(95, 95, 105), f"{resort['daymin']}-{resort['daymax']}°F")

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

            graphics.DrawText(self.sign.canvas, self.sign.font46, moonx+7, moony+5, graphics.Color(95, 95, 105), f"{resort['nightmin']}-{resort['nightmax']}°F")

    def drawoverview(self):

        if time.perf_counter()-self.lastupdate.value > 1300:
            self.getdata()

        if self.resorts:
            offset = 0
            for i in range(min(4,len(self.resorts))):

                ind = (self.lastdisp+1+i)%len(self.resorts)
                resort = self.resorts[ind]

                if resort["open"]:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 1, 7+offset, graphics.Color(40, 167, 69), resort['name'][:15])
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 1, 7+offset, graphics.Color(115, 18, 15), resort['name'][:15])#231, 109, 99
                
                graphics.DrawLine(self.sign.canvas, 94, 0, 94, 31, graphics.Color(13, 13, 25))
                
                graphics.DrawText(self.sign.canvas, self.sign.font57, 87-round((len(resort['new'])+1)*5/2), 7+offset, snowcolor(resort['new']), resort['new']+'"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 106-round((len(resort['5d'])+1)*5/2), 7+offset, snowcolor(resort['5d']), resort['5d']+'"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 123-round((len(resort['10d'])+1)*5/2), 7+offset, snowcolor(resort['10d']), resort['10d']+'"')

                offset += 8
            self.lastdisp = ind

    def getdata(self):

        with requests.Session() as s:
            response = s.post('https://opensnow.com/user/login', data={'email': 'russellnadler@gmail.com', 'password': 'llessur5SNOW!'})

        if response and response.status_code == requests.codes.ok:
            soup = BeautifulSoup(response.content, "html.parser")

            self.lastupdate.value = time.perf_counter()
            self.resorts[:] = []

            for i in range(1,11):
                resort = {}
                resdiv = soup.find(attrs={"data-user-rank" : str(i)})

                if resdiv:
                    resort['name'] = resdiv.find('div', {'class' :'compare-title'}).find('div', {'class' :'title-location'}).text

                    resort['rank'] = i

                    resort['iconurl'] = resdiv.find('img', {'class' :'location-icon'})['src']
                    try:
                        image = Image.open(f'{shared_config.icons_dir}/resorts/{resort["name"].replace(" ","_")}.png').convert('RGB')
                    except:
                        try:
                            image = Image.open(requests.get(resort['iconurl'], stream=True).raw)
                            image = fixicon(image)
                        except:
                            image = Image.new('RGB', (20, 20), (0, 0, 0))

                    resort['icon'] = image

                    if resdiv.find('div', {'class' :'compare-update'}).find('span', {'class' :'status-open'}):
                        resort['open'] = True
                    else:
                        resort['open'] = False
                        
                    newsnow = resdiv.find('div', {'class' :'summary-data-value'}).text
                    try:
                        resort["new"] = re.findall('\d+', newsnow, re.MULTILINE)[0]
                    except:
                        resort["new"] = "-"
                    
                    summary = resdiv.find('div', {'class':'col-8'}).contents[3].find_all('div', {'class':'text'})

                    if len(summary)>0:
                        try:
                            resort['5d']=re.findall('\d+',summary[0].text, re.MULTILINE)[0]
                        except:
                            resort['5d']="-"

                    if len(summary)>1:
                        try:
                            resort['10d']=re.findall('\d+',summary[1].text, re.MULTILINE)[0]
                        except:
                            resort['10d']="-"

                    resort['forcast']=[]
                    for bar in resdiv.find('table', {'class' :'tiny-graph'}).find_all("td", {'class' :'snow-bar'}):
                        try:
                            inches=re.findall('\d+',bar.find("span", {'class' :'bar'})['value'], re.MULTILINE)[0]
                        except:
                            inches=0
                        resort['forcast'].append(int(inches))

                    resort['dates']=[]
                    for bar in resdiv.find('table', {'class' :'tiny-graph'}).find_all("td", {'class' :'tiny-date'}):
                        resort['dates'].append(bar.find("span", {'class' :'dow'}).text+" "+bar.find("span", {'class' :'day'}).text)

                    try:
                        temp = re.findall('\S+',resdiv.find('div', {'class':'temperature-compare'}).find('div', {'class':'summary-data-value'}).text, re.MULTILINE)[0]
                        
                    except:
                        temp = '?°F'

                    resort['curtemp'] = temp
                    

                    resort['nightmin']=100
                    resort['nightmax']=-100
                    resort['daymin']=100
                    resort['daymax']=-100

                    for bar in resdiv.find('div', {'class':'forecasts-compare'}).find('table', {'class' :'tiny-graph'}).find_all("td", {'class' :'snow-bar'}):
                    
                        try:
                            temp = int(re.findall('\d+',bar.find("span", {'class' :'temp'}).text, re.MULTILINE)[0])
                        except:
                            continue

                        if 'day' in bar.get("class"):
                            if temp > resort['daymax']:
                                resort['daymax'] = temp
                            elif temp < resort['daymin']:
                                resort['daymin'] = temp
                        elif 'night' in bar.get("class"):
                            if temp > resort['nightmax']:
                                resort['nightmax'] = temp
                            elif temp < resort['nightmin']:
                                resort['nightmin'] = temp

                if resort:
                    self.resorts.append(resort)

@__main__.planesign_mode_handler(420)
def snow_forcast(sign):
    sign.canvas.Clear()

    last_draw = time.perf_counter()

    sr = SnowReport(sign)

    while shared_config.shared_mode.value == 420:

        if ((time.perf_counter()-last_draw > 30) and (shared_config.shared_snow_mode.value == 1)) or time.perf_counter()-last_draw > 15 or (sr.last_snow_mode != shared_config.shared_snow_mode.value):
                    
            if shared_config.shared_snow_mode.value == 1:
                sr.drawresort()
            else:
                sr.drawoverview()
            sr.last_snow_mode = shared_config.shared_snow_mode.value
                
            last_draw = time.perf_counter()
            
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.canvas.Clear()
            
        breakout = sign.wait_loop(0.5)

        if breakout:
            return