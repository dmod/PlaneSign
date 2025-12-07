#!/usr/bin/python3
# -*- coding: utf-8 -*-
import time
import finnhub
import re
from PIL import Image, ImageDraw
from multiprocessing import Process, Value
import websocket
import numpy as np
import favicon
import re
import json
import utilities
import requests
from rgbmatrix import graphics
from requests import Session
from datetime import datetime
from scipy.interpolate import interp1d
import shared_config
import __main__
import logging

from modes import DisplayMode

def update_global_lists(client = None):

    if client == None:
        if "FINNHUB_API_KEY" not in shared_config.CONF or shared_config.CONF["FINNHUB_API_KEY"] == "":
            logging.error("Finnhub API key is not configured. Finance mode will not function.")
            return [], [], []
        else:   
            client = finnhub.Client(api_key=shared_config.CONF["FINNHUB_API_KEY"])

    if "us_symbols" not in shared_config.data_dict:
        try:
            # Halve the number of symbols by only saving "Common Stock" types (filters out ETFs, preferred shares, etc)
            us_symbols = client.stock_symbols("US")
            us_symbols = list(filter(lambda x: x["type"] == "Common Stock", us_symbols))
            shared_config.data_dict["us_symbols"] = us_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            us_symbols = []
    else:
        us_symbols = shared_config.data_dict["us_symbols"]

    cbpat = re.compile("^COINBASE:.+-USD$")
    bnpat = re.compile("^.+/USDT*$")

    if "cb_symbols" not in shared_config.data_dict:
        try:
            cb_symbols = client.crypto_symbols("COINBASE")
            cb_symbols = list(filter(lambda x: cbpat.match(x["symbol"]), cb_symbols))
            shared_config.data_dict["cb_symbols"] = cb_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            cb_symbols = []
    else:
        cb_symbols = shared_config.data_dict["cb_symbols"]

    if "bn_symbols" not in shared_config.data_dict:
        try:
            bn_symbols = client.crypto_symbols("BINANCE")
            bn_symbols = list(filter(lambda x: bnpat.match(x["displaySymbol"]), bn_symbols))
            shared_config.data_dict["bn_symbols"] = bn_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            bn_symbols = []
    else:
        bn_symbols = shared_config.data_dict["bn_symbols"]

    return us_symbols, cb_symbols, bn_symbols

def get_tickers():

    if "FINNHUB_API_KEY" not in shared_config.CONF or shared_config.CONF["FINNHUB_API_KEY"] == "":
        logging.error("Finnhub API key is not configured. Finance mode will not function.")
        return {'bn':[], 'cb':[], 'us':[]}

    us_symbols, cb_symbols, bn_symbols = update_global_lists()
    return {'bn': bn_symbols, 'cb': cb_symbols, 'us': us_symbols}

@__main__.planesign_mode_handler(DisplayMode.FINANCE)
def finance(self):
    self.canvas.Clear()
    shared_config.data_dict["ticker"] = None
    s = None

    graphics.DrawText(self.canvas, self.fontreallybig, 7, 12, graphics.Color(50, 150, 0), "Finance")
    graphics.DrawText(self.canvas, self.fontreallybig, 34, 26, graphics.Color(50, 150, 0), "Sign")
    image = Image.open(f"{shared_config.icons_dir}/finance/money.png")
    image = image.resize((20, 20), Image.BICUBIC)
    self.canvas.SetImage(image.convert('RGB'), 10, 14)

    if "FINNHUB_API_KEY" not in shared_config.CONF or shared_config.CONF["FINNHUB_API_KEY"] == "":
        logging.error("Finnhub API key is not configured. Finance mode will not function.")
        graphics.DrawText(self.canvas, self.font57, 75, 13, graphics.Color(200, 0, 0), "No Finnhub")
        graphics.DrawText(self.canvas, self.font57, 80, 23, graphics.Color(200, 0, 0), "API Key!")
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        self.canvas.Clear()
        return self.wait_loop(-1)
    else:
        image = Image.open(f"{shared_config.icons_dir}/finance/increase.png")
        self.canvas.SetImage(image.convert('RGB'), 75, -5)

    self.canvas = self.matrix.SwapOnVSync(self.canvas)
    self.canvas.Clear()

    client = finnhub.Client(api_key=shared_config.CONF["FINNHUB_API_KEY"])

    update_global_lists(client)

    while shared_config.shared_mode.value == DisplayMode.FINANCE.value:

        ticker = shared_config.data_dict["ticker"]

        if ticker != None:
            if s == None:
                s = Stock(self, client, ticker)
            elif s.ticker != ticker:
                s.setticker(ticker)

            s.drawfullpage()

        breakout = self.wait_loop(0.5)
        if breakout:
            return


