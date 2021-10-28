#!/usr/bin/python3
# -*- coding: utf-8 -*-
import time
import yfinance as yf
import re
from PIL import Image, ImageDraw
import numpy as np
import favicon
import re
import json
import requests
from rgbmatrix import graphics
from requests import Session
from datetime import datetime
from scipy.interpolate import interp1d
import os

def colordista(c1,c2):
    r1=c1[0]/255
    r2=c2[0]/255
    g1=c1[1]/255
    g2=c2[1]/255
    b1=c1[2]/255
    b2=c2[2]/255
    a1=c1[3]/255
    a2=c2[3]/255
    
    r1 *= a1
    g1 *= a1
    b1 *= a1
    
    r2 *= a2
    g2 *= a2
    b2 *= a2
    
    dr=r1-r2
    dg=g1-g2
    db=b1-b2

    return np.sqrt(max(dr**2, (dr - a1+a2)**2) + max(dg**2, (dg - a1+a2)**2) + max(db**2, (db - a1+a2)**2))*255

def flood(image,x,y,color,bg):
    
    sizex, sizey = image.size
    
    if color == None:
        color = image.getpixel((x,y))
    
    if x >= sizex or y >= sizey or x < 0 or y < 0:
        return
    
    threshold = 50
    threshold2 = 80
    q = []
    q.append((x,y))
    while (len(q)>0):
        (x1,y1) = q.pop()
    
        imagecolor = image.getpixel((x1,y1))
         
        image.putpixel((x1,y1),bg)
    
        if x1<sizex-1 and image.getpixel((x1+1,y1))!=bg and colordista(imagecolor,image.getpixel((x1+1,y1)))<threshold and colordista(color,image.getpixel((x1+1,y1)))<threshold2:
            q.append((x1+1,y1))
        if y1<sizey-1 and image.getpixel((x1,y1+1))!=bg and colordista(imagecolor,image.getpixel((x1,y1+1)))<threshold and colordista(color,image.getpixel((x1,y1+1)))<threshold2:
            q.append((x1,y1+1))
        if x1>1 and image.getpixel((x1-1,y1))!=bg and colordista(imagecolor,image.getpixel((x1-1,y1)))<threshold and colordista(color,image.getpixel((x1-1,y1)))<threshold2:
            q.append((x1-1,y1))
        if y1>1 and image.getpixel((x1,y1-1))!=bg and colordista(imagecolor,image.getpixel((x1,y1-1)))<threshold and colordista(color,image.getpixel((x1,y1-1)))<threshold2:
            q.append((x1,y1-1))
            
def autocrop(image,bg):

    sizex, sizey = image.size
    
    flag=False
    for row in range(sizey):
        for col in range(sizex):
            if image.getpixel((col,row))!=bg:
                flag=True
            if flag:
                break
        if flag:
            break
        
    top = row
        
    flag=False
    for row in range(sizey-1,top+2,-1):
        for col in range(sizex):
            if image.getpixel((col,row))!=bg:
                flag=True
            if flag:
                break
        if flag:
            break
    bot = row
    
    flag=False
    for col in range(sizex):
        for row in range(top+1,bot,1):
            if image.getpixel((col,row))!=bg:
                flag=True
            if flag:
                break
        if flag:
            break
        
    left = col
    
    flag=False
    for col in range(sizex-1,left+2,-1):
        for row in range(top+1,bot,1):
            if image.getpixel((col,row))!=bg:
                flag=True
            if flag:
                break
        if flag:
            break
        
    right = col
    
    return image.crop((left, top, right, bot))   

