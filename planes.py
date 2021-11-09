import logging
import shared_config
import time
import requests
from rgbmatrix import graphics
from utilities import *


def show_planes(sign):

    prev_thing = {}
    prev_thing["distance"] = 0
    prev_thing["altitude"] = 0
    prev_thing["speed"] = 0
    prev_thing["flight"] = None

    plane_to_show = None

    while shared_config.shared_mode.value >= 1 and shared_config.shared_mode.value <= 5:

        if shared_config.shared_mode.value == 1:
            if shared_config.data_dict["closest"] and shared_config.data_dict["closest"]["distance"] <= 2:
                plane_to_show = shared_config.data_dict["closest"]
            else:
                plane_to_show = None

        if shared_config.shared_mode.value == 2:
            plane_to_show = shared_config.data_dict["closest"]

        if shared_config.shared_mode.value == 3:
            plane_to_show = shared_config.data_dict["highest"]

        if shared_config.shared_mode.value == 4:
            plane_to_show = shared_config.data_dict["fastest"]

        if shared_config.shared_mode.value == 5:
            plane_to_show = shared_config.data_dict["slowest"]

        if plane_to_show:
            interpol_distance = interpolate(prev_thing["distance"], plane_to_show["distance"])
            interpol_alt = interpolate(prev_thing["altitude"], plane_to_show["altitude"])
            interpol_speed = interpolate(prev_thing["speed"], plane_to_show["speed"])

            # We only have room to display one full airport name. So pick the one that is further away assuming
            # the user probably hasn't heard of that one
            origin_distance = 0
            if plane_to_show["origin"]:
                origin_config = shared_config.code_to_airport.get(plane_to_show["origin"])
                if origin_config:
                    origin_distance = get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (origin_config[1], origin_config[2]))
                    logging.info(f"Origin is {origin_distance:.2f} miles away")

            destination_distance = 0
            if plane_to_show["destination"]:
                destination_config = shared_config.code_to_airport.get(plane_to_show["destination"])
                if destination_config:
                    destination_distance = get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (destination_config[1], destination_config[2]))
                    logging.info(f"Destination is {destination_distance:.2f} miles away")

            if origin_distance != 0 and origin_distance > destination_distance:
                friendly_name = origin_config[0]
            elif destination_distance != 0:
                friendly_name = destination_config[0]
            else:
                friendly_name = ""

            logging.info("Full airport name from code: " + friendly_name)

            # Front pad the flight number to a max of 7 for spacing
            formatted_flight = plane_to_show["flight"].rjust(7, ' ')

            if not plane_to_show["origin"]:
                plane_to_show["origin"] = "???"

            if not plane_to_show["destination"]:
                plane_to_show["destination"] = "???"

            for i in range(NUM_STEPS):
                sign.canvas.Clear()
                graphics.DrawText(sign.canvas, sign.fontreallybig, 1, 12, graphics.Color(20, 200, 20), plane_to_show["origin"] + "->" + plane_to_show["destination"])
                graphics.DrawText(sign.canvas, sign.font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
                graphics.DrawText(sign.canvas, sign.font57, 37, 30, graphics.Color(0, 0, 200), formatted_flight)
                graphics.DrawText(sign.canvas, sign.font57, 2, 30, graphics.Color(180, 180, 180), plane_to_show["typecode"])

                graphics.DrawText(sign.canvas, sign.font57, 79, 8, graphics.Color(60, 60, 160), "Dst: {0:.1f}".format(interpol_distance[i]))
                graphics.DrawText(sign.canvas, sign.font57, 79, 19, graphics.Color(160, 160, 200), "Alt: {0:.0f}".format(interpol_alt[i]))
                graphics.DrawText(sign.canvas, sign.font57, 79, 30, graphics.Color(20, 160, 60), "Vel: {0:.0f}".format(interpol_speed[i]))

                forced_breakout = sign.wait_loop(0.065)
                if forced_breakout:
                    break

                sign.matrix.SwapOnVSync(sign.canvas)

            prev_thing = plane_to_show
        else:
            # NOT ALERT RADIUS
            prev_thing = {}
            prev_thing["distance"] = 0
            prev_thing["altitude"] = 0
            prev_thing["speed"] = 0

            sign.show_time()


def track_a_flight(sign):

    if "track_a_flight_num" not in shared_config.data_dict:
        sign.canvas.Clear()
        sign.matrix.SwapOnVSync(sign.canvas)
        return

    requests_limiter = 0
    blip_count = 0

    while shared_config.shared_mode.value == 99:

        flight_num_to_track = shared_config.data_dict["track_a_flight_num"]

        if (requests_limiter % 50 == 0):
            parse_this_to_get_hex = requests.get(f"https://www.flightradar24.com/v1/search/web/find?query={flight_num_to_track}&limit=10").json()

            live_flight_info = first(parse_this_to_get_hex["results"], lambda x: x["type"] == "live")

            logging.info(live_flight_info)

            flight_data = requests.get(f"https://data-live.flightradar24.com/clickhandler/?version=1.5&flight={live_flight_info['id']}").json()
            current_location = flight_data['trail'][0]
            reverse_geocode = requests.get(
                f"https://maps.googleapis.com/maps/api/geocode/json?latlng={current_location['lat']},{current_location['lng']}&result_type=country|administrative_area_level_1|natural_feature&key=AIzaSyD65DETlTi-o5ymfcSp2Gl8JxBS7fwOl5g").json()

            if len(reverse_geocode['results']) != 0:
                formatted_address = reverse_geocode['results'][0]['formatted_address']
            else:
                formatted_address = 'Somewhere'

            logging.info(current_location)
            logging.info(formatted_address)

        requests_limiter = requests_limiter + 1

        sign.canvas.Clear()

        flight_number_header = f"- {flight_data['identification']['callsign']} -"

        graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, flight_number_header), 6, graphics.Color(200, 10, 10), flight_number_header)

        graphics.DrawText(sign.canvas, sign.fontreallybig, 1, 14, graphics.Color(20, 200, 20), flight_data['airport']['origin']['code']['iata'])
        graphics.DrawText(sign.canvas, sign.fontreallybig, 100, 14, graphics.Color(20, 200, 20), flight_data['airport']['destination']['code']['iata'])

        scheduled_start_time = flight_data['time']['scheduled']['departure']
        real_start_time = flight_data['time']['real']['departure']
        estimated_start_time = flight_data['time']['estimated']['departure']

        scheduled_end_time = flight_data['time']['scheduled']['arrival']
        real_end_time = flight_data['time']['real']['arrival']
        estimated_end_time = flight_data['time']['estimated']['arrival']

        if real_start_time is not None:
            start_time = real_start_time
        elif estimated_start_time is not None:
            start_time = estimated_start_time
        else:
            start_time = scheduled_start_time

        if real_end_time is not None:
            end_time = real_end_time
        elif estimated_end_time is not None:
            end_time = estimated_end_time
        else:
            end_time = scheduled_end_time

        # current progress divided by total
        current_time = int(time.time())
        duration = end_time - start_time
        current_progress = current_time - start_time

        percent_complete = current_progress / duration

        line_x_start = 30
        line_x_end = 98
        line_y = 9

        line_distance = line_x_end - line_x_start

        for x in range(line_x_start, line_x_end):
            sign.canvas.SetPixel(x, line_y, 120, 120, 120)

        # Left Bar
        for y in range(line_y - 2, line_y + 3):
            sign.canvas.SetPixel(line_x_start, y, 255, 255, 255)

        # Right Bar
        for y in range(line_y - 2, line_y + 3):
            sign.canvas.SetPixel(line_x_end, y, 255, 255, 255)

        progress_box_start_offset = int(line_distance * percent_complete) + line_x_start

        if blip_count == 0:
            sign.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)
        elif blip_count == 1:
            for x in range(progress_box_start_offset - 1, progress_box_start_offset + 2):
                for y in range(line_y - 1, line_y + 2):
                    sign.canvas.SetPixel(x, y, 255, 0, 0)

            sign.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)
        elif blip_count == 2:
            sign.canvas.SetPixel(progress_box_start_offset, line_y, 255, 255, 255)

        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            graphics.DrawText(sign.canvas, sign.font46, 2, 22, graphics.Color(40, 40, 255), f"{time.strftime('%H:%M%p', time.localtime(start_time))}")
            graphics.DrawText(sign.canvas, sign.font46, 99, 22, graphics.Color(40, 40, 255), f"{time.strftime('%H:%M%p', time.localtime(end_time))}")
        else:
            graphics.DrawText(sign.canvas, sign.font46, 2, 22, graphics.Color(40, 40, 255), f"{time.strftime('%I:%M%p', time.localtime(start_time))}")
            graphics.DrawText(sign.canvas, sign.font46, 99, 22, graphics.Color(40, 40, 255), f"{time.strftime('%I:%M%p', time.localtime(end_time))}")

        #graphics.DrawText(sign.canvas, sign.font46, 31, 17, graphics.Color(200, 200, 10), flight_data['aircraft']['model']['text'])

        graphics.DrawText(sign.canvas, sign.font46, 32, 19, graphics.Color(160, 160, 200), f"Alt:{current_location['alt']}")
        graphics.DrawText(sign.canvas, sign.font46, 70, 19, graphics.Color(20, 160, 60), f"Spd:{current_location['spd']}")

        graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, formatted_address), 30, graphics.Color(246, 242, 116), formatted_address)

        sign.matrix.SwapOnVSync(sign.canvas)

        blip_count = blip_count + 1
        if blip_count == 3:
            blip_count = 0

        sign.wait_loop(0.8)
