#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from PIL import Image
import tempfile

blah = {}
blah["ehre"] = 2
blah["4"]

options = RGBMatrixOptions()
options.cols = 64
options.gpio_slowdown = 4
options.chain_length = 2

matrix = RGBMatrix(options = options)

image = Image.open(f"/home/pi/plane.jpg")
#image.thumbnail((64, 32), Image.ANTIALIAS)
matrix.SetImage(image.convert('RGB'), 0, -12)

pass