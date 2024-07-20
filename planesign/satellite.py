from http.client import OK
import time
from datetime import datetime, timedelta
import random
import requests
import utilities
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import shared_config
from rgbmatrix import graphics
import country_converter as coco
import numpy as np
import logging
import math
from bs4 import BeautifulSoup
from os.path import exists
import os
import __main__

def shorten_name(name):
    name = name.replace("French Southern and Antarctic Lands","French S. Lands")
    name = name.replace("Northern", "N.").replace("North", "N.")
    name = name.replace("Southern", "S.").replace("South", "S.")
    name = name.replace("Eastern", "E.").replace("East", "E.")
    name = name.replace("Western", "W.").replace("West", "W.")
    name = name.replace("Central", "C.")
    name = name.replace("Federated States of ", "").replace("State of ", "").replace(", USA", "")
    name = name.replace("Province", "Prov.").replace("Democratic Republic", "D.R.")
    name = name.replace("Saint", "St.")
    return name

class Star:
    def __init__(self,sign,x,y,period=None,minbright=None):
        self.x=x
        self.y=y
        if period == None:
            self.period = random.randint(15,50)
        else:
            self.period = period
        self.phase = random.randint(1,self.period)
        if minbright == None:
            self.minbright = 0.1+random.random()*0.1
        else:
            self.minbright = minbright
        self.maxbright = random.randint(100,150)
        self.dir = random.randint(0,1)*2-1
        self.sign = sign
    
    def draw(self):
        if self.phase + self.dir > self.period or self.phase + self.dir < 0:
            self.dir *= -1
        self.phase += self.dir

        c=round(max(self.minbright,(self.phase/self.period))*self.maxbright)
        self.sign.canvas.SetPixel(self.x, self.y, c, c, c)


def get_country_code(rawname,date):

    fullcode = ""

    for country in rawname.split("/"):

        country = country.strip().upper()

        if country == "EU" or country.find("ESA") != -1 or country.find("(EUTE)") != -1 or country.find("(EUME)") != -1:
            code = "EU"
        elif country == "USR" or country.find("USSR") != -1 or country.find("(CIS)") != -1 or country.find("(TBD)") != -1:
            if datetime.strptime(date, "%Y-%m-%d").date()<datetime(1991, 10, 26, 0, 0).date():
                code = "USR"
            else:
                code = "RUS"
        elif country.find("(ITSO)") != -1 or country.find("(ASRA)") != -1:
            code = "USA"
        elif country.find("INMARSAT") != -1 or country.find("(NICO)") != -1:
            code = "GBR"
        elif country == "UN" or country == "MULTINATIONAL" or country.find("(AB)") != -1 or country.find("(RASC)") != -1:
            code = "UN"
        elif country.find("(SES)") != -1:
            code = "LUX"
        elif country == "NATO" or country.find("(NATO)") != -1:
            code = "NATO"
        elif country.find("(SWTZ)") != -1:
            code = "CHE"
        elif country.find("TÜRKIYE") != -1:
            code = "TUR"
        elif country.find("(ASIASAT)") != -1:
            code = "HKG"
        else:
            code = coco.convert(names=country.replace("(","").replace(")","").rstrip(), to="ISO3", not_found="UNKNOWN")
            if isinstance(code, list):
                code = code[0]
 
        if code != "UNKNOWN":
            fullcode += f'{code}/'

    return fullcode.rstrip("/")

