import logging
import shared_config
import time
from rgbmatrix import graphics
import utilities
import __main__

prev_stats = {}
prev_stats["distance"] = 0
prev_stats["altitude"] = 0
prev_stats["speed"] = 0


@__main__.planesign_mode_handler(1)
def show_closest_plane_if_in_alert_radius(sign):
    while shared_config.shared_mode.value == 1:
        if shared_config.data_dict["closest"] and shared_config.data_dict["closest"]["distance"] <= 2:
            plane_to_show = shared_config.data_dict["closest"]
        else:
            # No closest plane, show time
            plane_to_show = None

        show_a_plane(sign, plane_to_show)


@__main__.planesign_mode_handler(2)
def always_show_closest_plane(sign):
    while shared_config.shared_mode.value == 2:
        plane_to_show = shared_config.data_dict["closest"]
        show_a_plane(sign, plane_to_show)


@__main__.planesign_mode_handler(3)
def always_show_highest_plane(sign):
    while shared_config.shared_mode.value == 3:
        plane_to_show = shared_config.data_dict["highest"]
        show_a_plane(sign, plane_to_show)


@__main__.planesign_mode_handler(4)
def always_show_fastest_plane(sign):
    while shared_config.shared_mode.value == 4:
        plane_to_show = shared_config.data_dict["fastest"]
        show_a_plane(sign, plane_to_show)


@__main__.planesign_mode_handler(5)
def always_show_slowest_plane(sign):
    while shared_config.shared_mode.value == 5:
        plane_to_show = shared_config.data_dict["slowest"]
        show_a_plane(sign, plane_to_show)


def show_a_plane(sign, plane_to_show):

    # TODO
    global prev_stats

    if plane_to_show:

        interpol_distance = utilities.interpolate(prev_stats["distance"], plane_to_show["distance"])
        interpol_alt = utilities.interpolate(prev_stats["altitude"], plane_to_show["altitude"])
        interpol_speed = utilities.interpolate(prev_stats["speed"], plane_to_show["speed"])

        prev_stats = plane_to_show

        # We only have room to display one full airport name. So pick the one that is further away assuming
        # the user probably hasn't heard of that one
        origin_distance = 0
        if plane_to_show["origin"]:
            origin_config = shared_config.code_to_airport.get(plane_to_show["origin"])
            if origin_config:
                origin_distance = utilities.get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (origin_config[1], origin_config[2]))
                logging.info(f"Origin is {origin_distance:.2f} miles away")

        destination_distance = 0
        if plane_to_show["destination"]:
            destination_config = shared_config.code_to_airport.get(plane_to_show["destination"])
            if destination_config:
                destination_distance = utilities.get_distance((float(shared_config.CONF["SENSOR_LAT"]), float(shared_config.CONF["SENSOR_LON"])), (destination_config[1], destination_config[2]))
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

        for i in range(utilities.NUM_STEPS):
            sign.canvas.Clear()
            graphics.DrawText(sign.canvas, sign.fontreallybig, 1, 12, graphics.Color(20, 200, 20), plane_to_show["origin"] + "->" + plane_to_show["destination"])
            graphics.DrawText(sign.canvas, sign.font57, 2, 21, graphics.Color(200, 10, 10), friendly_name[:14])
            graphics.DrawText(sign.canvas, sign.font57, 37, 30, graphics.Color(0, 0, 200), formatted_flight)
            graphics.DrawText(sign.canvas, sign.font57, 2, 30, graphics.Color(180, 180, 180), plane_to_show["typecode"])

            graphics.DrawText(sign.canvas, sign.font57, 78, 8, graphics.Color(60, 60, 160), "Dst: {0:.1f}".format(interpol_distance[i]))
            graphics.DrawText(sign.canvas, sign.font57, 78, 19, graphics.Color(160, 160, 200), "Alt: {0:.0f}".format(interpol_alt[i]))
            graphics.DrawText(sign.canvas, sign.font57, 78, 30, graphics.Color(20, 160, 60), "Vel: {0:.0f}".format(interpol_speed[i]))

            forced_breakout = sign.wait_loop(0.065)
            if forced_breakout:
                return

            sign.matrix.SwapOnVSync(sign.canvas)

    else:
        # NOT ALERT RADIUS
        prev_stats["distance"] = 0
        prev_stats["altitude"] = 0
        prev_stats["speed"] = 0

        utilities.show_time(sign)
        sign.wait_loop(0.5)
