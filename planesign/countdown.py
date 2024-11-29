#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from datetime import datetime
from collections import namedtuple
import time
import random
import shared_config
import logging
import __main__
from modes import DisplayMode
RGB = namedtuple('RGB', 'r g b')

COLORS = {}
COLORS[0] = [RGB(3, 194, 255)]  # Plain
COLORS[1] = [RGB(0, 0, 0)]  # RAINBOW
COLORS[2] = [RGB(12, 169, 12), RGB(206, 13, 13)]  # CHRISTMAS
COLORS[3] = [RGB(173, 0, 30), RGB(178, 178, 178), RGB(37, 120, 178)]  # FOURTH_OF_JULY
COLORS[4] = [RGB(20, 20, 20), RGB(247, 95, 28)]  # HALLOWEEN

@__main__.planesign_mode_handler(DisplayMode.COUNTDOWN)
def countdown(sign):

    sign.canvas.Clear()

    color_mode_offset = 6
    starting_color_index = 0

    blink_frame_time = time.perf_counter()
    blink_cycle_time = 0
    blink_period = 1

    # color_frame_time = time.perf_counter()
    # color_cycle_time = 0
    # color_period = 0.01

    if "countdown_datetime" in shared_config.data_dict:
        now = datetime.now().astimezone(shared_config.local_timezone)
        logging.info(f'Countdown datetime set to: {shared_config.data_dict["countdown_datetime"]}')
        logging.info(f'Current datetime: {now}')
        logging.info(f'Delta datetime: {shared_config.data_dict["countdown_datetime"]-now}')

    while shared_config.shared_mode.value == DisplayMode.COUNTDOWN.value:

        #enable_blink = False
        enable_blink = True

        curr_time = time.perf_counter()

        blink_cycle_time = curr_time-blink_frame_time
        
        if blink_cycle_time > blink_period:
            blink_frame_time = time.perf_counter()
            blink_cycle_time = 0

        if shared_config.shared_color_mode.value == 1:
            selected_color_list = [RGB(random.randrange(10, 255), random.randrange(10, 255), random.randrange(10, 255))]
            # color_period = 0.1
            # enable_blink = True
        elif shared_config.shared_color_mode.value >= color_mode_offset:
            selected_color_list = [RGB(((shared_config.shared_color_mode.value-color_mode_offset) >> 16) & 255, ((shared_config.shared_color_mode.value -
                                    color_mode_offset) >> 8) & 255, (shared_config.shared_color_mode.value-color_mode_offset) & 255)]
            # color_period = 0.1
            # enable_blink = True
        elif shared_config.shared_color_mode.value == 5:
            selected_color_list = COLORS[0]
            # color_period = 0.1
            # enable_blink = True
        else:
            selected_color_list = COLORS[shared_config.shared_color_mode.value]
            # color_period = 1.1
            # if shared_config.shared_color_mode.value == 0:
            #     enable_blink = True
             

        if starting_color_index >= len(selected_color_list):
            starting_color_index = 0

        color_index = starting_color_index

        if "countdown_datetime" not in shared_config.data_dict:

            string = "Countdown!"
            xloc = 19

            for char in string:

                char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
                graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, 21, char_color, char)

                xloc += 9
                                    
                color_index = color_index + 1 if char != ' ' else color_index
                if color_index >= len(selected_color_list):
                    color_index = 0

        else:
            dt = shared_config.data_dict["countdown_datetime"]-(datetime.now().astimezone(shared_config.local_timezone))
            dts = round(dt.total_seconds())

            if "countdown_message" in shared_config.data_dict and shared_config.data_dict["countdown_message"] != "":
                yloc = 27
            else:
                yloc = 21

            if dts>0:
                days = dts // 86400
                hours = (dts % 86400) // 3600
                minutes = (dts % 3600) // 60
                seconds = dts % 60
            
                if days>=100:
                    string = f'{days} Days'
                else:
                    if days>0:
                        if blink_cycle_time<0.8 or not enable_blink:
                            string = f'{days}D:{hours:02d}h:{minutes:02d}m'
                        else:
                            string = f'{days}D {hours:02d}h {minutes:02d}m'
                    elif hours>0:
                            string = f'{hours}h:{minutes:02d}m:{seconds:02d}s'
                    elif minutes>0:
                            string = f'{minutes}m:{seconds:02d}s'
                    else:
                        string = f'{seconds}s'

                line_2 = string

                if "countdown_message" in shared_config.data_dict and shared_config.data_dict["countdown_message"] != "":

                    line_1 = shared_config.data_dict["countdown_message"]
                    xloc = round(65-len(line_1)*4.5)

                    for char in line_1:

                        char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
                        graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, yloc-14, char_color, char)

                        xloc += 9
                                            
                        color_index = color_index + 1 if char != ' ' else color_index
                        if color_index >= len(selected_color_list):
                            color_index = 0

                xloc = round(65-len(line_2)*4.5)
        
                for char in line_2:

                    char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
                    graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, yloc, char_color, char)

                    xloc += 9

                    color_index += 1
                    if color_index >= len(selected_color_list):
                        color_index = 0

            else:
                if "countdown_message" in shared_config.data_dict and shared_config.data_dict["countdown_message"] != "":

                    line_1 = shared_config.data_dict["countdown_message"]
                    xloc = round(65-len(line_1)*4.5)

                    for char in line_1:

                        char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
                        graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, yloc-14, char_color, char)

                        xloc += 9
                                            
                        color_index = color_index + 1 if char != ' ' else color_index
                        if color_index >= len(selected_color_list):
                            color_index = 0

                line_2 = "!!!"
                xloc = 51
                
                if blink_cycle_time<0.5:

                    for char in line_2:

                        char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
                        graphics.DrawText(sign.canvas, sign.fontreallybig, xloc, yloc, char_color, char)

                        xloc += 9

                        color_index = color_index + 1 if char != ' ' else color_index
                        if color_index >= len(selected_color_list):
                            color_index = 0

        # color_cycle_time = curr_time-color_frame_time
        
        # if color_cycle_time > color_period:
        #     color_frame_time = time.perf_counter()
        #     color_cycle_time = 0
        #     starting_color_index += 1

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        breakout = sign.wait_loop(0.1)
        if breakout:
            return
        