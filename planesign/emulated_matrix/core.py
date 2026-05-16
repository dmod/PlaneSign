"""
Drop-in replacements for rgbmatrix.RGBMatrix, RGBMatrixOptions, and FrameCanvas.

Canvas is backed by a PIL Image. SwapOnVSync broadcasts the frame to
connected WebSocket display clients via the FrameServer.
"""

import logging

from PIL import Image

from emulated_matrix.server import FrameServer

logger = logging.getLogger(__name__)


class RGBMatrixOptions:
    """Accepts any attribute assignment — hardware options are ignored."""

    def __init__(self):
        self.rows = 32
        self.cols = 64
        self.chain_length = 1
        self.parallel = 1
        self.hardware_mapping = ""
        self.gpio_slowdown = 1
        self.pwm_bits = 11
        self.brightness = 100
        self.scan_mode = 0
        self.row_address_type = 0
        self.multiplexing = 0
        self.disable_hardware_pulsing = False
        self.show_refresh_rate = False
        self.inverse_colors = False
        self.led_rgb_sequence = "RGB"
        self.pixel_mapper_config = ""
        self.panel_type = ""
        self.limit_refresh_rate_hz = 0
        self.drop_privileges = True


class Canvas:
    """PIL Image-backed canvas matching rgbmatrix FrameCanvas API."""

    def __init__(self, width: int, height: int):
        self._width = width
        self._height = height
        self._image = Image.new("RGB", (width, height), (0, 0, 0))
        self._brightness = 100

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        self._brightness = max(0, min(255, value))

    def Clear(self):
        self._image = Image.new("RGB", (self._width, self._height), (0, 0, 0))

    def Fill(self, red: int, green: int, blue: int):
        self._image = Image.new("RGB", (self._width, self._height), (red, green, blue))

    def SetPixel(self, x: int, y: int, red: int, green: int, blue: int):
        x, y = int(x), int(y)
        if 0 <= x < self._width and 0 <= y < self._height:
            self._image.putpixel((x, y), (int(red), int(green), int(blue)))

    def SetImage(self, image, offset_x: int = 0, offset_y: int = 0, unsafe: bool = True):
        """Paste a PIL Image onto the canvas, matching rgbmatrix SetImage behavior."""
        if image.mode != "RGB":
            raise ValueError(
                "Currently, only RGB mode is supported for SetImage(). "
                "Please create images with mode 'RGB' or convert first with "
                "image = image.convert('RGB')."
            )
        img_width, img_height = image.size
        for x in range(max(0, -offset_x), min(img_width, self._width - offset_x)):
            for y in range(max(0, -offset_y), min(img_height, self._height - offset_y)):
                r, g, b = image.getpixel((x, y))
                self._image.putpixel((x + offset_x, y + offset_y), (r, g, b))

    def _get_rgba_bytes(self) -> bytes:
        """Return the canvas content as raw RGBA bytes for WebSocket streaming."""
        return self._image.convert("RGBA").tobytes()


class RGBMatrix:
    """Emulated RGB matrix that streams frames via WebSocket instead of driving hardware."""

    def __init__(self, options: RGBMatrixOptions | None = None, **kwargs):
        if options is None:
            options = RGBMatrixOptions()

        self._width = options.cols * options.chain_length
        self._height = options.rows if hasattr(options, "rows") else 32
        self._brightness = getattr(options, "brightness", 100)

        self._frame_server = FrameServer()
        self._frame_server.start()

        logger.info(
            "Emulated RGB matrix initialized: %dx%d, streaming on ws://0.0.0.0:5001",
            self._width, self._height,
        )

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def brightness(self) -> int:
        return self._brightness

    @brightness.setter
    def brightness(self, value: int):
        self._brightness = max(0, min(255, value))

    def CreateFrameCanvas(self) -> Canvas:
        return Canvas(self._width, self._height)

    def SwapOnVSync(self, canvas: Canvas, framerate_fraction: int = 1) -> Canvas:
        """Broadcast the current frame to WebSocket clients and return the canvas."""
        self._frame_server.broadcast(canvas._get_rgba_bytes())
        return canvas

    def Clear(self):
        pass

    def Fill(self, red: int, green: int, blue: int):
        pass

    def SetPixel(self, x: int, y: int, red: int, green: int, blue: int):
        pass
