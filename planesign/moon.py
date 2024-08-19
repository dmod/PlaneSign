from datetime import datetime, timedelta
import time
import utilities
import random
from PIL import Image, ImageDraw
import shared_config
from rgbmatrix import graphics
import logging
import math
import __main__
from skyfield.api import load, wgs84
from skyfield.trigonometry import position_angle_of
from skyfield.framelib import ecliptic_frame
from skyfield import almanac
from satellite import Star


@__main__.planesign_mode_handler(18)
def moon(sign):

    i=0
    sign.canvas.Clear()

    image = Image.open(f"{shared_config.icons_dir}/nightsky.png")
    sign.canvas.SetImage(image.convert('RGB'), 0, 0)
    for i in range(-1,2):
        for j in range(-1,2):
            graphics.DrawText(sign.canvas, sign.fontbig, 3+i, 28+j, graphics.Color(0,0,0), "Loading...")
    graphics.DrawText(sign.canvas, sign.fontbig, 3, 28, graphics.Color(110, 110, 150), "Loading...")
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.canvas.Clear()

    eph = load('de421.bsp')

    stars = []

    stars.append(Star(sign, random.randint(44,55), random.randint(18,24), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(44,55), random.randint(18,24), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(52,55), random.randint(8,17), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(52,55), random.randint(8,17), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(87,97), random.randint(7,14), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(87,97), random.randint(7,14), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(87,97), random.randint(7,14), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(0,10), random.randint(18,24), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(0,10), random.randint(18,24), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(0,10), random.randint(18,24), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(0,50), random.randint(8,9), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(0,50), random.randint(8,9), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(122,127), random.randint(0,3), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(125,127), random.randint(4,7), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(97,100), random.randint(27,31), random.randint(50,150), 0))
    
    stars.append(Star(sign, random.randint(122,127), random.randint(27,31), random.randint(50,150), 0))

    lastcalc = None

    while shared_config.shared_mode.value == 18:

        i=(i+1)%25

        if lastcalc==None or time.perf_counter()-lastcalc>5:

            now = datetime.utcnow()
            ts = load.timescale()
            t = ts.utc(now.year, now.month, now.day, now.hour, now.minute, now.second)

            sun, moon, earth = eph['sun'], eph['moon'], eph['earth']

            e = earth.at(t)
            s = e.observe(sun).apparent()
            m = e.observe(moon).apparent()

            _, slon, _ = s.frame_latlon(ecliptic_frame)
            _, mlon, centermoondist = m.frame_latlon(ecliptic_frame)
            phase = (mlon.degrees - slon.degrees) % 360.0

            percent = 100.0 * m.fraction_illuminated(sun)

            europacafe = earth + wgs84.latlon(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
            b = europacafe.at(t)
            m = b.observe(moon).apparent()
            s = b.observe(sun).apparent()
            moonalt, moonaz, moondist = m.altaz(temperature_C='standard', pressure_mbar='standard')

            moonangle = position_angle_of(m.altaz(), s.altaz()).degrees

            if phase > 180: #waning
                moonorient = moonangle - 90
            else: #waxing
                moonorient = moonangle + 90

            w, h = 300, 300
            major = 250

            angle = phase*math.pi/180
            minor = major*abs(math.cos(angle))

            bg = Image.open("./icons/moon/moonbg.png").convert('RGBA')
            moon = Image.open("./icons/moon/moon.png").convert('RGBA')

            if angle<math.pi:
                mask = Image.open("./icons/moon/moonmaskright.png").convert('L')
            else:
                mask = Image.open("./icons/moon/moonmaskleft.png").convert('L')

            if angle<math.pi/2 or angle>math.pi*3/2:
                maskcolor = "black"
            else:
                maskcolor = "white"
                
            maskdraw = ImageDraw.Draw(mask)
            maskdraw.ellipse([(w/2-minor/2,h/2-major/2),(w/2+minor/2,h/2+major/2)], fill = maskcolor, outline = maskcolor)

            moon.putalpha(mask)
            bg.paste(moon, (0, 0), mask)
            bg = bg.rotate(moonorient, resample=Image.BICUBIC, expand=False)
            bg = bg.resize((36,36),Image.BICUBIC)

            _, ymonth = almanac.find_discrete(ts.utc(t.utc.year,t.utc.month,1,0), ts.utc(t.utc.year+1 if t.utc.month==12 else t.utc.year,(t.utc.month%12)+1,1,0), almanac.moon_phases(eph))

            phasename = ""
            fullflag = False
            if phase<=19.948 or phase>340.052:
                if (ymonth==0).sum()>1 and t.utc.day>15:
                    phasename = "Black Moon"
                else:
                    if centermoondist.km < 360000:
                        phasename = "Super New Moon"
                    elif centermoondist.km > 405000:
                        phasename = "Micro New Moon"
                    else:
                        phasename = "New Moon"
            elif phase<=84.261:
                phasename = "Waxing Crescent"
            elif phase<=95.739:
                phasename = "First Quarter"
            elif phase<=160.052:
                phasename = "Waxing Gibbous"
            elif phase<=199.948:
                fullflag = True
                _, ys = almanac.find_discrete(t-timedelta(days=14, hours=18, minutes=22, seconds=1.5), t+timedelta(days=14, hours=18, minutes=22, seconds=1.5), almanac.seasons(eph))
                if 2 in ys and not ((ymonth==2).sum()>1 and t.utc.day>15):
                    phasename = "Harvest Moon"
                else:
                    if centermoondist.km < 360000:
                        phasename += "Super "
                    elif centermoondist.km > 405000:
                        phasename += "Micro "
                    if (ymonth==2).sum()>1 and t.utc.day>15:
                        phasename += "Blue Moon"
                    else:
                        phasename += "Full Moon"
            elif phase<=264.261:
                phasename = "Waning Gibbous"
            elif phase<=275.739:
                phasename = "Third Quarter"
            elif phase<=340.052:
                phasename = "Waning Crescent"

            keytimes, y = almanac.find_discrete(t, t+timedelta(days=30), almanac.moon_phases(eph))

            found = 0
            for i in range(len(y)):
                if y[i]==2:
                    found=found+1
                if (not fullflag and found==1) or (fullflag and found==2):
                    break

            nextnewdate = keytimes[i].astimezone(shared_config.local_timezone).strftime('%m/%d')

            phaseangle = '({0:.0f}°)'.format(phase)

            moondir = utilities.direction_lookup(moonaz.degrees)

            scalestart = 5
            scaley = 28
            scalemax = 43
            scalecolor = graphics.Color(30, 50, 70)
            scale = scalemax*(moondist.km-356500)/(406700-356500)
            scale = min(max(scale,0),scalemax)
            scalepos = scalestart+round(scale)


            
            lastcalc = time.perf_counter()


        sign.canvas.SetImage(bg.convert('RGB'), 94, -2) 

        for s in stars:
            s.draw()
        
        graphics.DrawText(sign.canvas, sign.font57, 1, 6, graphics.Color(200, 10, 10), phasename)#110, 110, 150
        graphics.DrawText(sign.canvas, sign.font46, 89-2*len(phaseangle), 6, graphics.Color(110, 110, 150), phaseangle)

        graphics.DrawText(sign.canvas, sign.font57, 1, 17, graphics.Color(60, 60, 160), 'Full:')
        graphics.DrawText(sign.canvas, sign.font57, 27, 17, graphics.Color(60, 60, 160), f'{nextnewdate}')

        graphics.DrawText(sign.canvas, sign.font57, 57, 14, graphics.Color(20, 160, 60), 'Dir:')
        graphics.DrawText(sign.canvas, sign.font57, 77, 14, graphics.Color(20, 160, 60), moondir)

        graphics.DrawText(sign.canvas, sign.font57, 57, 22, graphics.Color(160, 160, 200), 'Alt:')
        graphics.DrawText(sign.canvas, sign.font57, 77, 22, graphics.Color(160, 160, 200), '{0:.0f}°'.format(moonalt.degrees))

        graphics.DrawText(sign.canvas, sign.font57, 56, 30, graphics.Color(20, 20, 210), 'Il:')
        if percent>=99.95:
            graphics.DrawText(sign.canvas, sign.font57, 72, 30, graphics.Color(20, 20, 210), '100%')
        else:
            graphics.DrawText(sign.canvas, sign.font57, 72, 30, graphics.Color(20, 20, 210), '{0:.1f}%'.format(percent))
        
        graphics.DrawLine(sign.canvas, scalestart, scaley, scalestart+scalemax, scaley,  scalecolor)
        graphics.DrawLine(sign.canvas, scalestart, scaley-2, scalestart, scaley+2,  scalecolor)
        graphics.DrawLine(sign.canvas, scalestart+scalemax, scaley-2, scalestart+scalemax, scaley+2,  scalecolor)

        graphics.DrawText(sign.canvas, sign.font46, scalestart-5, scaley+3, graphics.Color(142, 140, 68), 'P')
        graphics.DrawText(sign.canvas, sign.font46, scalestart+scalemax+3, scaley+3, graphics.Color(142, 140, 68), 'A')
        graphics.DrawText(sign.canvas, sign.font46, 12, scaley-4, graphics.Color(142, 140, 68), '{0:.0f}km'.format(moondist.km))#110, 90, 0

        
        if i<20:

            moonx = scalepos-1
            moony = scaley-2

            sign.canvas.SetPixel(moonx+1, moony, 92, 99, 103)
            sign.canvas.SetPixel(moonx+2, moony, 103, 111, 116)
            sign.canvas.SetPixel(moonx+3, moony, 31, 33, 34)
            sign.canvas.SetPixel(moonx, moony+1, 92, 99, 103)
            sign.canvas.SetPixel(moonx+1, moony+1, 113, 122, 116)
            sign.canvas.SetPixel(moonx+2, moony+1, 31, 33, 35)
            sign.canvas.SetPixel(moonx, moony+2, 113, 122, 127)
            sign.canvas.SetPixel(moonx+1, moony+2, 113, 122, 127)
            sign.canvas.SetPixel(moonx+2, moony+2, 18, 19, 20)
            sign.canvas.SetPixel(moonx, moony+3, 92, 99, 103)
            sign.canvas.SetPixel(moonx+1, moony+3, 113, 122, 127)
            sign.canvas.SetPixel(moonx+2, moony+3, 81, 87, 91)
            sign.canvas.SetPixel(moonx+1, moony+4, 92, 100, 104)
            sign.canvas.SetPixel(moonx+2, moony+4, 113, 122, 127)
            sign.canvas.SetPixel(moonx+3, moony+4, 92, 100, 104)

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        
        breakout = sign.wait_loop(0.1)

        if breakout:
            return