import time
from datetime import datetime
import random
import requests
import shared_config
from utilities import *
from rgbmatrix import graphics
import country_converter as coco

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
    
    drawtime = None
    
    while True:

        if drawtime==None or time.perf_counter()-drawtime>30:
            
            response = requests.get(satsite+f'/above/{shared_config.CONF["SENSOR_LAT"]}/{shared_config.CONF["SENSOR_LON"]}/0/45/0/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI')
            #/positions/{id}/{observer_lat}/{observer_lng}/{observer_alt}/{seconds}/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI
            #/above/{observer_lat}/{observer_lng}/{observer_alt}/{search_radius}/{category_id}/&apiKey=89PNJ8-5FCFDN-TEKWUN-4SYI
            #/visualpasses/{id}/{observer_lat}/{observer_lng}/{observer_alt}/{days}/{min_visibility} 


            if response.status_code == requests.codes.ok:
                data = response.json()
                above = data["above"]
                
                above = list(map(lambda item: dict(item, dist=get_distance((item["satlat"],item["satlng"]),(float(shared_config.CONF["SENSOR_LAT"]),float(shared_config.CONF["SENSOR_LON"]))), vel=math.sqrt(398600/(6371.009+item["satalt"]))), above))

                #remove debris from results
                above = list(filter(lambda x: " DEB" not in x["satname"] and " R/B" not in x["satname"], above))

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
                    low_name=low_name.replace("-", "")
                pindex = low_name.find(' (')
                if pindex != -1 and len(low_name)>12:
                    clean_low_name = low_name[:pindex]
                else:
                    clean_low_name = low_name

                #closest
                graphics.DrawText(sign.canvas, sign.font57, 1, 7, graphics.Color(20, 200, 20), clean_close_name[:12])
                if len(clean_close_name)>12:
                    for x in range(61,63):
                        sign.canvas.SetPixel(x, 6, 100, 100, 100)
                graphics.DrawText(sign.canvas, sign.font57, 0, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%b"))
                graphics.DrawText(sign.canvas, sign.font57, 16, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%d"))
                graphics.DrawText(sign.canvas, sign.font57, 29, 15, graphics.Color(200, 10, 10), datetime.strptime(closest["launchDate"], "%Y-%m-%d").strftime("%Y"))
                
                sign.canvas.SetPixel(26, 14, 200, 10, 10)
                sign.canvas.SetPixel(25, 15, 200, 10, 10)

                image = Image.new("RGBA", (13,9), (0, 0, 0, 255))
                        
                if satellite_data:
                    sat = [d for d in satellite_data if d["NORAD"] == closest["satid"]]
                    if len(sat)==0:
                        sat = [d for d in satellite_data if d["COSPAR"] == closest["intDesignator"]]
                    if len(sat)>0:
                        try:
                            if sat[0]["country"].upper()=="MULTINATIONAL":
                                image = Image.open('/home/pi/PlaneSign/icons/flags/MULTINATIONAL.png').convert('RGBA')
                            else:
                                image = Image.open(f'/home/pi/PlaneSign/icons/flags/{coco.convert(names=sat[0]["country"], to="ISO3", not_found=None)}.png').convert('RGBA')
                        except Exception:
                            pass
                    elif close_name.find("COSMOS") == 0  or close_name.find("MOLNIYA") == 0:
                        image = Image.open('/home/pi/PlaneSign/icons/flags/USR.png').convert('RGBA')
                    elif close_name.find("USA") == 0:
                        image = Image.open('/home/pi/PlaneSign/icons/flags/USA.png').convert('RGBA')
                    
                    image = image.resize((13, 9), Image.BICUBIC)
                    sign.canvas.SetImage(image.convert('RGB'), 49, 8)

                graphics.DrawText(sign.canvas, sign.font57, 1, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if closest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(closest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 1, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(closest["dist"]))
                
                graphics.DrawText(sign.canvas, sign.font57, 23, 24, graphics.Color(160, 160, 200), "Alt:")
                if dupeflag:
                    for x in range(23,37):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                close_alt = closest["satalt"]*KM_2_MI
                if close_alt < 10000:
                    graphics.DrawText(sign.canvas, sign.font57, 23, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(close_alt))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 23, 32, graphics.Color(160, 160, 200), str(round(close_alt/1000))+"k")

                graphics.DrawText(sign.canvas, sign.font57, 44, 24, graphics.Color(20, 160, 60), "Vel:")
                graphics.DrawText(sign.canvas, sign.font57, 44, 32, graphics.Color(20, 160, 60), "{0:.1f}".format(closest["vel"]*KM_2_MI))
                
                # close_vel = closest["vel"]*KM_2_MI*3600
                # if close_vel < 10000:
                #     graphics.DrawText(sign.canvas, sign.font57, 44, 31, graphics.Color(20, 160, 60), "{0:.0f}".format(close_vel))
                # else:
                #     graphics.DrawText(sign.canvas, sign.font57, 44, 31, graphics.Color(20, 160, 60), str(round(close_vel/1000))+"k")

                #divider
                for y in range(32):
                    sign.canvas.SetPixel(63, y, 0, 0, 100)

                #lowest
                graphics.DrawText(sign.canvas, sign.font57, 66, 7, graphics.Color(20, 200, 20), clean_low_name[:12])
                if len(clean_low_name)>12:
                    for x in range(126,128):
                        sign.canvas.SetPixel(x, 6, 100, 100, 100)
                graphics.DrawText(sign.canvas, sign.font57, 65, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%b"))
                graphics.DrawText(sign.canvas, sign.font57, 81, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%d"))
                graphics.DrawText(sign.canvas, sign.font57, 94, 15, graphics.Color(200, 10, 10), datetime.strptime(lowest["launchDate"], "%Y-%m-%d").strftime("%Y"))

                sign.canvas.SetPixel(91, 14, 200, 10, 10)
                sign.canvas.SetPixel(90, 15, 200, 10, 10)

                image = Image.new("RGBA", (13,9), (0, 0, 0, 255))
                        
                if satellite_data:
                    sat = [d for d in satellite_data if d["NORAD"] == lowest["satid"]]
                    if len(sat)==0:
                        sat = [d for d in satellite_data if d["COSPAR"] == lowest["intDesignator"]]
                    if len(sat)>0:
                        try:
                            if sat[0]["country"].upper()=="MULTINATIONAL":
                                image = Image.open('/home/pi/PlaneSign/icons/flags/MULTINATIONAL.png').convert('RGBA')
                            else:
                                image = Image.open(f'/home/pi/PlaneSign/icons/flags/{coco.convert(names=sat[0]["country"], to="ISO3", not_found=None)}.png').convert('RGBA')
                        except Exception:
                            pass
                    elif low_name.find("COSMOS") == 0 or low_name.find("MOLNIYA") == 0:
                        image = Image.open('/home/pi/PlaneSign/icons/flags/USR.png').convert('RGBA')
                    elif low_name.find("USA") == 0:
                        image = Image.open('/home/pi/PlaneSign/icons/flags/USA.png').convert('RGBA')
                    
                    image = image.resize((13, 9), Image.BICUBIC)
                    sign.canvas.SetImage(image.convert('RGB'), 114, 8)

                graphics.DrawText(sign.canvas, sign.font57, 66, 24, graphics.Color(60, 60, 160), "Dst:")
                for x in range(1,15):
                    sign.canvas.SetPixel(x, 24, 110, 90, 0)
                if lowest["dist"]<100:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.1f}".format(lowest["dist"]))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 66, 32, graphics.Color(60, 60, 160), "{0:.0f}".format(lowest["dist"]))

                graphics.DrawText(sign.canvas, sign.font57, 88, 24, graphics.Color(160, 160, 200), "Alt:")
                if dupeflag:
                    for x in range(89,102):
                        sign.canvas.SetPixel(x, 24, 110, 90, 0)
                low_alt = lowest["satalt"]*KM_2_MI
                if low_alt < 10000:
                    graphics.DrawText(sign.canvas, sign.font57, 88, 32, graphics.Color(160, 160, 200), "{0:.0f}".format(low_alt))
                else:
                    graphics.DrawText(sign.canvas, sign.font57, 88, 32, graphics.Color(160, 160, 200), str(round(low_alt/1000))+"k")

                graphics.DrawText(sign.canvas, sign.font57, 109, 24, graphics.Color(20, 160, 60), "Vel:")
                graphics.DrawText(sign.canvas, sign.font57, 109, 32, graphics.Color(20, 160, 60), "{0:.1f}".format(lowest["vel"]*KM_2_MI))

                # low_vel = lowest["vel"]*KM_2_MI*3600
                # if low_vel < 10000:
                #     graphics.DrawText(sign.canvas, sign.font57, 109, 31, graphics.Color(20, 160, 60), "{0:.0f}".format(low_vel))
                # else:
                #     graphics.DrawText(sign.canvas, sign.font57, 109, 31, graphics.Color(20, 160, 60), str(round(low_vel/1000))+"k")

                sign.matrix.SwapOnVSync(sign.canvas)
                sign.canvas = sign.matrix.CreateFrameCanvas()

            drawtime = time.perf_counter()


        breakout = sign.wait_loop(0.1)

        if breakout:
            return
