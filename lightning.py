#!/usr/bin/python3
# -*- coding: utf-8 -*-
import random
import websocket #sudo -H pip3 install websocket-client
import json
import time
import os
import base64
import ssl
from multiprocessing import Process, Manager, Value
import numpy as np
from utilities import *
from rgbmatrix import graphics
from flask import Flask, request
from flask_cors import CORS
import requests
from math import floor
import PIL.ImageDraw as ImageDraw
import PIL.Image as Image
import _thread as thread
import os.path

USAlong=-96
USAlat=38
USAscale=55

#@app.route("/lightning/<zi>")
def set_zoom(zi):
    LightningManager.zoomind.value = int(zi)
    return ""

def mercator_proj(lat, lon):
    x = np.radians(lon)
    y = np.log(np.tan(np.radians(lat))+1/np.cos(np.radians(lat)))
    return x,y

def get_lightning_color(strike_time,now,format):
    if strike_time > now: #future
        color = (150,150,150)
    elif strike_time + 20 > now:
        color = (150,150,150)
    elif strike_time + 30 > now:
        color = (160,160,100)
    elif strike_time + 40 > now:
        color = (140,120,10)
    elif strike_time + 50 > now:
        color = (140,50,10)
    elif strike_time + 60 > now:
        color = (120,10,0)
    elif strike_time + 120 > now:
        color = (50,0,0)  
    else:   #older than 2 mins
        color = (50,0,0) 
    if format:
        return color
    else:
        return color[0],color[1],color[2]

def draw_power(x,y,radius,sign):
    t1 = 900#650
    t2 = 1500#1200
    t3 = 2500#2000
    sign.canvas.SetPixel(x, y-2, 0, 90, 0)
    if radius > t1:
        sign.canvas.SetPixel(x, y-3, 140, 120, 10)
    if radius > t2:
        sign.canvas.SetPixel(x, y-4, 140, 50, 10)
    if radius > t3:
        sign.canvas.SetPixel(x, y-5, 120, 0, 0)

