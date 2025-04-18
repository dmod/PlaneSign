from PIL import Image
import utilities
import logging
import time
import shared_config
import requests
import __main__
from rgbmatrix import graphics

from modes import DisplayMode

@__main__.planesign_mode_handler(DisplayMode.WEATHER)
def show_weather(sign):

    polltime = None

    while shared_config.shared_mode.value == DisplayMode.WEATHER.value:

        sign.canvas.Clear()

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if (utilities.convert_unix_to_local_time(time.time()).hour >= 18):
            start_index_day = 1

        if polltime==None or time.perf_counter()-polltime>30:
            polltime = time.perf_counter()

            day0 = shared_config.data_dict['weather']['daily'][start_index_day]
            day1 = shared_config.data_dict['weather']['daily'][start_index_day + 1]
            day2 = shared_config.data_dict['weather']['daily'][start_index_day + 2]

            sunrise_time = utilities.convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunrise'])
            sunset_time = utilities.convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunset'])

        draw_daily_forcast(sign,day0,day_0_xoffset)
        draw_daily_forcast(sign,day1,day_1_xoffset)
        draw_daily_forcast(sign,day2,day_2_xoffset)

        graphics.DrawText(sign.canvas, sign.font46, 1, 5, graphics.Color(20, 20, 210), shared_config.CONF["WEATHER_CITY_NAME"])

        # Calculate and draw the horizontal boarder around the WEATHER_CITY_NAME
        num_horizontal_pixels = (len(shared_config.CONF["WEATHER_CITY_NAME"]) * 4)+1
        for x in range(num_horizontal_pixels):
            sign.canvas.SetPixel(x, 6, 140, 140, 140)

        # Draw the vertical boarder around the WEATHER_CITY_NAME
        for y in range(7):
            sign.canvas.SetPixel(num_horizontal_pixels, y, 140, 140, 140)

        sunrise_sunset_start_x = min(num_horizontal_pixels + 20,70)

        time_format = '%-I:%M'
        if shared_config.CONF["MILITARY_TIME"].lower() == 'true':
            time_format = '%H:%M'

        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), sunrise_time.strftime(time_format))
        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), sunset_time.strftime(time_format))

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        breakout = sign.wait_loop(0.1)
        if breakout:
            return

def get_weather_data_worker(data_dict):
    # Check if API key is configured
    if not shared_config.CONF.get("OPENWEATHER_API_KEY"):
        logging.error("OpenWeather API key is not configured. Weather data will not be available.")
        shared_config.shared_shutdown_event.wait()
        return

    shutdown_flag = False

    while not shutdown_flag:
        try:
            weather_data = requests.get(f"https://api.openweathermap.org/data/3.0/onecall?lat={shared_config.CONF['SENSOR_LAT']}&lon={shared_config.CONF['SENSOR_LON']}&appid={shared_config.CONF['OPENWEATHER_API_KEY']}&units=imperial")
            data_dict["weather"] = weather_data.json()
            logging.info(f"At: {utilities.convert_unix_to_local_time(data_dict['weather']['current']['dt'])} Temp: {data_dict['weather']['current']['temp']}")
            timeout = 900
        except Exception as e:
            logging.exception("Error getting weather data...", exc_info=e)
            timeout = 15

        shutdown_flag = shared_config.shared_shutdown_event.wait(timeout=timeout)

def draw_daily_forcast(sign,day,xloc):
    code = day['weather'][0]['id']
    status = day['weather'][0]['main']

    icon,status = utilities.weather_icon_decode(code,status)

    image = Image.open(f"{shared_config.icons_dir}/weather/{icon}.png")
    iw,ih=image.size
    sign.canvas.SetImage(image.convert('RGB'), xloc + 25 - round(iw/2), 9)

    graphics.DrawText(sign.canvas, sign.font57, xloc, 14, graphics.Color(47, 158, 19), utilities.convert_unix_to_local_time(day['dt']).strftime('%a'))
    graphics.DrawText(sign.canvas, sign.font57, xloc, 22, graphics.Color(210, 20, 20), str(round(day['temp']['max'])))
    graphics.DrawText(sign.canvas, sign.font57, xloc, 30, graphics.Color(20, 20, 210), str(round(day['temp']['min'])))
    graphics.DrawText(sign.canvas, sign.font46, xloc + 26 - len(status)*2, 30, graphics.Color(52, 235, 183), status)

    return