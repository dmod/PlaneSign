import logging
import os
import time

import shared_config
from modes import DisplayMode
from rgbmatrix import RGBMatrix, RGBMatrixOptions, graphics


class PlaneSign:
    # Brightness has no change notification so it still has to be polled; forced updates
    # interrupt the wait immediately and are unaffected by this cadence.
    BRIGHTNESS_POLL_INTERVAL = 0.05

    def __init__(self, defined_mode_handlers):
        options = RGBMatrixOptions()
        options.cols = 64
        options.gpio_slowdown = int(shared_config.CONF["GPIO_SLOWDOWN"])
        options.chain_length = 2
        options.limit_refresh_rate_hz = 120
        options.hardware_mapping = shared_config.CONF["PINOUT_HARDWARE_MAPPING"]
        options.led_rgb_sequence = shared_config.CONF["RGB_SEQUENCE"]
        options.drop_privileges = False

        self.matrix = RGBMatrix(options=options)
        self.canvas = self.matrix.CreateFrameCanvas()

        self.defined_mode_handlers = defined_mode_handlers

        self.font57 = graphics.Font()
        self.font46 = graphics.Font()
        self.fontbig = graphics.Font()
        self.fontreallybig = graphics.Font()
        self.fontplanesign = graphics.Font()
        self.font57.LoadFont(os.path.join(shared_config.font_dir, "5x7.bdf"))
        self.font46.LoadFont(os.path.join(shared_config.font_dir, "4x6.bdf"))
        self.fontbig.LoadFont(os.path.join(shared_config.font_dir, "6x13.bdf"))
        self.fontreallybig.LoadFont(os.path.join(shared_config.font_dir, "9x18B.bdf"))
        self.fontplanesign.LoadFont(os.path.join(shared_config.font_dir, "helvR12.bdf"))

        shared_config.shared_current_brightness.value = int(shared_config.CONF["DEFAULT_BRIGHTNESS"])

        self.canvas.brightness = shared_config.shared_current_brightness.value

        self.matrix.brightness = shared_config.shared_current_brightness.value

        self.last_brightness = shared_config.shared_current_brightness.value

    # Call this with a positive value to stay within the loop for that specificed amount of time
    # Call this with -1 to stay in the loop forever or until shared_forced_sign_update is set
    def wait_loop(self, seconds):
        exit_loop_time = time.perf_counter() + seconds

        forced_breakout = False

        while True:
            brightness = shared_config.shared_current_brightness.value
            if brightness != self.last_brightness:
                self.matrix.brightness = brightness
                self.last_brightness = brightness

            timeout = self.BRIGHTNESS_POLL_INTERVAL
            if seconds != -1:
                timeout = min(exit_loop_time - time.perf_counter(), timeout)

            # Returns True immediately if already set, so a forced update never waits out the poll interval.
            if shared_config.shared_forced_sign_update.wait(max(timeout, 0)):
                logging.debug("Forcing breakout")
                forced_breakout = True
                break

            if timeout <= 0:
                break

        shared_config.shared_forced_sign_update.clear()
        return forced_breakout

    def sign_loop(self):

        while not shared_config.shared_shutdown_event.is_set():
            try:
                display_mode = DisplayMode(shared_config.shared_mode.value)  # Convert int to enum
                if display_mode in self.defined_mode_handlers:
                    logging.info(f"Setting mode to {display_mode.name}")
                    self.defined_mode_handlers[display_mode](self)
                else:
                    logging.error(f"Mode {display_mode.name} has no handler defined...")
                    shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value

            except KeyboardInterrupt:
                logging.info("KeyboardInterrupt received, shutting down sign loop...")
                shared_config.shared_shutdown_event.set()
                break
            except Exception:
                logging.exception("General error in main loop, waiting...")
                time.sleep(3)
                shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value  # Reset to default mode

        logging.info("--- END OF SIGN LOOP ---")