def colordista(c1, c2):
    r1 = c1[0]/255
    r2 = c2[0]/255
    g1 = c1[1]/255
    g2 = c2[1]/255
    b1 = c1[2]/255
    b2 = c2[2]/255
    a1 = c1[3]/255
    a2 = c2[3]/255

    r1 *= a1
    g1 *= a1
    b1 *= a1

    r2 *= a2
    g2 *= a2
    b2 *= a2

    dr = r1-r2
    dg = g1-g2
    db = b1-b2

    return np.sqrt(max(dr**2, (dr - a1+a2)**2) + max(dg**2, (dg - a1+a2)**2) + max(db**2, (db - a1+a2)**2))*255


def flood(image, x, y, color, bg):

    sizex, sizey = image.size

    if color == None:
        color = image.getpixel((x, y))

    if x >= sizex or y >= sizey or x < 0 or y < 0:
        return

    threshold = 50
    threshold2 = 80
    q = []
    q.append((x, y))
    while (len(q) > 0):
        (x1, y1) = q.pop()

        imagecolor = image.getpixel((x1, y1))

        image.putpixel((x1, y1), bg)

        if x1 < sizex-1 and image.getpixel((x1+1, y1)) != bg and colordista(imagecolor, image.getpixel((x1+1, y1))) < threshold and colordista(color, image.getpixel((x1+1, y1))) < threshold2:
            q.append((x1+1, y1))
        if y1 < sizey-1 and image.getpixel((x1, y1+1)) != bg and colordista(imagecolor, image.getpixel((x1, y1+1))) < threshold and colordista(color, image.getpixel((x1, y1+1))) < threshold2:
            q.append((x1, y1+1))
        if x1 > 1 and image.getpixel((x1-1, y1)) != bg and colordista(imagecolor, image.getpixel((x1-1, y1))) < threshold and colordista(color, image.getpixel((x1-1, y1))) < threshold2:
            q.append((x1-1, y1))
        if y1 > 1 and image.getpixel((x1, y1-1)) != bg and colordista(imagecolor, image.getpixel((x1, y1-1))) < threshold and colordista(color, image.getpixel((x1, y1-1))) < threshold2:
            q.append((x1, y1-1))

