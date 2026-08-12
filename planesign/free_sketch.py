import shared_config
from modes import DisplayMode

import __main__

WIDTH = 128
HEIGHT = 32
CHANNELS = 3


@__main__.planesign_mode_handler(DisplayMode.FREE_SKETCH)
def free_sketch(sign):
    while shared_config.shared_mode.value == DisplayMode.FREE_SKETCH.value:
        pixel_buffer = shared_config.free_sketch_pixels.get_obj()
        with shared_config.free_sketch_pixels.get_lock():
            pixels = bytes(pixel_buffer)

        for y in range(HEIGHT):
            row_offset = y * WIDTH * CHANNELS
            for x in range(WIDTH):
                index = row_offset + x * CHANNELS
                sign.canvas.SetPixel(x, y, pixels[index], pixels[index + 1], pixels[index + 2])

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        if sign.wait_loop(0.03):
            return
