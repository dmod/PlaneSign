"""
Drop-in replacement for rgbmatrix.graphics.

Provides Color, Font (with BDF parser), DrawText, and DrawLine that
render onto the emulated Canvas backed by a PIL Image.

The BDF parsing and glyph rendering logic mirrors the C++ implementation
in rpi-rgb-led-matrix/lib/bdf-font.cc to produce pixel-identical output.
"""

import re


class Color:
    """RGB color value, matching rgbmatrix.graphics.Color API."""

    __slots__ = ("red", "green", "blue")

    def __init__(self, red: int = 0, green: int = 0, blue: int = 0):
        self.red = int(red) & 0xFF
        self.green = int(green) & 0xFF
        self.blue = int(blue) & 0xFF


class _Glyph:
    """Parsed glyph from a BDF font file."""

    __slots__ = ("width", "height", "x_offset", "y_offset",
                 "device_width", "bitmap")

    def __init__(self):
        self.width = 0
        self.height = 0
        self.x_offset = 0
        self.y_offset = 0
        self.device_width = 0
        # bitmap: list of list[bool], each row is a list of pixel-on flags
        # row[0] is the topmost row, columns indexed 0..device_width-1
        self.bitmap: list[list[bool]] = []


class Font:
    """BDF font loader and glyph renderer, matching rgbmatrix.graphics.Font API."""

    def __init__(self):
        self._glyphs: dict[int, _Glyph] = {}
        self._font_height: int = -1
        self._base_line: int = 0

    @property
    def height(self) -> int:
        return self._font_height

    @property
    def baseline(self) -> int:
        return self._base_line

    def LoadFont(self, path: str) -> None:
        """Parse a BDF font file — mirrors rpi-rgb-led-matrix bdf-font.cc."""
        self._glyphs.clear()
        self._font_height = -1
        self._base_line = 0

        with open(path, "r") as f:
            codepoint = 0
            tmp_device_width = 0
            tmp_width = 0
            tmp_height = 0
            tmp_x_offset = 0
            tmp_y_offset = 0
            current_glyph: _Glyph | None = None
            row = -1
            in_bitmap = False

            for line in f:
                line = line.strip()

                # FONTBOUNDINGBOX w h xoff yoff
                m = re.match(r"FONTBOUNDINGBOX\s+(\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)", line)
                if m:
                    self._font_height = int(m.group(2))
                    self._base_line = int(m.group(4)) + int(m.group(2))
                    continue

                # ENCODING <codepoint>
                m = re.match(r"ENCODING\s+(\d+)", line)
                if m:
                    codepoint = int(m.group(1))
                    continue

                # DWIDTH <x> <y>
                m = re.match(r"DWIDTH\s+(\d+)\s+(\d+)", line)
                if m:
                    tmp_device_width = int(m.group(1))
                    continue

                # BBX <w> <h> <xoff> <yoff>
                m = re.match(r"BBX\s+(\d+)\s+(\d+)\s+(-?\d+)\s+(-?\d+)", line)
                if m:
                    tmp_width = int(m.group(1))
                    tmp_height = int(m.group(2))
                    tmp_x_offset = int(m.group(3))
                    tmp_y_offset = int(m.group(4))
                    current_glyph = _Glyph()
                    current_glyph.width = tmp_width
                    current_glyph.height = tmp_height
                    current_glyph.x_offset = tmp_x_offset
                    current_glyph.y_offset = tmp_y_offset
                    current_glyph.device_width = tmp_device_width
                    current_glyph.bitmap = []
                    row = -1
                    in_bitmap = False
                    continue

                if line == "BITMAP":
                    row = 0
                    in_bitmap = True
                    continue

                if line == "ENDCHAR":
                    if current_glyph is not None and row == current_glyph.height:
                        self._glyphs[codepoint] = current_glyph
                    current_glyph = None
                    in_bitmap = False
                    continue

                # Bitmap row data (hex string)
                if in_bitmap and current_glyph is not None and 0 <= row < current_glyph.height:
                    row_bits = self._parse_bitmap_row(line, current_glyph.x_offset,
                                                     current_glyph.device_width)
                    current_glyph.bitmap.append(row_bits)
                    row += 1

    @staticmethod
    def _parse_bitmap_row(hex_str: str, x_offset: int, device_width: int) -> list[bool]:
        """Parse a hex bitmap row, applying x_offset shift to match rgbmatrix behavior.

        The C++ code stores bits MSB-first in a large bitset, then shifts right
        by x_offset. When rendering, it tests bit (kMaxFontWidth - 1 - x) for
        column x. The net effect is that the hex data describes the glyph
        left-aligned within the BBX width, and x_offset shifts the rendered
        output rightward within the device_width.

        We replicate this by converting hex to bits, shifting right by x_offset,
        and extracting the leftmost device_width bits.
        """
        # Convert hex string to integer
        value = int(hex_str, 16)
        total_bits = len(hex_str) * 4  # each hex char = 4 bits

        # Extract bits from MSB to LSB, producing a list of booleans
        # that represents the full hex row
        all_bits = []
        for i in range(total_bits - 1, -1, -1):
            all_bits.append(bool(value & (1 << i)))

        # Apply x_offset shift: shift the pattern right by x_offset positions
        # This matches the C++ `bitmap[row] >>= x_offset`
        if x_offset > 0:
            all_bits = [False] * x_offset + all_bits
        elif x_offset < 0:
            all_bits = all_bits[abs(x_offset):]

        # Take the first device_width bits (what gets rendered)
        result = []
        for x in range(device_width):
            if x < len(all_bits):
                result.append(all_bits[x])
            else:
                result.append(False)
        return result

    def CharacterWidth(self, char_code: int) -> int:
        """Return the device width (advance) of a character."""
        glyph = self._glyphs.get(char_code)
        if glyph is None:
            glyph = self._glyphs.get(0xFFFD)  # replacement character
        if glyph is None:
            return 0
        return glyph.device_width

    def DrawGlyph(self, canvas, x_pos: int, y_pos: int, color: Color, char_code: int) -> int:
        """Render a single glyph onto the canvas. Returns the device width (advance)."""
        glyph = self._glyphs.get(char_code)
        if glyph is None:
            glyph = self._glyphs.get(0xFFFD)
        if glyph is None:
            return 0

        # Matches C++: y_pos = y_pos - g->height - g->y_offset
        render_y = y_pos - glyph.height - glyph.y_offset

        for row_idx, row_bits in enumerate(glyph.bitmap):
            py = render_y + row_idx
            for col_idx, is_set in enumerate(row_bits):
                if is_set:
                    canvas.SetPixel(x_pos + col_idx, py,
                                    color.red, color.green, color.blue)

        return glyph.device_width