def improcess(image):
    width, height = image.size

    testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
    testimage.paste(image, (0, 0), image)
    testimage = testimage.convert('RGB')

    # replace black parts of logo with dark grey if enough of the logo is black
    if np.count_nonzero(np.all(np.array(testimage) == (0, 0, 0), axis=-1))/(width*height) > 0.05:

        rgba = np.array(image)
        #mask = (rgba[:,:,0] < 35) & (rgba[:,:,1] < 35) & (rgba[:,:,2] < 35) & (rgba[:,:,3] > 200)
        #rgba[mask,0:3] = [35,35,35]
        mask = (rgba[:, :, 0] < 50) & (rgba[:, :, 1] < 50) & (rgba[:, :, 2] < 50) & (rgba[:, :, 3] > 0)
        rgba[mask, 0:3] = np.true_divide(rgba[mask, 0:3], 2.0)+[35, 35, 35]
        image = Image.fromarray(rgba)

    bg = (0, 0, 0, 255)

    new_image = Image.new("RGBA", image.size, bg)
    new_image.paste(image, (0, 0), image)

    image = new_image

    tl = image.getpixel((0, 0))
    tr = image.getpixel((-1, 0))
    bl = image.getpixel((0, -1))
    br = image.getpixel((-1, -1))

    if max(colordista(tl, tr), colordista(tl, bl), colordista(tl, br), colordista(tr, bl), colordista(tr, br), colordista(bl, br)) < 30:

        # flood background starting at the corners
        flood(image, 0, 0, None, bg)
        flood(image, width-1, height-1, None, bg)
        flood(image, width-1, 0, None, bg)
        flood(image, 0, height-1, None, bg)

    # crop out background regions
    image = utilities.autocrop(image, bg)

    width, height = image.size

    # rescale to 20px max, preserving logo aspect ratio
    if width > height:
        image = image.resize((20, int(20*height/width)), Image.BICUBIC)
    elif height > width:
        image = image.resize((int(20*width/height), 20), Image.BICUBIC)
    else:
        image = image.resize((20, 20), Image.BICUBIC)

    # tone down brightness
    bg = (0, 0, 0, 30)
    new_image = Image.new("RGBA", image.size, bg)
    image.paste(new_image, (0, 0), new_image)

    return image.convert('RGB')

def getLogo(name, headers, website):

    image = None

    host = re.sub(r"https?:\/\/", "", website)
    host = re.sub(r"\/.*$", "", host)

    headers["Host"] = host
    headers["Referer"] = website

    filetype = website.split('.')[-1].lower()

    req = requests.get(website, stream=True, headers=headers, timeout=5)
    if req.status_code == requests.codes.ok:
        image = open(f'{shared_config.icons_dir}/finance/logos/{name}.{filetype}', "wb")
        image.write(req.content)
        image.close()

        image = Image.open(f'{shared_config.icons_dir}/finance/logos/{name}.{filetype}')

        width, height = image.size

        image = image.convert('RGBA')

        testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
        testimage.paste(image, (0, 0), image)
        testimage = testimage.convert('RGB')

        # replace black parts of logo with dark grey if enough of the logo is black
        if np.count_nonzero(np.all(np.array(testimage) == (0, 0, 0), axis=-1))/(width*height) > 0.05:

            rgba = np.array(image)
            mask = (rgba[:, :, 0] < 35) & (rgba[:, :, 1] < 35) & (rgba[:, :, 2] < 35) & (rgba[:, :, 3] > 200)
            rgba[mask] = [35, 35, 35, 255]
            image = Image.fromarray(rgba)

        bg = (0, 0, 0, 255)

        new_image = Image.new("RGBA", image.size, bg)
        new_image.paste(image, (0, 0), image)

        image = new_image

        # Preshrink logo so recursive flood doesn't cause stack overflow or hit recursion limit
        width, height = image.size
        sz = 50
        if width > sz or height > sz:
            if width > height:
                image = image.resize((sz, int(sz*height/width)), Image.BICUBIC)
            elif height > width:
                image = image.resize((int(sz*width/height), sz), Image.BICUBIC)
            else:
                image = image.resize((sz, sz), Image.BICUBIC)

            width, height = image.size

        # flood background starting at the corners only if it is white
        white = (255, 255, 255, 255)

        tl = image.getpixel((0, 0))
        tr = image.getpixel((-1, 0))
        bl = image.getpixel((0, -1))
        br = image.getpixel((-1, -1))

        if max(colordista(tl, tr), colordista(tl, bl), colordista(tl, br), colordista(tr, bl), colordista(tr, br), colordista(bl, br)) < 30:

            flood(image, 0, 0, white, bg)
            flood(image, width-1, height-1, white, bg)
            flood(image, width-1, 0, white, bg)
            flood(image, 0, height-1, white, bg)

        # crop out background regions
        image = utilities.autocrop(image, bg)

        width, height = image.size

        # rescale to 20px max, preserving logo aspect ratio
        if width > height:
            image = image.resize((20, int(20*height/width)), Image.BICUBIC)
        elif height > width:
            image = image.resize((int(20*width/height), 20), Image.BICUBIC)
        else:
            image = image.resize((20, 20), Image.BICUBIC)

        # tone down brightness
        bg = (0, 0, 0, 30)
        new_image = Image.new("RGBA", image.size, bg)
        image.paste(new_image, (0, 0), new_image)

        image.convert('RGB').save(f'{shared_config.icons_dir}/finance/logos/{name}.png')

    return image


