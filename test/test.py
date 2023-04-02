#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from PIL import Image
import time

options = RGBMatrixOptions()
options.cols = 64
options.gpio_slowdown = 5
options.chain_length = 2

# "adafruit-hat" or "regular"
options.hardware_mapping = "adafruit-hat"

myMatrix = RGBMatrix(options = options)
myCanvas = myMatrix.CreateFrameCanvas()

font57 = graphics.Font()
font57.LoadFont('/home/pi/rpi-rgb-led-matrix/fonts/4x6.bdf')

#graphics.DrawText(myCanvas, font57, 10, 18, graphics.Color(60, 60, 160), "Hellllooooooo")
#


image = Image.open(f"/home/pi/ind.png").convert('RGB')
image = image.resize((25, 20), Image.BICUBIC).convert('RGB')
myCanvas.SetImage(image, 20, 1)
myCanvas = myMatrix.SwapOnVSync(myCanvas)
#image = image.resize((20, 20))
#myCanvas.SetImage(image, 10, 10)
#image.thumbnail((64, 32), Image.ANTIALIAS)

time.sleep(15)