class LightningManager:

    zoomind = Value('i', 6)

    def __init__(self,sign,CONF):
        self.host = ''
        self.ws = None
        self.thread = None
        self.ws_server = None
        self.ws_key = None
        self.header = None
        self.CONF = CONF
        self.floc = '/home/pi/PlaneSign/icons/lightning/'
        self.connected = Value('i', 0)
        self.strikes = Manager().list()
        self.sign = sign
        self.bgwidth = 64
        self.bgheight = 32
        self.minzoom = 800
        self.maxzoom = 3200
        self.zoomstep = 300
        self.numzooms = (((self.maxzoom-self.minzoom)//self.zoomstep)+1)
        self.zooms = np.linspace(self.minzoom,self.maxzoom,self.numzooms)
        self.draw_loading()
        self.background = None
        self.backgrounds = [None] * self.numzooms
        self.x1 = None
        self.y1 = None
        self.usa = None
        self.genBackgrounds()

    def draw_loading(self):
        image = Image.open("/home/pi/PlaneSign/icons/11d.png")
        image = image.resize((35, 35), Image.BICUBIC)
        self.sign.canvas.SetImage(image.convert('RGB'), 90, -1)

        graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 7, 12, graphics.Color(180,180,40), "Storm")
        graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 55, 18, graphics.Color(180,180,40), "Sign")
        graphics.DrawText(self.sign.canvas, self.sign.font57, 15, 26, graphics.Color(180,180,40), "Loading...")
        for i in range(self.numzooms+1):
            self.sign.canvas.SetPixel(15+i, 28, 180, 20, 0)

    def genBackgrounds(self):
        x0,y0 = mercator_proj(USAlat, USAlong)
        self.x1,self.y1 = mercator_proj(float(self.CONF["SENSOR_LAT"]), float(self.CONF["SENSOR_LON"]))

        countyurl=f'https://public.opendatasoft.com/api/records/1.0/search/?dataset=us-county-boundaries&q=&lang=EN&rows=200&facet=countyfp&geofilter.distance={self.CONF["SENSOR_LAT"]}%2C{self.CONF["SENSOR_LON"]}%2C220000'
        usaurl='https://public.opendatasoft.com/explore/dataset/georef-united-states-of-america-state/download/?format=geojson&timezone=America/New_York&lang=en'

        genmaps = (not os.path.exists(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')) or len(Image.open(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png').getcolors())==1

        if not genmaps:
            for scale in range(self.minzoom,self.maxzoom+self.zoomstep,self.zoomstep):   
                if (not os.path.exists(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png')) or len(Image.open(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png').getcolors())==1:
                    genmaps = True
                    break

        if genmaps:
            
            response = requests.get(countyurl, stream=True, timeout=10)
            if response.status_code == requests.codes.ok:
                countydata=response.json()
            else:
                countydata=None
                
            response = requests.get(usaurl, stream=True, timeout=10)
            if response.status_code == requests.codes.ok:
                usadata=response.json()
            else:
                usadata=None
        else:
            usadata=None
            countydata=None
            
                
        if usadata:
            usapoints=[]
            for feature in usadata["features"]:
                shape = feature["geometry"]
                
                if shape["type"]=='Polygon':
                    points=[]
                    for coord in shape["coordinates"][0]:
                        x,y=mercator_proj(coord[1], coord[0])
                        points.append((x,y))
                    usapoints.append(points)
                elif shape["type"]=='MultiPolygon':
                    for subshape in shape["coordinates"]:
                        points=[]
                        for coord in subshape[0]:
                            x,y=mercator_proj(coord[1], coord[0])
                            points.append((x,y))
                        usapoints.append(points)

        if (not os.path.exists(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')) or len(Image.open(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png').getcolors())==1:
            self.usa = Image.new("RGB", (self.bgwidth, self.bgheight))
            usadraw = ImageDraw.Draw(self.usa)
            
            if usadata:
                for polygon in usapoints:
                    temp = []
                    for p in polygon:
                        temp.append((self.bgwidth/2+(p[0]-x0)*USAscale,self.bgheight/2-(p[1]-y0)*USAscale))
                    usadraw.polygon((temp),outline=(60,60,60))

            self.usa.save(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')

        else:
            self.usa = Image.open(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')
            
        loadingind = 0
        self.sign.canvas.SetPixel(15+loadingind, 28, 20, 180, 0)
        loadingind += 1

        i=-1
        for scale in range(self.minzoom,self.maxzoom+self.zoomstep,self.zoomstep):   
            i+=1
            if (not os.path.exists(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png')) or len(Image.open(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png').getcolors())==1:
                
                self.backgrounds[i]=Image.new("RGB", (self.bgwidth, self.bgheight))
                draw = ImageDraw.Draw(self.backgrounds[i])
                
                if countydata:

                    for record in countydata["records"]:
                        shape = record["fields"]["geo_shape"]
                        if shape["type"]=='Polygon':
                            points=[]
                            for coord in shape["coordinates"][0]:
                                x,y=mercator_proj(coord[1], coord[0])
                                points.append((self.bgwidth/2+(x-self.x1)*scale,self.bgheight/2-(y-self.y1)*scale))
                            draw.polygon((points),outline=(30,30,30))
                        elif shape["type"]=='MultiPolygon':
                            for subshape in shape["coordinates"]:
                                points=[]
                                for coord in subshape[0]:
                                    x,y=mercator_proj(coord[1], coord[0])
                                    points.append((self.bgwidth/2+(x-self.x1)*scale,self.bgheight/2-(y-self.y1)*scale))
                                draw.polygon((points),outline=(30,30,30))
                                
                if usadata:
                    for polygon in usapoints:
                        temp = []
                        for p in polygon:
                            temp.append((self.bgwidth/2+(p[0]-self.x1)*scale,self.bgheight/2-(p[1]-self.y1)*scale))
                        draw.polygon((temp),outline=(80,80,80))
            
                self.backgrounds[i].save(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png')

            else:
                self.backgrounds[i] = Image.open(self.floc+f'local_{self.CONF["SENSOR_LAT"]}_{self.CONF["SENSOR_LON"]}_{scale}.png')  
            self.sign.canvas.SetPixel(15+loadingind, 28, 20, 180, 0)
            loadingind += 1
        
    def onMessage(self, ws, message):
        strike_js = json.loads(message)

        dets = []
        for det in strike_js["sig"]:
            dets.append(get_distance((det["lat"],det["lon"]), (strike_js["lat"],strike_js["lon"])))
        dets.sort()
        #Median detector distance - use dets[floor(len(dets)/2.0)]
        #Second farthest detector distance - user dets[len(dets)-2]

        strike={"time":strike_js["time"]/1e9,"lat":strike_js["lat"],"lon":strike_js["lon"],"dist":get_distance((strike_js["lat"],strike_js["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))),"radius":dets[len(dets)-2]}
        #print(strike)
        self.strikes.append(strike)

    def onError(self, ws, err):
        print("Got an error: ", err)
    
    def onClose(self, ws, close_status_code="", close_msg=""):
        print("### closed ###", close_status_code," : ", close_msg)
        self.connected.value = 0
        
    def onOpen(self, ws):

        def heartbeat(*args):
            while True:
                json_data = json.dumps({"wsServer":self.ws_server})
                time.sleep(25)
                ws.send(json_data)

        thread.start_new_thread(heartbeat, ())
    
        print('Opening Websocket connection to the server ... ')
    
        json_data = json.dumps({"time":0})
        ws.send(json_data)
        json_data = json.dumps({"wsServer":self.ws_server})
        ws.send(json_data)

        print(json_data)

        #json_data = json.dumps({"sig":False})
        #ws.send(json_data)
        
        self.connected.value = 1
    
    def close(self):
        if self.connected.value == 1:
            self.ws.close()
        if self.thread and self.thread.is_alive():
            self.thread.terminate()

    
    def draw(self):

        now = time.time()

        #print(self.strikes)
        x=[]
        y=[]
        c=np.empty((0,3), int)

        strikescopy = sorted(self.strikes, key=lambda k: k["dist"])
        closest = strikescopy
        
        closest1 = None
        closest2 = None
        closest3 = None

        for strike in closest:
            if closest3 != None:
                break
            if strike["time"] + 60 <= now: #too old to show in close list
                continue
            if closest1==None or strike["dist"]<=closest1["dist"]:
                closest3 = closest2
                closest2 = closest1
                closest1 = strike
            elif closest2 == None or strike["dist"]<=closest2["dist"]:
                closest3 = closest2
                closest2 = strike
            elif closest3 == None or strike["dist"]<=closest3["dist"]:
                closest3 = strike


        strikescopy = sorted(strikescopy, key=lambda k: k["time"], reverse=True)
        recent = strikescopy

        newclose = None
        for strike in strikescopy:
            if strike["dist"]<500:
                newclose = strike
                break
            else:
                if newclose == None or strike["dist"]<newclose["dist"]:
                    newclose=strike

        lightningmap = None
        self.background = self.backgrounds[LightningManager.zoomind.value]
        if self.background:
            lightningmap=self.background.copy()
            draw = ImageDraw.Draw(lightningmap)

        if lightningmap:
            x=self.bgwidth/2
            y=self.bgheight/2
            draw.point([x,y], fill=(0,0,255))

            self.sign.canvas.SetImage(lightningmap.convert('RGB'), 64, 0)

        if strikescopy:
            for strike in strikescopy:
                strike_time = strike["time"]
                
                if strike_time > now: #sound hasn't reached us yet
                    continue
                elif strike_time + 120 <= now:
                    self.strikes.remove(strike)#sound hit more than 2 mins ago
                    continue
                else:
                    color=get_lightning_color(strike_time,now,True)

                if lightningmap:
                    x=self.bgwidth/2+(strike["lon"]-float(self.CONF["SENSOR_LON"]))*self.zooms[LightningManager.zoomind.value]
                    y=self.bgheight/2-(strike["lat"]-float(self.CONF["SENSOR_LAT"]))*self.zooms[LightningManager.zoomind.value]
                    x,y = mercator_proj(strike["lat"], strike["lon"])
                    draw.point([self.bgwidth/2+(x-self.x1)*self.zooms[LightningManager.zoomind.value],self.bgheight/2-(y-self.y1)*self.zooms[LightningManager.zoomind.value]], fill=color)

            for i in range(32):
                self.sign.canvas.SetPixel(63, i, 120, 120, 120)

            graphics.DrawText(self.sign.canvas, self.sign.font46, 1, 6, graphics.Color(20, 20, 210), "Close:")
            if closest1:
                r,g,b = get_lightning_color(closest1["time"],now,False)
                if closest1["dist"]<100:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(r,g,b), "{0:.1f}".format(closest1["dist"])+direction_lookup((closest1["lat"],closest1["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(r,g,b), "{0:.0f}".format(closest1["dist"])+direction_lookup((closest1["lat"],closest1["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                
                draw_power(0,14,closest1["radius"],self.sign)

            if closest2:
                r,g,b = get_lightning_color(closest2["time"],now,False)
                if closest2["dist"]<100:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(r,g,b), "{0:.1f}".format(closest2["dist"])+direction_lookup((closest2["lat"],closest2["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(r,g,b), "{0:.0f}".format(closest2["dist"])+direction_lookup((closest2["lat"],closest2["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
            
                draw_power(0,22,closest2["radius"],self.sign)

            if closest3:    
                r,g,b = get_lightning_color(closest3["time"],now,False)
                if closest3["dist"]<100:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(r,g,b), "{0:.1f}".format(closest3["dist"])+direction_lookup((closest3["lat"],closest3["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(r,g,b), "{0:.0f}".format(closest3["dist"])+direction_lookup((closest3["lat"],closest3["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))

                draw_power(0,30,closest3["radius"],self.sign)

            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 6, graphics.Color(20, 20, 210), "Recent:")
            if recent[0]:
                if recent[0]["dist"]<100:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 14, graphics.Color(180,180,40), "{0:.1f}".format(recent[0]["dist"])+direction_lookup((recent[0]["lat"],recent[0]["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 14, graphics.Color(180,180,40), "{0:.0f}".format(recent[0]["dist"])+direction_lookup((recent[0]["lat"],recent[0]["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))

                draw_power(31,14,recent[0]["radius"],self.sign)

            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 22, graphics.Color(20, 20, 210), "Near:")
            if newclose:
                if newclose["dist"]<100:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 30, graphics.Color(180,180,40), "{0:.1f}".format(newclose["dist"])+direction_lookup((newclose["lat"],newclose["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))
                else:
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 30, graphics.Color(180,180,40), "{0:.0f}".format(newclose["dist"])+direction_lookup((newclose["lat"],newclose["lon"]), (float(self.CONF["SENSOR_LAT"]),float(self.CONF["SENSOR_LON"]))))

                draw_power(31,30,newclose["radius"],self.sign)

            self.sign.matrix.SwapOnVSync(self.sign.canvas)
            self.sign.canvas = self.sign.matrix.CreateFrameCanvas()

    def connect(self):
          
        if not self.connected.value:
            self.connected.value = 2
            try:    
                ws_servers = ["ws5.blitzortung.org", "ws6.blitzortung.org", "ws7.blitzortung.org", "ws8.blitzortung.org"]
                
                self.ws_server = ws_servers[random.randint(0,len(ws_servers)-1)]
                
                self.ws_key = base64.b64encode(os.urandom(16)).decode('ascii')
                
                self.host = 'wss://' + self.ws_server + ':3000'
                
                self.header = {
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0",
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
                "Cache-Control": "no-cache"
                }
        
                websocket.enableTrace(False)
        
                self.ws = websocket.WebSocketApp(self.host,
                                                 on_message=lambda ws,message: self.onMessage(ws, message),
                                                 on_error=self.onError,
                                                 on_close=self.onClose,
                                                 on_open=self.onOpen,
                                                 header = self.header)

                self.ws.on_open = self.onOpen
        
                self.thread = Process(target=self.ws.run_forever, kwargs={'host':self.ws_server, 'origin':"https://map.blitzortung.org", 'sslopt':{"cert_reqs": ssl.CERT_NONE}})
                self.thread.start()

            except Exception as e:
                print("### Exception ### ",e)
                self.connected.value = 0
