"""Boot welcome screen: an 80's Outrun sunset with a chrome PLANE SIGN title.

Frames are composed in a numpy array and pushed with SetImage. The scenery that never moves is
built once; each frame only adds the grid rows, stars, title, streak and version number on top.
"""

import math
import os
import time
from functools import cache

import numpy as np
import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image, ImageDraw, ImageFont
from utilities import get_version

WIDTH, HEIGHT = 128, 32
FRAME_INTERVAL = 1 / 40

# Timeline, in seconds from the start of the screen
FADE_IN = 0.5
TITLE_START, TITLE_SLIDE = 0.2, 0.75
STREAK_START, STREAK_DRAW, STREAK_FADE, STREAK_FLASH = 1.1, 0.45, 0.4, 0.5
BEACON_DELAY, BEACON_PERIOD, BEACON_BLINK = 0.6, 1.3, 0.12
SUBTITLE_START, SUBTITLE_FADE = 2.0, 0.4
# The glint wipes across the title column by column: each column lights fully as the leading edge reaches it,
# stays lit for about a letter's width behind the edge, then fades out over the trail
GLINT_SPEED, GLINT_WIDTH, GLINT_TRAIL, GLINT_PAUSE = 50, 9, 5, 0.6  # columns per second, columns, columns, seconds

HORIZON = 20  # the bright horizon row: sky and sun above, grid floor below
CENTER_X = (WIDTH - 1) / 2
SKY = [(0, (6, 0, 24)), (0.55, (50, 0, 80)), (1, (150, 10, 110))]
SUN_RADIUS = 13
SUN_TOP, SUN_BOTTOM = (255, 225, 60), (255, 30, 140)
SUN_BANDS = ((1, 2), (2, 1), (2, 1))  # (solid, gap) row pairs, counted up from the horizon
FLOOR = (18, 0, 32)
GRID_LINES, GRID_SPACING = 6, 24  # converging lines each side of centre, and their spacing on the bottom row
GRID_ROWS, GRID_SPEED = 6, 1.6
GRID_V, GRID_H, HORIZON_COLOR = (150, 0, 210), (230, 0, 255), (255, 70, 210)

TITLE = "PLANE SIGN"
TITLE_TOP = 5
TITLE_SLANT = 0.4  # italic shear, in pixels per row
# One color per ink row of the 9x18B capitals: sky-blue chrome, a dark horizon line, then gold
CHROME = [(235, 250, 255), (190, 230, 255), (140, 200, 255), (90, 150, 245), (40, 70, 180), (110, 30, 40), (230, 100, 30), (255, 160, 60), (255, 210, 130), (255, 245, 210)]
SPEED_LINES = (0, 220, 255)

STREAK_ROW = 2
SUBTITLE_TOP = 25
SUBTITLE_COLOR = (255, 235, 255)

# Fixed star positions; the seed only keeps them the same on every boot
_stars = np.random.default_rng(1986)
STAR_X = _stars.integers(0, WIDTH - 1, 22)
STAR_Y = _stars.integers(0, 12, 22)
STAR_PHASE = _stars.uniform(0, 2 * math.pi, 22)


def _clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def _lerp(a, b, t):
    return a + (b - a) * t


def _ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def _ease_in_out_sine(p):
    return 0.5 - 0.5 * math.cos(math.pi * p)


def _round(value):
    # round() rounds halves to even, which makes lines through .5 coordinates skip pixels
    return math.floor(value + 0.5)


def _gradient(stops, rows):
    positions = [position for position, _ in stops]
    v = np.linspace(0, 1, rows)
    return np.stack([np.interp(v, positions, [color[channel] for _, color in stops]) for channel in range(3)], axis=1)


def _text_mask(font_file, text, bold=False):
    """Ink mask of text, cropped to its ink. The bundled .pil fonts match the BDF glyphs pixel for pixel."""
    font = ImageFont.load(os.path.join(shared_config.font_dir, font_file))
    image = Image.new("1", (len(text) * 12 + 8, 32))
    ImageDraw.Draw(image).text((2, 2), text, font=font, fill=1)
    mask = np.array(image, dtype=bool)
    if bold:  # faux bold: thicken every stroke one pixel to the right
        mask[:, 1:] = mask[:, 1:] | mask[:, :-1]
    rows, cols = np.nonzero(mask)
    return mask[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]


