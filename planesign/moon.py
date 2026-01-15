from datetime import datetime, timedelta, timezone
import time
import utilities
import random
import shutil
import os.path
from PIL import Image, ImageDraw, ImageChops
import shared_config
from rgbmatrix import graphics
import logging
import numpy as np
import __main__
from skyfield.api import load, wgs84, Loader, PlanetaryConstants
from skyfield.trigonometry import position_angle_of
from skyfield.framelib import ecliptic_frame
from skyfield.constants import ERAD
from skyfield.functions import angle_between, length_of
from skyfield import almanac
from satellite import Star

from modes import DisplayMode

@__main__.planesign_mode_handler(DisplayMode.MOON)
def moon(sign):

    # Fixed radii
    earth_radius_km = ERAD / 1e3
    solar_radius_km = 696340.0
    moon_radius_km  = 1737.1

    # Rotation offset to apply to the base Moon images
    # to align the pole upward. Determined experimentally
    # by matching other simulated depictions
    rotoffset = -75.0

    # Moon image dimensions
    w, h = 300, 300

    # Diameter of Moon in image in pixels
    major = 250

    # Distance (in km) defining bounds for "Super" and "Micro" moons respectively
    perigee_dist = 360000
    apogee_dist = 405000

    sign.canvas.Clear()

    image = Image.open(f"{shared_config.icons_dir}/nightsky.png")
    sign.canvas.SetImage(image.convert('RGB'), 0, 0)
    for i in range(-1,2):
        for j in range(-1,2):
            graphics.DrawText(sign.canvas, sign.fontbig, 3+i, 28+j, graphics.Color(0,0,0), "Loading...")
    graphics.DrawText(sign.canvas, sign.fontbig, 3, 28, graphics.Color(110, 110, 150), "Loading...")
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.canvas.Clear()

    # ---------------------------------------------------------
    # Load Ephemeris
    # ---------------------------------------------------------
    load = Loader(shared_config.datafiles_dir)

    # Move ephemeris file from old location if needed
    if os.path.isfile("./de421.bsp") and not os.path.isfile(f"{shared_config.datafiles_dir}/de421.bsp"):
        logging.debug("Moving de421.bsp to datafiles directory")
        shutil.move("./de421.bsp", f"{shared_config.datafiles_dir}/de421.bsp")

    msg = ""
    try:
        eph = load('de421.bsp')
    except Exception as e:
        msg = "Error getting ephemeris!"
        logging.error(f"Error loading {shared_config.datafiles_dir}/de421.bsp: %s", e)
        logging.error(f"Try updating certifi package with: pip3 install --upgrade --break-system-packages certifi \
                      or manually download from https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp and place\
                      it in {shared_config.datafiles_dir}.")

    pc = PlanetaryConstants()

    try:
        pc.read_text(load('moon_080317.tf'))
        pc.read_text(load('pck00008.tpc'))
        pc.read_binary(load('moon_pa_de421_1900-2050.bpc'))
    except Exception as e:
        msg = "Error getting moon eph!"
        logging.error(f"Error loading {shared_config.datafiles_dir}/de421.bsp: %s", e)
        logging.error(f"Try updating certifi package with: pip3 install --upgrade --break-system-packages certifi \
                      or manually download from https://naif.jpl.nasa.gov/pub/naif/LADEE/kernels/fk/moon_080317.tf, \
                      https://naif.jpl.nasa.gov/pub/naif/JUNO/kernels/pck/pck00008.tpc, \
                      https://ssd.jpl.nasa.gov/ftp/eph/planets/bpc/moon_pa_de421_1900-2050.bpc \
                      and place them in {shared_config.datafiles_dir}.")

    if msg != "":
        sign.canvas.SetImage(image.convert('RGB'), 0, 0)
        for i in range(-1,2):
            for j in range(-1,2):
                graphics.DrawText(sign.canvas, sign.font57, 3+i, 28+j, graphics.Color(0,0,0), msg)
        graphics.DrawText(sign.canvas, sign.font57, 3, 28, graphics.Color(200, 10, 10), msg)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        return sign.wait_loop(-1)

    # Build lunar reference frame
    lunar_frame = pc.build_frame_named('MOON_ME_DE421')

    sun, moon, earth = eph['sun'], eph['moon'], eph['earth']

    # Construct the observer's location
    observer = earth + wgs84.latlon(float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"]))
    
    # Construct the north pole of the moon which is taken to correspond
    # to the top center of our moon image.
    mnp = moon + pc.build_latlon_degrees(lunar_frame, 90.0, 0.0)

    ts  = load.timescale()

    # ---------------------------------------------------------

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

    blink_tic = 0
    while shared_config.shared_mode.value == DisplayMode.MOON.value:

        blink_tic = (blink_tic + 1)%25

        if lastcalc==None or time.perf_counter()-lastcalc>0.1:

            # ---------------------------------------------------------
            # Current Barycentric Positions
            # ---------------------------------------------------------

            now = datetime.utcnow()
            t = ts.utc(now.year, now.month, now.day, now.hour, now.minute, now.second)

            e_bary = earth.at(t)
            s_bary = sun.at(t)
            m_bary = moon.at(t)
            obs_bary = observer.at(t)
            mnp_bary = mnp.at(t)

            # ---------------------------------------------------------
            # Orbit Phase
            # ---------------------------------------------------------

            s_geo = s_bary - e_bary
            m_geo = m_bary - e_bary
            obs_geo = obs_bary - e_bary

            # Ecliptic frame longitudes are measured on the Earth-Sun orbit plane
            _, slon, _ = s_geo.frame_latlon(ecliptic_frame)
            _, mlon, centermoondist = m_geo.frame_latlon(ecliptic_frame)
            
            # Orbit phase goes from 0 -> 360 each orbit of the Moon around Earth
            # 0.0 -> ~New (Sun, Moon, and Earth are aligned - in that order)
            # 90.0 -> ~1st Quarter
            # 180.0 -> ~Full 
            # 270.0 -> ~3rd Quarter
            orbit_phase = (mlon.degrees - slon.degrees) % 360.0

            # ---------------------------------------------------------
            # Illumination Phase, Altitude, and Azimuth
            # ---------------------------------------------------------

            m_topo = obs_bary.observe(moon)
            s_topo = obs_bary.observe(sun)

            m_app = m_topo.apparent()
            s_app = s_topo.apparent()
            
            # Return the phase (Sun-Moon-Observer) angle.
            # Phase determines the shape of Moon illumination
            # (and if we are waxing/waning).
            # Exactly 0.0 -> Full (also perfectly aligned total lunar eclipse)
            # Exactly 90.0 -> 3rd Quarter
            # Exactly 180.0 -> New (also perfectly aligned solar eclipse)
            # Exactly 270.0 -> 1st Quarter
            # However, we shift everything + 180.0 (mod 360.0) to align
            # with the orbit_phase system
            phase = -m_app.phase_angle(sun).degrees
            if (orbit_phase > 180):
                phase = -phase
            phase = (phase + 180.0)%360.0
            
            # Moon altitude and azimuth are relative to the observer's local
            # horizon where azimuth is measured in degrees east of north.
            # These values are computed using the APPARENT position of the moon (where you would
            # actually look to see the moon) not where the moon actually is now.
            moonalt, moonaz, _ = m_app.altaz(temperature_C='standard', pressure_mbar='standard')

            moonangle = position_angle_of(m_app.altaz(), s_app.altaz()).degrees
            
            percent = 100.0 * m_app.fraction_illuminated(sun)

            if phase > 180:
                # Waning
                illumangle = moonangle - 90
            else:
                # Waxing
                illumangle = moonangle + 90

            # ---------------------------------------------------------
            # Moon Rotation
            # ---------------------------------------------------------
            
            # Create coodinate axis where "up_moon" is the Moon's
            # North pole projected on the viewing plane

            # Axis vector "moon_hat" points from Moon -> Earth
            moon_hat = -(m_geo.xyz.km)
            moon_hat /= np.linalg.norm(moon_hat)
            
            np_moon = (mnp_bary - m_bary).xyz.km
            np_moon /= np.linalg.norm(np_moon)
            
            # Project Moon's north pole vector onto the viewing plane
            up_moon = np_moon - np.dot(np_moon, moon_hat) * moon_hat
            up_moon /= np.linalg.norm(up_moon)
                    
            east_hat = np.cross(moon_hat, up_moon)
            east_hat /= np.linalg.norm(east_hat)
            
            # Project observer's normal direction onto the viewing plane
            up_obs = obs_geo.xyz.km / np.linalg.norm(obs_geo.xyz.km)
            up_obs_proj = up_obs - np.dot(up_obs, moon_hat) * moon_hat
            up_obs_proj /= np.linalg.norm(up_obs_proj)
            
            # Find the rotation angle between the projected observer's "up" and
            # the moon's "up" in the viewing plane. This is rotation at which the
            # observer views the Moon!
            moonorient = np.rad2deg(np.arccos(np.clip(np.dot(up_obs_proj,up_moon),-1,1)))
            if (np.dot(up_obs_proj, east_hat) > 0):
                moonorient = -moonorient

            # ---------------------------------------------------------
            # Phase Name
            # ---------------------------------------------------------

            _, ymonth = almanac.find_discrete(ts.utc(t.utc.year,t.utc.month,1,0), ts.utc(t.utc.year+1 if t.utc.month==12 else t.utc.year,(t.utc.month%12)+1,1,0), almanac.moon_phases(eph))
            tseason,_ = almanac.find_discrete(t-timedelta(days=92), t+timedelta(days=92), almanac.seasons(eph))
            tseason_events, yseason = almanac.find_discrete(tseason[0],tseason[1],almanac.moon_phases(eph))
            
            phasename = ""
            fullflag = False
            if phase<=19.948 or phase>340.052:
                if ((ymonth==0).sum()>1 and t.utc.day>15) or ((yseason==0).sum()>3 and np.argmin(abs(tseason_events[yseason==0]-t))==2):
                    if centermoondist.km < perigee_dist:
                        phasename = "Sup. "
                    elif centermoondist.km > apogee_dist:
                        phasename = "Mic. "
                    phasename += "Black Moon"
                else:
                    if centermoondist.km < perigee_dist:
                        phasename = "Super "
                    elif centermoondist.km > apogee_dist:
                        phasename = "Micro "
                    phasename += "New Moon"
            elif phase<=84.261:
                phasename = "Waxing Crescent"
            elif phase<=95.739:
                phasename = "First Quarter"
            elif phase<=160.052:
                phasename = "Waxing Gibbous"
            elif phase<=199.948:
                fullflag = True
                _, ys = almanac.find_discrete(t-timedelta(days=14, hours=18, minutes=22, seconds=1.5), t+timedelta(days=14, hours=18, minutes=22, seconds=1.5), almanac.seasons(eph))
                if 2 in ys and not (((ymonth==2).sum()>1 and t.utc.day>15) or ((yseason==2).sum()>3 and np.argmin(abs(tseason_events[yseason==2]-t))==2)):
                    if centermoondist.km < perigee_dist:
                        phasename = "S. "
                    elif centermoondist.km > apogee_dist:
                        phasename = "M. "
                    phasename += "Harvest Moon"
                else:
                    if centermoondist.km < perigee_dist:
                        phasename = "Super "
                    elif centermoondist.km > apogee_dist:
                        phasename = "Micro "
                    if ((ymonth==2).sum()>1 and t.utc.day>15) or ((yseason==2).sum()>3 and np.argmin(abs(tseason_events[yseason==2]-t))==2):
                        phasename += "Blue Moon"
                    else:
                        phasename += "Full Moon"
            elif phase<=264.261:
                phasename = "Waning Gibbous"
            elif phase<=275.739:
                phasename = "Third Quarter"
            elif phase<=340.052:
                phasename = "Waning Crescent"

            # ---------------------------------------------------------
            # Lunar Eclipse Checks
            # ---------------------------------------------------------

            draw_eclipse = False
            if 170 <= phase <= 190:

                # Eclipse detection algorithms adapted from skyfield.eclipselib
                earth_to_sun  = s_geo.xyz.km
                earth_to_moon = m_geo.xyz.km

                p_m = earth_radius_km / length_of(earth_to_moon)
                p_s = earth_radius_km / length_of(earth_to_sun)
                s_s = solar_radius_km / length_of(earth_to_sun)
                s_m = np.arcsin(moon_radius_km / length_of(earth_to_moon))

                p_1 = 1.01 * p_m    
                penumbra_radius = p_1 + p_s + s_s
                umbra_radius    = p_1 + p_s - s_s

                eclipse_angle = angle_between(-earth_to_sun, earth_to_moon)

                if(eclipse_angle + s_m < umbra_radius):
                    # Total lunar eclipse
                    phasename = ""
                    if centermoondist.km < perigee_dist:
                        phasename = "Sup. "
                    elif centermoondist.km > apogee_dist:
                        phasename = "Mic. "
                    phasename += "Blood Moon"
                    draw_eclipse = True
                elif(eclipse_angle - s_m < umbra_radius):
                    # Partial lunar eclipse
                    phasename = "Partial Eclipse"
                    draw_eclipse = True
                elif(eclipse_angle - s_m < penumbra_radius):
                    # Penumbral lunar eclipse
                    phasename = "Penumb. Eclipse"
                    draw_eclipse = True

            # ---------------------------------------------------------
            # Draw Moon Illumination
            # ---------------------------------------------------------

            angle = np.deg2rad(phase)
            minor = major * abs(np.cos(angle))

            bg = Image.open(f"{shared_config.icons_dir}/moon/moonbg.png").convert("RGBA").rotate(rotoffset, resample=Image.BICUBIC)
            moonim = Image.open(f"{shared_config.icons_dir}/moon/moon.png").convert("RGBA").rotate(rotoffset, resample=Image.BICUBIC)
            moonmask = moonim.getchannel('A')

            mask = Image.open(
                f"{shared_config.icons_dir}/moon/moonmaskright.png"
                if angle < np.pi else
                f"{shared_config.icons_dir}/moon/moonmaskleft.png"
            ).convert("L")

            maskdraw = ImageDraw.Draw(mask)
            maskdraw.ellipse(
                [(w/2 - minor/2, h/2 - major/2),
                (w/2 + minor/2, h/2 + major/2)],
                fill=0 if angle < np.pi/2 or angle > 3*np.pi/2 else 255
            )
            # Rotate the ilumination mask to the computed illumination angle
            mask.rotate(illumangle, resample=Image.BICUBIC)

            moonim.putalpha(mask)
            bg.paste(moonim, (0, 0), mask)

            # ---------------------------------------------------------
            # Draw Eclipse Shadow
            # ---------------------------------------------------------

            if draw_eclipse:
                
                # Anti-solar shadow axis
                shadow_hat = -s_geo.xyz.km
                shadow_hat /= np.linalg.norm(shadow_hat)
                
                # Earth-Moon vector
                moon_hat = m_geo.xyz.km
                
                # Angular Moon–shadow separation
                theta_sep = angle_between(shadow_hat, moon_hat)

                # Project shadow's center the viewing plane of the Moon
                shadow_proj = shadow_hat - np.dot(shadow_hat, moon_hat) * moon_hat
                shadow_proj /= np.linalg.norm(shadow_proj)

                # Shadow's rotation in viewing plane
                shadow_rot = np.arctan2(
                    np.dot(shadow_proj, -east_hat),
                    np.dot(shadow_proj, up_moon)
                )

                pixels_per_rad = (major / 2) / s_m
                
                # Compute the x,y location of the shadow's center on the image
                dx =  theta_sep * pixels_per_rad * np.sin(shadow_rot)
                # Minus sign on dy because PIL designates (0,0) in the top left corner
                dy = -theta_sep * pixels_per_rad * np.cos(shadow_rot)

                shadow_radius = umbra_radius * pixels_per_rad

                cx = w/2 + dx
                cy = h/2 + dy

                # Draw shadow
                eclipse = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(eclipse)
                draw.ellipse(
                    [(cx-shadow_radius, cy-shadow_radius),
                    (cx+shadow_radius, cy+shadow_radius)],
                    fill=(170, 70, 40, 130)
                )

                # Only put shadow on the Moon
                eclipse.putalpha(ImageChops.multiply(
                    eclipse.getchannel("A"), moonmask
                ))

                bg.paste(eclipse, (0, 0), eclipse)

            # ---------------------------------------------------------
            # Rotate Final Moon Image
            # ---------------------------------------------------------

            bg = bg.rotate(moonorient, resample=Image.BICUBIC)

            if ((now.month == 10 and now.day == 31) or (now.month == 11 and now.day == 1 and now.hour < 6)):
                if percent >= 70:
                    pumpkin = Image.open(f"{shared_config.icons_dir}/moon/witch.png").convert("RGBA")
                    bg.paste(pumpkin, (0, 0), pumpkin)
                else:
                    pumpkin = Image.open(f"{shared_config.icons_dir}/moon/pumpkin.png").convert("RGBA")
                    bg.paste(pumpkin, (shadow_center, 0), pumpkin)

            moon_image = bg.resize((36,36),Image.BICUBIC)
    
            # Find next full moon date
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
            scale = scalemax*(centermoondist.km-356500)/(406700-356500)
            scale = min(max(scale,0),scalemax)
            scalepos = scalestart+round(scale)

            lastcalc = time.perf_counter()

        # Draw the moon
        sign.canvas.SetImage(moon_image.convert('RGB'), 94, -2) 

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
        
        # Perigee/Apogee indicator scale
        graphics.DrawLine(sign.canvas, scalestart, scaley, scalestart+scalemax, scaley,  scalecolor)
        graphics.DrawLine(sign.canvas, scalestart, scaley-2, scalestart, scaley+2,  scalecolor)
        graphics.DrawLine(sign.canvas, scalestart+scalemax, scaley-2, scalestart+scalemax, scaley+2,  scalecolor)

        graphics.DrawText(sign.canvas, sign.font46, scalestart-5, scaley+3, graphics.Color(142, 140, 68), 'P')
        graphics.DrawText(sign.canvas, sign.font46, scalestart+scalemax+3, scaley+3, graphics.Color(142, 140, 68), 'A')
        graphics.DrawText(sign.canvas, sign.font46, 12, scaley-4, graphics.Color(142, 140, 68), '{0:.0f}km'.format(centermoondist.km))#110, 90, 0

        
        if blink_tic<20:
            # Blinking moon for perigee/apogee indicator
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