#!/usr/bin/python3
# -*- coding: utf-8 -*-
import time
import finnhub
import re
from PIL import Image, ImageDraw
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

repl = re.compile(r'(?:\s+(?:CO|CORP|LTD|LLC|PLC|INC|GRO|OPTION|ETF|EQ|INVT|TRUST))+|(?:\s+\w{1,2})+$|[\s\"\_\'\-\&\.\+\/\\]')

def similarity(search, entry):
    
    ls = len(search)
            
    if search in entry["symbol"]:
        le = len(entry["symbol"])
        symscore = ls / le
        if le > 2*ls+1:
            symscore *= 0.75
        if entry["symbol"].startswith(search):
            symscore *= 1.5
    else:
        symscore = 0.0
        
    if search in entry["description"]:
        strippeddesc = re.sub(repl, "", entry["description"])
        lds = len(strippeddesc)
        ld = len(entry["description"])
        descscore = ls / lds
        if descscore > 1.0:
            descscore = 1.0 - 0.02*(ld-lds)
        if ls < 3 or lds > 3*ls+2:
            descscore *= 0.75
        if entry["description"].startswith(search):
            descscore *= 1.5
    else:
        descscore = 0.0

    return max(symscore, descscore)
    
def cb_similarity(search, entry):
    
    ls = len(search)
    lds = len(entry["displaySymbol"].removesuffix("-USD"))
    
    score = ls / lds
    if lds > 2*ls+1:
        score *= 0.75
    if entry["displaySymbol"].startswith(search):
        score *= 1.5

    return score

def bn_similarity(search, entry):
    
    ls = len(search)
    lds = len(entry["displaySymbol"].removesuffix("/USDT"))
    
    score = ls / lds
    if lds > 2*ls+1:
        score *= 0.75
    if entry["displaySymbol"].startswith(search):
        score *= 1.5

    return score

def update_global_lists(client = None):

    if client == None:
        if "FINNHUB_API_KEY" not in shared_config.CONF or shared_config.CONF["FINNHUB_API_KEY"] == "":
            logging.error("Finnhub API key is not configured. Satellite mode will not function.")
        else:   
            client = finnhub.Client(api_key=shared_config.CONF["FINNHUB_API_KEY"])

    if "us_symbols" not in shared_config.data_dict:
        try:
            # Halve the number of symbols by only saving "Common Stock" types (filters out ETFs, preferred shares, etc)
            us_symbols = list(filter(lambda x: x["type"] == "Common Stock", client.stock_symbols("US")))
            shared_config.data_dict["us_symbols"] = us_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            us_symbols = []
    else:
        us_symbols = shared_config.data_dict["us_symbols"]

    if "cb_symbols" not in shared_config.data_dict:
        try:
            cb_symbols = client.crypto_symbols("COINBASE")
            shared_config.data_dict["cb_symbols"] = cb_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            cb_symbols = []
    else:
        cb_symbols = shared_config.data_dict["cb_symbols"]

    if "bn_symbols" not in shared_config.data_dict:
        try:
            bn_symbols = client.crypto_symbols("BINANCE")
            shared_config.data_dict["bn_symbols"] = bn_symbols
        except Exception as e:
            logging.error(f"Finnhub API Error: {e}")
            bn_symbols = []
    else:
        bn_symbols = shared_config.data_dict["bn_symbols"]

    return us_symbols, cb_symbols, bn_symbols

