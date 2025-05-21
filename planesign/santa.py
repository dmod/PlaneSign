#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from datetime import datetime, timedelta, timezone
import random
import pytz
import requests
import time
import math
import PIL.Image as Image
import shared_config
import utilities
import __main__
from modes import DisplayMode

class SleighParticle:

    def __init__(self,sign,x,y):
        self.x=x
        self.x0=x
        self.y=y
        self.sign = sign
        self.t0=time.perf_counter()
        self.color=30+random.random()*100
        self.color0 = self.color
        self.degspeed = 30+random.random()*10
        self.movespeed = 5#+random.random()

    def draw(self):
        self.sign.canvas.SetPixel(round(self.x), self.y, round(self.color), round(self.color), round(self.color))
        self.x = self.x0-self.movespeed*(time.perf_counter()-self.t0)
        self.color = self.color0-self.degspeed*(time.perf_counter()-self.t0)



class XmasLight:

    lastcolor = None

    def __init__(self,sign,x,y,color=None,period=None,minbright=None):
        self.x=x
        self.y=y
        self.color=color
        self.sign = sign
        if self.color == None:
            if XmasLight.lastcolor==None:
                self.color = random.randint(0,4)
            else:
                self.color = (XmasLight.lastcolor+1)%5
                #color = random.randint(0,4)
                #while color==XmasLight.lastcolor:
                #    color = random.randint(0,4)
        XmasLight.lastcolor = self.color

        self.evalcolor()

        if period == None:
            self.period = random.randint(10,20)
        else:
            self.period = period
        self.phase = random.randint(1,self.period)
        if minbright == None:
            self.minbright = 0.3+random.random()*0.2
        else:
            self.minbright = minbright
        self.maxbright = 1-random.random()*0.1
        self.dir = random.randint(0,1)*2-1
    
    def evalcolor(self):
        if self.color==0:
            self.r=255
            self.g=0
            self.b=0
        elif self.color==1:
            self.r=0
            self.g=255
            self.b=0
        elif self.color==2:
            self.r=0
            self.g=0
            self.b=255
        elif self.color==3:
            self.r=200
            self.g=0
            self.b=180
        else:
            self.r=200
            self.g=180
            self.b=0

    def draw(self):
        if self.phase + self.dir > self.period or self.phase + self.dir < 0:
            self.dir *= -1
        self.phase += self.dir

        #print(self.r,self.g,self.b)
        h,s,v = utilities.rgb_2_hsv(self.r,self.g,self.b)
        #print(h,s,v)
        v = (self.minbright+(self.maxbright-self.minbright)*(self.phase/self.period))*v
        #print(h,s,v)
        r,g,b = utilities.hsv_2_rgb(h/360.0,s/100.0,v/100.0)
        #print(r,g,b)
        #print("--------------")

        self.sign.canvas.SetPixel(self.x, self.y, r, g, b)