def improcess(image):
    width, height = image.size
    
    testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
    testimage.paste(image,(0,0),image)
    testimage=testimage.convert('RGB')
    
    #replace black parts of logo with dark grey if enough of the logo is black
    if np.count_nonzero(np.all(np.array(testimage) == (0,0,0), axis = -1))/(width*height)>0.05:
        
        rgba = np.array(image)
        #mask = (rgba[:,:,0] < 35) & (rgba[:,:,1] < 35) & (rgba[:,:,2] < 35) & (rgba[:,:,3] > 200)
        #rgba[mask,0:3] = [35,35,35]
        mask = (rgba[:,:,0] < 50) & (rgba[:,:,1] < 50) & (rgba[:,:,2] < 50) & (rgba[:,:,3] > 0)
        rgba[mask,0:3] = np.true_divide(rgba[mask,0:3],2.0)+[35,35,35]
        image = Image.fromarray(rgba)
    
    bg=(0,0,0,255)

    new_image = Image.new("RGBA", image.size, bg)
    new_image.paste(image,(0,0),image)
    
    image = new_image
    
    tl = image.getpixel((0,0))
    tr = image.getpixel((-1,0))
    bl = image.getpixel((0,-1))
    br = image.getpixel((-1,-1))

    if max(colordista(tl,tr), colordista(tl,bl), colordista(tl,br), colordista(tr,bl), colordista(tr,br), colordista(bl,br))<30:
        
        #flood background starting at the corners
        flood(image,0,0,None,bg)
        flood(image,width-1,height-1,None,bg)
        flood(image,width-1,0,None,bg)
        flood(image,0,height-1,None,bg)
    
    #crop out background regions
    image = autocrop(image,bg)
    
    width, height = image.size
    
    #rescale to 20px max, preserving logo aspect ratio
    if width>height:
        image = image.resize((20,int(20*height/width)), Image.BICUBIC)
    elif height>width:
        image = image.resize((int(20*width/height),20), Image.BICUBIC)
    else:
        image = image.resize((20,20), Image.BICUBIC)

    #tone down brightness
    bg=(0,0,0,100)
    new_image = Image.new("RGBA", image.size, bg)
    image.paste(new_image,(0,0),new_image)

    return image.convert('RGB')

def getFavicon(floc,website):
    
    headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0",
    "Accept": "image/webp,*/*",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Keep-Alive": "timeout=5, max=1",
    'Sec-Fetch-Dest': 'image',
    'Sec-Fetch-Mode': 'no-cors',
    'Sec-Fetch-Site': 'same-origin',
    "Sec-Fetch-User": "?1"
    }

    icons = favicon.get(website)

    image = None
    panic = False

    for icon in icons:

        host = re.sub(r"https?:\/\/", "", icon.url)
        host = re.sub(r"\/.*$", "", host)
        
        headers["Host"]=host
        headers["Referer"]=icon.url

        req = requests.get(icon.url, stream=True, headers=headers, timeout=5)
        if req.status_code == requests.codes.ok:
            image = open(floc+"favicon."+icon.format,"wb")
            image.write(req.content)
            image.close()
            # with open(floc+"favicon."+icon.format, 'wb') as image:
            #     for chunk in req.iter_content(chunk_size=1024):
            #         if chunk:
            #             image.write(chunk)
            #             image.flush()
                    
            image = Image.open(floc+"favicon."+icon.format)        
    
            width, height = image.size
            if width <= 200 and height <= 200:
                panic = False
                break

    if image == None or panic:
        return None
    else:

        width, height = image.size
    
        image = image.convert('RGBA')

        testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
        testimage.paste(image,(0,0),image)
        testimage=testimage.convert('RGB')
        
        #replace black parts of logo with dark grey if enough of the logo is black
        if np.count_nonzero(np.all(np.array(testimage) == (0,0,0), axis = -1))/(width*height)>0.05:
            
            rgba = np.array(image)
            mask = (rgba[:,:,0] < 35) & (rgba[:,:,1] < 35) & (rgba[:,:,2] < 35) & (rgba[:,:,3] > 200)
            rgba[mask] = [35,35,35,255]
            image = Image.fromarray(rgba)
        
        bg=(0,0,0,255)

        new_image = Image.new("RGBA", image.size, bg)
        new_image.paste(image,(0,0),image)
        
        image = new_image
        
        #preshrink logo so recursive flood doesn't cause stack overflow or hit recursion limit
        width, height = image.size
        sz=50
        if width>sz or height>sz:
            if width>height:
                image = image.resize((sz,int(sz*height/width)), Image.BICUBIC)
            elif height>width:
                image = image.resize((int(sz*width/height),sz), Image.BICUBIC)
            else:
                image = image.resize((sz,sz), Image.BICUBIC)
                
            width, height = image.size

        #flood background starting at the corners only if it is white
        white = (255,255,255,255)

        tl = image.getpixel((0,0))
        tr = image.getpixel((-1,0))
        bl = image.getpixel((0,-1))
        br = image.getpixel((-1,-1))

        if max(colordista(tl,tr), colordista(tl,bl), colordista(tl,br), colordista(tr,bl), colordista(tr,br), colordista(bl,br))<30:
        
            flood(image,0,0,white,bg)
            flood(image,width-1,height-1,white,bg)
            flood(image,width-1,0,white,bg)
            flood(image,0,height-1,white,bg)

        #crop out background regions
        image = autocrop(image,bg)
    
        width, height = image.size
    
        #rescale to 20px max, preserving logo aspect ratio
        if width>height:
            image = image.resize((20,int(20*height/width)), Image.BICUBIC)
        elif height>width:
            image = image.resize((int(20*width/height),20), Image.BICUBIC)
        else:
            image = image.resize((20,20), Image.BICUBIC)


        #tone down brightness
        bg=(0,0,0,100)
        new_image = Image.new("RGBA", image.size, bg)
        image.paste(new_image,(0,0),new_image)

        return image.convert('RGB')

