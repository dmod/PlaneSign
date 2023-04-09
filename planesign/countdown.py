#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from datetime import datetime
import shared_config
import __main__

@__main__.planesign_mode_handler(21)
def countdown(sign):

    sign.canvas.Clear()
    graphics.DrawText(sign.canvas, sign.fontreallybig, 19, 21, graphics.Color(150, 0, 0), "Countdown!")
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    sign.canvas.Clear()
    while "countdown_datetime" not in shared_config.data_dict:
        sign.wait_loop(0.5)

    frame = 0
    while shared_config.shared_mode.value == 21:

        frame = (frame+1)%10

        dt = shared_config.data_dict["countdown_datetime"]-datetime.now()
        dts = round(dt.total_seconds())

        if dts>0:
            days = dts // 86400
            hours = (dts % 86400) // 3600
            minutes = (dts % 3600) // 60
            seconds = dts % 60
           
            if days>=100:
                string = f'{days} Days'
            else:
                if days>0:
                    if frame<8:
                        string = f'{days}D:{hours:02d}h:{minutes:02d}m'
                    else:
                        string = f'{days}D {hours:02d}h {minutes:02d}m'
                elif hours>0:
                        string = f'{hours}h:{minutes:02d}m:{seconds:02d}s'
                elif minutes>0:
                        string = f'{minutes}m:{seconds:02d}s'
                else:
                    string = f'{seconds}s'

            graphics.DrawText(sign.canvas, sign.fontreallybig, round(65-len(string)*4.5), 21, graphics.Color(150, 0, 0), string)
        else:
            if frame<5:
                graphics.DrawText(sign.canvas, sign.fontreallybig, 51, 21, graphics.Color(0, 150, 0), "!!!")

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        sign.wait_loop(0.1)
        