def getFavicon(name, headers, website):

    icons = favicon.get(website)

    image = None

    for icon in icons:

        host = re.sub(r"https?:\/\/", "", icon.url)
        host = re.sub(r"\/.*$", "", host)

        headers["Host"] = host
        headers["Referer"] = icon.url

        req = requests.get(icon.url, stream=True, headers=headers, timeout=5)
        if req.status_code == requests.codes.ok:
            image = open(f'{shared_config.icons_dir}/finance/logos/favicon.{icon.format}', "wb")
            image.write(req.content)
            image.close()

            image = Image.open(f'{shared_config.icons_dir}/finance/logos/favicon.{icon.format}')

            if image:
                break

    if image:
        width, height = image.size

        image = image.convert('RGBA')

        testimage = Image.new("RGBA", image.size, (255, 255, 255, 255))
        testimage.paste(image, (0, 0), image)
        testimage = testimage.convert('RGB')

        # Replace black parts of logo with dark grey if enough of the logo is black
        if np.count_nonzero(np.all(np.array(testimage) == (0, 0, 0), axis=-1))/(width*height) > 0.05:

            rgba = np.array(image)
            mask = (rgba[:, :, 0] < 35) & (rgba[:, :, 1] < 35) & (rgba[:, :, 2] < 35) & (rgba[:, :, 3] > 200)
            rgba[mask] = [35, 35, 35, 255]
            image = Image.fromarray(rgba)

        bg = (0, 0, 0, 255)

        new_image = Image.new("RGBA", image.size, bg)
        new_image.paste(image, (0, 0), image)

        image = new_image

        # Preshrink logo so recursive flood doesn't cause stack overflow or hit recursion limit
        width, height = image.size
        sz = 50
        if width > sz or height > sz:
            if width > height:
                image = image.resize((sz, int(sz*height/width)), Image.BICUBIC)
            elif height > width:
                image = image.resize((int(sz*width/height), sz), Image.BICUBIC)
            else:
                image = image.resize((sz, sz), Image.BICUBIC)

            width, height = image.size

        # Flood background starting at the corners only if it is white
        white = (255, 255, 255, 255)

        tl = image.getpixel((0, 0))
        tr = image.getpixel((-1, 0))
        bl = image.getpixel((0, -1))
        br = image.getpixel((-1, -1))

        if max(colordista(tl, tr), colordista(tl, bl), colordista(tl, br), colordista(tr, bl), colordista(tr, br), colordista(bl, br)) < 30:

            flood(image, 0, 0, white, bg)
            flood(image, width-1, height-1, white, bg)
            flood(image, width-1, 0, white, bg)
            flood(image, 0, height-1, white, bg)

        # crop out background regions
        image = utilities.autocrop(image, bg)

        width, height = image.size

        # rescale to 20px max, preserving logo aspect ratio
        if width > height:
            image = image.resize((20, int(20*height/width)), Image.BICUBIC)
        elif height > width:
            image = image.resize((int(20*width/height), 20), Image.BICUBIC)
        else:
            image = image.resize((20, 20), Image.BICUBIC)

        # tone down brightness
        bg = (0, 0, 0, 30)
        new_image = Image.new("RGBA", image.size, bg)
        image.paste(new_image, (0, 0), new_image)

        image.convert('RGB').save(f'{shared_config.icons_dir}/finance/logos/{name}.png')

    return image

