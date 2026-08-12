import time

import shared_config
from modes import DisplayMode
from rgbmatrix import graphics
from utilities import get_centered_text_x_offset_value, get_mac_id

import __main__

IDENTIFY_DURATION_SECONDS = 8
FLASH_HZ = 2.5
# Saturated but not full-white, so the panel is obvious from across a room without
# driving every channel at max.
FLASH_COLORS = [(0, 200, 255), (255, 40, 200), (60, 255, 90), (255, 170, 0)]


@__main__.planesign_mode_handler(DisplayMode.IDENTIFY)
def identify(self, duration=IDENTIFY_DURATION_SECONDS):
    """Transient mode: flash the whole matrix so a user can tell which sign they're talking to."""

    device_name = f"PlaneSign-BLE-{get_mac_id()}"
    device_name_x = int(get_centered_text_x_offset_value(5, device_name))

    label = "IDENTIFY"
    label_x = int(get_centered_text_x_offset_value(6, label))

    start_time = time.perf_counter()
    interrupted = False

    while True:
        elapsed = time.perf_counter() - start_time
        if shared_config.shared_forced_sign_update.is_set():
            shared_config.shared_forced_sign_update.clear()
            interrupted = True
            break
        if elapsed >= duration:
            break

        cycle = elapsed * FLASH_HZ
        r, g, b = FLASH_COLORS[int(cycle) % len(FLASH_COLORS)]
        filled = (cycle % 1.0) < 0.5

        if filled:
            self.canvas.Fill(r, g, b)
            text_color = graphics.Color(0, 0, 0)
        else:
            self.canvas.Clear()
            text_color = graphics.Color(r, g, b)

        graphics.DrawText(self.canvas, self.fontbig, label_x, 13, text_color, label)
        graphics.DrawText(self.canvas, self.font57, device_name_x, 26, text_color, device_name)

        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        time.sleep(0.02)

    self.canvas.Clear()
    self.canvas = self.matrix.SwapOnVSync(self.canvas)

    # A forced update means someone else already picked the next mode, so leave it alone.
    if not interrupted:
        shared_config.shared_mode.value = shared_config.shared_identify_return_mode.value