def assign_role(i,now):
    if now.month==12 and (now.day==25 or (now.day==26 and now.hour<6)):
        r = 0
    elif ((now.hour+hash(str(i))%4)//6)%3 == 1:
        r = 0 #sleeping
    elif (now.day+now.hour+(now.minute//15)+hash(str(i))%6)%6 < 2:
        r = 1 #napping
    else:
        r = (now.day+now.hour+(now.minute//15)+hash(str(i))%6)%6
        if i==1 or i==2: #Dancer, Prancer Bias
            if (now.hour+(now.minute//15)+hash(str(i))%6)%3 == 1:
                r = 4
        if i==0 or i==4 or i==7: #Dasher, Comet, Blitzen Bias
            if (now.hour+(now.minute//15)+hash(str(i))%6)%3 == 1:
                r = 5
                
    #2-snacking
    #3-frolicking
    #4-prancing
    #5-galloping
    #6-playing

    #i: 0-Dasher, 1-Dancer, 2-Prancer, 3-Vixen, 4-Comet, 5-Cupid, 6-Donner, 7-Blitzen, 8-Rudolph

    return r

@__main__.planesign_mode_handler(DisplayMode.SANTA)
def santa(sign):
    sign.canvas.Clear()

    reindeer_status=[0,0,0,0,0,0,0,0,0]
    roles = ["Sleeping", "Napping", "Snacking", "Frolicking", "Prancing", "Galloping", "Playing"]
    deernames = ["Dasher", "Dancer", "Prancer", "Vixen", "Comet", "Cupid", "Donner", "Blitzen", "Rudolph"]
    
    now = datetime.now(timezone.utc)
    for i in range(len(reindeer_status)):
        reindeer_status[i] = assign_role(i,now)

    changetime = time.perf_counter()

    weatherpoll = None

    lights = []    
    lights.append(XmasLight(sign, 2, 29))
    lights.append(XmasLight(sign, 1, 26))
    lights.append(XmasLight(sign, 4, 22))
    lights.append(XmasLight(sign, 2, 24))
    lights.append(XmasLight(sign, 0, 21))
    lights.append(XmasLight(sign, 1, 18))
    lights.append(XmasLight(sign, 3, 15))
    lights.append(XmasLight(sign, 1, 12))
    lights.append(XmasLight(sign, 2, 9))
    lights.append(XmasLight(sign, 0, 6))
    lights.append(XmasLight(sign, 2, 4))
    lights.append(XmasLight(sign, 3, 0))
    lights.append(XmasLight(sign, 6, 2))
    lights.append(XmasLight(sign, 9, 3))
    lights.append(XmasLight(sign, 13, 0))
    lights.append(XmasLight(sign, 17, 1))
    lights.append(XmasLight(sign, 21, 3))
    lights.append(XmasLight(sign, 25, 1))
    lights.append(XmasLight(sign, 28, 0))
    lights.append(XmasLight(sign, 27, 5))
    lights.append(XmasLight(sign, 31, 3))
    lights.append(XmasLight(sign, 34, 1))
    lights.append(XmasLight(sign, 37, 2))
    lights.append(XmasLight(sign, 41, 0))
    lights.append(XmasLight(sign, 43, 3))
    lights.append(XmasLight(sign, 47, 5))
    lights.append(XmasLight(sign, 51, 3))
    lights.append(XmasLight(sign, 55, 2))
    lights.append(XmasLight(sign, 58, 0))
    lights.append(XmasLight(sign, 60, 2))
    lights.append(XmasLight(sign, 63, 0))
    lights.append(XmasLight(sign, 64, 3))
    lights.append(XmasLight(sign, 68, 1))
    lights.append(XmasLight(sign, 71, 3))
    lights.append(XmasLight(sign, 75, 2))
    lights.append(XmasLight(sign, 78, 0))
    lights.append(XmasLight(sign, 80, 2))
    lights.append(XmasLight(sign, 83, 1))
    lights.append(XmasLight(sign, 86, 0))
    lights.append(XmasLight(sign, 89, 1))
    lights.append(XmasLight(sign, 92, 0))
    lights.append(XmasLight(sign, 96, 1))
    lights.append(XmasLight(sign, 99, 3))
    lights.append(XmasLight(sign, 102, 2))
    lights.append(XmasLight(sign, 103, 0))
    lights.append(XmasLight(sign, 99, 0))
    lights.append(XmasLight(sign, 105, 4))
    lights.append(XmasLight(sign, 108, 2))
    lights.append(XmasLight(sign, 111, 2))
    lights.append(XmasLight(sign, 114, 1))
    lights.append(XmasLight(sign, 117, 0))
    lights.append(XmasLight(sign, 120, 4))
    lights.append(XmasLight(sign, 118, 3))
    lights.append(XmasLight(sign, 121, 1))
    lights.append(XmasLight(sign, 124, 1))
    lights.append(XmasLight(sign, 127, 0))
    lights.append(XmasLight(sign, 126, 3))
    lights.append(XmasLight(sign, 126, 6))
    lights.append(XmasLight(sign, 125, 12))
    lights.append(XmasLight(sign, 124, 15))
    lights.append(XmasLight(sign, 126, 17))
    lights.append(XmasLight(sign, 124, 20))
    lights.append(XmasLight(sign, 123, 24))
    lights.append(XmasLight(sign, 126, 26))
    lights.append(XmasLight(sign, 125, 29))
    lights.append(XmasLight(sign, 122, 30))
    lights.append(XmasLight(sign, 121, 28))
    lights.append(XmasLight(sign, 120, 31))
    lights.append(XmasLight(sign, 118, 29))
    lights.append(XmasLight(sign, 114, 30))
    lights.append(XmasLight(sign, 111, 29))
    lights.append(XmasLight(sign, 109, 31))
    lights.append(XmasLight(sign, 105, 30))
    lights.append(XmasLight(sign, 99, 31))
    lights.append(XmasLight(sign, 96, 29))
    lights.append(XmasLight(sign, 92, 29))
    lights.append(XmasLight(sign, 89, 30))
    lights.append(XmasLight(sign, 86, 27))
    lights.append(XmasLight(sign, 84, 30))
    lights.append(XmasLight(sign, 81, 31))
    lights.append(XmasLight(sign, 77, 31))
    lights.append(XmasLight(sign, 74, 28))
    lights.append(XmasLight(sign, 77, 27))
    lights.append(XmasLight(sign, 76, 29))
    lights.append(XmasLight(sign, 73, 30))
    lights.append(XmasLight(sign, 70, 29))
    lights.append(XmasLight(sign, 66, 30))
    lights.append(XmasLight(sign, 64, 27))
    lights.append(XmasLight(sign, 61, 28))
    lights.append(XmasLight(sign, 57, 28))
    lights.append(XmasLight(sign, 55, 30))
    lights.append(XmasLight(sign, 52, 31))
    lights.append(XmasLight(sign, 52, 28))
    lights.append(XmasLight(sign, 50, 27))
    lights.append(XmasLight(sign, 47, 28))
    lights.append(XmasLight(sign, 45, 31))
    lights.append(XmasLight(sign, 43, 29))
    lights.append(XmasLight(sign, 40, 28))
    lights.append(XmasLight(sign, 41, 26))
    lights.append(XmasLight(sign, 43, 27))
    lights.append(XmasLight(sign, 39, 30))
    lights.append(XmasLight(sign, 36, 28))
    lights.append(XmasLight(sign, 33, 29))
    lights.append(XmasLight(sign, 29, 28))
    lights.append(XmasLight(sign, 27, 31))
    lights.append(XmasLight(sign, 24, 30))
    lights.append(XmasLight(sign, 20, 28))
    lights.append(XmasLight(sign, 17, 28))
    lights.append(XmasLight(sign, 15, 31))
    lights.append(XmasLight(sign, 12, 29))
    lights.append(XmasLight(sign, 9, 29))
    lights.append(XmasLight(sign, 6, 30))

    scroll=utilities.TextScroller(sign,22,27,(160,160,20),boxdim=(78,9),space=1,font="4x6",scrollspeed=10,holdtime=0)
    scroll2 = utilities.TextScroller(sign,5,20,(150,0,0),boxdim=(96,14),space=2,font="fontreallybig",scrollspeed=10,holdtime=0,forcescroll=True)
    scroll2.text="Ho Ho Ho!"

    present = Image.open(f"{shared_config.icons_dir}/santa/present.png").convert('RGB')
    deer = Image.open(f"{shared_config.icons_dir}/santa/deer.png").convert('RGB')
    cookie = Image.open(f"{shared_config.icons_dir}/santa/cookie.png").convert('RGB')
    milk = Image.open(f"{shared_config.icons_dir}/santa/milk.png").convert('RGB')
    globe = Image.open(f"{shared_config.icons_dir}/santa/globe.png").convert('RGB')
    list_img = Image.open(f"{shared_config.icons_dir}/santa/list.png").convert('RGB')
    lightstring = Image.open(f"{shared_config.icons_dir}/santa/background.png").convert('RGB')
    lightstring2 = Image.open(f"{shared_config.icons_dir}/santa/background2.png").convert('RGB')
    ccane = Image.open(f'{shared_config.icons_dir}/santa/ccane3.png').convert('RGB')
    ccane_dark = Image.open(f'{shared_config.icons_dir}/santa/ccane_dark3.png').convert('RGB')
    
    decorations=[]
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/bulb.png').convert('RGB'))
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/wreath.png').convert('RGB'))
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/star.png').convert('RGB'))
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/tree.png').convert('RGB'))
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/mistletoe.png').convert('RGB'))
    decorations.append(Image.open(f'{shared_config.icons_dir}/santa/candle.png').convert('RGB'))
    index = None
    
    gifts=[]
    for i in range(10):
        gifts.append(Image.open(f'{shared_config.icons_dir}/santa/gift{i+1}.png').convert('RGB'))

    particles=[]

    santapath_times = []
    santapath_codes = []
    santapath_names = []
    totlandtime = 0
    with open("datafiles/santapath.txt", "r", encoding='utf8') as f:
        lines = f.readlines()
        nline = 0
        for line in lines:
            parts = line.split('\t')
            t = int(parts[2])
            ccode = parts[1]
            fullname = parts[0]
            santapath_times.append(t)
            santapath_codes.append(ccode)
            santapath_names.append(fullname)
            if nline!=0 and santapath_codes[nline-1] != "NORTH" and santapath_codes[nline-1] != "OCEAN":
                totlandtime += santapath_times[nline]-santapath_times[nline-1]
            nline+=1

    
    santasheet = Image.open(f"{shared_config.icons_dir}/santa/sleigh.png").convert("RGB")
    frameheight=16
    nframes = round(santasheet.height/frameheight)
    framewidth=santasheet.width

    santaframes = []
    for f in range(nframes):
        santaframes.append(santasheet.crop((0, f*frameheight, framewidth, (f + 1)*frameheight)))

    deerflag = True
    code = None
    gift = None
    frame = -1

    #now = datetime(2023, 12, 24, 18, 0, tzinfo=pytz.utc)+timedelta(seconds=-60)
    #now = datetime(2023, 12, 25, 9, 0, tzinfo=pytz.utc)+timedelta(seconds=-10)
    #now = datetime(2023, 12, 26, 0, 0, tzinfo=pytz.utc)+timedelta(seconds=-10)
    #now = datetime(2024, 1, 1, 0, 0, tzinfo=pytz.utc)+timedelta(seconds=-10)
    while shared_config.shared_mode.value == DisplayMode.SANTA.value:

        now = datetime.now(pytz.utc).astimezone(shared_config.local_timezone)
        #now = now+timedelta(seconds=0.1)


        numkids = int(536785866*(1+0.01*(now.year-2019)))
        maxcookies = int(395830485*(1+(hash(str(now.year+3))%10)/10)*(1+0.01*(now.year-2019)))
        maxmilk = int(395830485*(1+(hash(str(now.year+6))%10)/10)*(1+0.01*(now.year-2019)))
        santavel = 25/9
        totaldist = (santavel*santapath_times[-2])
        numnaughty = int(numkids*(0.05+(hash(str(now.year+15))%10000000)/30000000))
        numnice = numkids-numnaughty
        maxpresents = int(numnice*(1+(hash(str(now.year))%10000000)/10000000))
        

        santastart = datetime(now.year, 12, 24, 18, tzinfo=pytz.utc)
        santaend = santastart+timedelta(seconds=santapath_times[-1])
        tts = santastart - now

        if now<santastart:
            xmas =  datetime(now.year, 12, 25, 0).astimezone(shared_config.local_timezone)
        else:
            xmas =  datetime(now.year+1, 12, 25, 0).astimezone(shared_config.local_timezone)

        ttc = xmas - now

        days = ttc.days
        hours = ttc.seconds//3600
        minutes = (ttc.seconds%3600)//60
        seconds = ttc.seconds%60

        dstring = f'{days}D'
        hstring = f'{hours}h'
        mstring = f'{minutes}m'
        sstring = f'{seconds}s'

        change = False
        if time.perf_counter()-changetime>2:
            changetime = time.perf_counter()
            change = True

        if now < santastart or (now.month==12 and now.day>25):
            #Before Christmas

            sign.canvas.SetImage(lightstring, 0, 0)

            for l in lights:
                if change:
                    l.color = (l.color-1)%5
                    l.evalcolor()                
                l.draw()

            graphics.DrawText(sign.canvas, sign.font46, 5, 13, graphics.Color(170,0,0), 'Christmas Day:')
            
            if days<10:
                strlen = (len(dstring)+len(hstring)+len(mstring)+len(sstring))
                graphics.DrawText(sign.canvas, sign.font46, 86-strlen*2+(len(dstring)+len(hstring)+len(mstring))*4, 13, graphics.Color(20,180,40), sstring)
            else:
                strlen = (len(dstring)+len(hstring)+len(mstring))
            graphics.DrawText(sign.canvas, sign.font46, 83-strlen*2, 13, graphics.Color(20,180,40), dstring)
            graphics.DrawText(sign.canvas, sign.font46, 84-strlen*2+len(dstring)*4, 13, graphics.Color(20,180,40), hstring)
            graphics.DrawText(sign.canvas, sign.font46, 85-strlen*2+(len(dstring)+len(hstring))*4, 13, graphics.Color(20,180,40), mstring)
          
            if int(seconds/15)%5==0:

                if now.month==12 and now.day>25:
                    graphics.DrawText(sign.canvas, sign.font46, 7, 24, graphics.Color(160,160,20), 'Toys Built:')
                    graphics.DrawText(sign.canvas, sign.font46, 52, 24, graphics.Color(160,160,20), f'Elf Holiday!')
                else:
                    sign.canvas.SetImage(present, 5, 16)

                    graphics.DrawText(sign.canvas, sign.font46, 17, 24, graphics.Color(160,160,20), 'Toys Built:')
                    graphics.DrawText(sign.canvas, sign.font46, 62, 24, graphics.Color(160,160,20), f'{int(maxpresents*(1-(tts.total_seconds()/31536000)))}')
            
            elif int(seconds/15)%5==1:
                
                sign.canvas.SetImage(list_img, 7, 17)

                if now > datetime(now.year, 12, 16, 4, tzinfo=pytz.utc) and not (now.month==12 and now.day>25):
                    graphics.DrawText(sign.canvas, sign.font46, 21, 24, graphics.Color(160,160,20), 'List Checked: Twice')
                elif now > datetime(now.year, 12, 5, 4, tzinfo=pytz.utc) and not (now.month==12 and now.day>25):
                    graphics.DrawText(sign.canvas, sign.font46, 21, 24, graphics.Color(160,160,20), 'List Checked: Once')
                else:
                    graphics.DrawText(sign.canvas, sign.font46, 21, 24, graphics.Color(160,160,20), "He's Making A List!")

            elif int(seconds/15)%5==2:

                if deerflag:
                    deerflag = False

                    deerorder = [0,1,2,3,4,5,6,7,8]
                    random.shuffle(deerorder)
                    text = ""
                    for i in deerorder:
                        text+=deernames[i]+":"+roles[reindeer_status[i]]+" "
                    scroll.text=text[:-1]

                sign.canvas.SetImage(deer, 6, 15)
                scroll.draw()

            else:

                deerflag = True

                if weatherpoll==None or time.perf_counter()-weatherpoll>900:
                    weatherpoll = time.perf_counter()
                    weather_data = requests.get(f"https://api.openweathermap.org/data/3.0/onecall?lat=90&lon=0&appid={shared_config.CONF['OPENWEATHER_API_KEY']}&exclude=minutely,hourly&units=imperial").json()
                    icon,_ = utilities.weather_icon_decode(weather_data['daily'][0]['weather'][0]['id'],weather_data['daily'][0]['weather'][0]['main'])

                image = Image.open(f"{shared_config.icons_dir}/weather/{icon}.png")
                iw,ih=image.size
                image = image.resize((int(iw*13/ih), 13), Image.BICUBIC)
                iw,ih=image.size
                sign.canvas.SetImage(image.convert('RGB'), 6, 20-int(iw/2))

                weatherstring = f"N Pole: {weather_data['daily'][0]['weather'][0]['main']} {round(weather_data['weather']['current']['temp'])}°F"
                graphics.DrawText(sign.canvas, sign.font46, max(7+iw,60-len(weatherstring)*2), 24, graphics.Color(160,160,20), weatherstring)


            for i in range(len(reindeer_status)):
                if random.random()<0.001:
                    reindeer_status[i] = assign_role(i,now)

        elif now>=santastart and now<santaend:
            #Santa in flight

            sign.canvas.SetImage(lightstring2, 0, 0)

            for l in lights:
                if change:
                    l.color = (l.color-1)%5
                    l.evalcolor()
                if l.y<26:
                    l.draw()

            deltasec=(now-santastart).total_seconds()

            currlandtime = 0

            for ind,timestamp in enumerate(santapath_times):
                if timestamp>deltasec:
                    break
                if ind!=0 and santapath_codes[ind-1] != "NORTH" and santapath_codes[ind-1] != "OCEAN":
                    currlandtime += santapath_times[ind]-santapath_times[ind-1]

            if ind!=0 and santapath_codes[ind-1] != "NORTH" and santapath_codes[ind-1] != "OCEAN":
                currlandtime += deltasec-santapath_times[ind-1]

            lastcode = code
            code = santapath_codes[ind-1]

            if code != lastcode:

                country_full = santapath_names[ind-1]

                if len(code)==2:
                    image = Image.open(f'{shared_config.icons_dir}/flags/states/{code}.png').convert('RGBA')
                else:
                    image = Image.open(f'{shared_config.icons_dir}/flags/{code}.png').convert('RGBA')
            
                if code != "NPL" and code != "OH" and code != "OCEAN":
                    image = utilities.fix_black(image)

                w, h = image.size
                maxw = 20
                maxh = 15
                if maxw*h<=maxh*w:
                    image = image.resize((maxw,min(round(maxw*h/w),maxh)), Image.BICUBIC)
                else:
                    image = image.resize((min(round(maxh*w/h),maxw),maxh), Image.BICUBIC)

                flagimage = image.convert('RGB')
                flagw, flagh = flagimage.size

            graphics.DrawText(sign.canvas, sign.font57, round(63.5-len(country_full)*2.5), 11, graphics.Color(200, 10, 10), country_full)

            if int(deltasec/15)%5==0:# or deltasec<santapath_times[1]:

                xsanta = 60

                if (random.random()<0.25 and len(particles)<15) or len(particles)<5:
                    particles.append(SleighParticle(sign, xsanta-round(random.random()*3), 20+round(random.random()*8)))

                particles.sort(key=lambda x: x.color, reverse=True)
                particlescopy = particles
                for p in particles:
                    if p.x<25 or p.color<5 or p.x0-p.x>20:
                        particlescopy.remove(p)
                    else:
                        p.draw()
                particles = particlescopy

                if gift==None and random.random()<0.05 and code != "NORTH" and code != "OCEAN":
                    gift=gifts[random.randint(0,9)]
                    giftx0=xsanta-10
                    gifty0=16+random.randint(-2,2)
                    giftvx=-(5+2*random.random())
                    giftvy=-(1.5+1*random.random())
                    gift_t0=deltasec
                    
                
                if gift != None:
                    giftx = giftx0+giftvx*(deltasec-gift_t0)
                    gifty = gifty0+giftvy*(deltasec-gift_t0) + 1.5*(deltasec-gift_t0)**2
                    if gifty>31:
                        gift=None
                    else:
                        sign.canvas.SetImage(gift, round(giftx), round(gifty))

                frame = (frame+1)%(3*nframes)
                sign.canvas.SetImage(santaframes[frame//3], xsanta, 12)


                currvel = santavel*3600*(1+(0.01*(1+0.2*math.sin(deltasec/13)))*math.sin(deltasec/100))
                if deltasec<200:
                    currvel *= (math.tanh((deltasec-60)/20)+1)/2
                elif (santaend-now).total_seconds()<200:
                    currvel *= (math.tanh(((santaend-now).total_seconds()-60)/20)+1)/2
                currvelstr = "{0:.0f}".format(currvel)
                graphics.DrawText(sign.canvas, sign.font57, 102, 19, graphics.Color(20, 160, 60), "Vel:")
                graphics.DrawText(sign.canvas, sign.font57, round(110-len(currvelstr)*2.5), 27, graphics.Color(20, 160, 60), currvelstr)

            elif int(deltasec/15)%5==1:

                sign.canvas.SetImage(cookie, 99, 13)

                currcookie = str(int(maxcookies*currlandtime/totlandtime))
                graphics.DrawText(sign.canvas, sign.font46, 32, 19, graphics.Color(160,160,20), 'Cookies Munched:')
                graphics.DrawText(sign.canvas, sign.font46, round(63.5-len(currcookie)*2), 27, graphics.Color(160,160,20), currcookie)

            elif int(deltasec/15)%5==2:

                sign.canvas.SetImage(milk, 100, 13)

                currmilk = str(int(maxmilk*currlandtime/totlandtime))
                graphics.DrawText(sign.canvas, sign.font46, 32, 20, graphics.Color(160,160,20), 'Glasses of Milk:')
                graphics.DrawText(sign.canvas, sign.font46, round(63.5-len(currmilk)*2), 27, graphics.Color(160,160,20), currmilk)
            
            elif int(deltasec/15)%5==3:

                sign.canvas.SetImage(present.resize((18, 15), Image.BICUBIC), 100, 12)

                currpresent = str(int(maxpresents*currlandtime/totlandtime))
                graphics.DrawText(sign.canvas, sign.font46, 32, 20, graphics.Color(160,160,20), 'Gifts Delivered:')
                graphics.DrawText(sign.canvas, sign.font46, round(63.5-len(currpresent)*2), 27, graphics.Color(160,160,20), currpresent)
            
            else:

                sign.canvas.SetImage(globe, 100, 12)

                currmiles = "{0:.0f}".format(totaldist*deltasec/santapath_times[-2])
                graphics.DrawText(sign.canvas, sign.font46, 34, 20, graphics.Color(160,160,20), 'Miles Traveled:')
                graphics.DrawText(sign.canvas, sign.font46, round(63.5-len(currmiles)*2), 27, graphics.Color(160,160,20), currmiles)
            

            sign.canvas.SetImage(flagimage, round(15-flagw/2), round(20.5-flagh/2))
            sign.canvas.SetImage(ccane_dark, 0, 29)
            sign.canvas.SetImage(ccane.crop((0, 0, round(128*deltasec/santapath_times[-2]), 6)), 0, 29)

        elif now.month==12 and now.day==25:
            
            deltasec=(now-santastart).total_seconds()
        
            sign.canvas.SetImage(lightstring, 0, 0)

            for l in lights:
                if change:
                    l.color = (l.color-1)%5
                    l.evalcolor()                
                l.draw()

            if int(deltasec/15)%2==0:
                if int(deltasec/2)%2==0:
                    scroll2.color=(150,0,0)
                else:
                    scroll2.color=(0,125,15)
                scroll2.draw()
                index = None
            elif int(deltasec/15)%2==1:
                if index == None:
                    index = random.sample(range(6), 2)
                    w1,h1 = decorations[index[0]].size
                    w2,h2 = decorations[index[1]].size
                if int(deltasec/3)%2==1:
                    sign.canvas.SetImage(decorations[index[0]], round(16-w1/2), round(16-h1/2))
                    sign.canvas.SetImage(decorations[index[1]], round(88-w2/2), round(16-h2/2))
                    graphics.DrawText(sign.canvas, sign.fontreallybig, 30, 20, graphics.Color(150,0,0), 'Merry')
                else:
                    graphics.DrawText(sign.canvas, sign.fontreallybig, 10, 20, graphics.Color(0,125,15), 'Christmas!')

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        sign.wait_loop(0.1)
