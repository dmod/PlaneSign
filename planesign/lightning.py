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
import PIL.ImageDraw as ImageDraw
import PIL.Image as Image
import _thread as thread
import os.path
import shared_config
import __main__


USAlong=-96
USAlat=38
USAscale=55

@__main__.planesign_mode_handler(15)
def lightning(sign):
    sign.canvas.Clear()

    LM = LightningManager(sign)
    LM.connect()

    last_draw = time.perf_counter()

    sign.canvas.Clear()
    while LM.connected.value:
        if time.perf_counter()-last_draw > 2 or (LM.last_drawn_zoomind.value != shared_config.shared_lighting_zoomind.value) or (LM.last_drawn_mode.value != shared_config.shared_lighting_mode.value):
            LM.draw()
            last_draw = time.perf_counter()

        breakout = sign.wait_loop(0.1)
        if breakout:
            LM.close()
            return

def mercator_proj(lat, lon):
    x = np.radians(lon)
    y = np.log(np.tan(np.radians(lat))+1/np.cos(np.radians(lat)))
    return x,y

def get_lightning_color(strike_time,now,format=False):

    max_bright=150

    dt=now-strike_time

    b=max(min(round(max_bright*(1-dt/60)),max_bright),0)#min brightness at 1 min
    g=max(min(round(max_bright*(2-dt/60)),max_bright),0)#min brightness at 2 mins
    r=max(min(round(dt*(30-max_bright)/180+(5*max_bright-60)/3),max_bright),30)#min brightness at 5 mins

    color=(r,g,b)

    if format:
        return color
    else:
        return r,g,b

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

    def __init__(self,sign):
        self.host = ''
        self.ws = None
        self.thread = None
        self.ws_server = None
        self.ws_key = None
        self.header = None
        self.floc = f'{shared_config.icons_dir}/lightning/'
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
        self.background = None
        self.backgrounds = [None] * self.numzooms
        self.x0 = None
        self.y0 = None
        self.x1 = None
        self.y1 = None
        self.usa = None
        self.last_drawn_zoomind = Value('i', 6)
        self.last_drawn_mode = Value('i', 1)
        self.genBackgrounds()

    def draw_loading(self):
        image = Image.open(f"{shared_config.icons_dir}/11d.png")
        image = image.resize((35, 35), Image.BICUBIC)
        self.sign.canvas.SetImage(image.convert('RGB'), 90, -1)

        graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 7, 12, graphics.Color(180,180,40), "Storm")
        graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 55, 18, graphics.Color(180,180,40), "Sign")
        graphics.DrawText(self.sign.canvas, self.sign.font57, 15, 26, graphics.Color(180,180,40), "Loading...")
        for i in range(self.numzooms+1):
            self.sign.canvas.SetPixel(15+i, 28, 180, 20, 0)

    def genBackgrounds(self):
        self.x0,self.y0 = mercator_proj(USAlat, USAlong)
        self.x1,self.y1 = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))

        countyurl=f'https://public.opendatasoft.com/api/records/1.0/search/?dataset=us-county-boundaries&q=&lang=EN&rows=200&facet=countyfp&geofilter.distance={shared_config.CONF["SENSOR_LAT"]}%2C{shared_config.CONF["SENSOR_LON"]}%2C220000'
        usaurl='https://public.opendatasoft.com/explore/dataset/georef-united-states-of-america-state/download/?format=geojson&timezone=America/New_York&lang=en'

        genmaps = (not os.path.exists(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')) or len(Image.open(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png').getcolors())==1

        if not genmaps:
            for scale in range(self.minzoom,self.maxzoom+self.zoomstep,self.zoomstep):   
                if (not os.path.exists(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png')) or len(Image.open(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png').getcolors())==1:
                    genmaps = True
                    break

        if genmaps:
            self.draw_loading()
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
            
                
        if usadata and genmaps:
            usapoints=[]
            for feature in usadata["features"]:
                shape = feature["geometry"]
                if feature["properties"]["ste_stusps_code"] not in ["AS","AK","VI","GU","HI","MP","PR"]:
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
                        temp.append((self.bgwidth/2+(p[0]-self.x0)*USAscale,self.bgheight/2-(p[1]-self.y0)*USAscale))
                    usadraw.polygon((temp),outline=(40,40,40))

            self.usa.save(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')

        else:
            self.usa = Image.open(self.floc+f'usa_{USAlat}_{USAlong}_{USAscale}.png')

        if genmaps:    
            loadingind = 0
            self.sign.canvas.SetPixel(15+loadingind, 28, 20, 180, 0)
            loadingind += 1

        i=-1
        for scale in range(self.minzoom,self.maxzoom+self.zoomstep,self.zoomstep):   
            i+=1
            if (not os.path.exists(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png')) or len(Image.open(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png').getcolors())==1:
                
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
            
                self.backgrounds[i].save(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png')

            else:
                self.backgrounds[i] = Image.open(self.floc+f'local_{shared_config.CONF["SENSOR_LAT"]}_{shared_config.CONF["SENSOR_LON"]}_{scale}.png')  
            
            if genmaps:
                self.sign.canvas.SetPixel(15+loadingind, 28, 20, 180, 0)
                loadingind += 1
        
    def onMessage(self, ws, message):
        strike_js = json.loads(message)

        dets = []
        for det in strike_js["sig"]:
            dets.append(utilities.get_distance((det["lat"],det["lon"]), (strike_js["lat"],strike_js["lon"])))
        dets.sort()
        #Median detector distance - use dets[floor(len(dets)/2.0)]
        #Second farthest detector distance - user dets[len(dets)-2]

        strike={"time":strike_js["time"]/1e9,"lat":strike_js["lat"],"lon":strike_js["lon"],"dist":utilities.get_distance((strike_js["lat"],strike_js["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))),"radius":dets[len(dets)-2]}
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

        if shared_config.shared_lighting_mode.value == 2:
            local = True
        else:
            local = False

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
            if local and strike["dist"]>250: #too far to show for local mode
                break
            if closest1==None or strike["dist"]<=closest1["dist"]:
                closest3 = closest2
                closest2 = closest1
                closest1 = strike
            elif closest2 == None or strike["dist"]<=closest2["dist"]:
                closest3 = closest2
                closest2 = strike
            elif closest3 == None or strike["dist"]<=closest3["dist"]:
                closest3 = strike

        if local:
            strikescopy = sorted(filter(lambda n: n["dist"]<250, strikescopy), key=lambda k: k["time"], reverse=True)
        else:
            strikescopy = sorted(strikescopy, key=lambda k: k["time"], reverse=True)
        
        recent = strikescopy
        oldest = recent.copy()
        oldest.reverse()

        numstrikes = 0
        for strike in recent:
            if strike["time"] + 300 > now: #strike within last 5 mins
                numstrikes+=1
            else:
                break

        lightningmap = None
        if local:
            self.background = self.backgrounds[shared_config.shared_lighting_zoomind.value]
        else:
            self.background =  self.usa

        if self.background:
            lightningmap=self.background.copy()
            draw = ImageDraw.Draw(lightningmap)

        if lightningmap:
            if local:
                x=self.bgwidth/2
                y=self.bgheight/2
            else:
                x,y = mercator_proj(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
                x=self.bgwidth/2+(x-self.x0)*USAscale
                y=self.bgheight/2-(y-self.y0)*USAscale
            draw.point([x,y], fill=(0,0,255))

        if oldest:
            for strike in oldest:
                strike_time = strike["time"]
                
                if strike_time > now: #desync in server and local clock
                    continue
                elif strike_time + 600 <= now:
                    self.strikes.remove(strike)#strike hit more than 10 mins ago
                    continue
                else:
                    color=get_lightning_color(strike_time,now,True)

                if lightningmap:
                    
                    x,y = mercator_proj(strike["lat"], strike["lon"])
                    if local:
                        x=self.bgwidth/2+(x-self.x1)*self.zooms[shared_config.shared_lighting_zoomind.value]
                        y=self.bgheight/2-(y-self.y1)*self.zooms[shared_config.shared_lighting_zoomind.value]
                    else:
                        x=self.bgwidth/2+(x-self.x0)*USAscale
                        y=self.bgheight/2-(y-self.y0)*USAscale
                    draw.point([x,y], fill=color)

        self.sign.canvas.SetImage(lightningmap.convert('RGB'), 64, 0)

        for i in range(32):
            self.sign.canvas.SetPixel(63, i, 50, 50, 200)

        graphics.DrawText(self.sign.canvas, self.sign.font46, 1, 6, graphics.Color(20, 20, 210), "Closest")
        if closest1:
            r,g,b = get_lightning_color(closest1["time"],now,False)
            if closest1["dist"]<100:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(r,g,b), "{0:.1f}".format(closest1["dist"])+utilities.direction_lookup((closest1["lat"],closest1["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
            else:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(r,g,b), "{0:.0f}".format(closest1["dist"])+utilities.direction_lookup((closest1["lat"],closest1["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
            
            draw_power(0,14,closest1["radius"],self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 14, graphics.Color(70, 70, 215), "----")

        if closest2:
            r,g,b = get_lightning_color(closest2["time"],now,False)
            if closest2["dist"]<100:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(r,g,b), "{0:.1f}".format(closest2["dist"])+utilities.direction_lookup((closest2["lat"],closest2["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
            else:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(r,g,b), "{0:.0f}".format(closest2["dist"])+utilities.direction_lookup((closest2["lat"],closest2["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
        
            draw_power(0,22,closest2["radius"],self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 22, graphics.Color(70, 70, 215), "----")

        if closest3:    
            r,g,b = get_lightning_color(closest3["time"],now,False)
            if closest3["dist"]<100:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(r,g,b), "{0:.1f}".format(closest3["dist"])+utilities.direction_lookup((closest3["lat"],closest3["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
            else:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(r,g,b), "{0:.0f}".format(closest3["dist"])+utilities.direction_lookup((closest3["lat"],closest3["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))

            draw_power(0,30,closest3["radius"],self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 2, 30, graphics.Color(70, 70, 215), "----")

        graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 6, graphics.Color(20, 20, 210), "Recent")
        if recent:
            if recent[0]["dist"]<100:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 14, graphics.Color(180,180,40), "{0:.1f}".format(recent[0]["dist"])+utilities.direction_lookup((recent[0]["lat"],recent[0]["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))
            else:
                graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 14, graphics.Color(180,180,40), "{0:.0f}".format(recent[0]["dist"])+utilities.direction_lookup((recent[0]["lat"],recent[0]["lon"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))))

            draw_power(31,14,recent[0]["radius"],self.sign)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 14, graphics.Color(70, 70, 215), "----")

        if local:
            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 22, graphics.Color(20, 20, 210), "#")
            graphics.DrawText(self.sign.canvas, self.sign.font46, 39, 22, graphics.Color(20, 20, 210), "Near")
        else:
            graphics.DrawText(self.sign.canvas, self.sign.font46, 33, 22, graphics.Color(20, 20, 210), "#")
            graphics.DrawText(self.sign.canvas, self.sign.font46, 39, 22, graphics.Color(20, 20, 210), "Global")
        self.sign.canvas.SetPixel(32, 18, 20, 20, 210)#fix the janky looking # symbol
        self.sign.canvas.SetPixel(32, 20, 20, 20, 210)#fix the janky looking # symbol

        graphics.DrawText(self.sign.canvas, self.sign.font57, 33, 30, graphics.Color(180,180,40), str(numstrikes))

        if closest1 and closest1["dist"]<0.5 and closest1["time"]+30 > now and ("warned" not in closest1):
            self.strikes[self.strikes.index(closest1)]["warned"]=True
            for i in range(6):
                if i%2==0:
                    for i in range(32):
                        self.sign.canvas.SetPixel(63, i, 200, 0, 0)
                        self.sign.canvas.SetPixel(127, i, 200, 0, 0)
                    for i in range(64,127):
                        self.sign.canvas.SetPixel(i, 0, 200, 0, 0)
                        self.sign.canvas.SetPixel(i, 31, 200, 0, 0)
                else:
                    for i in range(32):
                        self.sign.canvas.SetPixel(63, i, 0, 0, 0)
                        self.sign.canvas.SetPixel(127, i, 0, 0, 0)
                    for i in range(64,127):
                        self.sign.canvas.SetPixel(i, 0, 0, 0, 0)
                        self.sign.canvas.SetPixel(i, 31, 0, 0, 0)
                self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)
                time.sleep(0.2)

        self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)
        self.sign.canvas.Clear()

        self.last_drawn_zoomind.value = shared_config.shared_lighting_zoomind.value
        self.last_drawn_mode.value = shared_config.shared_lighting_mode.value

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
