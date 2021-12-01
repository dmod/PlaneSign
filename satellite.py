import time
from datetime import datetime, timedelta
import random
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import shared_config
from utilities import *
from rgbmatrix import graphics
import country_converter as coco
import numpy as np
from __main__ import planesign_mode_handler


def fix_black(image):
    #brighten black
    rgb = np.array(image.convert('RGB'))
    mask = (rgb[:,:,0] < 30) & (rgb[:,:,1] < 30) & (rgb[:,:,2] < 30)
    rgb[mask] = np.true_divide(rgb[mask],2.0)+[15,15,15]
    image = Image.fromarray(rgb)    

    return image

def shorten_name(name):
    name = name.replace("French Southern and Antarctic Lands","French S. Lands")
    name = name.replace("Northern", "N.").replace("North", "N.")
    name = name.replace("Southern", "S.").replace("South", "S.")
    name = name.replace("Eastern", "E.").replace("East", "E.")
    name = name.replace("Western", "W.").replace("West", "W.")
    name = name.replace("Federated States of ", "").replace("State of ", "").replace(", USA", "")
    name = name.replace("Province", "Prov.").replace("Democratic Republic of", "D.R.")
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


def get_country_code(rawname):

    rawname = rawname.upper()

    if rawname=="MULTINATIONAL":
        name = "UN"
    elif rawname=="ESA":
        name = "EU"
    else:
        try:
            name = coco.convert(names=rawname, to="ISO3", not_found=None)
        except Exception:
            name = rawname
        
    return name

def get_flag(selected,satellite_data):
    
    image = None
    if satellite_data:
        sat_name = selected["satname"]
        sat = [d for d in satellite_data if d["NORAD"] == selected["satid"]]
        if len(sat)==0:
            sat = [d for d in satellite_data if d["COSPAR"] == selected["intDesignator"]]
        if len(sat)>0:

            if sat[0]["country"].find("/") != -1:

                countries = sat[0]["country"].split("/")
                llmask = Image.open("/home/pi/PlaneSign/icons/flags/MASK_LL.png").convert('RGBA')
                cmask = Image.open("/home/pi/PlaneSign/icons/flags/MASK_C.png").convert('RGBA')

                if len(countries)==2:
                    
                    try:
                        image = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(countries[1])}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                        foreground = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(countries[0])}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                        image.paste(foreground, (0, 0), llmask)

                    except Exception:
                        pass

                elif len(countries)==3:

                    try:
                        image = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(countries[2])}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                        foreground = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(countries[1])}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')
                        center =  Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(countries[0])}.png').convert('RGBA').resize((13, 9), Image.BICUBIC).convert('RGB')

                        image.paste(foreground, (0, 0), llmask)
                        image.paste(center, (0, 0), cmask)

                    except Exception:
                        pass

                elif len(countries)>3:
                    image = Image.open('/home/pi/PlaneSign/icons/flags/UN.png').convert('RGBA')

            else:
                try:
                    image = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(sat[0]["country"])}.png').convert('RGBA')
                except Exception:
                    pass

        #can't find in static file lookup, apply known cases
        elif sat_name.find("USA") == 0 or sat_name.find("OPS") == 0 or sat_name.find("GALAXY") == 0 or sat_name.find("FLOCK") == 0 or sat_name.find("DOVE ") == 0 or sat_name.find("IRIDIUM") == 0 or sat_name.find("NAVSTAR") == 0 or sat_name.find("EXPLORER") == 0 or sat_name.find("METEOSAT") == 0 or sat_name.find("GLOBALSTAR") == 0 or sat_name.find("ORBCOMM") == 0 or sat_name.find("LANDSAT") == 0 or sat_name.find("COMSTAR") == 0 or sat_name.find("TELSTAR") == 0:
            image = Image.open('/home/pi/PlaneSign/icons/flags/USA.png').convert('RGBA')

        elif sat_name.find("COSMOS") == 0  or sat_name.find("MOLNIYA") == 0 or sat_name.find("METEOR") == 0:
            image = Image.open('/home/pi/PlaneSign/icons/flags/USR.png').convert('RGBA')

        elif sat_name.find("DIADEME") == 0:
            image = Image.open('/home/pi/PlaneSign/icons/flags/FRA.png').convert('RGBA')

        elif sat_name.find("ANIK") == 0:
            image = Image.open('/home/pi/PlaneSign/icons/flags/CAN.png').convert('RGBA')
        
    if image == None:

        image = Image.new("RGB", (13,9), (0, 0, 0))

    else:

        image = fix_black(image)  

        image = image.resize((13, 9), Image.BICUBIC)

    return image

