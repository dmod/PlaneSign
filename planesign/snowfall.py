import random
import time

import numpy as np
import PIL.Image as Image
import shared_config
import utilities
from modes import DisplayMode, planesign_mode_handler
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics

# Flake speeds are pixels per frame, so this sets how fast the snow falls.
FRAME_INTERVAL = 1 / 120


class SnowFlake:
    def __init__(self):
        self.x = None
        self.y = random.randint(-80, -13)
        self.speed = None
        self.sprite = None
        self.layer = None
        self.hue = None

        self.load()

    def load(self):
        self.x = random.randint(-10, 127)
        self.layer = random.randint(0, 2)
        r = random.random()
        if r < 0.5:
            num = 3
        elif r < 0.75:
            num = random.choice([1, 4, 6, 16, 17, 18])
        elif r < 0.9:
            num = random.choice([2, 7, 8, 9, 10, 11, 12, 13, 14, 15, 19, 20, 21, 22])
        else:
            num = random.randint(1, 22)
        sprite = Image.open(f"{shared_config.icons_dir}/santa/snowflake{num}.png").convert("RGBA")
        w, _ = sprite.size
        self.speed = (random.random() * 0.03 + 0.075 - w / 1200) / 1.5
        self.sat = random.random() * 0.8

        # The tint only depends on values chosen here, so apply it once per flake instead of every frame.
        r, g, b = utilities.hsv_2_rgb(0.56, self.sat, 1 - 0.3 * self.layer)
        rgba = np.array(sprite)
        mask = (rgba[:, :, 0] == 255) & (rgba[:, :, 1] == 255) & (rgba[:, :, 2] == 255) & (rgba[:, :, 3] == 255)
        rgba[mask] = [r, g, b, 255]
        self.sprite = Image.fromarray(rgba)

    def draw(self, image):
        image.paste(self.sprite, (int(self.x), int(self.y)), self.sprite)

        self.y += self.speed
        if self.y > 31:
            self.y -= 50
            self.load()


@planesign_mode_handler(DisplayMode.SNOWFALL)
def snowfall(sign):

    sign.canvas.Clear()

    flakes = []
    for i in range(30):
        flakes.append(SnowFlake())

    next_frame = time.perf_counter()
    while shared_config.shared_mode.value == DisplayMode.SNOWFALL.value:
        background = Image.new("RGB", (128, 32), (0, 0, 0))
        for f in flakes:
            if f.layer == 2:
                f.draw(background)
        for f in flakes:
            if f.layer == 1:
                f.draw(background)
        for f in flakes:
            if f.layer == 0:
                f.draw(background)
        sign.canvas.SetImage(background, 0, 0)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()
        # Keep a steady schedule, but never catch up by more than one frame after a stall.
        next_frame = max(next_frame + FRAME_INTERVAL, time.perf_counter() - FRAME_INTERVAL)
        if sign.wait_loop(max(0.0, next_frame - time.perf_counter())):
            return
