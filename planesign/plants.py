#!/usr/bin/python3
# -*- coding: utf-8 -*-

from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
import random
import time
import logging
from PIL import Image, ImageEnhance, ImageFilter
import shared_config
import utilities
import __main__
from modes import DisplayMode

class Sprite:
    def __init__(self):
        self.frames = []
        self.maxFrames = 0
        self.currFrame = 0
        self.lastFrame = None
        self.lastFrameChange = None
        self.brighten = False
        self.width = 0
        self.height = 0
        self.x0 = 0
        self.y0 = 0
        self.x = 0
        self.y = 0

    def loadframes(self, name):
        while True:
            filename = f"{shared_config.icons_dir}/plants/{name}{self.maxFrames}.png"
            try:
                frame = Image.open(filename)
                if self.brighten:
                    converter = ImageEnhance.Color(frame)
                    frame = converter.enhance(1.7)
                    frame = frame.filter(ImageFilter.SHARPEN)
                self.frames.append(frame)
                self.maxFrames += 1
            except FileNotFoundError:
                break
        if self.maxFrames > 0:
            self.width = self.frames[0].size[0]
            self.height = self.frames[0].size[1]
            self.x0 = round(self.width/2)
            self.y0 = self.height-1

    def draw(self, im):
        if self.maxFrames > 0:
            frame = self.frames[self.currFrame].convert("RGBA")
            im.paste(frame, (self.x-self.x0, self.y-self.y0), frame)
            if self.currFrame != self.lastFrame:
                self.lastFrameChange = time.perf_counter()
                self.lastFrame = self.currFrame

class Plant(Sprite):
    def __init__(self):
        Sprite.__init__(self)
        self.growthInterval = 1
        self.brighten = True

    def loadframes(self, name):
        super().loadframes(name)
        if self.maxFrames > 0:
            self.currFrame = 1

    def draw(self, im):
        # Change frames if we need to before drawing
        if self.lastFrameChange is not None and (time.perf_counter() >= self.lastFrameChange + self.growthInterval):
            if (self.currFrame < self.maxFrames - 1):
                self.currFrame = self.currFrame + 1

        super().draw(im)


@__main__.planesign_mode_handler(DisplayMode.PLANTS)
def plantmode(sign):
    sign.canvas.Clear()

    background = Image.open(f"{shared_config.icons_dir}/plants/Background.png").convert('RGB')

    # Format is: (Plant name, x0, y0, growthInterval (mins), 0 <= availability weight <= 1)
    plantlist = [("Anthurium",       6,   21,    1+random.random(),      1.0),
                ("Begonia",          10,  22,    1.5+random.random(),    0.9),
                ("Bromeliad",        11,  22,    2+random.random(),      1.0),
                ("Cactus",           4,   13,    5+random.random(),      1.0),
                ("CrownOfThorns",    8,   22,    3+random.random(),      1.0),
                ("Daisy",            4,   19,    1.5+random.random(),    1.0),
                ("EnglishIvy",       15,  18,    1+random.random(),      1.0),
                ("Fern",             6,   13,    1+random.random(),      1.0),
                ("Lavender",         6,   25,    1+random.random(),      1.0),
                ("Orchid",           8,   22,    3+random.random(),      1.0),
                ("Philodendron",     13,  23,    2+random.random(),      0.9),
                ("Pitcherplant",     13,  20,    3+random.random(),      0.7),
                ("Pothos",           8,   18,    1+random.random(),      1.0),
                ("Prayerplant",      13,  23,    2+random.random(),      0.8),
                ("Rafflesia",        13,  23,    10*(1+random.random()), 0.05),
                ("Rubberplant",      7,   26,    2+random.random(),      0.8),
                ("Succulent",        4,   9,     3+random.random(),      1.0),
                ("Violet",           5,   15,    1+random.random(),      1.0),
                ("XmasCactus",       12,  14,    1+random.random(),      1.0)]

    edge = 2
    extent = edge-1
    miny = 23
    maxy = 28
    attempt = 0
    max_attempts = 5
    min_plants = 6

    while True:

        attempt += 1

        # Keep plants based on their availability
        curatedlist = [p for p in plantlist if random.random() < p[4]]

        plants = []

        # Select random plants to fill the table
        while True:
            if (len(curatedlist) == 0):
                break

            index = random.randint(0, len(curatedlist)-1)

            (name, x0, y0, growthInterval, _) = curatedlist[index]
            del curatedlist[index]

            plant = Plant()
            plant.loadframes(name)
            plant.x0 = x0
            plant.y0 = y0
            plant.growthInterval = growthInterval * 60
            center = round(plant.width/2 + extent - 0.5)
            left = center
            right = center + 1
            plant.x = random.randint(left, right)
            ywiggle = max(0, 32 - plant.height - 1)
            bot = maxy
            top = max(miny, bot - ywiggle)
            plant.y = random.randint(top, bot)
            test_extent = plant.x + round(plant.width/2 - 0.5)
            
            if (test_extent <= 127 - edge):
                # Plant fits on the table
                plants.append(plant)
                extent = test_extent
            else:
                # Can't fit any more plants on the table
                break

        if (len(plants) >= min_plants or attempt >= max_attempts):
            # Try and get more than 5 plants on the table at once
            break

    plants = sorted(plants, key=lambda p: p.y)

    while shared_config.shared_mode.value == DisplayMode.PLANTS.value:

        bg = background.copy()

        for plant in plants:
            plant.draw(bg)

        sign.canvas.SetImage(bg.convert('RGB'), 0, 0)
        
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        breakout = sign.wait_loop(0.1)
        if breakout:
            break
