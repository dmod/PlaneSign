import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import planes
import shared_config
from modes import DisplayMode
from rgbmatrix import graphics
from timezonefinder import TimezoneFinder
from utilities import get_centered_text_x_offset_value, get_distance, reverse_geocode

import __main__

KNOTS_TO_MPH = 1.15078
REFRESH_EVERY_N_LOOPS = 50

timezone_finder = None
airport_timezones = {}


def get_airport_position(iata_code):
    airport = shared_config.code_to_airport.get(iata_code)
    if airport is None:
        return None
    return (airport[1], airport[2])


def get_airport_timezone(iata_code, position):
    global timezone_finder

    if iata_code not in airport_timezones:
        if timezone_finder is None:
            timezone_finder = TimezoneFinder()
        airport_timezones[iata_code] = timezone_finder.timezone_at(lat=position[0], lng=position[1])

    tz_name = airport_timezones[iata_code]
    return ZoneInfo(tz_name) if tz_name else timezone.utc


def as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@__main__.planesign_mode_handler(DisplayMode.TRACK_A_FLIGHT)
def track_a_flight(sign):

    if "track_a_flight_num" not in shared_config.data_dict:
        sign.canvas.Clear()
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        return sign.wait_loop(-1)

    requests_limiter = 0
    blip_count = 0
    flight = None
    formatted_address = None

    while shared_config.shared_mode.value == DisplayMode.TRACK_A_FLIGHT.value:
        callsign = shared_config.data_dict["track_a_flight_num"]

        if requests_limiter % REFRESH_EVERY_N_LOOPS == 0:
            try:
                flight = planes.get_live_flight(callsign)
            except Exception:
                logging.exception(f"Could not fetch live data for {callsign}")
                flight = None

            if flight:
                # Perform reverse geocoding
                formatted_address, _ = reverse_geocode(flight.latitude, flight.longitude)

                if formatted_address == "Unknown":
                    # Show coordinates instead
                    formatted_address = f"({flight.latitude:.1f}, {flight.longitude:.1f})"

                logging.info(f"{flight.callsign} at {flight.latitude}, {flight.longitude} over {formatted_address}")
            else:
                formatted_address = None
                logging.warning(f"No live flight data for {callsign}")

        requests_limiter = requests_limiter + 1

        sign.canvas.Clear()

        if flight is None:
            not_tracking_header = f"- {callsign} -"
            graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, not_tracking_header), 14, graphics.Color(200, 10, 10), not_tracking_header)
            graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, "NOT IN THE AIR"), 24, graphics.Color(160, 160, 160), "NOT IN THE AIR")
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

            breakout = sign.wait_loop(0.8)
            if breakout:
                return
            continue

        flight_number_header = f"- {flight.callsign} -"

        graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, flight_number_header), 6, graphics.Color(200, 10, 10), flight_number_header)

        graphics.DrawText(sign.canvas, sign.fontreallybig, 1, 14, graphics.Color(20, 200, 20), flight.origin_airport_iata)
        graphics.DrawText(sign.canvas, sign.fontreallybig, 100, 14, graphics.Color(20, 200, 20), flight.destination_airport_iata)

        origin_position = get_airport_position(flight.origin_airport_iata)
        destination_position = get_airport_position(flight.destination_airport_iata)
        current_position = (flight.latitude, flight.longitude)

        if origin_position and destination_position:
            origin_distance_to_destination = get_distance(origin_position, destination_position)
            current_position_to_destination = get_distance(current_position, destination_position)

            # Handle case where origin and destination are the same
            if origin_distance_to_destination == 0:
                percent_complete = 0
            else:
                percent_complete = min(max((origin_distance_to_destination - current_position_to_destination) / origin_distance_to_destination, 0), 1)

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

            # The live feed carries no schedule, so departure/arrival are estimated from ground speed
            ground_speed_mph = (as_float(flight.ground_speed) or 0) * KNOTS_TO_MPH

            if ground_speed_mph > 50:
                now = datetime.now(tz=timezone.utc)
                distance_travelled = max(origin_distance_to_destination - current_position_to_destination, 0)
                start_time = now - timedelta(hours=distance_travelled / ground_speed_mph)
                end_time = now + timedelta(hours=current_position_to_destination / ground_speed_mph)

                origin_local_time = start_time.astimezone(get_airport_timezone(flight.origin_airport_iata, origin_position))
                destination_local_time = end_time.astimezone(get_airport_timezone(flight.destination_airport_iata, destination_position))

                if shared_config.CONF["MILITARY_TIME"].lower() == "true":
                    graphics.DrawText(sign.canvas, sign.font46, 6, 22, graphics.Color(40, 40, 255), origin_local_time.strftime("%H:%M"))
                    graphics.DrawText(sign.canvas, sign.font46, 103, 22, graphics.Color(40, 40, 255), destination_local_time.strftime("%H:%M"))
                else:
                    graphics.DrawText(sign.canvas, sign.font46, 2, 22, graphics.Color(40, 40, 255), origin_local_time.strftime("%I:%M%p"))
                    graphics.DrawText(sign.canvas, sign.font46, 99, 22, graphics.Color(40, 40, 255), destination_local_time.strftime("%I:%M%p"))

        altitude = as_float(flight.altitude)
        ground_speed = as_float(flight.ground_speed)

        if altitude is not None:
            graphics.DrawText(sign.canvas, sign.font46, 32, 19, graphics.Color(160, 160, 200), f"Alt:{int(altitude)}")

        if ground_speed is not None:
            graphics.DrawText(sign.canvas, sign.font46, 70, 19, graphics.Color(20, 160, 60), f"Vel:{int(ground_speed)}")

        if formatted_address:
            graphics.DrawText(sign.canvas, sign.font57, get_centered_text_x_offset_value(5, formatted_address), 30, graphics.Color(246, 242, 116), formatted_address)

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        blip_count = blip_count + 1
        if blip_count == 3:
            blip_count = 0

        breakout = sign.wait_loop(0.8)
        if breakout:
            return
