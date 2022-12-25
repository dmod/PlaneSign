#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
from datetime import datetime, timedelta, timezone
import random
import numpy as np
from pyowm import OWM
import PIL.Image as Image
import shared_config
import utilities
import __main__

class SnowFlake:
        def __init__(self):
            self.x=None
            self.y=random.randint(-80,-13)
            self.speed = None
            self.sprite = None
            self.layer = None
            self.hue = None

            self.load()
        
        def load(self):
            self.x = random.randint(-10,127)
            self.layer = random.randint(0,2)
            r=random.random()
            if r<0.5:
                num = 3
            elif r<0.75:
                num = random.choice([1,4,6,16,17,18])
            elif r<0.9:
                num = random.choice([2,7,8,9,10,11,12,13,14,15,19,20,21,22])
            else:
                num = random.randint(1,22)
            self.sprite=Image.open(f"{shared_config.icons_dir}/santa/snowflake{num}.png").convert("RGBA")
            w,_=self.sprite.size
            self.speed=(random.random()*0.03+0.075-w/1200)/1.5
            self.sat = random.random()*0.8
            
        def draw(self,image):
            sprite = self.sprite
            r,g,b = utilities.hsv_2_rgb(0.56,self.sat,1-0.3*self.layer)

            rgba = np.array(sprite)
            mask = (rgba[:, :, 0] == 255) & (rgba[:, :, 1] == 255) & (rgba[:, :, 2] == 255) & (rgba[:, :, 3] == 255)
            rgba[mask] = [r, g, b, 255]
            sprite = Image.fromarray(rgba)

            #w,h = sprite.size
            #for i in range(w):
            #    for j in range(h):
            #        if sprite.getpixel((i,j))==(255,255,255,255):
            #            sprite.putpixel( (i, j), (r, g, b, 255) )

            image.paste(sprite,(int(self.x),int(self.y)),sprite)
            
            self.y += self.speed
            if self.y > 31:
                self.y-=50
                self.load()
            
@__main__.planesign_mode_handler(20)
def snowfall(sign):

    sign.canvas.Clear()

    flakes = []
    for i in range(30):
        flakes.append(SnowFlake())

    while shared_config.shared_mode.value == 20:
        background = Image.new('RGB', (128, 32), (0, 0, 0)) 
        for f in flakes:
            if f.layer==2:
                f.draw(background)
        for f in flakes:
            if f.layer==1:
                f.draw(background)
        for f in flakes:
            if f.layer==0:
                f.draw(background)
        sign.canvas.SetImage(background, 0, 0)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
