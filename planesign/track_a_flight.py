import logging
import shared_config
import time
import requests
from rgbmatrix import graphics
from FlightRadar24.api import FlightRadar24API, Flight
import utilities
import __main__
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from modes import DisplayMode

@__main__.planesign_mode_handler(DisplayMode.TRACK_A_FLIGHT)
def track_a_flight(sign):
    # Check if Google Maps API key is configured
    if not shared_config.CONF.get("GOOGLEMAPS_API_KEY"):
        logging.error("Google Maps API key is not configured. Location names will not be available.")
        formatted_address = "No API key"
    
    if "track_a_flight_num" not in shared_config.data_dict:
        sign.canvas.Clear()
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        return sign.wait_loop(-1)

    requests_limiter = 0
    blip_count = 0

    while shared_config.shared_mode.value == DisplayMode.TRACK_A_FLIGHT.value:

        flight_num_hex = shared_config.data_dict["track_a_flight_num"]

        if (requests_limiter % 50 == 0):
                
            flightdatareq = requests.get(f"https://data-live.flightradar24.com/clickhandler/?version=1.5&flight={flight_num_hex}")
            if flightdatareq and flightdatareq.status_code == requests.codes.ok:
                flight_data = flightdatareq.json()
            else:
                flight_data = None
                
            if flight_data and "trail" in flight_data:
                current_location = flight_data['trail'][0]
                
                # Only attempt reverse geocoding if we have an API key
                if shared_config.CONF.get("GOOGLEMAPS_API_KEY"):
                    reverse_geocode = requests.get(f"https://maps.googleapis.com/maps/api/geocode/json?latlng={current_location['lat']},{current_location['lng']}&result_type=country|administrative_area_level_1|natural_feature&key={shared_config.CONF['GOOGLEMAPS_API_KEY']}").json()
                    if len(reverse_geocode['results']) != 0:
                        formatted_address = reverse_geocode['results'][0]['formatted_address']
                    else:
                        formatted_address = 'Ocean'
                else:
                    # Show coordinates when no API key is available
                    formatted_address = f"({current_location['lat']:.1f}, {current_location['lng']:.1f})"

                logging.info(current_location)
                logging.info(formatted_address)
            else:
                logging.exception("No flight data")

        requests_limiter = requests_limiter + 1

        sign.canvas.Clear()

        if flight_data:
            flight_number_header = f"- {flight_data['identification']['callsign']} -"

            graphics.DrawText(sign.canvas, sign.font57, utilities.get_centered_text_x_offset_value(5, flight_number_header), 6, graphics.Color(200, 10, 10), flight_number_header)

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

            origin_distance_to_destination = utilities.get_distance((flight_data['airport']['origin']['position']['latitude'], flight_data['airport']['origin']['position']['longitude']), (flight_data['airport']['destination']['position']['latitude'], flight_data['airport']['destination']['position']['longitude']))
            current_position_to_destination = utilities.get_distance((current_location['lat'], current_location['lng']), (flight_data['airport']['destination']['position']['latitude'], flight_data['airport']['destination']['position']['longitude']))

            # Handle case where origin and destination are the same
            if origin_distance_to_destination == 0:
                percent_complete = 0
            else:
                percent_complete = round((origin_distance_to_destination - current_position_to_destination) / origin_distance_to_destination, 2)

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

            # Convert Unix timestamp to local time at origin airport
            origin_timezone = flight_data['airport']['origin']['timezone']['name']
            origin_local_time = datetime.fromtimestamp(start_time, tz=timezone.utc).astimezone(ZoneInfo(origin_timezone))
            destination_timezone = flight_data['airport']['destination']['timezone']['name']
            destination_local_time = datetime.fromtimestamp(end_time, tz=timezone.utc).astimezone(ZoneInfo(destination_timezone))

            if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
                graphics.DrawText(sign.canvas, sign.font46, 6, 22, graphics.Color(40, 40, 255), origin_local_time.strftime('%H:%M'))
                graphics.DrawText(sign.canvas, sign.font46, 103, 22, graphics.Color(40, 40, 255), destination_local_time.strftime('%H:%M'))
            else:
                graphics.DrawText(sign.canvas, sign.font46, 2, 22, graphics.Color(40, 40, 255), origin_local_time.strftime('%I:%M%p'))
                graphics.DrawText(sign.canvas, sign.font46, 99, 22, graphics.Color(40, 40, 255), destination_local_time.strftime('%I:%M%p'))

            if current_location:
                graphics.DrawText(sign.canvas, sign.font46, 32, 19, graphics.Color(160, 160, 200), f"Alt:{current_location['alt']}")
                graphics.DrawText(sign.canvas, sign.font46, 70, 19, graphics.Color(20, 160, 60), f"Vel:{current_location['spd']}")

            if formatted_address:
                graphics.DrawText(sign.canvas, sign.font57, utilities.get_centered_text_x_offset_value(5, formatted_address), 30, graphics.Color(246, 242, 116), formatted_address)

            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

            blip_count = blip_count + 1
            if blip_count == 3:
                blip_count = 0

        breakout = sign.wait_loop(0.8)
        if breakout:
            return