def get_crypto(name, symbol):

    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/map'
    parameters = {
        'symbol': symbol
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

        coinid = 0
        try:
            coinid = [x for x in data["data"] if x["symbol"] == symbol][0]["id"]
        except:
            coinid = 0
        if coinid == 0:
            return None
        else:
            req = requests.get(f"https://s2.coinmarketcap.com/static/img/coins/64x64/{coinid}.png", stream=True, timeout=5)
            if req.status_code == requests.codes.ok:
                image = Image.open(req.raw)
                image = improcess(image.convert("RGBA"))
                image = image.convert("RGB")
                image.save(f'{shared_config.icons_dir}/finance/logos/{name}.png')
                return image
            else:
                return None
    else:
        return None


class Stock:
    def __init__(self, sign, client, ticker):

        self.sign = sign
        self.client = client
        self.ws_server = "wss://ws.finnhub.io"
        self.ws = None
        self.thread = None

        # Multithreading safe variables so that
        # the websocket thread can update them
        self.curr_price = Value('d', -1.0)
        self.prev_price = Value('d', -1.0)
        self.perc_change = Value('d', 0.0)
        self.high_price = Value('d', -1.0)
        self.low_price = Value('d', -1.0)

        self.setticker(ticker)
    
    def __del__(self):
        if self.thread and self.thread.is_alive():
            self.thread.terminate()

    def setticker(self, ticker):

        self.kill_ws()

        self.ticker = ticker

        us_symbols, cb_symbols, bn_symbols = update_global_lists(self.client)

        if (ticker.startswith("COINBASE:")):
            display_ticker = next(data for data in cb_symbols if data["symbol"] == ticker)["displaySymbol"].removesuffix("-USD").removesuffix("/USD")
            self.type = "CRYPTO"
            self.logo_name = "CRYPTO:"+display_ticker
            self.display_ticker = display_ticker
        elif (ticker.startswith("BINANCE:")):
            display_ticker = next(data for data in bn_symbols if data["symbol"] == ticker)["displaySymbol"].removesuffix("/USDT").removesuffix("-USDT")
            self.type = "CRYPTO"
            self.logo_name = "CRYPTO:"+display_ticker
            self.display_ticker = display_ticker
        else:
            display_ticker = next(data for data in us_symbols if data["symbol"] == ticker)["displaySymbol"]
            self.type = "STOCK"
            self.logo_name = ticker
            self.display_ticker = display_ticker

        try:
            data = self.client.quote(ticker)
        except Exception as e:
            logging.error(f"No data for ticker {ticker}: {e}")
            data = None

        if data:
            self.curr_price.value = data["c"]
            self.prev_price.value = data["c"]
            self.high_price.value = data["h"]
            self.low_price.value = data["l"]
            self.open_price = data["o"]
            self.prev_close = data["pc"]

            if self.prev_close > 0:
                self.perc_change.value = 100*(self.curr_price.value - self.prev_close)/self.prev_close
            else:
                self.perc_change.value = 0.0

            logging.debug(f"Set ticker to {ticker}: \
Current Price={self.curr_price.value}, \
Previous Close={self.prev_close}, \
Percent Change={self.perc_change.value}%, \
High Price={self.high_price.value}, \
Low Price={self.low_price.value}, \
Open Price={self.open_price}")
        else:
            self.curr_price.value = -1.0
            self.prev_price.value = -1.0
            self.high_price.value = -1.0
            self.low_price.value = -1.0
            self.open_price = -1.0
            self.prev_close = -1.0
            self.perc_change = 0.0

        self.get_logo()
        self.connect()

    def get_logo(self):
        # First try to get saved logo
        try:
            logo = Image.open(f'{shared_config.icons_dir}/finance/logos/{self.logo_name}.png')
        except:
            logo = None

        # Need to go get logo from web
        if logo == None:
            logging.debug(f"No previously saved logo for ticker {self.ticker} ({self.logo_name}). Getting from web.")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Keep-Alive": "timeout=5, max=1",
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'same-origin',
                "Sec-Fetch-User": "?1"
            }

            if self.type == "CRYPTO":
                logo = get_crypto(self.logo_name, self.display_ticker)
                if logo == None:
                    logging.debug(f"Could not get logo from CoinMarketCap for crypto {self.display_ticker}.")
                else:
                    logging.debug(f"Got logo from CoinMarketCap for crypto {self.display_ticker}.")
            else:
                # self.type == "STOCK"
                profile = self.client.company_profile2(symbol=self.ticker)
                if "logo" in profile and profile["logo"] != "":
                    logo = getLogo(self.logo_name, headers, profile["logo"])
                    if logo == None:
                        logging.debug(f"Could not get logo from Finnhub for ticker {self.ticker}.")
                    else:
                        logging.debug(f"Got logo from Finnhub for ticker {self.ticker} ({profile['logo']}).")
                if logo == None and "weburl" in profile and profile["weburl"] != "":
                    logo = getFavicon(self.logo_name, headers, profile["weburl"])
                    if logo == None:
                        logging.debug(f"Could not get favicon from website for ticker {self.ticker}.")
                    else:
                        logging.debug(f"Got favicon from company website for ticker {self.ticker} ({profile['weburl']}).")

            if logo == None:
                logo = Image.open(f"{shared_config.icons_dir}/finance/UNKNOWN.png")
                logging.debug(f"Could not get logo for ticker {self.ticker} from web.")

        self.logo = logo.convert("RGB")

    def kill_ws(self):
        # Close existing websocket if we have one
        if self.ws:
            self.ws.close()
            self.ws = None

        # Kill thread if we already have one running
        if self.thread:
            self.thread.terminate()

            while self.thread.is_alive():
                pass


    def connect(self):

        self.kill_ws()

        # Set to true for debugging
        websocket.enableTrace(False)

        self.ws = websocket.WebSocketApp(f"{self.ws_server}?token={shared_config.CONF['FINNHUB_API_KEY']}",
                                          on_open=self.onOpen,
                                          on_message=self.onMessage,
                                          on_error=self.onError,
                                          on_close=self.onClose)
        self.thread = Process(target=self.ws.run_forever, daemon=True)
        self.thread.start()

    def onMessage(self, ws, message):
        data = json.loads(message)

        if "data" in data and "type" in data and data["type"] == "trade":
            trades = data["data"]
            trade = trades[-1]

            # Use the last trade price as current price
            curr_price = trade["p"]
            self.curr_price.value = curr_price
            if self.prev_close > 0:
                self.perc_change.value = 100*(curr_price - self.prev_close)/self.prev_close
            else:
                self.perc_change.value = 0.0
            
            for trade in trades:
                p = trade["p"]
                if p > self.high_price.value:
                    self.high_price.value = p
                if p < self.low_price.value:
                    self.low_price.value = p

    def onError(self, ws, err):
        logging.error(f"Websocket Error: {err}")
    
    def onClose(self, ws, close_status_code="", close_msg=""):
        logging.debug(f"Websocket Closed: {close_status_code} : {close_msg}")
        
    def onOpen(self, ws):
        logging.debug(f'Opening Websocket connection to the server {self.ws_server} subscribed to ticker {self.ticker}...')
        ws.send(json.dumps({"type":"subscribe","symbol":self.ticker}))

    def drawlogo(self):

        if self.logo == None:
            return
        width, height = self.logo.size
        self.sign.canvas.SetImage(self.logo, 7+round((20-width)/2.0), 11+round((20-height)/2.0))

    def drawtime(self):

        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            print_time = utilities.convert_unix_to_local_time(time.time()).strftime('%H:%M')
        else:
            print_time = utilities.convert_unix_to_local_time(time.time()).strftime('%-I:%M%p')
        graphics.DrawText(self.sign.canvas, self.sign.font57, 93, 8, graphics.Color(255, 158, 31), print_time)

    def drawticker(self):

        if self.display_ticker == None:
            return
        if len(self.display_ticker) <= 4:
            graphics.DrawText(self.sign.canvas, self.sign.fontreallybig, 17-round(4.5*len(self.display_ticker)), 10, graphics.Color(20,200,20), self.display_ticker)
        else:
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 17-round(3*len(self.display_ticker[:5])), 10, graphics.Color(20,200,20), self.display_ticker[:5])

    def drawprice(self):

        curr_price = self.curr_price.value
        prev_price = self.prev_price.value
        perc_change = self.perc_change.value
        low_price = self.low_price.value
        high_price = self.high_price.value
        open_price = self.open_price

        price_format_str = "{0:.2f}"
        if self.type == "CRYPTO":
            if  curr_price < 1.0:
                price_format_str = "{0:.5f}"
            elif curr_price < 10.0:
                price_format_str = "{0:.4f}"
            elif curr_price < 100.0:
                price_format_str = "{0:.3f}"

        if curr_price >= 100000.0:
            price_format_str = "{0:.0f}"
        elif curr_price >= 10000.0:
                price_format_str = "{0:.1f}"

        if curr_price >= 0:
            # Draw percent change
            if perc_change > 0.001:
                change_color = graphics.Color(50, 150, 0)
            elif perc_change < -0.001:
                change_color = graphics.Color(150, 50, 0)
            else:
                change_color = graphics.Color(140, 140, 30)
                
            percent_format_str = "{0:+.3f}%"
            if (abs(perc_change) >= 100.0):
                percent_format_str = "{0:+.1f}%"
            elif (abs(perc_change) >= 10.0):
                percent_format_str = "{0:+.2f}%"
            perc_change_str = percent_format_str.format(perc_change)
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 32, 22, change_color, perc_change_str)

            # Draw current price
            currprice_str = price_format_str.format(curr_price)
            currprice_xloc = max(38, 32+round(3*(len(perc_change_str) - len(currprice_str))))
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, currprice_xloc, 10, graphics.Color(180, 180, 180), currprice_str)

            # Draw up/down arrow if price changed since last draw
            if prev_price >=0 and prev_price != curr_price:
                if curr_price > prev_price:
                    image = Image.open(f"{shared_config.icons_dir}/finance/up.png")
                else:
                    image = Image.open(f"{shared_config.icons_dir}/finance/down.png")
                self.sign.canvas.SetImage(image.convert('RGB'), 41+6*len(currprice_str), 2)

            # Draw price delta since open
            if open_price >= 0:
                delta = curr_price - open_price
                split_delta_str = str(delta).split('.')
                count_before_decimal = len(split_delta_str[0])
                count_after_decimal = len(split_delta_str[1])

                count_after_decimal_curr = len(currprice_str.split('.')[1])

                if (count_after_decimal > count_after_decimal_curr):
                    count_after_decimal = count_after_decimal_curr

                tot_length = count_before_decimal + count_after_decimal + 1
                if (tot_length > 8):
                    # Too long to fit, reduce decimal places
                    count_after_decimal = max(0, 8 - count_before_decimal - 1)
                delta_format_str = "{0:+." + str(count_after_decimal) + "f}"

                delta_str = delta_format_str.format(delta)
                graphics.DrawText(self.sign.canvas, self.sign.font57, 32+round(3*len(perc_change_str) - 2.5*len(delta_str)), 30, change_color, delta_str)

            # Remember the current price we just drew for next time
            self.prev_price.value = curr_price

        # Draw high price
        high_str = "--"
        if high_price >= 0:
            high_str = price_format_str.format(high_price)

        high_color = graphics.Color(20, 160, 60)
        if high_price >= 0 and curr_price == high_price:
            high_color = graphics.Color(70, 210, 110)

        graphics.DrawText(self.sign.canvas, self.sign.font57, min(83, 127 - 5*(len(high_str)+2)), 20, high_color, "H:"+ high_str)

        # Draw low price
        low_color = graphics.Color(60, 60, 160)
        if low_price >= 0 and curr_price == low_price:
            low_color = graphics.Color(110, 110, 210)

        low_str = "--"
        if low_price >= 0:
            low_str = price_format_str.format(low_price)
        graphics.DrawText(self.sign.canvas, self.sign.font57, min(83, 127 - 5*(len(low_str)+2)), 30, low_color, "L:"+ low_str)

    def drawfullpage(self):

        self.drawlogo()
        self.drawtime()
        self.drawticker()
        self.drawprice()

        self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)
        self.sign.canvas.Clear()
