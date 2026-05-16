import time
import math
import random
import shared_config
from rgbmatrix import graphics
from utilities import get_centered_text_x_offset_value, get_mac_id, get_version
import __main__

from modes import DisplayMode


@__main__.planesign_mode_handler(DisplayMode.WELCOME)
def welcome(self, duration=None):

    device_name = f"PlaneSign-BLE-{get_mac_id()}"
    device_name_x = int(get_centered_text_x_offset_value(4, device_name))

    version_str = f"v{get_version()}"
    version_x = int(get_centered_text_x_offset_value(4, version_str))

    title = "Plane Sign"
    title_x = 34
    title_y = 12

    # Shimmer / gloss parameters
    base_r, base_g = 46, 210
    shimmer_width = 22
    sweep_start = title_x - shimmer_width
    sweep_end = title_x + 85 + shimmer_width
    sweep_range = sweep_end - sweep_start
    sweep_speed_1 = 90  # primary sweep speed
    sweep_speed_2 = 55  # secondary slower sweep

    # Sparkle setup — stars across the entire 128x32 matrix (night sky)
    star_spots = []
    for _ in range(80):
        sx = random.randint(0, 127)
        sy = random.randint(0, 31)
        phase = random.random() * math.pi * 2
        speed = 1.5 + random.random() * 4.0
        max_bright = random.randint(30, 120)  # dim background stars
        star_spots.append((sx, sy, phase, speed, max_bright))

    # Brighter sparkle stars scattered across the matrix
    for _ in range(25):
        sx = random.randint(0, 127)
        sy = random.randint(0, 31)
        phase = random.random() * math.pi * 2
        speed = 3.0 + random.random() * 4.0
        max_bright = random.randint(140, 255)  # bright twinkle stars
        star_spots.append((sx, sy, phase, speed, max_bright))

    start_time = time.perf_counter()

    while True:
        elapsed = time.perf_counter() - start_time
        if shared_config.shared_forced_sign_update.value == 1:
            shared_config.shared_forced_sign_update.value = 0
            break
        if duration is not None and elapsed >= duration:
            break

        self.canvas.Clear()

        # Draw twinkling night sky background across entire matrix
        for sx, sy, phase, speed, max_bright in star_spots:
            brightness = (math.sin(elapsed * speed + phase) + 1.0) / 2.0  # 0..1
            brightness = brightness**2.0  # sharpen the twinkle
            if brightness > 0.15:
                sv = int(max_bright * brightness)
                self.canvas.SetPixel(sx, sy, sv, sv, sv)

        # Two shimmer positions for richer effect
        shimmer_pos_1 = sweep_start + ((elapsed * sweep_speed_1) % sweep_range)
        shimmer_pos_2 = sweep_end - ((elapsed * sweep_speed_2) % sweep_range)

        # Draw title character by character with dual shimmer + bold (double draw with 1px x-offset)
        cx = title_x
        for ch in title:
            char_mid = cx + 4

            # Combine two shimmer streaks
            dist1 = abs(char_mid - shimmer_pos_1)
            dist2 = abs(char_mid - shimmer_pos_2)

            t = 0.0
            if dist1 < shimmer_width:
                t1 = 1.0 - (dist1 / shimmer_width)
                t = max(t, t1 * t1)
            if dist2 < shimmer_width:
                t2 = 1.0 - (dist2 / shimmer_width)
                t2 = t2 * t2 * 0.7  # secondary shimmer slightly dimmer
                t = max(t, t2)

            r = int(base_r + (255 - base_r) * t)
            g = int(base_g + (255 - base_g) * t)
            b = 255

            color = graphics.Color(r, g, b)
            # Bold: draw at cx and cx+1 for a faux-bold effect
            graphics.DrawText(self.canvas, self.fontplanesign, cx, title_y, color, ch)
            adv = graphics.DrawText(self.canvas, self.fontplanesign, cx + 1, title_y, color, ch)
            cx += adv

        # Device name and version below
        graphics.DrawText(self.canvas, self.font46, device_name_x, 22, graphics.Color(150, 150, 150), device_name)
        graphics.DrawText(self.canvas, self.font46, version_x, 30, graphics.Color(100, 100, 100), version_str)

        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        time.sleep(0.025)  # ~40fps

    self.canvas.Clear()