def _shear(mask, slope):
    """Slant a mask into italics: each row moves right by its height above the bottom row times slope."""
    height, width = mask.shape
    out = np.zeros((height, width + _round((height - 1) * slope)), bool)
    for row in range(height):
        shift = _round((height - 1 - row) * slope)
        out[row, shift : shift + width] = mask[row]
    return out


def _outline(mask):
    """The mask grown by one pixel all round; draw it one pixel up and left of the mask."""
    height, width = mask.shape
    out = np.zeros((height + 2, width + 2), bool)
    for dy in range(3):
        for dx in range(3):
            out[dy : dy + height, dx : dx + width] |= mask
    return out


def _paint(frame, mask, x, y, color, alpha=1.0):
    """Blend color into frame wherever mask is set. color is one RGB value or one per mask pixel."""
    height, width = mask.shape
    x, y = _round(x), _round(y)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(WIDTH, x + width), min(HEIGHT, y + height)
    if x0 >= x1 or y0 >= y1:
        return
    inside = mask[y0 - y : y1 - y, x0 - x : x1 - x]
    color = np.asarray(color, np.float32)
    if color.ndim == 3:
        color = color[y0 - y : y1 - y, x0 - x : x1 - x][inside]
    region = frame[y0:y1, x0:x1]
    region[inside] = region[inside] * (1 - alpha) + color * alpha


def _light(frame, x, y, color):
    """Brighten one pixel toward color, keeping whichever channels are already brighter."""
    x, y = _round(x), _round(y)
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        np.maximum(frame[y, x], color, out=frame[y, x])


def _scenery(monochrome):
    """The backdrop that never moves (sky, banded sun, floor, converging grid lines, horizon) and the sun's mask.

    A monochrome display lights every non-black pixel, so there the sky and floor stay black.
    """
    frame = np.zeros((HEIGHT, WIDTH, 3), np.float32)
    if not monochrome:
        frame[:HORIZON] = _gradient(SKY, HORIZON)[:, None, :]

    gaps, row = set(), HORIZON - 1
    for solid, gap in SUN_BANDS:
        row -= solid
        gaps.update(range(row - gap + 1, row + 1))
        row -= gap
    sun = np.zeros((HEIGHT, WIDTH), bool)
    top = HORIZON - SUN_RADIUS
    for y in range(top, HORIZON):
        if y in gaps:
            continue
        half = math.sqrt(SUN_RADIUS**2 - (HORIZON - y - 0.5) ** 2)
        x0, x1 = int(CENTER_X - half + 0.5), int(CENTER_X + half + 0.5) + 1
        sun[y, x0:x1] = True
        frame[y, x0:x1] = _lerp(np.array(SUN_TOP), np.array(SUN_BOTTOM), (y - top) / (SUN_RADIUS - 1))

    depth = HEIGHT - 1 - HORIZON
    if not monochrome:
        frame[HORIZON + 1 :] = FLOOR
    for k in range(-GRID_LINES, GRID_LINES + 1):
        for y in range(HORIZON + 1, HEIGHT):
            brightness = _clamp(0.3 + (y - HORIZON) / depth)
            _light(frame, CENTER_X + k * GRID_SPACING * (y - HORIZON) / depth, y, np.multiply(GRID_V, brightness))
    frame[HORIZON] = HORIZON_COLOR
    return frame, sun


