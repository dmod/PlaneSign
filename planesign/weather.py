from pyowm import OWM
from PIL import Image
import utilities
import logging
import time
import shared_config
import __main__
from rgbmatrix import graphics


@__main__.planesign_mode_handler(6)
def show_weather(sign):

    while shared_config.shared_mode.value == 6:

        sign.canvas.Clear()

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if (utilities.convert_unix_to_local_time(time.time()).hour >= 18):
            start_index_day = 1

        # Day 0
        day = shared_config.data_dict['weather'].forecast_daily[start_index_day]
        image = Image.open(f"{shared_config.icons_dir}/{day.weather_icon_name}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_0_xoffset + 15, 5)
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 14, graphics.Color(47, 158, 19), utilities.convert_unix_to_local_time(day.ref_time).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 22, graphics.Color(210, 20, 20), str(round(day.temp['max'])))
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 30, graphics.Color(20, 20, 210), str(round(day.temp['min'])))
        graphics.DrawText(sign.canvas, sign.font46, day_0_xoffset + 15, 30, graphics.Color(52, 235, 183), day.status)

        # Day 1
        day = shared_config.data_dict['weather'].forecast_daily[start_index_day + 1]
        image = Image.open(f"{shared_config.icons_dir}/{day.weather_icon_name}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_1_xoffset + 15, 5)
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 14, graphics.Color(47, 158, 19), utilities.convert_unix_to_local_time(day.ref_time).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 22, graphics.Color(210, 20, 20), str(round(day.temp['max'])))
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 30, graphics.Color(20, 20, 210), str(round(day.temp['min'])))
        graphics.DrawText(sign.canvas, sign.font46, day_1_xoffset + 15, 30, graphics.Color(52, 235, 183), day.status)

        # Day 2
        day = shared_config.data_dict['weather'].forecast_daily[start_index_day + 2]
        image = Image.open(f"{shared_config.icons_dir}/{day.weather_icon_name}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_2_xoffset + 15, 5)
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 14, graphics.Color(47, 158, 19), utilities.convert_unix_to_local_time(day.ref_time).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 22, graphics.Color(210, 20, 20), str(round(day.temp['max'])))
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 30, graphics.Color(20, 20, 210), str(round(day.temp['min'])))
        graphics.DrawText(sign.canvas, sign.font46, day_2_xoffset + 15, 30, graphics.Color(52, 235, 183), day.status)

        graphics.DrawText(sign.canvas, sign.font46, 0, 5, graphics.Color(20, 20, 210), shared_config.CONF["WEATHER_CITY_NAME"])

        # Calculate and draw the horizontal boarder around the WEATHER_CITY_NAME
        num_horizontal_pixels = (len(shared_config.CONF["WEATHER_CITY_NAME"]) * 4)
        for x in range(num_horizontal_pixels):
            sign.canvas.SetPixel(x, 6, 140, 140, 140)

        # Draw the vertical boarder around the WEATHER_CITY_NAME
        for y in range(7):
            sign.canvas.SetPixel(num_horizontal_pixels, y, 140, 140, 140)

        sunrise_sunset_start_x = min(num_horizontal_pixels + 20,70)

        time_format = '%-I:%M'
        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            time_format = '%-H:%M'

        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), utilities.convert_unix_to_local_time(shared_config.data_dict['weather'].current.srise_time).strftime(time_format))
        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), utilities.convert_unix_to_local_time(shared_config.data_dict['weather'].current.sset_time).strftime(time_format))

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        breakout = sign.wait_loop(30)
        if breakout:
            return


def get_weather_data_worker(data_dict):
    owm = OWM(shared_config.CONF["OPENWEATHER_API_KEY"])
    mgr = owm.weather_manager()

    shutdown_flag = False

    while not shutdown_flag:
        try:
            one_call_object = mgr.one_call(lat=float(shared_config.CONF["SENSOR_LAT"]), lon=float(shared_config.CONF["SENSOR_LON"]), exclude='minutely,hourly', units='imperial')
            data_dict["weather"] = one_call_object
            logging.info(f"At: {utilities.convert_unix_to_local_time(data_dict['weather'].current.ref_time)} Temp: {data_dict['weather'].current.temperature()['temp']}")
            timeout = 300
        except:
            logging.exception("Error getting weather data...")
            timeout = 5

        shutdown_flag = shared_config.shared_shutdown_event.wait(timeout=timeout)
        #shutdown_flag = shared_config.shared_shutdown_event.wait(timeout=300)