def gen_flag(code):

    image = None

    if code.find("/") != -1:
        countries = code.split("/")
        llmask = Image.open(f"{shared_config.icons_dir}/flags/MASK_LL.png").convert('RGBA')
        cmask = Image.open(f"{shared_config.icons_dir}/flags/MASK_C.png").convert('RGBA')

        if len(countries)==2:
            
            try:
                image = Image.open(f'{shared_config.icons_dir}/flags/{countries[1]}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                foreground = Image.open(f'{shared_config.icons_dir}/flags/{countries[0]}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                image.paste(foreground, (0, 0), llmask)

            except Exception:
                pass

        elif len(countries)==3:

            try:
                image = Image.open(f'{shared_config.icons_dir}/flags/{countries[2]}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                foreground = Image.open(f'{shared_config.icons_dir}/flags/{countries[1]}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                center =  Image.open(f'{shared_config.icons_dir}/flags/{countries[0]}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')

                image.paste(foreground, (0, 0), llmask)
                image.paste(center, (0, 0), cmask)

            except Exception:
                pass

        elif len(countries)>3:
            image = Image.open(f'{shared_config.icons_dir}/flags/UN.png').convert('RGBA')

    else:
        try:
            image = Image.open(f'{shared_config.icons_dir}/flags/{code}.png').convert('RGBA')
        except Exception:
            pass
    
    return image

def get_flag(selected,satellite_data):

    image = None
    
    if satellite_data:

        code = ""

        sat_name = selected["satname"]

        #Search by NORAD ID
        sat = [d for d in satellite_data if d["NORAD"] == selected["satid"]]

        if len(sat)==0:
            #Fallback search by COSPAR ID
            sat = [d for d in satellite_data if d["COSPAR"] == selected["intDesignator"]]

        if len(sat)>0:

            code = get_country_code(sat[0]["country"],selected["launchDate"])

        #can't find in static file lookup, apply known cases
        elif sat_name.find("USA") == 0 or sat_name.find("STARLINK") == 0 or sat_name.find("SATCOM") == 0 or sat_name.find("DIRECTV") == 0 or sat_name.find("NOAA") == 0 or sat_name.find("GOES ") == 0 or sat_name.find("OPS ") == 0 or sat_name.find("HAWK-") == 0 or sat_name.find("DMSP ") == 0 or sat_name.find("GALAXY") == 0 or sat_name.find("INTELSAT") == 0 or sat_name.find("WESTFORD NEEDLES") == 0 or sat_name.find("FLOCK") == 0 or sat_name.find("DOVE ") == 0 or sat_name.find("IRIDIUM") == 0 or sat_name.find("NAVSTAR") == 0 or sat_name.find("EXPLORER") == 0 or sat_name.find("GLOBALSTAR") == 0 or sat_name.find("ORBCOMM") == 0 or sat_name.find("LANDSAT") == 0 or sat_name.find("COMSTAR") == 0 or sat_name.find("SPACEBEE-") == 0 or sat_name.find("GLOBAL-") == 0 or sat_name.find("ECHOSTAR") == 0 or sat_name.find("AEROCUBE ") == 0 or sat_name.find("LEASAT ") == 0 or sat_name.find("ESSA ") == 0 or sat_name.find("LES ") == 0 or sat_name.find("SECOR ") == 0 or sat_name.find("TIROS ") == 0:
            code = "USA"

        elif sat_name.find("COSMOS") == 0  or sat_name.find("MOLNIYA") == 0 or sat_name.find("METEOR") == 0 or sat_name.find("GONETS") == 0 or sat_name.find("GORIZONT") == 0 or sat_name.find("YUZGU") == 0 or sat_name.find("RADIO ") == 0 or sat_name.find("EXPRESS") == 0 or sat_name.find("NADEZHDA") == 0 or sat_name.find("KANOPUS") == 0 or sat_name.find("EKRAN") == 0 or sat_name.find("RADUGA") == 0 or sat_name.find("OKEAN ") == 0:
            if datetime.strptime(selected["launchDate"], "%Y-%m-%d").date()<datetime(1991, 10, 26, 0, 0).date():
                code = "USR"
            else:
                code = "RUS"

        elif sat_name.find("SINOSAT") == 0 or sat_name.find("SHIYAN") == 0 or sat_name.find("FENGYUN") == 0 or sat_name.find("GAOFEN") == 0 or sat_name.find("BEIDOU") == 0 or sat_name.find("CHINASAT") == 0 or sat_name.find("JILIN") == 0 or sat_name.find("YAOGAN") == 0 or sat_name.find("GEESAT") == 0:
            code = "CHN"

        elif sat_name.find("ONEWEB") == 0 or sat_name.find("O3B") == 0 or sat_name.find("INMARSAT") == 0 or sat_name.find("SKYNET ") == 0:
            code = "GBR"

        elif sat_name.find("EUTE") == 0 or sat_name.find("METEOSAT") == 0:
            code = "EU"

        elif sat_name.find("INSAT ") == 0 or sat_name.find("GSAT ") == 0 or sat_name.find("GSAT-") == 0 or sat_name.find("IRS ") == 0 or sat_name.find("IRNSS") == 0:
            code = "IND"

        elif sat_name.find("DIADEME") == 0 or sat_name.find("SPOT ") == 0 or sat_name.find("TELECOM ") == 0 or sat_name.find("BRO-") == 0:
            code = "FRA"
        
        elif sat_name.find("UNISAT") == 0 or sat_name.find("ION SCV") == 0:
            code = "ITA"
        
        elif sat_name.find("SAUDISAT") == 0 or sat_name.find("SAUDICOMSAT") == 0:
            code = "SAU"

        elif sat_name.find("NUSAT") == 0:
            code = "ARG"

        elif sat_name.find("ASTROCAST") == 0:
            code = "CHE"

        elif sat_name.find("ANIK ") == 0 or sat_name.find("GHGSAT") == 0:
            code = "CAN"

        elif sat_name.find("ASTRA") == 0:
            code = "LUX"

        elif sat_name.find("OPTUS") == 0 or sat_name.find("SKYKRAFT") == 0:
            code = "AUS"

        elif sat_name.find("ICEYE") == 0:
            code = "FIN"
        
        elif sat_name.find("SPACEBEENZ") == 0:
            code = "NZL"

        elif sat_name.find("STORK") == 0:
            code = "POL"

        elif sat_name.find("TEVEL") == 0:
            code = "ISR"

        #Still can't find country: go scrape country from website
        else:

            try:
                with requests.Session() as s:
                    response = s.get(f'https://www.n2yo.com/satellite/?s={selected["satid"]}',timeout=2)
            except Exception:
                response = None

            if response and response.status_code == requests.codes.ok:
                soup = BeautifulSoup(response.content, "html.parser")
                info = soup.find('div', {'id':'satinfo'})

                fullcountry = info.find("b",text="Source").next_sibling[2:].strip()

                code = get_country_code(fullcountry,selected["launchDate"])

                if code != "":
                    logging.debug(f'Found country for satellite: {sat_name}\t{selected["satid"]}\t{selected["intDesignator"]}\t{code}')
                    with open("satsup.txt", "a+") as suppliment_satfile:

                        suppliment_satfile.write(f'{sat_name}\t{selected["satid"]}\t{selected["intDesignator"]}\t{code}\n')
                        satellite_data.append({"COSPAR":selected["intDesignator"], "NORAD":selected["satid"], "country":code})
                else:
                    logging.debug(f'Couldn\'t find country for satellite: {sat_name}\t{selected["satid"]}\t{selected["intDesignator"]} from {fullcountry}')

        #Try to find or generate flag from country code
        image = gen_flag(code)
    
    if image == None:

        image = Image.new("RGB", (13,9), (0, 0, 0))

    else:

        image = utilities.fix_black(image)

        w, h = image.size

        if round(9*w/h)<13:
            image = image.resize((round(9*w/h), 9), Image.BICUBIC)
        else:
            image = image.resize((13, 9), Image.BICUBIC)

    return image

@__main__.planesign_mode_handler(17)
def satellites(sign):

    sign.canvas.Clear()

    image = Image.open(f"{shared_config.icons_dir}/galaxy.png")
    sign.canvas.SetImage(image.convert('RGB'), 0, 0)
    for i in range(-1,2):
        for j in range(-1,2):
            graphics.DrawText(sign.canvas, sign.fontbig, 3+i, 28+j, graphics.Color(0,0,0), "Loading...")
    graphics.DrawText(sign.canvas, sign.fontbig, 3, 28, graphics.Color(180,100,180), "Loading...")
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.canvas.Clear()

    satellite_data = []
    try:
        with open("satdat.txt",encoding='windows-1252') as f:
            pass
    except:
        satdaturl = "https://www.ucsusa.org/media/11490"
        file = requests.get(satdaturl, stream=True, allow_redirects=True)
        if file.status_code == requests.codes.ok:
            sat_lines = file.text.splitlines()[1:]
            print(f"Found static data for {len(sat_lines)} satellites")
            with open("satdat.txt", 'wb') as f:
                f.write(file.content)

    try:
        with open("satdat.txt",encoding='windows-1252',errors='replace') as f:
            lines = f.readlines()[1:]
            nline = 0
            for line in lines:
                nline+=1
                if nline==1:
                    continue
                parts = line.strip().split('\t')
                if len(parts)>25:
                    country = parts[2]
                    cospar = parts[24]
                    norad = int(parts[25])
                    satellite_data.append({"COSPAR":cospar, "NORAD":norad, "country":country})
        if exists("satsup.txt"):
            with open("satsup.txt", "r") as f:
                lines = f.readlines()
                nline = 0
                for line in lines:
                    nline+=1
                    parts = line.split('\t')
                    if len(parts)>3:
                        norad = int(parts[1])
                        cospar = parts[2]
                        country = parts[3]
                        satellite_data.append({"COSPAR":cospar, "NORAD":norad, "country":country})
        else:
            with open("satsup.txt", "w+") as f:
                pass
            os.chmod("satsup.txt", 0o777)

    except Exception as e:
        logging.exception("Can't read static satellite data")
        logging.exception(e)

    elevation = 0
    with requests.Session() as s:
        s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=1, respect_retry_after_header=False)))
        try:
            response = s.get(f'https://api.open-elevation.com/api/v1/lookup?locations={shared_config.CONF["SENSOR_LAT"]},{shared_config.CONF["SENSOR_LON"]}',timeout=1)
 
            if response.status_code == requests.codes.ok:
                data = response.json()
                elevation = data["results"][0]['elevation']
                logging.info(f'Got elevation as {elevation}m')
            else:
                logging.warning(f'Could not get elevation data, using {elevation}m')
        except:
            logging.warning(f'Could not get elevation data... using {elevation}m')

    satsite = "https://api.n2yo.com/rest/v1/satellite"
    
    polltime = None
    closest = None
    lowest = None
    multiplier=1

    iss_polltime = None
    iss_flyby_polltime = None
    iss_pos = None
    iss_flyby = None
    iss_dist = None
    iss_alt = None
    iss_vel = None
    iss_dir = None
    iss_last_loc = None
    geotime = None

    blip_count = 0
    
    iss_image = Image.open(f'{shared_config.icons_dir}/ISS.png').convert("RGB")

    stars = []
    stars.append(Star(sign, 100, 14))
    stars.append(Star(sign, 110, 17))
    stars.append(Star(sign, 117, 13))
    stars.append(Star(sign, 102, 21))
    stars.append(Star(sign, 116, 28))
    stars.append(Star(sign, 124, 25))
    stars.append(Star(sign, 105, 30))
    stars.append(Star(sign, 123, 31))
    stars.append(Star(sign, 120, 20))

    stars.append(Star(sign, random.randint(41,46), random.randint(9,17), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(41,51), random.randint(18,24), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(94,99), random.randint(9,24), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(28,64), random.randint(0,3), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(28,64), random.randint(0,3), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(65,110), random.randint(0,3), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(65,110), random.randint(0,3), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(28,36), random.randint(0,11), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(112,127), random.randint(0,12), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(112,127), random.randint(0,12), random.randint(50,150), 0))

    while shared_config.shared_mode.value == 17:

        if shared_config.shared_satellite_mode.value == 1:

            if polltime==None or time.perf_counter()-polltime>10*multiplier:

                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    response = s.get(satsite+f'/above/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/{elevation}/45/0/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                if response.status_code == requests.codes.ok:
                    polltime = time.perf_counter()
                    data = response.json()

                    #slow down requests as we approach limit
                    if data["info"]["transactionscount"]>500:
                        multiplier = 1+2*(data["info"]["transactionscount"]-500)/400
                    else:
                        multiplier = 1

                    above = data["above"]
                    
                    above = list(map(lambda item: dict(item, dist=utilities.get_distance((item["satlat"],item["satlng"]),(float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))), vel=math.sqrt(398600/(6371.009+item["satalt"]))), above))

                    #remove debris from results
                    above = list(filter(lambda x: " DEB" not in x["satname"] and " R/B" not in x["satname"] and " AKM" not in x["satname"] and " ABM" not in x["satname"] and "OBJECT " not in x["satname"] and "OBJECT-" not in x["satname"] and x["satname"] != "OBJECT" and (("STARLINK" not in x["satname"]) if shared_config.CONF["HIDE_STARLINK"].lower() == 'true' else True), above))

                    closest_list = sorted(above, key=lambda k: k["dist"])
                    lowest_list = sorted(above, key=lambda k: k["satalt"])

                    closest = closest_list[0]
                    lowest = lowest_list[0]

                    dupeflag = False
                    if closest == lowest:
                        dupeflag = True
                        lowest=closest_list[random.randint(1,len(closest_list)-1)]

                    close_name = closest["satname"]
                    if close_name.find("STARLINK") != -1:
                        close_name=close_name.replace("-", "").replace(" ", "")
                    elif close_name.find("SPACE STATION") == 0:
                        close_name="ISS"
                    pindex = close_name.find(' (')
                    if pindex != -1 and len(close_name)>12:
                        clean_close_name = close_name[:pindex]
                    else:
                        clean_close_name = close_name

                    low_name = lowest["satname"]
                    if low_name.find("STARLINK") != -1:
                        low_name=low_name.replace("-", "").replace(" ", "")
                    elif low_name.find("SPACE STATION") == 0:
                        low_name="ISS"
                    pindex = low_name.find(' (')
                    if pindex != -1 and len(low_name)>12:
                        clean_low_name = low_name[:pindex]
                    else:
                        clean_low_name = low_name

            if closest:
                graphics.DrawText(sign.canvas, sign.font57, 1, 7, graphics.Color(20, 200, 20), clean_close_name[:12])
                if len(clean_close_name)>12:
                    for x in range(61,63):
                        sign.canvas.SetPixel(x, 6, 100, 100, 100)
                graphics.DrawText(sign.canvas, sign.font57, 0, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%b"))
                graphics.DrawText(sign.canvas, sign.font57, 16, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%d"))
                graphics.DrawText(sign.canvas, sign.font57, 29, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%Y"))
                
                sign.canvas.SetPixel(26, 14, 200, 10, 10)
                sign.canvas.SetPixel(25, 15, 200, 10, 10)

                flag = get_flag(closest,satellite_data)
                w, _ = flag.size
                sign.canvas.SetImage(flag, round(55.5-w/2), 8)

                graphics.DrawText(sign.canvas, sign.font57, 1, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if closest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(closest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(closest["dist"]))
                
                graphics.DrawText(sign.canvas, sign.font57, 22, 24, graphics.Color(20, 160, 60), "Dir:")
                close_dir = utilities.direction_lookup((closest["satlat"],closest["satlng"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                if len(close_dir)==1:
                    graphics.DrawText(sign.canvas, sign.font57, 27, 32, graphics.Color(20, 160, 60), close_dir)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 25, 32, graphics.Color(20, 160, 60), close_dir)

                graphics.DrawText(sign.canvas, sign.font57, 43, 24, graphics.Color(160, 160, 200), "Alt:")
                if dupeflag:
                    for x in range(43,57):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                close_alt = closest["satalt"]*utilities.KM_2_MI
                if close_alt < 10000:
                    graphics.DrawText(sign.canvas, sign.font57, 43, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(close_alt))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 43, 32, graphics.Color(160, 160, 200), str(round(close_alt/1000))+"k")

            #divider
            for y in range(32):
                sign.canvas.SetPixel(63, y, 0, 0, 100)

            if lowest:
                graphics.DrawText(sign.canvas, sign.font57, 66, 7, graphics.Color(20, 200, 20), clean_low_name[:12])
                if len(clean_low_name)>12:
                    for x in range(126,128):
                        sign.canvas.SetPixel(x, 6, 100, 100, 100)
                graphics.DrawText(sign.canvas, sign.font57, 65, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%b"))
                graphics.DrawText(sign.canvas, sign.font57, 81, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%d"))
                graphics.DrawText(sign.canvas, sign.font57, 94, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%Y"))

                sign.canvas.SetPixel(91, 14, 200, 10, 10)
                sign.canvas.SetPixel(90, 15, 200, 10, 10)

                flag = get_flag(lowest,satellite_data)
                w, _ = flag.size
                sign.canvas.SetImage(flag, round(120.5-w/2), 8)

                graphics.DrawText(sign.canvas, sign.font57, 66, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if lowest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(lowest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(lowest["dist"]))

                graphics.DrawText(sign.canvas, sign.font57, 87, 24, graphics.Color(20, 160, 60), "Dir:")
                low_dir = utilities.direction_lookup((lowest["satlat"],lowest["satlng"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                if len(low_dir)==1:
                    graphics.DrawText(sign.canvas, sign.font57, 92, 32, graphics.Color(20, 160, 60), low_dir)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 90, 32, graphics.Color(20, 160, 60), low_dir)

                graphics.DrawText(sign.canvas, sign.font57, 108, 24, graphics.Color(160, 160, 200), "Alt:")
                if not dupeflag:
                    for x in range(108,122):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                low_alt = lowest["satalt"]*utilities.KM_2_MI
                if low_alt < 10000:
                    graphics.DrawText(sign.canvas, sign.font57, 108, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(low_alt))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 108, 32, graphics.Color(160, 160, 200), str(round(low_alt/1000))+"k")

        #ISS data
        else:

            if iss_polltime==None or time.perf_counter()-iss_polltime>270:
                
                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    response = s.get(satsite+f'/positions/25544/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/{elevation}/300/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                if response.status_code == requests.codes.ok:
                    iss_polltime = time.perf_counter()
                    data = response.json()

                    iss_pos = data["positions"]

            if iss_flyby_polltime==None or time.perf_counter()-iss_flyby_polltime>86400:
                iss_flyby = None
                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    iss_response = s.get(satsite+f'/visualpasses/25544/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/{elevation}/10/180/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                if iss_response.status_code == requests.codes.ok:
                    iss_flyby_polltime = time.perf_counter()
                    iss_data = iss_response.json()

                    if iss_data["info"]["passescount"]>0:
                        iss_flyby = iss_data["passes"]
            
            overhead_flag = 0
            now = time.time()
            if iss_flyby:
                for flyby in iss_flyby:
                    if flyby["startUTC"]<=now and now<flyby["endUTC"]:
                        overhead_flag = 1
                        break
                    if flyby["startUTC"]>now:
                        break

            if iss_pos:
                for pos in iss_pos:
                    if pos["timestamp"]>now:
                        break

                if pos:
                    if geotime == None or time.perf_counter()-geotime>60:
                        geotime = time.perf_counter()
                        reverse_geocode = requests.get(f"https://maps.googleapis.com/maps/api/geocode/json?latlng={pos['satlatitude']},{pos['satlongitude']}&result_type=country|administrative_area_level_1|natural_feature&key={shared_config.CONF['GOOGLEMAPS_API_KEY']}").json()
                
                        if len(reverse_geocode['results']) != 0:
                            formatted_address = reverse_geocode['results'][0]['formatted_address']
                            full_country_name = None
                            country = None
                            comps = reverse_geocode['results'][0]['address_components']
                            for c in comps:
                                if "country" in c["types"]:
                                    country = c
                                    break
                            if country != None:
                                full_country_name = c["long_name"]

                            if len(formatted_address)>17:
                                formatted_address = shorten_name(formatted_address)

                            if len(formatted_address)>17:
                                formatted_address = full_country_name
                                if len(formatted_address)>17:
                                    formatted_address = shorten_name(formatted_address)

                        else:
                            formatted_address = 'Ocean'

                    iss_dist = utilities.get_distance((pos["satlatitude"],pos["satlongitude"]),(float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                    iss_alt = pos["sataltitude"]*utilities.KM_2_MI
                    iss_vel = math.sqrt(398600/(6371.009+pos["sataltitude"]))*utilities.KM_2_MI
                    iss_dir = utilities.direction_lookup((pos["satlatitude"],pos["satlongitude"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))

            else: 
                formatted_address = 'Somewhere'
                iss_dist = None
                iss_alt = None
                iss_vel = None
                iss_dir = None

            sign.canvas.SetImage(iss_image, 99, 11)

            for s in stars:
                s.draw()

            image = None
            if country:
                if formatted_address.find("Ocean") != -1:
                    image = Image.open(f'{shared_config.icons_dir}/flags/OCEAN.png').convert('RGBA')
                else:

                    if full_country_name == "United States":
                        state = None
                        comps = reverse_geocode['results'][0]['address_components']
                        for c in comps:
                            if "administrative_area_level_1" in c["types"]:
                                state = c
                                break
                        if state != None:
                            state_code = c["short_name"]

                        if state:
                            try:
                                image = Image.open(f'{shared_config.icons_dir}/flags/states/{state_code}.png').convert('RGBA')
                            except Exception:
                                image = Image.open(f'{shared_config.icons_dir}/flags/USA.png').convert('RGBA')
                        else:
                            image = Image.open(f'{shared_config.icons_dir}/flags/USA.png').convert('RGBA')
                    else:
                        try:
                            image = Image.open(f'{shared_config.icons_dir}/flags/{get_country_code(full_country_name,"2000-01-01")}.png').convert('RGBA')
                            image = utilities.fix_black(image)
                        except Exception:
                            pass
            elif formatted_address.find("Ocean") != -1 or formatted_address.find("Gulf") != -1 or formatted_address.find("Sea") != -1 or formatted_address.find("River") != -1 or formatted_address.find("Bay") != -1 or formatted_address.find("Lake") != -1:
                    image = Image.open(f'{shared_config.icons_dir}/flags/OCEAN.png').convert('RGBA')
                    
            if image:

                w, h = image.size

                if round(10*w/h)<15:
                    image = image.resize((round(10*w/h), 10), Image.BICUBIC)
                else:
                    image = image.resize((15, 10), Image.BICUBIC)

                w, _ = image.size

                sign.canvas.SetImage(image.convert('RGB'), 128-w, 0)

            for x in range(25):
                for y in range(11):
                    sign.canvas.SetPixel(x, y, 5, 5, 5)
            
            for x in range(25):
                sign.canvas.SetPixel(x, 10, 25, 25, 25)
            for y in range(11):
                sign.canvas.SetPixel(25, y, 25, 25, 25)

            graphics.DrawText(sign.canvas, sign.fontreallybig, -1, 10, graphics.Color(20, 20, 200), "I")
            graphics.DrawText(sign.canvas, sign.fontreallybig, 7, 10, graphics.Color(20, 20, 200), "SS")

            formatted_address=formatted_address[:17]
            graphics.DrawText(sign.canvas, sign.font57, max(27,round(68-len(formatted_address)*2.5)), 8, graphics.Color(200, 10, 10), formatted_address)

            graphics.DrawText(sign.canvas, sign.font57, 1, 18, graphics.Color(60, 60, 160), "Dst:")
            if iss_dist<100:
                graphics.DrawText(sign.canvas, sign.font57, 21, 18, graphics.Color(60, 60, 160), "{0:.1f}".format(iss_dist))
            elif iss_dist>=10000:
                graphics.DrawText(sign.canvas, sign.font57, 21, 18, graphics.Color(60, 60, 160), str(round(iss_dist/1000))+"k")
            else:
                graphics.DrawText(sign.canvas, sign.font57, 21, 18, graphics.Color(60, 60, 160), "{0:.0f}".format(iss_dist))

            graphics.DrawText(sign.canvas, sign.font57, 1, 25, graphics.Color(20, 160, 60), "Vel:")
            graphics.DrawText(sign.canvas, sign.font57, 21, 25, graphics.Color(20, 160, 60), "{0:.2f}".format(iss_vel))

            graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(160, 160, 200), "Alt:")
            graphics.DrawText(sign.canvas, sign.font57, 21, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(iss_alt))

            if iss_flyby:
                s = round(flyby["startUTC"]-now)
                hours = s // 3600 
                s = s - (hours * 3600)
                minutes = s // 60
                seconds = s - (minutes * 60)
                flyby_time = "{:02}:{:02}:{:02}".format(int(hours),int(minutes),int(seconds))
                if overhead_flag:
                    graphics.DrawText(sign.canvas, sign.font57, 49, 16, graphics.Color(246, 242, 116), "Overhead")
                elif int(hours)>=48:
                    days = hours//24
                    text = str(days)+" Days"
                    graphics.DrawText(sign.canvas, sign.font57, 69-round(len(text)*2.5), 16, graphics.Color(246, 242, 116), text)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 49, 16, graphics.Color(246, 242, 116), flyby_time)
                
                startdir = flyby["startAzCompass"]
                maxdir = flyby["maxAzCompass"]
                enddir = flyby["endAzCompass"]

                #graphics.DrawText(sign.canvas, sign.font57, 55, 24, graphics.Color(220, 180, 90), "El:")
                #graphics.DrawText(sign.canvas, sign.font57, 71, 24, graphics.Color(220, 180, 90), "{0:.0f}".format(flyby["maxEl"]))
                graphics.DrawText(sign.canvas, sign.font57, 64, 24, graphics.Color(220, 180, 90), "°")
                graphics.DrawText(sign.canvas, sign.font57, 55, 24, graphics.Color(220, 180, 90), "{0:.0f}".format(flyby["maxEl"]))
                graphics.DrawText(sign.canvas, sign.font57, 70, 24, graphics.Color(220,180,90), f'{maxdir}')
                

                #for x in range(82,84):
                #    for y in range(18,20):
                #        sign.canvas.SetPixel(x, y, 220, 180, 90)

                mx = 88
                my = 21
                mag = flyby["mag"]
                
                b0 = -70*mag+80
                b1 = -60*mag
                b11 = -40*mag-40
                b2 = -20*mag-40

                if b0<0:
                    b0=0
                elif b0>255:
                    b0=255
                
                if b1<0:
                    b1=0
                elif b1>255:
                    b1=255

                if b11<0:
                    b11=0
                elif b11>255:
                    b11=255

                if b2<0:
                    b2=0
                elif b2>255:
                    b2=255

                sign.canvas.SetPixel(mx, my-1, b1, b1, b1)
                sign.canvas.SetPixel(mx-1, my, b1, b1, b1)
                sign.canvas.SetPixel(mx, my, b0, b0, b0)
                sign.canvas.SetPixel(mx+1, my, b1, b1, b1)
                sign.canvas.SetPixel(mx, my+1, b1, b1, b1)
                sign.canvas.SetPixel(mx, my-2, b2, b2, b2)
                sign.canvas.SetPixel(mx-2, my, b2, b2, b2)
                sign.canvas.SetPixel(mx+2, my, b2, b2, b2)
                sign.canvas.SetPixel(mx, my+2, b2, b2, b2)
                sign.canvas.SetPixel(mx+1, my+1, b11, b11, b11)
                sign.canvas.SetPixel(mx-1, my-1, b11, b11, b11)
                sign.canvas.SetPixel(mx-1, my+1, b11, b11, b11)
                sign.canvas.SetPixel(mx+1, my-1, b11, b11, b11)


                if overhead_flag:
                    graphics.DrawText(sign.canvas, sign.font57, 47-(len(startdir)-1)*5, 32, graphics.Color(246, 242, 116), startdir)
                    graphics.DrawText(sign.canvas, sign.font57, 85, 32, graphics.Color(246, 242, 116), enddir)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 47-(len(startdir)-1)*5, 32, graphics.Color(142, 140, 68), startdir)
                    graphics.DrawText(sign.canvas, sign.font57, 85, 32, graphics.Color(142, 140, 68), enddir)


                left_bar = 52
                right_bar = 83
                line_y = 28

                if overhead_flag:
                    val = 255
                else:
                    val = 153
                
                for y in range(line_y-2, line_y+3):
                    sign.canvas.SetPixel(left_bar, y, val, val, val)
                    sign.canvas.SetPixel(right_bar, y, val, val, val)
                for x in range(left_bar+1,right_bar):
                    sign.canvas.SetPixel(x, line_y, val, val, val)
                

                if overhead_flag:
                    blip_loc = left_bar+round((right_bar-left_bar)*(now-flyby["startUTC"])/(flyby["endUTC"]-flyby["startUTC"]))
                    if blip_count == 0:
                        sign.canvas.SetPixel(blip_loc, line_y, 255, 0, 0)
                    elif blip_count == 1:
                        for x in range(blip_loc - 1, blip_loc + 2):
                            for y in range(line_y - 1, line_y + 2):
                                sign.canvas.SetPixel(x, y, 255, 0, 0)
                        sign.canvas.SetPixel(blip_loc, line_y, 255, 255, 255)
                    elif blip_count == 2:
                        sign.canvas.SetPixel(blip_loc, line_y, 255, 0, 0)
                    blip_count += 1
                    if blip_count == 3:
                        blip_count = 0
            else:
                graphics.DrawText(sign.canvas, sign.font57, 46, 18, graphics.Color(246, 242, 116), "Next Flyby")
                graphics.DrawText(sign.canvas, sign.font57, 51, 26, graphics.Color(246, 242, 116), "10+ Days")
                    
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        
        breakout = sign.wait_loop(0.5)

        if breakout:
            return

        

        
