import logging
import shared_config
import types
from rgbmatrix import graphics
import utilities
import __main__
from FlightRadar24.api import FlightRadar24API, Flight

prev_stats = types.SimpleNamespace()
prev_stats.distance = 0
prev_stats.altitude = 0
prev_stats.ground_speed = 0

def shorten_airport_name(name,desired_length):
    name = name.replace(" Airport", "").replace("International International","Intl.")
    if len(name)<=desired_length: return name
    name = name.replace("Northeast ","NE ").replace("Northwest ","NW ").replace("Southeast ","SE ").replace("Southwest ","SW ")
    if len(name)<=desired_length: return name
    name = name.replace("Air National Guard Base","ANGB")
    if len(name)<=desired_length: return name
    name = name.replace("International","Intl.").replace("National","Natl.").replace("Regional","Rgnl.")
    if len(name)<=desired_length: return name
    name = name.replace("Memorial","Mem.")
    if len(name)<=desired_length: return name
    name = name.replace("Air Force Base","AFB").replace("Air Force","AF")
    if len(name)<=desired_length: return name
    name = name.replace("Army Air Field", "AAF").replace("Army Airfield", "AAF")
    if len(name)<=desired_length: return name
    name = name.replace("Air Station","AS").replace("Air Base","AB").replace("Airbase","AB")
    if len(name)<=desired_length: return name
    name = name.replace("Municipal","Muni.").replace("Fort","Ft.").replace("Saint","St.")
    return name


@__main__.planesign_mode_handler(1)
def show_closest_plane_if_in_alert_radius(sign):
    scroll=utilities.TextScroller(sign,2,21,(200, 10, 10),boxdim=(70,7),space=3,scrollspeed=10,holdtime=2)
    while shared_config.shared_mode.value == 1:
        if shared_config.data_dict["closest"] and shared_config.data_dict["closest"].distance <= 2:
            plane_to_show = shared_config.data_dict["closest"]
        else:
            # No closest plane, show time
            plane_to_show = None

        show_a_plane(sign, plane_to_show, scroll)


@__main__.planesign_mode_handler(2)
def always_show_closest_plane(sign):
    scroll=utilities.TextScroller(sign,2,21,(200, 10, 10),boxdim=(70,7),space=3,scrollspeed=10,holdtime=2)
    while shared_config.shared_mode.value == 2:
        plane_to_show = shared_config.data_dict["closest"]
        show_a_plane(sign, plane_to_show, scroll)


@__main__.planesign_mode_handler(3)
def always_show_highest_plane(sign):
    scroll=utilities.TextScroller(sign,2,21,(200, 10, 10),boxdim=(70,7),space=3,scrollspeed=10,holdtime=2)
    while shared_config.shared_mode.value == 3:
        plane_to_show = shared_config.data_dict["highest"]
        show_a_plane(sign, plane_to_show, scroll)


@__main__.planesign_mode_handler(4)
def always_show_fastest_plane(sign):
    scroll=utilities.TextScroller(sign,2,21,(200, 10, 10),boxdim=(70,7),space=3,scrollspeed=10,holdtime=2)
    while shared_config.shared_mode.value == 4:
        plane_to_show = shared_config.data_dict["fastest"]
        show_a_plane(sign, plane_to_show, scroll)


@__main__.planesign_mode_handler(5)
def always_show_slowest_plane(sign):
    scroll=utilities.TextScroller(sign,2,21,(200, 10, 10),boxdim=(70,7),space=3,scrollspeed=10,holdtime=2)
    while shared_config.shared_mode.value == 5:
        plane_to_show = shared_config.data_dict["slowest"]
        show_a_plane(sign, plane_to_show, scroll)