@planesign_mode_handler(17)
def satellites(sign):
    sign.canvas.Clear()

    satellite_data = []
    try:
        with open("/home/pi/PlaneSign/satdat.txt",encoding='windows-1252') as f:
            pass
    except:
        satdaturl = "https://www.ucsusa.org/media/11490"
        file = requests.get(satdaturl, stream=True, allow_redirects=True)
        if file.status_code == requests.codes.ok:
            sat_lines = file.text.splitlines()[1:]
            print(f"Found static data for {len(sat_lines)} satellites")
            with open("/home/pi/PlaneSign/satdat.txt", 'wb') as f:
                f.write(file.content)

    try:
        with open("/home/pi/PlaneSign/satdat.txt",encoding='windows-1252') as f:
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
    except Exception as e:
        print("Can't read static satellite data")
        print(e)

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
    
    iss_image = Image.open('/home/pi/PlaneSign/icons/ISS.png').convert("RGB")

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
    #stars.append(Star(sign, random.randint(28,127), random.randint(0,3), random.randint(50,150), 0))
    #stars.append(Star(sign, random.randint(28,127), random.randint(0,3), random.randint(50,150), 0))
    #stars.append(Star(sign, random.randint(28,127), random.randint(0,3), random.randint(50,150), 0))
    #stars.append(Star(sign, random.randint(100,127), random.randint(0,8), random.randint(50,150), 0))
    #stars.append(Star(sign, random.randint(100,127), random.randint(0,8), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(28,36), random.randint(0,11), random.randint(50,150), 0))

    stars.append(Star(sign, random.randint(112,127), random.randint(0,12), random.randint(50,150), 0))
    stars.append(Star(sign, random.randint(112,127), random.randint(0,12), random.randint(50,150), 0))

    while True:

        if shared_config.shared_satellite_mode.value == 1:

            if polltime==None or time.perf_counter()-polltime>10*multiplier:

                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    response = s.get(satsite+f'/above/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/0/45/0/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                #currently assumes 0 elevation - todo: use google api to get elevation from lat/lon

                if response.status_code == requests.codes.ok:
                    polltime = time.perf_counter()
                    data = response.json()

                    #slow down requests as we approach limit
                    if data["info"]["transactionscount"]>500:
                        multiplier = 1+2*(data["info"]["transactionscount"]-500)/400
                    else:
                        multiplier = 1

                    above = data["above"]
                    
                    above = list(map(lambda item: dict(item, dist=get_distance((item["satlat"],item["satlng"]),(float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))), vel=math.sqrt(398600/(6371.009+item["satalt"]))), above))

                    #remove debris from results
                    above = list(filter(lambda x: " DEB" not in x["satname"] and " R/B" not in x["satname"]and "OBJECT " not in x["satname"], above))

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
                        close_name=close_name.replace("-", "")
                    pindex = close_name.find(' (')
                    if pindex != -1 and len(close_name)>12:
                        clean_close_name = close_name[:pindex]
                    else:
                        clean_close_name = close_name

                    low_name = lowest["satname"]
                    if low_name.find("STARLINK") != -1:
                        low_name=low_name.replace("-", "").replace(" ", "")
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

                sign.canvas.SetImage(get_flag(closest,satellite_data), 49, 8)

                graphics.DrawText(sign.canvas, sign.font57, 1, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if closest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(closest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(closest["dist"]))
                
                graphics.DrawText(sign.canvas, sign.font57, 22, 24, graphics.Color(20, 160, 60), "Dir:")
                close_dir = direction_lookup((closest["satlat"],closest["satlng"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                if len(close_dir)==1:
                    graphics.DrawText(sign.canvas, sign.font57, 27, 32, graphics.Color(20, 160, 60), close_dir)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 25, 32, graphics.Color(20, 160, 60), close_dir)

                graphics.DrawText(sign.canvas, sign.font57, 43, 24, graphics.Color(160, 160, 200), "Alt:")
                if dupeflag:
                    for x in range(43,57):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                close_alt = closest["satalt"]*KM_2_MI
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

                sign.canvas.SetImage(get_flag(lowest,satellite_data), 114, 8)

                graphics.DrawText(sign.canvas, sign.font57, 66, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if lowest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(lowest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(lowest["dist"]))

                graphics.DrawText(sign.canvas, sign.font57, 87, 24, graphics.Color(20, 160, 60), "Dir:")
                low_dir = direction_lookup((lowest["satlat"],lowest["satlng"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                if len(low_dir)==1:
                    graphics.DrawText(sign.canvas, sign.font57, 92, 32, graphics.Color(20, 160, 60), low_dir)
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 90, 32, graphics.Color(20, 160, 60), low_dir)

                graphics.DrawText(sign.canvas, sign.font57, 108, 24, graphics.Color(160, 160, 200), "Alt:")
                if not dupeflag:
                    for x in range(108,122):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                low_alt = lowest["satalt"]*KM_2_MI
                if low_alt < 10000:
                    graphics.DrawText(sign.canvas, sign.font57, 108, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(low_alt))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 108, 32, graphics.Color(160, 160, 200), str(round(low_alt/1000))+"k")

        #ISS data
        else:

            if iss_polltime==None or time.perf_counter()-iss_polltime>270:
                
                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    response = s.get(satsite+f'/positions/25544/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/0/300/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                #currently assumes 0 elevation - todo: use google api to get elevation from lat/lon

                if response.status_code == requests.codes.ok:
                    iss_polltime = time.perf_counter()
                    data = response.json()

                    iss_pos = data["positions"]

            if iss_flyby_polltime==None or time.perf_counter()-iss_flyby_polltime>86400:
                
                with requests.Session() as s:
                    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5, backoff_factor=0.1)))
                    iss_response = s.get(satsite+f'/visualpasses/25544/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/0/5/180/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')

                #currently assumes 0 elevation - todo: use google api to get elevation from lat/lon

                if iss_response.status_code == requests.codes.ok:
                    iss_flyby_polltime = time.perf_counter()
                    iss_data = iss_response.json()

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
                        reverse_geocode = requests.get(f"https://maps.googleapis.com/maps/api/geocode/json?latlng={pos['satlatitude']},{pos['satlongitude']}&result_type=country|administrative_area_level_1|natural_feature&key=AIzaSyD65DETlTi-o5ymfcSp2Gl8JxBS7fwOl5g").json()
                
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

                            # iss_last_loc = formatted_address
                        else:
                            formatted_address = 'Ocean'
                            # if iss_last_loc != None:
                            #     formatted_address = iss_last_loc
                            # else:
                            #     formatted_address = 'Somewhere'

                    iss_dist = get_distance((pos["satlatitude"],pos["satlongitude"]),(float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))
                    iss_alt = pos["sataltitude"]*KM_2_MI
                    iss_vel = math.sqrt(398600/(6371.009+pos["sataltitude"]))*KM_2_MI
                    iss_dir = direction_lookup((pos["satlatitude"],pos["satlongitude"]), (float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"])))

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
                    image = Image.open('/home/pi/PlaneSign/icons/flags/OCEAN.png').convert('RGBA')
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
                                image = Image.open(f'/home/pi/PlaneSign/icons/flags/states/{state_code}.png').convert('RGBA')
                            except Exception:
                                image = Image.open(f'/home/pi/PlaneSign/icons/flags/USA.png').convert('RGBA')
                        else:
                            image = Image.open(f'/home/pi/PlaneSign/icons/flags/USA.png').convert('RGBA')
                    else:
                        try:
                            image = Image.open(f'/home/pi/PlaneSign/icons/flags/{get_country_code(full_country_name)}.png').convert('RGBA')
                            image = fix_black(image)
                        except Exception:
                            pass
            elif formatted_address.find("Ocean") != -1 or formatted_address.find("Gulf") != -1 or formatted_address.find("Sea") != -1 or formatted_address.find("River") != -1 or formatted_address.find("Bay") != -1 or formatted_address.find("Lake") != -1:
                    image = Image.open('/home/pi/PlaneSign/icons/flags/OCEAN.png').convert('RGBA')
                    
            if image:
                sign.canvas.SetImage(image.resize((15, 10), Image.BICUBIC).convert('RGB'), 113, 0)
                # for x in range(113,128):
                #     sign.canvas.SetPixel(x, 10, 25, 25, 25)
                # for y in range(11):
                #     sign.canvas.SetPixel(112, y, 25, 25, 25)

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

            #if len(formatted_address) < 16:
            #    graphics.DrawText(sign.canvas, sign.font57, max(27,round(68-len(formatted_address)*2.5)), 8, graphics.Color(200, 10, 10), formatted_address)
            #else:
            #    graphics.DrawText(sign.canvas, sign.font57, max(27,round(77.5-len(formatted_address)*2.5)), 8, graphics.Color(200, 10, 10), formatted_address)

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


            s = round(flyby["startUTC"]-now)
            hours = s // 3600 
            s = s - (hours * 3600)
            minutes = s // 60
            seconds = s - (minutes * 60)
            flyby_time = "{:02}:{:02}:{:02}".format(int(hours),int(minutes),int(seconds))
            if overhead_flag:
                graphics.DrawText(sign.canvas, sign.font57, 49, 16, graphics.Color(246, 242, 116), "Overhead")
            elif hours>=1000:
                days = s//86400
                graphics.DrawText(sign.canvas, sign.font57, 49, 16, graphics.Color(246, 242, 116), str(days)+" Days")
            else:
                graphics.DrawText(sign.canvas, sign.font57, 49, 16, graphics.Color(246, 242, 116), flyby_time)
            
            graphics.DrawText(sign.canvas, sign.font57, 55, 24, graphics.Color(220, 180, 90), "El:")
            graphics.DrawText(sign.canvas, sign.font57, 71, 24, graphics.Color(220, 180, 90), "{0:.0f}".format(flyby["maxEl"]))

            for x in range(82,84):
                for y in range(18,20):
                    sign.canvas.SetPixel(x, y, 220, 180, 90)

            mx = 88
            my = 21
            mag = flyby["mag"]
            if mag<-4:
                sign.canvas.SetPixel(mx, my-1, 255, 255, 255)
                sign.canvas.SetPixel(mx-1, my, 255, 255, 255)
                sign.canvas.SetPixel(mx, my, 255, 255, 255)
                sign.canvas.SetPixel(mx+1, my, 255, 255, 255)
                sign.canvas.SetPixel(mx, my+1, 255, 255, 255)
                sign.canvas.SetPixel(mx, my-2, 180, 180, 180)
                sign.canvas.SetPixel(mx-2, my, 180, 180, 180)
                sign.canvas.SetPixel(mx+2, my, 180, 180, 180)
                sign.canvas.SetPixel(mx, my+2, 180, 180, 180)
                sign.canvas.SetPixel(mx+1, my+1, 180, 180, 180)
                sign.canvas.SetPixel(mx-1, my-1, 180, 180, 180)
                sign.canvas.SetPixel(mx-1, my+1, 180, 180, 180)
                sign.canvas.SetPixel(mx+1, my-1, 180, 180, 180)
            elif mag<-3:
                sign.canvas.SetPixel(mx, my-1, 200, 200, 200)
                sign.canvas.SetPixel(mx-1, my, 200, 200, 200)
                sign.canvas.SetPixel(mx, my, 255, 255, 255)
                sign.canvas.SetPixel(mx+1, my, 200, 200, 200)
                sign.canvas.SetPixel(mx, my+1, 200, 200, 200)
                sign.canvas.SetPixel(mx+1, my+1, 100, 100, 100)
                sign.canvas.SetPixel(mx-1, my-1, 100, 100, 100)
                sign.canvas.SetPixel(mx-1, my+1, 100, 100, 100)
                sign.canvas.SetPixel(mx+1, my-1, 100, 100, 100)
            elif mag<-2:
                sign.canvas.SetPixel(mx, my-1, 150, 150, 150)
                sign.canvas.SetPixel(mx-1, my, 150, 150, 150)
                sign.canvas.SetPixel(mx, my, 200, 200, 200)
                sign.canvas.SetPixel(mx+1, my, 150, 150, 150)
                sign.canvas.SetPixel(mx, my+1, 150, 150, 150)
            elif mag<-1:
                sign.canvas.SetPixel(mx, my-1, 45, 45, 45)
                sign.canvas.SetPixel(mx-1, my, 45, 45, 45)
                sign.canvas.SetPixel(mx, my, 150, 150, 150)
                sign.canvas.SetPixel(mx+1, my, 45, 45, 45)
                sign.canvas.SetPixel(mx, my+1, 45, 45, 45)
            else:
                sign.canvas.SetPixel(mx, my-1, 5, 5, 5)
                sign.canvas.SetPixel(mx-1, my, 5, 5, 5)
                sign.canvas.SetPixel(mx, my, 50, 50, 50)
                sign.canvas.SetPixel(mx+1, my, 5, 5, 5)
                sign.canvas.SetPixel(mx, my+1, 5, 5, 5)

            startdir = flyby["startAzCompass"]
            enddir = flyby["endAzCompass"]
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
                    sign.canvas.SetPixel(left_bar, line_y, 255, 0, 0)
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
                    

        sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas = sign.matrix.CreateFrameCanvas()   

        breakout = sign.wait_loop(0.5)

        if breakout:
            return