def check_logos(floc,ticker):
    try:
        logo = Image.open(floc+ticker+".png") 
    except:
        logo = None

    return logo

def get_crypto(symbol,name):

    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/map'
    parameters = {
    'start':'1',
    'limit':'5000'
    }
    headers = {
    'Accepts': 'application/json',
    'X-CMC_PRO_API_KEY': '34ee49b5-5a76-4275-a497-32ef53b46e17',
    }

    session = Session()
    session.headers.update(headers)


    response = session.get(url, params=parameters, timeout=10)

    if response.status_code == requests.codes.ok:
        data = json.loads(response.text)
   
        coinid=0
        try:
            coinid=[x for x in data["data"] if x["symbol"]==symbol][0]["id"]
        except:
            try:
                coinid=[x for x in data["data"] if x["name"]==name][0]["id"]
            except:
                coinid=0
        if coinid == 0:
            return None
        else:
            req = requests.get(f"https://s2.coinmarketcap.com/static/img/coins/32x32/{coinid}.png", stream=True, timeout=5)
            if req.status_code == requests.codes.ok:
                image = Image.open(req.raw)
                logo = improcess(image.convert("RGBA"))
                logo = logo.convert("RGB")
                return logo
            else:
                return None
    else:
        return None


class Stock:
    def __init__(self,sign,raw_ticker,CONF):

        self.sign = sign
        self.CONF = CONF

        self.clean_ticker = None
        self.cleaner_ticker = None
        self.ticker_data = None
        self.prev_ticker = None
        self.prev_price = None
        self.curr_price = None
        self.perc_change = None
        self.logo = None
        self.chart = None
        self.x = None

        self.floc = '/home/pi/PlaneSign/icons/favicons/'

        self.last_time = None

        self.isnew = False
        self.isvalid = False

        try:
            self.setticker(raw_ticker)
        except Exception as e:
            print(e)

    def setticker(self,raw_ticker):
        clean_ticker, cleaner_ticker, ticker_data = self.validate(raw_ticker)

        if self.isvalid:
            if self.isnew:

                self.prev_ticker = self.clean_ticker
                self.clean_ticker = clean_ticker
                self.cleaner_ticker = cleaner_ticker
                self.ticker_data = ticker_data

                self.updatedata(False)
                self.isnew = False
        else:
            raise ValueError(f'No data for ticker {raw_ticker}')

    def updatedata(self,newticker=True):

        self.prev_price = self.curr_price
        if newticker:
            self.ticker_data = yf.Ticker(self.clean_ticker)
        self.curr_price = self.ticker_data.info["regularMarketPrice"]
        self.open_price = self.ticker_data.info["regularMarketOpen"]
        self.prev_close = self.ticker_data.info["previousClose"]
        self.perc_change=100*(self.curr_price-self.prev_close)/self.prev_close

        #avoid image processing after the first time unless ticker changes
        if self.logo == None or self.isnew: 

            logo = check_logos(self.floc,self.cleaner_ticker)
            
            if logo == None: #logo not saved, go get it from the web

                logourl=self.ticker_data.info["logo_url"]
                
                if self.ticker_data.info["quoteType"]=="CRYPTOCURRENCY": #go get this logo somewhere else
                    logo = get_crypto(self.ticker_data.info["fromCurrency"],self.ticker_data.info["name"])
                elif logourl != "":
                    #website = self.ticker_data.info["website"]
                    try:
                        website = self.ticker_data.info["website"]
                    except:
                        website = re.findall(r"([^\/]*)$", logourl)[0]

                    req = requests.get(logourl, stream=True, timeout=5)
                    if req.status_code == requests.codes.ok:
                        image = Image.open(req.raw)
                        logo = improcess(image.convert("RGBA")).convert("RGB")
                        width, height = logo.size
                        if height<6: #not enough detail on scaled logo, get favicon instead
                            logo = getFavicon(self.floc,website)
                    else: #logourl failed, get favicon instead
                        logo = getFavicon(self.floc,website)

                if logo == None:
                    logo = Image.new("RGB", (20,20), (0, 0, 0))
                else:
                    logo.save(self.floc+self.cleaner_ticker, 'PNG')

            self.logo = logo

        #avoid getting history data more frequently than the interval unless ticker changes
        if  self.chart == None or self.isnew or time.perf_counter()-self.last_time > 300:
            self.last_time = time.perf_counter()
            dayvals = self.ticker_data.history(period="1d",interval="5m")
            dayvals.Open.to_csv("prices.csv", index=False, header=None)
            dayvals=dayvals.Open.tolist()
            
            numpts = 32
            tnew=np.linspace(0, 63, numpts)
            if len(dayvals)>numpts:
                told=np.linspace(0, 63, len(dayvals))
                interpdayvals = interp1d(told, dayvals)
                dayvals = interpdayvals(tnew)

            daymax = max(dayvals)
            daymin = min(dayvals)
            dayspread = daymax - daymin

            if dayspread < 0.001*self.open_price:
                dayspread = 0.001*self.open_price

            stockplot = Image.new("RGB", (64*2, 20*2), (0, 0, 0))
            points = []
            for col in range(len(dayvals)):
                points.append((round(tnew[col])*2,(20-round(20*(dayvals[col]-daymin)/dayspread))*2))
            draw = ImageDraw.Draw(stockplot)
            if self.perc_change>=0:
                draw.line(points, width=1, fill=(50, 255, 0), joint="curve")
            else:
                draw.line(points, width=1, fill=(255, 50, 0), joint="curve")

            self.chart=stockplot.resize((64, 20), Image.BICUBIC)

    def validate(self,raw_ticker):

        clean_ticker = re.sub(r'[^A-Z-.]', '', raw_ticker)
        ticker_data = yf.Ticker(clean_ticker)

        parts = clean_ticker.split('-')
        cleaner_ticker = parts[0]

        if ticker_data.info["regularMarketPrice"] != None:

            if self.clean_ticker != clean_ticker:
                self.isnew = True

            self.isvalid = True
        else:
            self.isvalid = False

        return clean_ticker, cleaner_ticker, ticker_data

    def drawlogo(self):

        width, height = self.logo.size
        self.sign.canvas.SetImage(self.logo, 5+round((20-width)/2.0), 11+round((20-height)/2.0))

    def drawtime(self):

        if self.CONF["MILITARY_TIME"].lower()=='true':
            print_time = datetime.now().strftime('%-H:%M%p')
        else:
            print_time = datetime.now().strftime('%-I:%M%p')
        graphics.DrawText(self.sign.canvas, self.sign.font57, 92, 8, graphics.Color(130, 90, 0), print_time)

    def drawticker(self):

        graphics.DrawText(self.sign.canvas, self.sign.fontbig, 3+round(3*(4-len(self.cleaner_ticker[0:4]))), 10, graphics.Color(0, 20, 150), self.cleaner_ticker[0:4])

    def drawprice(self):

        if self.perc_change>=0:
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 29, 22, graphics.Color(50,150,0), "+{0:.1f}".format(self.perc_change)+"%")
        else:
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 29, 22, graphics.Color(150,50,0), "{0:.1f}".format(self.perc_change)+"%")
        currprice_str="{0:.2f}".format(self.curr_price)
        graphics.DrawText(self.sign.canvas, self.sign.fontbig, 29, 10, graphics.Color(150, 150, 150), currprice_str)

        if self.prev_price != None and self.prev_price != self.curr_price:
            if self.curr_price>self.prev_price:
                image = Image.open("/home/pi/PlaneSign/icons/finance/up.png")
            else:
                image = Image.open("/home/pi/PlaneSign/icons/finance/down.png")
            self.sign.canvas.SetImage(image.convert('RGB'), 32+6*len(currprice_str), 2)  
                
    def drawchart(self):

        self.sign.canvas.SetImage(self.chart, 64, 11)

    def drawfullpage(self):

        self.updatedata()

        self.sign.canvas.Clear()

        self.drawlogo()
        self.drawtime()
        self.drawticker()
        self.drawprice()
        self.drawchart()