def DrawText(canvas, font: Font, x: int, y: int, color: Color, text: str) -> int:
    """Draw text onto canvas. Returns the total advance width (pixels).

    Matches rgbmatrix.graphics.DrawText signature and return value.
    The y parameter is the text baseline.
    """
    start_x = x
    for char in text:
        x += font.DrawGlyph(canvas, x, y, color, ord(char))
    return x - start_x


def DrawLine(canvas, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
    """Draw a line using Bresenham's algorithm, matching rgbmatrix behavior."""
    dx = x1 - x0
    dy = y1 - y0
    shift = 0x10

    if abs(dx) > abs(dy):
        if x1 < x0:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        if dx == 0:
            canvas.SetPixel(x0, y0, color.red, color.green, color.blue)
            return
        gradient = (dy << shift) // dx
        y = 0x8000 + (y0 << shift)
        for x in range(x0, x1 + 1):
            canvas.SetPixel(x, y >> shift, color.red, color.green, color.blue)
            y += gradient
    elif dy != 0:
        if y1 < y0:
            x0, x1 = x1, x0
            y0, y1 = y1, y0
        gradient = (dx << shift) // dy
        x = 0x8000 + (x0 << shift)
        for y in range(y0, y1 + 1):
            canvas.SetPixel(x >> shift, y, color.red, color.green, color.blue)
            x += gradient
    else:
        canvas.SetPixel(x0, y0, color.red, color.green, color.blue)