def show_a_plane(sign, plane_to_show, scroll):

    # TODO
    global prev_stats

    if plane_to_show:

        interpol_distance = utilities.interpolate(prev_stats.distance, plane_to_show.distance)
        interpol_alt = utilities.interpolate(prev_stats.altitude, plane_to_show.altitude)
        interpol_speed = utilities.interpolate(prev_stats.ground_speed, plane_to_show.ground_speed)

        prev_stats = plane_to_show

        # We only have room to display one full airport name. So pick the one that is further away assuming
        # the user probably hasn't heard of that one
        origin_distance = 0
        if plane_to_show.origin_airport_iata:
            origin_config = shared_config.code_to_airport.get(plane_to_show.origin_airport_iata)
            if origin_config:
                origin_distance = utilities.get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (origin_config[1], origin_config[2]))
                logging.info(f"Origin is {origin_distance:.2f} miles away")

        destination_distance = 0
        if plane_to_show.destination_airport_iata:
            destination_config = shared_config.code_to_airport.get(plane_to_show.destination_airport_iata)
            if destination_config:
                destination_distance = utilities.get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (destination_config[1], destination_config[2]))
                logging.info(f"Destination is {destination_distance:.2f} miles away")


        if origin_distance == 0 and destination_distance == 0:
            friendly_name = ""
        elif origin_distance != 0 and destination_distance == 0:
            friendly_name = shorten_airport_name(origin_config[0],14)
        elif origin_distance == 0 and destination_distance != 0:
            friendly_name = shorten_airport_name(destination_config[0],14)
        else:
            if shared_config.CONF["AIRPORT_SCROLL"].lower() == 'true':
                friendly_name = f'{shorten_airport_name(origin_config[0],10)} to {shorten_airport_name(destination_config[0],10)}'
            else:
                if origin_distance > destination_distance:
                    friendly_name = origin_config[0]
                else:
                    friendly_name = destination_config[0]


        logging.info("Full airport name from code: " + friendly_name)

        # Front pad the flight number to a max of 7 for spacing
        formatted_flight = plane_to_show.callsign.rjust(7, ' ')

        for i in range(utilities.NUM_STEPS):
            sign.canvas.Clear()
            graphics.DrawText(sign.canvas, sign.fontreallybig, 1, 12, graphics.Color(20, 200, 20), plane_to_show.origin_airport_iata + "->" + plane_to_show.destination_airport_iata)
            if shared_config.CONF["AIRPORT_SCROLL"].lower() == 'true':
                scroll.text=friendly_name
                scroll.draw()
            else:
                graphics.DrawText(sign.canvas, sign.font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
            graphics.DrawText(sign.canvas, sign.font57, 37, 30, graphics.Color(0, 0, 200), formatted_flight)
            graphics.DrawText(sign.canvas, sign.font57, 2, 30, graphics.Color(180, 180, 180), plane_to_show.aircraft_code)

            graphics.DrawText(sign.canvas, sign.font57, 78, 8, graphics.Color(60, 60, 160), "Dst: {0:.1f}".format(interpol_distance[i]))
            graphics.DrawText(sign.canvas, sign.font57, 78, 19, graphics.Color(160, 160, 200), "Alt: {0:.0f}".format(interpol_alt[i]))
            graphics.DrawText(sign.canvas, sign.font57, 78, 30, graphics.Color(20, 160, 60), "Vel: {0:.0f}".format(interpol_speed[i]))

            forced_breakout = sign.wait_loop(0.065)
            if forced_breakout:
                return

            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

    else:
        # NOT ALERT RADIUS
        prev_stats.distance = 0
        prev_stats.altitude = 0
        prev_stats.ground_speed = 0

        utilities.show_time(sign)
        sign.wait_loop(0.5)


def get_plane_data_worker(data_dict):

    fr_api = FlightRadar24API()

    bounds = f"{float(shared_config.CONF['SENSOR_LAT']) + 2},{float(shared_config.CONF['SENSOR_LAT']) - 2},{float(shared_config.CONF['SENSOR_LON']) - 2},{float(shared_config.CONF['SENSOR_LON']) + 2}"

    shutdown_flag = False

    while not shutdown_flag:

        try:
            if shared_config.shared_mode.value == 0:
                logging.info("Sign off, skipping FR24 request...")
            else:

                flights = fr_api.get_flights(bounds=bounds)

                closest = None
                highest = None
                fastest = None
                slowest = None

                for flight in flights:

                    # Filter out planes on the ground
                    if flight.on_ground:
                        continue

                    # Not included in the API, we calculate this on the fly
                    flight.distance = utilities.get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (flight.latitude, flight.longitude))

                    if (closest is None or (flight.distance < closest.distance and flight.altitude < float(shared_config.CONF["CLOSEST_HEIGHT_LIMIT"]))):
                        closest = flight

                    # The rest of these are for fun, filter out the unknown planes
                    if not flight.origin_airport_iata:
                        continue

                    if (highest is None or flight.altitude > highest.altitude):
                        highest = flight

                    if (fastest is None or flight.ground_speed > fastest.ground_speed):
                        fastest = flight

                    if (slowest is None or flight.ground_speed < slowest.ground_speed):
                        slowest = flight

                logging.info(f"{closest.distance:.2f} miles away: {closest}")

                data_dict["closest"] = closest
                data_dict["highest"] = highest
                data_dict["fastest"] = fastest
                data_dict["slowest"] = slowest

        except:
            logging.exception("Error getting FR24 data...")

        shutdown_flag = shared_config.shared_shutdown_event.wait(timeout=7)
