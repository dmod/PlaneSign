"""SSD1305 bonnet backend using the same canvas and BDF fonts as the web emulator."""

import logging
from contextlib import ExitStack

import shared_config
from emulated_matrix import graphics
from emulated_matrix.core import Canvas, RGBMatrixOptions
from emulated_matrix.server import FrameServer
from modes import DisplayMode
from PIL import Image, ImageChops

__all__ = ["RGBMatrix", "RGBMatrixOptions", "graphics"]

logger = logging.getLogger(__name__)

ART_THRESHOLDS = {DisplayMode.AQUARIUM.value: 96, DisplayMode.PLANTS.value: 96, DisplayMode.HALLOWEEN.value: 96, DisplayMode.CCA.value: 96, DisplayMode.HORSE_RACE.value: 48, DisplayMode.OUTSIDE.value: 48}


def monochrome_image(image: Image.Image, *, threshold: int | None = None) -> Image.Image:
    if threshold is not None:
        return image.convert("L").point([0] * threshold + [255] * (256 - threshold)).convert("1", dither=Image.Dither.NONE)
    red, green, blue = image.split()
    intensity = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return intensity.point([0] + [255] * 255).convert("1", dither=Image.Dither.NONE)


class SSD1305Output:
    def __init__(self):
        import adafruit_ssd1305
        import board
        import busio
        import digitalio

        with ExitStack() as resources:
            reset = digitalio.DigitalInOut(board.D4)
            resources.callback(reset.deinit)
            i2c = busio.I2C(board.SCL, board.SDA)
            resources.callback(i2c.deinit)
            self._display = adafruit_ssd1305.SSD1305_I2C(128, 32, i2c, addr=0x3C, reset=reset)
            resources.callback(self._display.poweroff)
            self._resources = resources.pop_all()

    def set_brightness(self, brightness: int):
        self._display.contrast(round(brightness * 255 / 100))
        # poweron() resets the controller; toggle display enable without resetting its setup.
        self._display.write_cmd(0xAF if brightness else 0xAE)

    def show(self, image: Image.Image):
        self._display.image(image)
        self._display.show()

    def close(self):
        self._resources.close()


class RGBMatrix(Canvas):
    """RGBMatrix-compatible OLED output, or a monochrome preview with --web."""

    monochrome = True

    def __init__(self, options: RGBMatrixOptions | None = None, **kwargs):
        if options is None:
            options = RGBMatrixOptions()
            options.chain_length = 2
        width, height = options.cols * options.chain_length, options.rows
        if (width, height) != (128, 32) or options.parallel != 1:
            raise ValueError("The Adafruit OLED bonnet requires a single 128x32 canvas")

        super().__init__(width, height)
        self._brightness = max(0, min(100, options.brightness))
        self._last_written: bytes | None = None
        self._frame_server: FrameServer | None = None
        with ExitStack() as resources:
            self._output = None if shared_config.emulated_display else SSD1305Output()
            if self._output is not None:
                resources.callback(self._output.close)
                self._output.set_brightness(self._brightness)
            else:
                self._frame_server = FrameServer(width, height)
                self._frame_server.start()
            resources.pop_all()
        if self._frame_server is not None:
            logger.info("SSD1305 OLED preview initialized: 128x32, streaming on port %d", self._frame_server.port)
        else:
            logger.info("SSD1305 OLED bonnet initialized: 128x32, I2C address 0x3c")

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        value = max(0, min(100, value))
        if value == self._brightness:
            return
        if self._output is not None:
            self._output.set_brightness(value)
        self._brightness = value
        self._present()

    def CreateFrameCanvas(self) -> Canvas:
        return Canvas(self.width, self.height)

    def SwapOnVSync(self, canvas: Canvas, framerate_fraction: int = 1) -> Canvas:
        self._image = canvas._image.copy()
        self._present()
        return canvas

    def _present(self):
        threshold = ART_THRESHOLDS.get(shared_config.shared_mode.value)
        image = monochrome_image(self._image, threshold=threshold) if self._brightness else Image.new("1", (self.width, self.height))
        frame = image.tobytes()
        if self._output is not None and frame != self._last_written:
            self._output.show(image)
            self._last_written = frame
        if self._frame_server is not None:
            self._frame_server.broadcast(image.convert("RGBA").tobytes())

    def Clear(self):
        super().Clear()
        self._present()

    def Fill(self, red: int, green: int, blue: int):
        super().Fill(red, green, blue)
        self._present()

    def SetPixel(self, x: int, y: int, red: int, green: int, blue: int):
        super().SetPixel(x, y, red, green, blue)
        self._present()

    def SetImage(self, image, offset_x: int = 0, offset_y: int = 0, unsafe: bool = True):
        super().SetImage(image, offset_x, offset_y, unsafe)
        self._present()

    def close(self):
        if self._output is not None:
            self._output.close()
