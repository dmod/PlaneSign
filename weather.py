import datetime
import time
from PIL import Image
from utilities import *
import shared_config
from rgbmatrix import graphics


def show_weather(sign):

    while shared_config.shared_mode.value == 6:
        sign.canvas = sign.matrix.CreateFrameCanvas()

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if (datetime.now().hour >= 18):
            start_index_day = 1

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        time.sleep(3)

        daily = shared_config.data_dict['weather']['daily']

        day = daily[start_index_day]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_0_xoffset + 15, 5)

        day = daily[start_index_day+1]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_1_xoffset + 15, 5)
        
        day = daily[start_index_day+2]
        image = Image.open(f"/home/pi/PlaneSign/icons/{day['weather'][0]['icon']}.png")
        image.thumbnail((22, 22), Image.BICUBIC)
        sign.canvas.SetImage(image.convert('RGB'), day_2_xoffset + 15, 5)

        graphics.DrawText(sign.canvas, sign.font46, 0, 5, graphics.Color(20, 20, 210), shared_config.CONF["WEATHER_CITY_NAME"])

        # Calculate and draw the horizontal boarder around the WEATHER_CITY_NAME
        num_horizontal_pixels = (len(shared_config.CONF["WEATHER_CITY_NAME"]) * 4)
        for x in range(num_horizontal_pixels):
            sign.canvas.SetPixel(x, 6, 140, 140, 140)

        # Draw the vertical boarder around the WEATHER_CITY_NAME
        for y in range(7):
            sign.canvas.SetPixel(num_horizontal_pixels, y, 140, 140, 140)

        sunrise_sunset_start_x = num_horizontal_pixels + 20

        if shared_config.CONF["MILITARY_TIME"].lower()=='true':
            graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunrise']).strftime('%-H:%M'))
            graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunset']).strftime('%-H:%M'))
        else:
            graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunrise']).strftime('%-I:%M'))
            graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), convert_unix_to_local_time(shared_config.data_dict['weather']['current']['sunset']).strftime('%-I:%M'))

        # Day 0
        day = daily[start_index_day]
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(sign.canvas, sign.font57, day_0_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(sign.canvas, sign.font46, day_0_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 1 
        day = daily[start_index_day + 1]
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(sign.canvas, sign.font57, day_1_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(sign.canvas, sign.font46, day_1_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        # Day 2 
        day = daily[start_index_day + 2]
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 14, graphics.Color(47, 158, 19), convert_unix_to_local_time(day["dt"]).strftime('%a'))
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
        graphics.DrawText(sign.canvas, sign.font57, day_2_xoffset, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
        graphics.DrawText(sign.canvas, sign.font46, day_2_xoffset + 15, 30, graphics.Color(52, 235, 183), day["weather"][0]["main"])

        sign.matrix.SwapOnVSync(sign.canvas)
        
        sign.wait_loop(30)
