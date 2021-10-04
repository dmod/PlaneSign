import math
import numpy as np
import pytz
import random
import favicon
import re
import json
import requests
from requests import Session
from PIL import Image
from math import pi, cos, sin
from datetime import tzinfo, timedelta, datetime

NUM_STEPS = 40
DEG_2_RAD = pi/180.0

local_tz = pytz.timezone('America/New_York')

def random_angle():
    return random.randrange(0, 360)

def random_rgb_255_sum():
    _, r, g, b = next_color_rainbow_linear(random_angle())
    return r, g, b

def random_rgb(rmin=0,rmax=255,gmin=0,gmax=255,bmin=0,bmax=255):
    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256
    if rmax<rmin: rmin=rmax
    if gmax<gmin: gmin=gmax
    if bmax<bmin: bmin=bmax
    r=random.randrange(rmin, rmax+1)
    g=random.randrange(gmin, gmax+1)
    b=random.randrange(bmin, bmax+1)
    return r, g, b

def hsv_2_rgb(h,s,v):
        if s == 0.0: v*=255; return (v, v, v)
        i = int(h*6.)
        f = (h*6.)-i; p,q,t = int(255*(v*(1.-s))), int(255*(v*(1.-s*f))), int(255*(v*(1.-s*(1.-f)))); v*=255; i%=6
        if i == 0: return (v, t, p)
        if i == 1: return (q, v, p)
        if i == 2: return (p, v, t)
        if i == 3: return (p, q, v)
        if i == 4: return (t, p, v)
        if i == 5: return (v, p, q)

def next_color_rainbow_linear(angle,dangle=1,bright=255):
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

def next_color_rainbow_sine(angle,dangle=1,bright=255):
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

def next_color_random_walk_const_sum(r,g,b,step=1,rmin=0,rmax=255,gmin=0,gmax=255,bmin=0,bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax<rmin: rmin=rmax
    if gmax<gmin: gmin=gmax
    if bmax<bmin: bmin=bmax

    dr=256
    dg=256
    db=256

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


def next_color_random_walk_uniform_step(r,g,b,step=1,rmin=0,rmax=255,gmin=0,gmax=255,bmin=0,bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax<rmin: rmin=rmax
    if gmax<gmin: gmin=gmax
    if bmax<bmin: bmin=bmax

    dr=256
    dg=256
    db=256

    while (r+dr) > rmax or (r+dr) < rmin or (g+dg) > gmax or (g+dg) < gmin or (b+db) > bmax or (b+db) < bmin:

        theta = math.acos(2*random.random()-1)
        phi = 2*pi*random.random()

        dr=round(step*cos(phi)*sin(theta))
        dg=round(step*sin(phi)*sin(theta))
        db=round(step*cos(theta))
    
    r += dr
    g += dg
    b += db

    return r, g, b

def next_color_random_walk_nonuniform_step(r,g,b,step=1,rmin=0,rmax=255,gmin=0,gmax=255,bmin=0,bmax=255):

    rmin %= 256
    rmax %= 256
    gmin %= 256
    gmax %= 256
    bmin %= 256
    bmax %= 256

    step %= 100

    if rmax<rmin: rmin=rmax
    if gmax<gmin: gmin=gmax
    if bmax<bmin: bmin=bmax

    dr=256
    dg=256
    db=256

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

def next_color_andrew_weird(r,g,b,dr,dg,db):

    rtemp = r+dr
    gtemp = g+dg
    btemp = b+db

    if not (r>230 and dr<0) and not (r<30 and dr>0) and (rtemp <= 30 or rtemp >= 230):
        dr *= -1

    if not (g>230 and dg>0) and not (g<30 and dg<0) and (gtemp <= 30 or gtemp >= 230):
        dg *= -1

    if not (b>230 and db>0) and not (b<30 and db<0) and (btemp <= 30 or btemp >= 230):
        db *= -1

    r += dr
    g += dg
    b += db

    return r, g, b, dr, dg, db


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
    threshold = 15
    sizex, sizey = image.size
    
    if x >= sizex or y >= sizey or x < 0 or y < 0:
        return
    
    imagecolor = image.getpixel((x,y))

    if imagecolor==bg:
        return
    
    if color == None or colordista(imagecolor,color)<threshold:
        image.putpixel((x,y),bg)
        
        if x<sizex-1 and colordista(imagecolor,image.getpixel((x+1,y)))<threshold:
            flood(image,x+1,y,imagecolor,bg)
        if y<sizey-1 and colordista(imagecolor,image.getpixel((x,y+1)))<threshold:
            flood(image,x,y+1,imagecolor,bg)
        if x>1 and colordista(imagecolor,image.getpixel((x-1,y)))<threshold:
            flood(image,x-1,y,imagecolor,bg)
        if y>1 and colordista(imagecolor,image.getpixel((x,y-1)))<threshold:
            flood(image,x,y-1,imagecolor,bg)
        
    
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
    for row in range(sizey-1,-1,-1):
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
        for row in range(sizey):
            if image.getpixel((col,row))!=bg:
                flag=True
            if flag:
                break
        if flag:
            break
        
    left = col
    
    flag=False
    for col in range(sizex-1,-1,-1):
        for row in range(sizey):
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

# Returns the distance in MILES
def get_distance(coord1, coord2):
    R = 3958.8  # Earth radius in meters
    lat1, lon1 = coord1
    lat2, lon2 = coord2

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * \
        math.cos(phi2)*math.sin(dlambda/2)**2

    return (2*R*math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def convert_unix_to_local_time(unix_timestamp):
    utc_time = datetime.fromtimestamp(unix_timestamp, tz=pytz.utc)
    local_time = utc_time.astimezone(local_tz)
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
