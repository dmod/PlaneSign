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

import _thread as thread

class LightningManager:

    def __init__(self,sign,lat,lon):
        self.host = ''
        self.ws = None
        self.thread = None
        self.ws_server = None
        self.ws_key = None
        self.header = None
        self.connected = Value('i', 0)
        self.strikes = Manager().list()
        self.sign = sign
        self.mylong = lon
        self.mylat = lat
        
    def onMessage(self, ws, message):
        strike_js = json.loads(message)
        strike={"time":strike_js["time"]/1e9,"lat":strike_js["lat"],"lon":strike_js["lon"],"dist":get_distance((strike_js["lat"],strike_js["lon"]), (self.mylat,self.mylong)),"radius":strike_js["mds"]*9.3141e-5}
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
            print("closing process")
            self.thread.join()
            print("process closed")
    
    def draw(self):
        #print(self.strikes)
        x=[]
        y=[]
        c=np.empty((0,3), int)

        #strikescopy = self.strikes._getvalue()
        strikescopy = sorted(self.strikes, key=lambda k: k["dist"])
        closest = strikescopy[0]
        strikescopy = sorted(strikescopy, key=lambda k: k["time"], reverse=True)
        recent = strikescopy[0]

        if strikescopy:
            for strike in strikescopy:
                now = time.time()
                strike_time = strike["time"]
                
                if strike_time > now: #sound hasn't reached us yet
                    continue
                elif strike_time + 20 > now:
                    color = (255,255,255)
                elif strike_time + 30 > now:
                    color = (255,255,160)
                elif strike_time + 40 > now:
                    color = (240,200,10)
                elif strike_time + 50 > now:
                    color = (240,90,10)
                elif strike_time + 60 > now:
                    color = (240,10,10)
                elif strike_time + 120 > now:
                    color = (70,0,0)           
                else:
                    self.strikes.remove(strike)#sound hit more than 2 mins ago
                    continue
                x.append(strike["lon"])
                y.append(strike["lat"])
                c=np.append(c,[np.array(color)],axis=0)

            graphics.DrawText(self.sign.canvas, self.sign.font57, 5, 9, graphics.Color(180,180,40), "Closest: "+"{0:.1f}".format(closest["dist"])+" miles "+direction_lookup((closest["lat"],closest["lon"]), (self.mylat,self.mylong)))
            graphics.DrawText(self.sign.canvas, self.sign.font57, 5, 19, graphics.Color(180,180,40), "Recent: "+"{0:.1f}".format(recent["dist"])+" miles "+direction_lookup((recent["lat"],recent["lon"]), (self.mylat,self.mylong)))
            graphics.DrawText(self.sign.canvas, self.sign.font57, 5, 29, graphics.Color(180,180,40), "# Strikes < 2m ago: "+str(len(strikescopy)))

            #plt.rcParams['axes.facecolor'] = 'black'
            #plt.rcParams['figure.facecolor'] = 'black'
            #plt.scatter(x, y, c=c/255.0)

            #plt.scatter(mylong,mylat,color=[0,0,1])
            #plt.xlim([-180, 180])
            #plt.ylim([-90, 90])
            #plt.show()

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