def get_tickers(search):

    search = search.upper()

    if "FINNHUB_API_KEY" not in shared_config.CONF or shared_config.CONF["FINNHUB_API_KEY"] == "":
        logging.error("Finnhub API key is not configured. Satellite mode will not function.")
        return []

    us_symbols, cb_symbols, bn_symbols = update_global_lists()

    cbpat = re.compile(rf"^COINBASE:\w*{re.escape(search)}\w*-USD$")
    bnpat = re.compile(rf"^\w*{re.escape(search)}\w*/USDT*$")
    
    # US lookup
    lookup_us = list(filter(lambda x: x["symbol"].startswith(search) or search in x["description"], us_symbols))

    for entry in lookup_us:
        entry["score"] = similarity(search, entry)

    # COINBASE lookup
    lookup_cb = list(filter(lambda x: cbpat.match(x["symbol"]), cb_symbols))
    
    for entry in lookup_cb:
        entry["score"] = cb_similarity(search, entry)

    # BINANCE lookup
    lookup_bn = list(filter(lambda x: bnpat.match(x["displaySymbol"]), bn_symbols))
    
    for entry in lookup_bn:
        entry["score"] = bn_similarity(search, entry)
    
    # Combined list sorted by score
    searchlist = sorted(lookup_us + lookup_cb + lookup_bn, key=lambda x: x["score"], reverse=True)

    return [{'description':dic['description'], 'symbol':dic['symbol']} for dic in searchlist[:25] if 'symbol' in dic and 'description' in dic]

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
        logging.error("Finnhub API key is not configured. Satellite mode will not function.")
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

        breakout = self.wait_loop(0.1)
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
    bg = (0, 0, 0, 100)
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
        bg = (0, 0, 0, 100)
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
        bg = (0, 0, 0, 100)
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

        self.setticker(ticker)

        self.prev_ticker = None
        self.chart = None
        self.polltime = None

        self.last_time = None

    def setticker(self, ticker):

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
            self.curr_price = data["c"]
            self.prev_price = data["c"]
            self.high_price = data["h"]
            self.low_price = data["l"]
            self.open_price = data["o"]
            self.prev_close = data["pc"]
            self.perc_change = 100*(self.curr_price - self.prev_close)/self.prev_close
        else:
            self.curr_price = None
            self.prev_price = None
            self.high_price = None
            self.low_price = None
            self.open_price = None
            self.prev_close = None
            self.perc_change = None

        self.get_logo()


    def updatedata(self, newticker=True):

        self.prev_price = self.curr_price

        if self.polltime==None or time.perf_counter()-self.polltime>5 or newticker:
            
            self.polltime = time.perf_counter()
            self.curr_price = self.ticker_data.info["currentPrice"]
            self.open_price = self.ticker_data.info["regularMarketOpen"]
            self.prev_close = self.ticker_data.info["previousClose"]
            self.perc_change = 100*(self.curr_price-self.prev_close)/self.prev_close

        # avoid getting history data more frequently than the interval unless ticker changes
        if self.chart == None or self.isnew or time.perf_counter()-self.last_time > 300:
            self.last_time = time.perf_counter()
            dayvals = self.ticker_data.history(period="1d", interval="5m")
            dayvals.Open.to_csv("prices.csv", index=False, header=None)
            dayvals = dayvals.Open.tolist()

            numpts = 32
            tnew = np.linspace(0, 63, numpts)
            if len(dayvals) > numpts:
                told = np.linspace(0, 63, len(dayvals))
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
                points.append((round(tnew[col])*2, (20-round(20*(dayvals[col]-daymin)/dayspread))*2))
            draw = ImageDraw.Draw(stockplot)
            if self.perc_change >= 0:
                draw.line(points, width=1, fill=(50, 255, 0), joint="curve")
            else:
                draw.line(points, width=1, fill=(255, 50, 0), joint="curve")

            self.chart = stockplot.resize((64, 20), Image.BICUBIC)

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

    def drawlogo(self):

        if self.logo == None:
            return
        width, height = self.logo.size
        self.sign.canvas.SetImage(self.logo, 5+round((20-width)/2.0), 11+round((20-height)/2.0))

    def drawtime(self):

        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            print_time = utilities.convert_unix_to_local_time(time.time()).strftime('%H:%M')
        else:
            print_time = utilities.convert_unix_to_local_time(time.time()).strftime('%-I:%M%p')
        graphics.DrawText(self.sign.canvas, self.sign.font57, 94, 8, graphics.Color(130, 90, 0), print_time)

    def drawticker(self):

        if self.display_ticker == None:
            return
        graphics.DrawText(self.sign.canvas, self.sign.fontbig, 3+round(3*(4-len(self.display_ticker[:5]))), 10, graphics.Color(0, 20, 150), self.display_ticker[:5])

    def drawprice(self):

        if self.perc_change:
            perc_change = self.perc_change
            if perc_change > 0:
                color = graphics.Color(50, 150, 0)
            elif perc_change < 0:
                color = graphics.Color(150, 50, 0)
            else:
                color = graphics.Color(120, 120, 0)
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 29, 22, color, "{0:+.1f}".format(perc_change)+"%")

        if self.curr_price:
            currprice_str = "{0:.2f}".format(self.curr_price)
            graphics.DrawText(self.sign.canvas, self.sign.fontbig, 32, 10, graphics.Color(150, 150, 150), currprice_str)

            if self.prev_price and self.prev_price != self.curr_price:
                if self.curr_price > self.prev_price:
                    image = Image.open(f"{shared_config.icons_dir}/finance/up.png")
                else:
                    image = Image.open(f"{shared_config.icons_dir}/finance/down.png")
                self.sign.canvas.SetImage(image.convert('RGB'), 34+6*len(currprice_str), 2)

    def drawchart(self):

        self.sign.canvas.SetImage(self.chart, 64, 11)

    def drawfullpage(self):

        #self.updatedata()

        self.drawlogo()
        self.drawtime()
        self.drawticker()
        self.drawprice()
        #self.drawchart()

        self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)
        self.sign.canvas.Clear()