class WelcomeScene:
    """Everything about the welcome screen that can be worked out once, plus render() for each frame."""

    def __init__(self, version, monochrome=False):
        self.background, sun = _scenery(monochrome)
        behind_sun = sun[STAR_Y, STAR_X]
        self.star_x, self.star_y, self.star_phase = STAR_X[~behind_sun], STAR_Y[~behind_sun], STAR_PHASE[~behind_sun]

        self.title = _shear(_text_mask("9x18B.pil", TITLE, bold=True), TITLE_SLANT)
        self.title_outline = _outline(self.title)
        self.title_x = (WIDTH - self.title.shape[1]) // 2
        self.chrome = np.repeat(np.array(CHROME, np.float32)[:, None, :], self.title.shape[1], axis=1)
        if monochrome:  # the chrome's dark horizon row would cut the letters in half
            self.chrome[:] = 255
        self.title_columns = np.arange(self.title.shape[1])
        # A sweep runs until its trail has left the last column, then pauses before the next one
        self.glint_period = (self.title.shape[1] + GLINT_WIDTH + GLINT_TRAIL) / GLINT_SPEED + GLINT_PAUSE
        # Every third row trails a speed line from its leftmost ink while the title slides in
        self.speed_rows = [(row, int(np.argmax(self.title[row]))) for row in range(1, self.title.shape[0], 3) if self.title[row].any()]
        # One pixel right of the top-right corner of the final N
        self.streak_end = self.title_x + int(np.nonzero(self.title[0])[0].max()) + 1

        self.subtitle = _text_mask("4x6.pil", version)
        self.subtitle_outline = _outline(self.subtitle)
        self.subtitle_x = (WIDTH - self.subtitle.shape[1]) // 2
        self.monochrome = monochrome

    def render(self, t):
        """The frame t seconds after the screen started, as a (HEIGHT, WIDTH, 3) uint8 array."""
        fade = _clamp(t / FADE_IN)
        frame = self.background * fade

        twinkle = (0.5 + 0.5 * np.sin(t * 3 + self.star_phase)) * 140 * fade
        if self.monochrome:  # dim pixels still light up fully, so twinkle by switching stars on and off
            twinkle = np.where(twinkle > 70, 140, 0)
        stars = twinkle[:, None] * np.array([1, 0.8, 1])
        frame[self.star_y, self.star_x] = np.maximum(frame[self.star_y, self.star_x], stars)

        depth = HEIGHT - 1 - HORIZON
        for i in range(GRID_ROWS):  # horizontal grid lines rushing toward the viewer
            z = (i - t * GRID_SPEED) % GRID_ROWS + 0.8
            y = HORIZON + depth * 0.8 / z
            if y >= HEIGHT:
                continue
            brightness = _clamp((y - HORIZON) / depth) ** 0.8 * fade
            row = int(y)
            rows = ((row, 1 - (y - row)), (row + 1, y - row))  # anti-aliased across two rows
            if self.monochrome:  # anti-aliasing would light both rows, so use one and drop the faint lines near the horizon
                rows = ((_round(y), 1.0),) if brightness > 0.25 else ()
            for r, weight in rows:
                if HORIZON < r < HEIGHT:
                    np.maximum(frame[r], np.multiply(GRID_H, brightness * weight), out=frame[r])

        self._draw_title(frame, t)
        self._draw_streak(frame, t)
        self._draw_subtitle(frame, t)
        return np.clip(frame, 0, 255).astype(np.uint8)

    def _draw_title(self, frame, t):
        progress = _clamp((t - TITLE_START) / TITLE_SLIDE)
        x = _lerp(-self.title.shape[1] - 10, self.title_x, _ease_out_cubic(progress))
        if 0 < progress < 1:  # speed lines that shrink as the title slows down
            length = 70 * (1 - progress) ** 2
            steps = np.arange(int(length))
            colors = (1 - steps / max(1.0, length))[:, None] * np.array(SPEED_LINES)
            for row, left in self.speed_rows:
                xs = np.floor(x + left - 2 - steps + 0.5).astype(int)
                keep = (xs >= 0) & (xs < WIDTH)
                y = TITLE_TOP + row
                frame[y, xs[keep]] = np.maximum(frame[y, xs[keep]], colors[keep])

        colors = self.chrome
        if progress >= 1:  # a white glint wipes across the title, one full-height column at a time
            edge = ((t - TITLE_START - TITLE_SLIDE) % self.glint_period) * GLINT_SPEED
            behind = edge - self.title_columns  # how far each column is behind the leading edge
            shine = np.clip(behind + 1, 0, 1) * np.clip(1 - (behind - GLINT_WIDTH) / GLINT_TRAIL, 0, 1)
            colors = colors + (255 - colors) * shine[None, :, None]
        _paint(frame, self.title_outline, x - 1, TITLE_TOP - 1, (0, 0, 0))
        _paint(frame, self.title, x, TITLE_TOP, colors)

    def _draw_streak(self, frame, t):
        """A white line drawn left to right above the title that lands in a flash and leaves a red beacon."""
        if t < STREAK_START:
            return
        arrive = STREAK_START + STREAK_DRAW
        head = self.streak_end * _ease_in_out_sine(_clamp((t - STREAK_START) / STREAK_DRAW))
        fade = 1.0 if t < arrive else _clamp(1 - (t - arrive) / STREAK_FADE)
        if fade > 0:
            xs = np.arange(_round(head) + 1)
            frame[STREAK_ROW, : len(xs)] = (255 * (0.25 + 0.75 * (xs / max(1.0, head)) ** 1.5) * fade)[:, None]
        if t < arrive:
            return

        since = t - arrive
        x, y = self.streak_end, STREAK_ROW
        if since < STREAK_FLASH:  # a four-point star glint that snaps open, then shrinks away
            size = _clamp(since / 0.07) * (1 - _clamp((since - 0.07) / (STREAK_FLASH - 0.07)))
            for arms, reach in ((((1, 0), (-1, 0)), 13 * size), (((0, 1), (0, -1)), 5 * size), (((1, 1), (-1, 1), (1, -1), (-1, -1)), 2 * size)):
                for i in range(1, math.ceil(reach) + 1):
                    a = 255 * min(1.0, size * 1.6) * (1 - (i - 1) / (reach + 0.5)) ** 1.3
                    for dx, dy in arms:
                        _light(frame, x + dx * i, y + dy * i, (a, a, a * 0.9))
        if 0.05 < since < 0.45:  # red shockwave ring
            q = (since - 0.05) / 0.4
            radius = 1.5 + 6 * _ease_out_cubic(q)
            for angle in np.linspace(0, 2 * math.pi, 48, endpoint=False):
                _light(frame, x + radius * math.cos(angle), y + radius * math.sin(angle), np.multiply((255, 60, 60), 1 - q))

        # The dot cools from white to red, then blinks like an aircraft beacon
        blinking = since > BEACON_DELAY and (since - BEACON_DELAY) % BEACON_PERIOD < BEACON_BLINK
        red = np.array((255.0 if blinking or since < BEACON_DELAY else 200.0, 0, 0))
        core = _lerp(np.array((255.0, 255, 255)), red, _clamp(since / 0.12))
        frame[y, x] = core
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            _light(frame, x + dx, y + dy, core * 0.6)
        if blinking:
            for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2), (1, 1), (-1, 1), (1, -1), (-1, -1)):
                _light(frame, x + dx, y + dy, (90, 0, 0))

    def _draw_subtitle(self, frame, t):
        alpha = _clamp((t - SUBTITLE_START) / SUBTITLE_FADE)
        if alpha > 0:
            _paint(frame, self.subtitle_outline, self.subtitle_x - 1, SUBTITLE_TOP - 1, (0, 0, 0), alpha)
            _paint(frame, self.subtitle, self.subtitle_x, SUBTITLE_TOP, SUBTITLE_COLOR, alpha)


@cache
def _scene(version, monochrome):
    return WelcomeScene(version, monochrome)


def draw_welcome_frame(sign, elapsed, version):
    """Draw the welcome screen as it looks elapsed seconds after it started."""
    scene = _scene(version, getattr(sign.matrix, "monochrome", False))
    sign.canvas.SetImage(Image.fromarray(scene.render(elapsed)), 0, 0)


@planesign_mode_handler(DisplayMode.WELCOME)
def welcome(self, duration=None):
    version = f"v{get_version()}"
    start = next_frame = time.perf_counter()
    while True:
        elapsed = time.perf_counter() - start
        if duration is not None and elapsed >= duration:
            break
        draw_welcome_frame(self, elapsed, version)
        self.canvas = self.matrix.SwapOnVSync(self.canvas)
        # Keep a steady schedule, but never catch up by more than one frame after a stall.
        next_frame = max(next_frame + FRAME_INTERVAL, time.perf_counter() - FRAME_INTERVAL)
        if self.wait_loop(max(0.0, next_frame - time.perf_counter())):
            break

    self.canvas.Clear()
