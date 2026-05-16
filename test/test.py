#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import RGBMatrix, RGBMatrixOptions
import time

options = RGBMatrixOptions()
options.cols = 64
options.gpio_slowdown = 5
options.chain_length = 2

# "adafruit-hat" or "regular"
options.hardware_mapping = "adafruit-hat"

myMatrix = RGBMatrix(options=options)
myCanvas = myMatrix.CreateFrameCanvas()

# Set every pixel to white
width = options.cols * options.chain_length
height = 32
for x in range(width):
    for y in range(height):
        myCanvas.SetPixel(x, y, 255, 255, 255)
myCanvas = myMatrix.SwapOnVSync(myCanvas)

time.sleep(90)
