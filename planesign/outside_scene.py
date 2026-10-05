"""Quiet Valley pixel art. Static geometry is cached; only intended motion changes."""

import math
import os
import random
from dataclasses import dataclass, fields, replace
from datetime import datetime
from functools import lru_cache
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import shared_config
from emulated_matrix import graphics as bitmap_graphics
from emulated_matrix.core import Canvas
from PIL import Image, ImageDraw, ImageStat

if TYPE_CHECKING:
    from outside import OutsideEnvironment

Color = tuple[int, int, int]
WIDTH, HEIGHT = 128, 32
OVERLAY_DARK_LUMINANCE = 0.01
OVERLAY_BRIGHT_LUMINANCE = 0.10
OVERLAY_NIGHT_OPACITY = 0.60
OVERLAY_LINEAR_LUT = [round(255 * (value / 255 / 12.92 if value <= 10 else ((value / 255 + 0.055) / 1.055) ** 2.4)) for value in range(256)] * 3
# Black and white have equal contrast at this relative luminance.
OVERLAY_POLARITY_LUMINANCE = math.sqrt(0.05 * 1.05) - 0.05
OVERLAY_POLARITY_HYSTERESIS = 0.01
OVERLAY_GAP = 5
# Notices too wide for the space between the corner labels pause, then scroll.
NOTICE_SCROLL_SPEED = 12
NOTICE_SCROLL_PAUSE = 1.5
NOTICE_SCROLL_SPACING = 16
# OpenWeather condition descriptions; also the set of codes Outside accepts.
WEATHER_DESCRIPTIONS = {
    200: "thunderstorm with light rain",
    201: "thunderstorm with rain",
    202: "thunderstorm with heavy rain",
    210: "light thunderstorm",
    211: "thunderstorm",
    212: "heavy thunderstorm",
    221: "ragged thunderstorm",
    230: "thunderstorm with light drizzle",
    231: "thunderstorm with drizzle",
    232: "thunderstorm with heavy drizzle",
    300: "light intensity drizzle",
    301: "drizzle",
    302: "heavy intensity drizzle",
    310: "light intensity drizzle rain",
    311: "drizzle rain",
    312: "heavy intensity drizzle rain",
    313: "shower rain and drizzle",
    314: "heavy shower rain and drizzle",
    321: "shower drizzle",
    500: "light rain",
    501: "moderate rain",
    502: "heavy intensity rain",
    503: "very heavy rain",
    504: "extreme rain",
    511: "freezing rain",
    520: "light intensity shower rain",
    521: "shower rain",
    522: "heavy intensity shower rain",
    531: "ragged shower rain",
    600: "light snow",
    601: "snow",
    602: "heavy snow",
    611: "sleet",
    612: "light shower sleet",
    613: "shower sleet",
    615: "light rain and snow",
    616: "rain and snow",
    620: "light shower snow",
    621: "shower snow",
    622: "heavy shower snow",
    701: "mist",
    711: "smoke",
    721: "haze",
    731: "sand/dust whirls",
    741: "fog",
    751: "sand",
    761: "dust",
    762: "volcanic ash",
    771: "squalls",
    781: "tornado",
    800: "clear sky",
    801: "few clouds",
    802: "scattered clouds",
    803: "broken clouds",
    804: "overcast clouds",
}
# Clouds and precipitation dim the palette toward slate haze by cover * this amount.
WEATHER_DIM_CLOUDS = 0.0225
WEATHER_DIM_PRECIPITATION = 0.04
# Oklab grade tuned on the LED panel: art colors are muted slightly, then the finished
# frame gets deeper midtones and stronger saturation so the scene does not wash out.
PALETTE_CHROMA = 0.75
PALETTE_CONTRAST = 0.15
FRAME_BLACK_POINT = 0.03
FRAME_GAMMA = 1.36
FRAME_CONTRAST = 0.35
FRAME_CHROMA = 1.6
FRAME_VIBRANCE = 0.25
VIBRANCE_CHROMA = 0.16
SRGB_TO_LINEAR = tuple(value / 255 / 12.92 if value <= 10 else ((value / 255 + 0.055) / 1.055) ** 2.4 for value in range(256))
SRGB_TO_LINEAR_ARRAY = np.array(SRGB_TO_LINEAR)
LINEAR_TO_LMS = np.array([[0.4122214708, 0.5363325363, 0.0514459929], [0.2119034982, 0.6806995451, 0.1073969566], [0.0883024619, 0.2817188376, 0.6299787005]])
LMS_TO_OKLAB = np.array([[0.2104542553, 0.7936177850, -0.0040720468], [1.9779984951, -2.4285922050, 0.4505937099], [0.0259040371, 0.7827717662, -0.8086757660]])
OKLAB_TO_LMS = np.linalg.inv(LMS_TO_OKLAB)
LMS_TO_LINEAR = np.linalg.inv(LINEAR_TO_LMS)


def linear_to_srgb(value: float) -> int:
    value = max(0.0, min(1.0, value))
    return round(255 * (value * 12.92 if value <= 0.0031308 else 1.055 * value ** (1 / 2.4) - 0.055))


def mix(a: Color, b: Color, fraction: float) -> Color:
    """Interpolate in linear light so blends keep their brightness instead of turning muddy."""
    fraction = max(0, min(1, fraction))
    return tuple(linear_to_srgb(SRGB_TO_LINEAR[int(x)] + (SRGB_TO_LINEAR[int(y)] - SRGB_TO_LINEAR[int(x)]) * fraction) for x, y in zip(a, b))


def to_oklab(rgb: np.ndarray) -> np.ndarray:
    return np.cbrt(SRGB_TO_LINEAR_ARRAY[rgb] @ LINEAR_TO_LMS.T) @ LMS_TO_OKLAB.T


def from_oklab(lab: np.ndarray) -> np.ndarray:
    linear = np.clip(((lab @ OKLAB_TO_LMS.T) ** 3) @ LMS_TO_LINEAR.T, 0, 1)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1 / 2.4) - 0.055)
    return np.round(srgb * 255).astype(np.uint8)


def grade_oklab(lab: np.ndarray, *, chroma: float, contrast: float, black_point: float = 0, gamma: float = 1, vibrance: float = 0) -> np.ndarray:
    lightness = lab[..., 0]
    if black_point:
        lightness = np.clip((lightness - black_point) / (1 - black_point), 0, 1)
    if gamma != 1:
        lightness = np.power(np.clip(lightness, 0, 1), gamma)
    if contrast:
        curve = np.clip(lightness, 0, 1)
        lightness = lightness + (curve * curve * (3 - 2 * curve) - lightness) * contrast
    # Vibrance lifts muted colors more than already-saturated ones.
    scale = chroma * (1 + vibrance * (1 - np.clip(np.hypot(lab[..., 1], lab[..., 2]) / VIBRANCE_CHROMA, 0, 1)))
    return np.stack([lightness, lab[..., 1] * scale, lab[..., 2] * scale], axis=-1)


def grain(x: int, y: int, seed: int = 0) -> int:
    return ((x * 73 + y * 151 + seed * 199) ^ (x * y * 13)) % 97


@dataclass(frozen=True)
class Palette:
    top: Color
    middle: Color
    horizon: Color
    far: Color
    ridge: Color
    field: Color
    foreground: Color
    grass: Color
    leaf: Color
    leaf_light: Color
    leaf_dark: Color
    trunk: Color
    roof: Color
    barn: Color
    trim: Color
    water: Color
    glint: Color
    animal: Color
    snowcap: Color


DUSK = Palette(
    (24, 46, 82), (99, 105, 136), (241, 162, 110), (95, 99, 125), (43, 71, 81), (62, 88, 76), (22, 48, 48), (116, 132, 94), (85, 84, 73), (159, 130, 78), (35, 56, 59), (32, 42, 49), (57, 47, 60), (156, 62, 51), (235, 198, 139), (68, 102, 121), (220, 163, 122), (170, 155, 122), (238, 196, 186)
)
DAY = Palette(
    (48, 130, 175), (100, 175, 191), (194, 213, 181), (99, 147, 143), (54, 106, 91), (104, 153, 79), (43, 94, 53), (164, 183, 86), (63, 125, 65), (148, 181, 74), (40, 86, 57), (80, 62, 47), (67, 65, 72), (171, 62, 51), (239, 220, 171), (55, 147, 169), (167, 219, 208), (166, 119, 73), (232, 238, 245)
)
NIGHT = Palette((5, 11, 28), (16, 29, 55), (53, 67, 91), (36, 48, 70), (23, 42, 55), (29, 51, 51), (13, 30, 35), (59, 79, 60), (46, 62, 60), (83, 98, 70), (26, 44, 47), (18, 26, 34), (23, 28, 43), (78, 47, 50), (139, 149, 146), (34, 65, 85), (129, 159, 171), (122, 127, 108), (122, 137, 162))
MATERIALS = tuple(field.name for field in fields(Palette))
INDEX = {name: index + 1 for index, name in enumerate(MATERIALS)}
INDEX["hill"] = len(MATERIALS) + 1
INDEX["peak"] = len(MATERIALS) + 2
# One prominent peak right of center keeps the rest of the horizon low so the night sky stays open.
MOUNTAIN = ((62, 23), (66, 22), (70, 20), (74, 18), (77, 16), (80, 15), (83, 14), (86, 15), (89, 16), (92, 18), (96, 20), (100, 21), (106, 23), (127, 23))
# The sunlit face runs from the summit down this spur to the foot of the mountain.
MOUNTAIN_LIT_FACE = ((83, 14), (80, 15), (77, 16), (74, 18), (70, 20), (66, 22), (62, 23), (78, 23), (80, 19), (82, 16))
TREE_X, TREE_CANOPY_Y = 115, 15
TREE_RADIUS_X, TREE_RADIUS_Y = 10.5, 7.8
TREE_BRANCHES = ((-10, -4), (9, -2), (-2, -8), (4, -7))
TREE_BLOSSOMS = ((-7, -5), (2, -7), (6, -2), (-4, 0), (4, 1))


def blend_palette(a: Palette, b: Palette, fraction: float) -> Palette:
    return Palette(*(mix(getattr(a, name), getattr(b, name), fraction) for name in MATERIALS))


def precipitation(environment: "OutsideEnvironment") -> tuple[float, float]:
    w = environment.weather
    if w.code is None:
        return 0, 0
    rain, snow = w.rain, w.snow
    if rain is None:
        rain = 0.35 if 300 <= w.code < 400 else 1.2 if 200 <= w.code < 300 or 500 <= w.code < 600 or w.code in (611, 612, 613, 615, 616) else 0
    if snow is None:
        snow = 0.7 if 600 <= w.code < 700 else 0
    return rain, snow


def cloud_cover(environment: "OutsideEnvironment") -> float:
    w = environment.weather
    if w.clouds is not None:
        return w.clouds
    if w.code is None:
        return 0.25
    return {800: 0, 801: 0.15, 802: 0.4, 803: 0.7, 804: 1}.get(w.code, 0.85)


def moonlight(environment: "OutsideEnvironment") -> float:
    if environment.moon_altitude is None or environment.moon_altitude <= 0:
        return 0
    fraction = (1 - math.cos(math.radians(environment.moon_phase))) / 2
    return fraction * min(1, environment.moon_altitude / 25) * (1 - cloud_cover(environment) * 0.8)


def scene_palette(environment: "OutsideEnvironment") -> Palette:
    altitude = environment.sun_altitude
    altitude = 0 if altitude is None else altitude
    if altitude < 0:
        palette = blend_palette(NIGHT, DUSK, (altitude + 10) / 10)
        illumination = moonlight(environment) * max(0, min(1, -altitude / 10))
        palette = Palette(*(mix(getattr(palette, name), (106, 133, 157), illumination * (0.075 if name in ("top", "middle", "horizon") else 0.12)) for name in MATERIALS))
    else:
        palette = blend_palette(DUSK, DAY, altitude / 14)
    daylight = max(0.12, min(1, (altitude + 10) / 20))
    if environment.season == "autumn":
        palette = replace(palette, leaf=mix(palette.leaf, (146, 84, 47), daylight * 0.45), leaf_light=mix(palette.leaf_light, (229, 153, 63), daylight * 0.55), grass=mix(palette.grass, (167, 142, 76), daylight * 0.2))
    elif environment.season == "spring":
        palette = replace(palette, leaf=mix(palette.leaf, (112, 145, 82), daylight * 0.5), leaf_light=mix(palette.leaf_light, (210, 176, 169), daylight * 0.65), field=mix(palette.field, (108, 141, 84), daylight * 0.3))
    elif environment.season == "winter":
        palette = replace(palette, field=mix(palette.field, (132, 135, 119), daylight * 0.65), foreground=mix(palette.foreground, (77, 92, 92), daylight * 0.55), grass=mix(palette.grass, (153, 150, 121), daylight * 0.5))
    rain, snow = precipitation(environment)
    temperature = environment.weather.temperature
    if temperature is not None and temperature <= 32 and snow == 0:
        palette = replace(palette, grass=mix(palette.grass, (181, 199, 195), daylight * 0.35), water=mix(palette.water, (131, 168, 180), daylight * 0.25))
    if snow > 0:
        palette = replace(palette, field=mix(palette.field, (207, 218, 226), daylight * 0.85 + 0.1), foreground=mix(palette.foreground, (151, 180, 199), daylight * 0.8 + 0.1), grass=mix(palette.grass, (236, 235, 226), daylight * 0.75))
    dim = cloud_cover(environment) * (WEATHER_DIM_PRECIPITATION if rain or snow else WEATHER_DIM_CLOUDS)
    return graded_palette(Palette(*(mix(getattr(palette, name), (45, 60, 75), dim) for name in MATERIALS)))


@lru_cache(maxsize=512)
def graded_palette(palette: Palette) -> Palette:
    lab = grade_oklab(to_oklab(np.array([getattr(palette, name) for name in MATERIALS])), chroma=PALETTE_CHROMA, contrast=PALETTE_CONTRAST)
    return Palette(*(tuple(int(value) for value in color) for color in from_oklab(lab)))


def grade_frame(image: Image.Image) -> Image.Image:
    lab = grade_oklab(to_oklab(np.asarray(image)), chroma=FRAME_CHROMA, contrast=FRAME_CONTRAST, black_point=FRAME_BLACK_POINT, gamma=FRAME_GAMMA, vibrance=FRAME_VIBRANCE)
    return Image.fromarray(from_oklab(lab), "RGB")


def geometry() -> tuple[Image.Image, Image.Image, Image.Image]:
    land = Image.new("P", (WIDTH, HEIGHT), 0)
    d = ImageDraw.Draw(land)

    def hill(points, material):
        d.polygon([(0, 31), *points, (127, 31)], fill=INDEX[material])

    hill([*MOUNTAIN], "far")
    d.polygon(MOUNTAIN_LIT_FACE, fill=INDEX["peak"])
    hill([(0, 23), (20, 22), (35, 23), (57, 22), (76, 23), (97, 22), (127, 23)], "hill")
    for x in range(0, 100, 4):
        height = 2 + grain(x, 24) % 3
        if grain(x, 24, 3) < 55:
            d.ellipse((x - 2, 24 - height, x + 2, 24), fill=INDEX["ridge"])
        else:
            d.polygon([(x, 24 - height), (x - 2, 24), (x + 2, 24)], fill=INDEX["ridge"])
    hill([(0, 26), (29, 25), (51, 27), (82, 25), (110, 26), (127, 25)], "field")
    d.rectangle((21, 19, 33, 25), fill=INDEX["barn"])
    d.rectangle((30, 19, 33, 25), fill=INDEX["barn"])
    d.polygon([(19, 20), (27, 15), (36, 20)], fill=INDEX["roof"])
    d.line((19, 20, 27, 15), fill=INDEX["trunk"])
    d.rectangle((25, 20, 29, 25), fill=INDEX["roof"])
    d.line((25, 20, 29, 20), fill=INDEX["trim"])
    d.line((25, 21, 29, 25), fill=INDEX["trim"])
    d.line((29, 21, 25, 25), fill=INDEX["trim"])
    for x, base, height in [(4, 28, 12), (38, 25, 7)]:
        d.line((x, base - height, x, base), fill=INDEX["trunk"])
        for offset in range(2, height - 1, 2):
            w, y = max(1, offset // 3), base - height + offset
            d.polygon([(x, y - 2), (x - w, y + 1), (x + w, y + 1)], fill=INDEX["leaf_dark"])
            d.line((x - w, y + 1, x, y), fill=INDEX["leaf"])
    hill([(0, 29), (20, 28), (45, 30), (79, 28), (102, 29), (127, 28)], "foreground")
    for y in range(29, 32):
        for x in range(WIDTH):
            if grain(x, y, 2) < 9:
                d.point((x, y), fill=INDEX["grass"])
    d.ellipse((51, 26, 80, 29), fill=INDEX["water"])
    d.line((3, 28, 40, 28), fill=INDEX["grass"])
    for x in range(3, 41, 6):
        d.line((x, 27, x, 31), fill=INDEX["trunk"])
        d.point((x, 27), fill=INDEX["trim"])
    leafy = Image.new("P", (WIDTH, HEIGHT), 0)
    bare = Image.new("P", (WIDTH, HEIGHT), 0)
    cx, cy = TREE_X, TREE_CANOPY_Y
    for mask in (leafy, bare):
        td = ImageDraw.Draw(mask)
        td.line((cx, cy - 2, cx, 31), fill=INDEX["trunk"], width=2)
        td.line((cx - 1, 31, cx + 2, 31), fill=INDEX["trunk"])
        for dx, dy in TREE_BRANCHES:
            td.line((cx, 28, cx + dx, cy + dy), fill=INDEX["trunk"])
            if mask is bare:
                td.line((cx + dx, cy + dy, cx + dx - 1, cy + dy - 2), fill=INDEX["trunk"])
    td = ImageDraw.Draw(leafy)
    for y in range(round(cy - TREE_RADIUS_Y) - 2, round(cy + TREE_RADIUS_Y) + 3):
        for x in range(round(cx - TREE_RADIUS_X) - 2, min(WIDTH, round(cx + TREE_RADIUS_X) + 3)):
            n = grain(x, y, 12)
            if ((x - cx) / TREE_RADIUS_X) ** 2 + ((y - cy) / TREE_RADIUS_Y) ** 2 < 0.8 + n / 290:
                material = "leaf_dark" if n <= 37 else "leaf"
                if y < cy - 1 and x < cx + 3 and n > 48:
                    material = "leaf_light"
                td.point((x, y), fill=INDEX[material])
    td.line((cx, 27, cx - 2, cy + 2), fill=INDEX["trunk"])
    td.line((cx, 26, cx + 3, cy + 2), fill=INDEX["trunk"])
    return land, leafy, bare


LAND, LEAFY_TREE, BARE_TREE = geometry()
TREE_FOLIAGE = LEAFY_TREE.point([value if value in (INDEX["leaf"], INDEX["leaf_light"], INDEX["leaf_dark"]) else 0 for value in range(256)])
TREE_WOOD = LEAFY_TREE.point([value if value == INDEX["trunk"] else 0 for value in range(256)])
STARS = tuple((x, y, grain(x, y, 5)) for y in range(1, 21) for x in range(2, 126) if grain(x, y, 9) < 2)
STAR_COLORS = ((232, 244, 255), (255, 239, 207), (225, 231, 255))
RIPPLES = ((60, 27, 15, 0), (55, 28, 9, 2.3), (68, 29, 7, 4.5))
PARTICLES = tuple((grain(i, 3) / 97 * 128, grain(i, 9) / 97 * 35, 0.7 + grain(i, 5) / 97, grain(i, 7)) for i in range(80))
MOON_PIXELS = tuple((x, y, math.sqrt(9 - y * y)) for y in range(-3, 4) for x in range(-3, 4) if x * x + y * y <= 9)


@lru_cache(maxsize=96)
def landscape(palette: Palette, bare: bool, snow: bool, snowcap: bool):
    table = [0, 0, 0]
    for name in MATERIALS:
        table.extend(getattr(palette, name))
    table.extend(mix(palette.far, palette.ridge, 0.6))
    table.extend(mix(palette.far, palette.horizon, 0.16))
    table.extend([0] * (768 - len(table)))

    def colorize(mask):
        indexed = mask.copy()
        indexed.putpalette(table)
        image = indexed.convert("RGBA")
        image.putalpha(mask.point([0] + [255] * 255, "L"))
        return image

    land = colorize(LAND)
    foliage = None if bare else colorize(TREE_FOLIAGE)
    wood = colorize(BARE_TREE if bare else TREE_WOOD)
    if snow:
        d = ImageDraw.Draw(land)
        for x in range(0, 128):
            if grain(x, 26, 1) < 25 and LAND.getpixel((x, 26)) not in (0, INDEX["water"], INDEX["roof"], INDEX["barn"]):
                d.point((x, 26), fill=palette.grass)
        d.line((19, 19, 27, 15, 36, 19), fill=palette.trim)
        d.line((3, 27, 40, 27), fill=palette.grass)
    if snowcap:
        d = ImageDraw.Draw(land)
        summit = min(y for _, y in MOUNTAIN)
        for y in range(summit, summit + 4):
            for x in range(WIDTH):
                material = LAND.getpixel((x, y))
                if material in (INDEX["far"], INDEX["peak"]) and y < summit + 2 + grain(x, y, 4) % 2:
                    d.point((x, y), fill=palette.snowcap if material == INDEX["peak"] else mix(palette.snowcap, palette.far, 0.35))
    return land, foliage, wood


def celestial_position(altitude: float, azimuth: float) -> tuple[int, int]:
    return round(64 - 56 * math.sin(math.radians(azimuth))), round(18 - 15 * math.sin(math.radians(max(0, altitude))))


CLOUD_TILE = 256
CLOUD_STREAK_MAX_COVER = 0.35
CLOUD_COLUMNS = np.arange(WIDTH)
CLOUD_ROWS = np.arange(HEIGHT)
CLOUD_FLASH_CATCH = np.array([0.95, 0.8, 0.6, 0.4], dtype=np.float32)


@dataclass(frozen=True)
class CloudLayer:
    salt: int
    count: int
    width: tuple[int, int]
    base: tuple[int, int]
    speed: float
    wind: float
    haze: float


# Small, hazy, slow clouds high up behind larger, lower cumulus that drift faster with the wind.
CLOUD_LAYERS = (CloudLayer(salt=3, count=26, width=(10, 24), base=(8, 12), speed=0.12, wind=0.012, haze=0.35), CloudLayer(salt=7, count=24, width=(16, 38), base=(15, 19), speed=0.3, wind=0.03, haze=0.0))


def periodic_noise(cell_x: int, cell_y: int, salt: int) -> np.ndarray:
    """Smooth value noise that wraps horizontally across CLOUD_TILE columns."""
    columns = CLOUD_TILE // cell_x
    grid = np.random.default_rng(salt).random((HEIGHT // cell_y + 2, columns))
    x, y = np.arange(CLOUD_TILE) / cell_x, np.arange(HEIGHT) / cell_y
    x0, y0 = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = x - x0, y - y0
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    x1 = (x0 + 1) % columns
    top = grid[y0][:, x0] + (grid[y0][:, x1] - grid[y0][:, x0]) * fx
    bottom = grid[y0 + 1][:, x0] + (grid[y0 + 1][:, x1] - grid[y0 + 1][:, x0]) * fx
    return top + (bottom - top) * fy[:, None]


@lru_cache(maxsize=len(CLOUD_LAYERS))
def cumulus(layer: CloudLayer) -> tuple[tuple[int, np.ndarray], ...]:
    """Cloud tone patches, in the order clouds appear as cover rises: (base row, tile-wide tones)."""
    rng = random.Random(layer.salt)
    clouds = []
    for _ in range(layer.count):
        width = rng.uniform(*layer.width)
        height = width * rng.uniform(0.26, 0.36)
        center, base = rng.uniform(0, CLOUD_TILE), rng.randint(*layer.base)
        tones = np.full((HEIGHT, CLOUD_TILE), -1, dtype=np.int8)
        puffs = max(3, round(width / 6))
        for index in range(puffs):
            # Puffs rise into a dome over a flat base; later puffs overlap earlier ones, each with its own lit rim.
            radius = height * (0.55 + 0.45 * math.sin(math.pi * (index + 0.5) / puffs)) * rng.uniform(0.8, 1.1)
            px = center - width / 2 + (index + 0.5) * width / puffs + rng.uniform(-1.5, 1.5)
            py = base - radius * 0.75
            rows = np.arange(max(0, math.floor(py - radius)), min(HEIGHT, base + 1))
            columns = np.arange(math.floor(px - radius), math.ceil(px + radius) + 1)
            dx, dy = columns[None, :] - px, rows[:, None] - py
            inside = dx * dx + dy * dy <= radius * radius
            light = (dx * 0.6 + dy) / radius
            patch = np.where(light < -0.8, 0, np.where(light < -0.35, 1, 2)).astype(np.int8)
            view = tones[rows[0] : rows[-1] + 1]
            wrapped = columns % CLOUD_TILE
            view[:, wrapped] = np.where(inside, patch, view[:, wrapped])
        cloud = tones >= 0
        tones[cloud & (CLOUD_ROWS[:, None] == base)] = 3
        clouds.append((base, tones))
    return tuple(clouds)


@lru_cache(maxsize=64)
def cloud_tones(layer: CloudLayer, coverage: int) -> np.ndarray:
    """Posterized tone per pixel: 0 rim light, 1 sunlit body, 2 body, 3 shadowed base; -1 is clear sky."""
    clouds = cumulus(layer)
    shown = clouds[: round(len(clouds) * max(0, min(1, (coverage / 20 - 0.1) / 0.9)) ** 1.4)]
    tones = np.full((HEIGHT, CLOUD_TILE), -1, dtype=np.int8)
    # Higher (more distant) clouds first, so lower ones overlap them.
    for _, patch in sorted(shown, key=lambda cloud: cloud[0]):
        tones = np.where(patch >= 0, patch, tones)
    return tones


@lru_cache(maxsize=32)
def ceiling_tones(coverage: int) -> np.ndarray | None:
    """An overcast stratus ceiling that lowers from the top of the sky as cover approaches 100%."""
    thickness = max(0, min(1, (coverage / 20 - 0.65) / 0.35)) * 9
    if thickness < 1:
        return None
    edge = thickness + (periodic_noise(64, HEIGHT, 11)[0] - 0.5) * 5 + (periodic_noise(16, HEIGHT, 12)[0] - 0.5) * 2
    rows = CLOUD_ROWS[:, None]
    cloud = rows < edge[None, :]
    streaks = periodic_noise(32, 2, 13) > 0.62
    tones = np.where(cloud, np.where(streaks, 1, 2), -1).astype(np.int8)
    tones[cloud & (rows >= edge[None, :] - 1)] = 3
    return tones


def cloud_palette(palette: Palette, haze: float, gloom: float) -> np.ndarray:
    # The palette's snow color is a neutral, time-of-day-lit white: white-blue by day, pink at dusk, cool at night.
    light = mix(palette.snowcap, palette.horizon, 0.25)
    body = mix(palette.snowcap, palette.top, 0.45)
    shadow = mix(body, palette.roof, 0.45)
    tones = [light, mix(light, body, 0.5), body, shadow]
    # Rain clouds darken from the base up; distant clouds fade toward the sky.
    tones = [mix(tone, mix(palette.top, palette.roof, 0.4), gloom * (0.35 + index * 0.2)) for index, tone in enumerate(tones)]
    return np.array([mix(tone, palette.middle, haze) for tone in tones], dtype=np.float32)


def draw_cloudscape(image: Image.Image, environment: "OutsideEnvironment", palette: Palette, elapsed: float, glows: list[tuple[int, int, Color, float]], lightning: "tuple[LightningEvent, float] | None") -> np.ndarray:
    """Draw the cloud layers and return the mask of cloud pixels."""
    covered = np.zeros((HEIGHT, WIDTH), dtype=bool)
    coverage = round(cloud_cover(environment) * 20)
    if coverage < 4:
        return covered
    rain, snow = precipitation(environment)
    # Overcast skies turn dull and gray; rain clouds darker still.
    gloom = 0.55 if rain or snow else 0.4 * max(0, min(1, (coverage / 20 - 0.7) / 0.3))
    wind = min(30, environment.weather.wind or 0)
    pixels = np.asarray(image, dtype=np.float32).copy()
    layers = [(ceiling_tones(coverage), 0.05, 0.006, 0.2), *((cloud_tones(layer, coverage), layer.speed, layer.wind, layer.haze) for layer in CLOUD_LAYERS)]
    for tile, speed, drift, haze in layers:
        if tile is None:
            continue
        offset = int(elapsed * (speed + wind * drift)) % CLOUD_TILE
        tones = np.take(tile, (CLOUD_COLUMNS + offset) % CLOUD_TILE, axis=1)
        cloud = tones >= 0
        if not cloud.any():
            continue
        colors = cloud_palette(palette, haze, gloom)[np.maximum(tones, 0)]
        # Silver linings: cloud edges near the sun or moon catch its light.
        for cx, cy, color, strength in glows:
            glow = strength * np.exp(-(((CLOUD_COLUMNS[None, :] - cx) / 18) ** 2 + ((CLOUD_ROWS[:, None] - cy) / 7) ** 2))
            colors += (np.array(color, dtype=np.float32) - colors) * (glow * np.where(tones <= 1, 0.75, 0.3))[..., None]
        if lightning is not None and lightning[1] >= 0:
            event, age = lightning
            base, local, spread = LIGHTNING_LIGHT[event.kind]
            light = event.intensity(age) * (base + local * np.exp(-0.5 * ((CLOUD_COLUMNS - event.center) / spread) ** 2))
            # Lit from within: billow tops catch the most light, so the cloud shapes stay readable.
            catch = CLOUD_FLASH_CATCH[np.maximum(tones, 0)]
            colors += (np.array(LIGHTNING_BRANCH, dtype=np.float32) - colors) * (np.clip(light * 1.1, 0, 1)[None, :] * catch)[..., None]
        pixels[cloud] = colors[cloud]
        covered |= cloud
    image.paste(Image.fromarray(np.round(pixels).astype(np.uint8), "RGB"))
    return covered


def draw_sky(image: Image.Image, environment: "OutsideEnvironment", palette: Palette, elapsed: float, lightning: "tuple[LightningEvent, float] | None" = None) -> np.ndarray:
    """Draw the sky and return the mask of cloud pixels."""
    d = ImageDraw.Draw(image)
    altitude = environment.sun_altitude
    night = max(0, min(1, -(altitude + 4) / 7)) if altitude is not None else 0
    cover = cloud_cover(environment)
    for x, y, phase in STARS:
        swell = 0.5 + 0.5 * math.sin(elapsed * (0.65 + phase / 160) + phase)
        sparkle = 0.85 + 0.15 * (0.5 + 0.5 * math.sin(elapsed * (1.8 + phase / 110) + phase * 0.37))
        shimmer = 0.04 + 0.96 * swell * swell * sparkle
        strength = night * (1 - cover * 0.92) * (1 - moonlight(environment) * 0.25) * shimmer
        if strength > 0:
            d.point((x, y), fill=mix(image.getpixel((x, y)), STAR_COLORS[phase % len(STAR_COLORS)], strength))
    glows = []
    if altitude is not None and altitude > -0.833:
        cx, cy = celestial_position(altitude, environment.sun_azimuth)
        sun = mix((255, 164, 94), (255, 235, 170), altitude / 20)
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=mix(palette.middle, sun, 0.23))
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=sun)
        glows.append((cx, cy, sun, 0.8))
    if environment.moon_altitude is not None and environment.moon_altitude > 0:
        cx, cy = celestial_position(environment.moon_altitude, environment.moon_azimuth)
        phase = math.radians(environment.moon_phase)
        fraction = (1 - math.cos(phase)) / 2
        strength = max(0.18, night) * (1 - cover * 0.5)
        glows.append((cx, cy, (214, 222, 235), fraction * night * 0.6))
        halo = Image.new("RGBA", (WIDTH, HEIGHT))
        hd = ImageDraw.Draw(halo)
        for radius, alpha in ((5, 10), (4, 18)):
            hd.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(155, 178, 192, round(alpha * fraction * night * (1 - cover))))
        image.paste(halo, (0, 0), halo)
        for dx, dy, edge in MOON_PIXELS:
            lit = dx >= math.cos(phase) * edge if phase <= math.pi else dx <= -math.cos(phase) * edge
            if lit and fraction > 0.005:
                x, y = cx + dx, cy + dy
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    d.point((x, y), fill=mix(image.getpixel((x, y)), (239, 226, 186), strength))
    clouds = draw_cloudscape(image, environment, palette, elapsed, glows, lightning)
    d = ImageDraw.Draw(image)
    wind = environment.weather.wind or 0
    # Thin streaks carry light cloud cover; the cloudscape takes over as the sky fills in.
    cloud_count = 1 + round(cover * 5) if cover < CLOUD_STREAK_MAX_COVER else 0
    for index in range(cloud_count):
        width = 16 + (index * 7) % 19
        x = round(((index * 37 + 12 + elapsed * (0.18 + min(30, wind) * 0.02)) % (128 + width)) - width)
        y = 3 + (index * 5) % 11
        color = mix(palette.middle, palette.horizon, 0.22 + index * 0.07)
        if cover > 0.65:
            color = mix(color, palette.roof, cover * 0.35)
        if lightning is not None and lightning[1] >= 0:
            # Clouds near the bolt light up from within.
            color = mix(color, LIGHTNING_BRANCH, min(1, lightning_light(lightning[0], lightning[0].intensity(lightning[1]), x + width / 2) * 1.1))
        d.line((x + 3, y, x + width - 5, y), fill=color)
        d.line((x + 7, y - 1, x + width - 9, y - 1), fill=mix(color, palette.top, 0.1))
        d.line((x, y + 1, x + width, y + 1), fill=mix(color, palette.middle, 0.2))
    return clouds


@lru_cache(maxsize=64)
def wildlife_visit(slot: int, seed: int):
    rng = random.Random(seed + slot * 317)
    return rng.random() < 0.8, rng.choice(("deer", "deer", "fox", "rabbit")), rng.uniform(4, 15), rng.uniform(50, 65), rng.choice((86, 91, 96)), rng.random() < 0.5


def draw_wildlife(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    d = ImageDraw.Draw(image)
    rain, snow = precipitation(environment)
    slot, age = divmod(elapsed, 100)
    present, species, start, duration, target, pair = wildlife_visit(int(slot), seed)
    if present and start <= age < start + duration and rain < 3 and snow < 2:
        visit_age = age - start
        arrival = max(0, min(1, visit_age / 18))
        departure = max(0, min(1, (visit_age - duration + 18) / 18))
        x = round(128 + (target - 128) * arrival + (128 - target) * departure)
        walking = arrival < 1 or departure > 0
        for offset in (0, 12) if pair and species == "deer" else (0,):
            dx = x + offset

            def px(local_x):
                return dx + 5 - local_x if arrival < 1 else dx + local_x

            c = palette.animal
            leg = int(elapsed * 2.5) % 2 if walking else 0
            if species == "deer":
                d.line((px(0), 28, px(5), 28), fill=c, width=2)
                grazing = not walking and math.sin(elapsed * 0.2) > 0.4
                if grazing:
                    d.line((px(5), 28, px(7), 30), fill=c)
                else:
                    d.line((px(5), 28, px(6), 26), fill=c)
                    d.line((px(6), 26, px(8), 26), fill=c)
                    d.point((px(6), 25), fill=c)
                d.line((px(0), 29, px(-leg), 31), fill=c)
                d.line((px(4), 29, px(4 + leg), 31), fill=c)
                d.point((px(-1), 27), fill=palette.trim)
            elif species == "fox":
                c = mix(c, (192, 110, 58), 0.5)
                d.line((px(0), 29, px(5), 29), fill=c, width=2)
                d.line((px(-1), 29, px(-3), 27), fill=c)
                d.point((px(-4), 27), fill=palette.trim)
                d.line((px(5), 29, px(7), 28), fill=c)
                d.point((px(6), 27), fill=c)
                d.point((px(1 - leg), 31), fill=palette.trunk)
                d.point((px(4 + leg), 31), fill=palette.trunk)
            else:
                d.line((px(0), 30, px(2), 30), fill=c, width=2)
                d.line((px(2), 29, px(2), 27), fill=c)
                d.point((px(-1), 30), fill=palette.trim)
    sun_altitude = environment.sun_altitude
    if sun_altitude is not None and sun_altitude > -5 and rain < 1.5 and snow < 1:
        flock_age = (elapsed + seed % 30) % 85
        if flock_age < 35:
            for index in range(3 if environment.season != "winter" else 2):
                x = round(-12 + flock_age * 4.5 - index * 7)
                y = 7 + index % 2 + round(math.sin(elapsed * 0.2 + index) * 1.5)
                wing = 1 if math.sin(elapsed * 7 + index) > 0 else -1
                d.line((x - 1, y - wing, x, y, x + 1, y - wing), fill=palette.roof)


RAIN_SPEED = 52
RAIN_COLOR = (206, 221, 234)
RAIN_GAP = 12


def draw_rain(image: Image.Image, rate: float, wind: float, elapsed: float):
    """Fast, wind-slanted streaks that end in a brief splash on the ground."""
    d = ImageDraw.Draw(image)
    slant = min(wind, 30) / 60
    count = min(60, round(8 + rate * 8))
    strength = min(1, 0.75 + rate * 0.06)
    for x0, y0, pace, phase in PARTICLES[:count]:
        # Faster drops leave longer motion streaks.
        length = 3 if pace < 1.2 else 4
        speed = RAIN_SPEED * (0.6 + 0.4 * pace)
        landing = 26 + phase % 6
        period = landing + length + RAIN_GAP + phase % 9
        travel, cycle = math.fmod(y0 / 35 * period + elapsed * speed, period), math.floor((y0 / 35 * period + elapsed * speed) / period)
        head = travel - length
        x = x0 + cycle * 53 + slant * head
        if head <= landing:
            for k in range(length):
                py = round(head) - k
                if 0 <= py < HEIGHT:
                    px = round(x - slant * k) % WIDTH
                    d.point((px, py), fill=mix(image.getpixel((px, py)), RAIN_COLOR, (0.8 - k * 0.18 + (phase % 5) * 0.02) * strength))
        elif head - landing < 3:
            px = round(x - slant * (head - landing))
            for dx, dy, amount in ((-1, 0, 0.4), (1, 0, 0.4), (0, -1, 0.25)):
                sx, sy = (px + dx) % WIDTH, landing + dy
                d.point((sx, sy), fill=mix(image.getpixel((sx, sy)), RAIN_COLOR, amount * strength))


LIGHTNING_SLOT_SECONDS = 4.0
LIGHTNING_LEADER_SECONDS = 0.1
LIGHTNING_CRAWL_SECONDS = 0.14
# Each stroke holds full brightness long enough to land on at least one ~20 fps frame, then decays.
LIGHTNING_HOLD_SECONDS = 0.06
LIGHTNING_DECAY_SECONDS = 0.08
LIGHTNING_AFTERGLOW_SECONDS = 0.6
LIGHTNING_FLASH = (226, 222, 255)
LIGHTNING_GLOW = (160, 140, 255)
LIGHTNING_BRANCH = (235, 230, 255)
LIGHTNING_CORE = (255, 255, 255)
# Relative storm activity per thunderstorm code; lightning frequency scales with it.
THUNDERSTORM_ACTIVITY = {200: 0.7, 201: 1.0, 202: 1.4, 210: 0.5, 211: 1.0, 212: 1.6, 221: 1.1, 230: 0.6, 231: 0.9, 232: 1.2}
# How strongly each lightning kind lights the whole sky versus the region around the bolt, and that region's width.
LIGHTNING_LIGHT = {"ground": (0.5, 0.45, 26), "cloud": (0.22, 0.6, 18), "sheet": (0.12, 0.35, 34)}
SURFACE = tuple(next(y for y in range(HEIGHT) if LAND.getpixel((x, y))) for x in range(WIDTH))
SCENERY = (np.asarray(LAND) > 0) | (np.asarray(LEAFY_TREE) > 0) | (np.asarray(BARE_TREE) > 0)
# Scenery catches less of the flash than open sky.
FLASH_RECEIVE = np.where(SCENERY, 0.38, 1.0)
FLASH_COLUMNS = np.arange(WIDTH)
FLASH_FALLOFF = np.linspace(1, 0.65, HEIGHT)


@dataclass(frozen=True)
class LightningEvent:
    kind: str
    start: float
    strokes: tuple[tuple[float, float], ...]
    center: int
    channel: tuple[tuple[int, int], ...]
    branches: tuple[tuple[int, int], ...]
    strike: tuple[int, int] | None

    @property
    def end(self) -> float:
        return self.strokes[-1][0] + LIGHTNING_AFTERGLOW_SECONDS

    def intensity(self, age: float) -> float:
        level = 0.0
        for offset, strength in self.strokes:
            since = age - offset
            if since >= 0:
                level = max(level, strength if since < LIGHTNING_HOLD_SECONDS else strength * math.exp(-(since - LIGHTNING_HOLD_SECONDS) / LIGHTNING_DECAY_SECONDS))
        return level


def trace(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pixels: list[tuple[int, int]] = []
    for (x0, y0), (x1, y1) in pairwise(points):
        steps = max(abs(x1 - x0), abs(y1 - y0), 1)
        for step in range(steps + 1):
            pixel = (round(x0 + (x1 - x0) * step / steps), round(y0 + (y1 - y0) * step / steps))
            if 0 <= pixel[0] < WIDTH and 0 <= pixel[1] < HEIGHT and (not pixels or pixels[-1] != pixel):
                pixels.append(pixel)
    return pixels


def ground_bolt(rng: random.Random):
    target = rng.randint(6, 100)
    x, y = max(4, min(100, target + rng.randint(-18, 18))), rng.randint(1, 4)
    points = [(x, y)]
    if rng.random() < 0.5:
        # Sometimes the channel crawls along the cloud base before it drops.
        side = rng.choice((-1, 1))
        for _ in range(rng.randint(2, 4)):
            x, y = max(4, min(100, x + side * rng.randint(3, 6))), max(0, min(6, y + rng.choice((-1, 0, 1))))
            points.append((x, y))
    while True:
        previous_x, previous_y = x, y
        y += rng.randint(2, 4)
        # Wander, drifting toward the strike target, until the bolt meets the land surface.
        x = max(2, min(102, round(x + max(-2, min(2, (target - x) / 4)) + rng.choice((-3, -2, -1, 0, 1, 2, 3)))))
        if y >= SURFACE[x] - 1:
            if SURFACE[x] - 1 < previous_y:
                x = previous_x
            points.append((x, SURFACE[x] - 1))
            break
        points.append((x, y))
    channel = trace(points)
    branches = []
    for _ in range(rng.randint(2, 4)):
        bx, by = channel[rng.randrange(max(1, len(channel) * 3 // 4))]
        side = rng.choice((-1, 1))
        fork = [(bx, by)]
        for _ in range(rng.randint(2, 5)):
            bx, by = bx + side * rng.randint(1, 3), by + rng.randint(1, 3)
            if by >= SURFACE[max(0, min(WIDTH - 1, bx))] - 1:
                break
            fork.append((bx, by))
        branches.extend(trace(fork)[1:])
    return x, tuple(channel), tuple(dict.fromkeys(branches)), (x, SURFACE[x])


def cloud_bolt(rng: random.Random):
    direction = rng.choice((-1, 1))
    x = rng.randint(10, 60) if direction > 0 else rng.randint(68, 118)
    y = rng.randint(3, 9)
    end = x + direction * rng.randint(24, 56)
    points = [(x, y)]
    while (x - end) * direction < 0:
        x += direction * rng.randint(3, 6)
        y = max(1, min(12, y + rng.choice((-2, -1, 0, 0, 1, 2))))
        points.append((x, y))
    channel = trace(points)
    branches = []
    for _ in range(rng.randint(2, 4)):
        bx, by = channel[rng.randrange(len(channel))]
        fork = [(bx, by)]
        for _ in range(rng.randint(1, 3)):
            bx, by = bx + rng.choice((-2, -1, 1, 2)), max(0, min(14, by + rng.choice((-2, 1, 2, 2))))
            fork.append((bx, by))
        branches.extend(trace(fork)[1:])
    xs = [px for px, _ in channel]
    return (min(xs) + max(xs)) // 2, tuple(channel), tuple(dict.fromkeys(branches)), None


@lru_cache(maxsize=32)
def lightning_event(slot: int, seed: int, activity: float) -> LightningEvent | None:
    rng = random.Random(seed * 7919 + slot * 104729 + 17)
    if rng.random() >= min(0.85, 0.42 * activity):
        return None
    start = slot * LIGHTNING_SLOT_SECONDS + rng.uniform(0.2, LIGHTNING_SLOT_SECONDS - 0.2)
    roll = rng.random()
    kind = "ground" if roll < 0.45 else "cloud" if roll < 0.85 else "sheet"
    if kind == "ground":
        center, channel, branches, strike = ground_bolt(rng)
        strokes, offset = [(0.0, 1.0)], 0.0
        for _ in range(rng.choice((1, 2, 2, 3))):
            offset += rng.uniform(0.06, 0.16)
            strokes.append((offset, rng.uniform(0.45, 0.95)))
    elif kind == "cloud":
        center, channel, branches, strike = cloud_bolt(rng)
        strokes, offset = [(0.0, 0.9)], 0.0
        for _ in range(rng.randint(2, 4)):
            offset += rng.uniform(0.04, 0.12)
            strokes.append((offset, rng.uniform(0.35, 0.85)))
    else:
        center, channel, branches, strike = rng.randint(10, 118), (), (), None
        strokes, offset = [(0.0, rng.uniform(0.3, 0.5))], 0.0
        for _ in range(rng.randint(1, 3)):
            offset += rng.uniform(0.05, 0.14)
            strokes.append((offset, rng.uniform(0.2, 0.45)))
    return LightningEvent(kind, start, tuple(strokes), center, channel, branches, strike)


def lightning_at(environment: "OutsideEnvironment", elapsed: float, seed: int) -> tuple[LightningEvent, float] | None:
    """Return the lightning event visible at `elapsed` and its age, or None outside thunderstorms."""
    code = environment.weather.code
    if code is None or not 200 <= code < 300:
        return None
    activity = THUNDERSTORM_ACTIVITY.get(code, 1.0)
    slot = math.floor(elapsed / LIGHTNING_SLOT_SECONDS)
    for candidate in (slot, slot - 1):
        event = lightning_event(candidate, seed, activity)
        if event is not None:
            age = elapsed - event.start
            if (-LIGHTNING_LEADER_SECONDS if event.kind == "ground" else 0) <= age <= event.end:
                return event, age
    return None


def lightning_light(event: LightningEvent, intensity: float, column: float) -> float:
    base, local, spread = LIGHTNING_LIGHT[event.kind]
    return intensity * (base + local * math.exp(-0.5 * ((column - event.center) / spread) ** 2))


def flash_scene(image: Image.Image, event: LightningEvent, intensity: float, clouds: np.ndarray) -> Image.Image:
    base, local, spread = LIGHTNING_LIGHT[event.kind]
    across = base + local * np.exp(-0.5 * ((FLASH_COLUMNS - event.center) / spread) ** 2)
    # Clouds are already lit from within, so the general flash only half-lights them to keep their shape.
    receive = np.where(clouds, FLASH_RECEIVE * 0.5, FLASH_RECEIVE)
    light = np.clip(intensity * across[None, :] * FLASH_FALLOFF[:, None] * receive, 0, 0.92)[..., None]
    pixels = np.asarray(image, dtype=np.float32)
    return Image.fromarray(np.round(pixels + (np.array(LIGHTNING_FLASH, dtype=np.float32) - pixels) * light).astype(np.uint8), "RGB")


def draw_lightning(image: Image.Image, event: LightningEvent, age: float):
    d = ImageDraw.Draw(image)

    def light(pixels, color, amount):
        for x, y in pixels:
            if not SCENERY[y, x]:
                d.point((x, y), fill=mix(image.getpixel((x, y)), color, amount))

    if age < 0:
        # The faint stepped leader feels its way down before the return stroke.
        reveal = (age + LIGHTNING_LEADER_SECONDS) / LIGHTNING_LEADER_SECONDS
        light(event.channel[: max(1, round(len(event.channel) * reveal))], LIGHTNING_GLOW, 0.5)
        return
    intensity = event.intensity(age)
    channel = event.channel
    if event.kind == "cloud":
        channel = channel[: max(1, round(len(channel) * min(1, age / LIGHTNING_CRAWL_SECONDS)))]
    if intensity >= 0.22:
        on_channel = set(channel)
        halo = {(x + dx, y + dy) for x, y in channel for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))}
        light([(x, y) for x, y in halo - on_channel if 0 <= x < WIDTH and 0 <= y < HEIGHT], LIGHTNING_GLOW, min(1, intensity * 0.75))
        light(channel, LIGHTNING_CORE, min(1, intensity * 1.6))
        if len(channel) == len(event.channel):
            light(event.branches, LIGHTNING_BRANCH, min(1, intensity * 1.1) * 0.85)
        if event.strike is not None:
            sx, sy = event.strike
            for dx, dy, amount in ((0, 0, 0.95), (-1, 0, 0.7), (1, 0, 0.7), (0, 1, 0.55), (-2, 0, 0.35), (2, 0, 0.35)):
                x, y = sx + dx, sy + dy
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    d.point((x, y), fill=mix(image.getpixel((x, y)), (255, 246, 228), amount * min(1, intensity * 1.3)))
    elif intensity > 0.03:
        # The channel lingers as a fading violet afterimage between strokes.
        light(channel, LIGHTNING_GLOW, min(1, intensity * 2.2))


def render_outside_frame(environment: "OutsideEnvironment", elapsed: float, seed: int = 0) -> Image.Image:
    palette = scene_palette(environment)
    image = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = min(1, y / 21)
        color = mix(palette.top, palette.middle, t / 0.55) if t < 0.55 else mix(palette.middle, palette.horizon, (t - 0.55) / 0.45)
        d.line((0, y, 127, y), fill=color)
    lightning = lightning_at(environment, elapsed, seed)
    clouds = draw_sky(image, environment, palette, elapsed, lightning)
    rain, snow = precipitation(environment)
    winter = environment.season == "winter"
    # The mountain keeps its snow all winter, even between snowfalls.
    land, foliage, wood = landscape(palette, winter, snow > 0, winter or snow > 0)
    image.paste(land, (0, 0), land)
    d = ImageDraw.Draw(image)
    for x, y, width, phase in RIPPLES:
        wave = 0.5 + 0.5 * math.sin(elapsed * 0.8 + phase)
        drift = round(math.sin(elapsed * 0.35 + phase))
        color = mix(palette.water, palette.glint, 0.22 + wave * 0.25)
        for column in range(x + drift, x + width + drift + 1):
            if LAND.getpixel((column, y)) == INDEX["water"]:
                d.point((column, y), fill=color)
    mist = environment.weather.visibility is not None and environment.weather.visibility < 5000
    if mist or environment.weather.code in (701, 711, 721, 741):
        fog = Image.new("RGBA", (WIDTH, HEIGHT))
        fd = ImageDraw.Draw(fog)
        for index in range(3):
            x = round((elapsed * 0.22 + index * 49) % 168) - 40
            fd.ellipse((x, 22 + index, x + 70, 25 + index), fill=(*palette.far, 90))
        image.paste(fog, (0, 0), fog)
    draw_wildlife(image, palette, environment, elapsed, seed)
    wind = environment.weather.wind or 0
    sway = round(math.sin(elapsed * 0.6) * min(1, wind / 12))
    if foliage is not None:
        image.paste(foliage, (sway, 0), foliage)
    d = ImageDraw.Draw(image)
    if environment.season == "spring":
        for dx, dy in TREE_BLOSSOMS:
            if environment.sun_altitude is not None and environment.sun_altitude > -5:
                d.point((TREE_X + dx + sway, TREE_CANOPY_Y + dy), fill=mix(palette.leaf_light, (239, 186, 182), 0.45))
    image.paste(wood, (0, 0), wood)
    night = environment.sun_altitude is not None and environment.sun_altitude < -6
    if night and environment.season in ("spring", "summer", "autumn") and rain == 0 and snow == 0 and wind < 15:
        for index, (x, y) in enumerate([(48, 29), (69, 31), (78, 28), (102, 30)]):
            glow = max(0, math.sin(elapsed * 0.8 + index * 2.4)) ** 3
            d.point((x, y), fill=mix(image.getpixel((x, y)), (180, 172, 74), glow * 0.65))
    if rain > 0:
        draw_rain(image, rain, wind, elapsed)
    if snow > 0:
        count = min(40, round(10 + snow * 9))
        for x0, y0, pace, phase in PARTICLES[:count]:
            y = int((y0 + elapsed * 1.6 * pace) % 36) - 2
            x = int((x0 + min(wind, 25) * elapsed * 0.035 + math.sin(elapsed * 0.7 + phase) * 2) % 128)
            if 0 <= y < HEIGHT:
                d.point((x, y), fill=mix(image.getpixel((x, y)), (234, 235, 225), 0.65 + (phase % 5) * 0.025))
    if lightning is not None:
        event, age = lightning
        if age >= 0 and event.intensity(age) > 0.01:
            image = flash_scene(image, event, event.intensity(age), clouds)
        draw_lightning(image, event, age)
    return grade_frame(image)


@lru_cache(maxsize=1)
def overlay_font() -> bitmap_graphics.Font:
    font = bitmap_graphics.Font()
    font.LoadFont(os.path.join(shared_config.font_dir, "4x6.bdf"))
    return font


@lru_cache(maxsize=128)
def overlay_text_mask(text: str) -> Image.Image:
    canvas = Canvas(len(text) * 4, 5)
    bitmap_graphics.DrawText(canvas, overlay_font(), 0, 5, bitmap_graphics.Color(255, 255, 255), text)
    mask = canvas._image.convert("L")
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError("Outside overlay text must contain visible glyphs")
    return mask.crop((bounds[0], 0, bounds[2], 5))


def overlay_relative_luminance(background: Image.Image, mask: Image.Image) -> float:
    channels = ImageStat.Stat(background.point(OVERLAY_LINEAR_LUT), mask).mean
    return sum(value * weight for value, weight in zip(channels, (0.2126, 0.7152, 0.0722))) / 255


def overlay_contrast_fraction(luminance: float) -> float:
    fraction = max(0, min(1, (luminance - OVERLAY_DARK_LUMINANCE) / (OVERLAY_BRIGHT_LUMINANCE - OVERLAY_DARK_LUMINANCE)))
    return fraction * fraction * (3 - 2 * fraction)


def draw_overlay(image: Image.Image, mask: Image.Image, x: int, *, previous_dark: bool | None = None, hold_style: bool = False) -> bool | None:
    if mask.getbbox() is None:
        return previous_dark
    background = image.crop((x, 0, x + mask.width, mask.height))
    luminance = overlay_relative_luminance(background, mask)
    threshold = OVERLAY_POLARITY_LUMINANCE + (OVERLAY_POLARITY_HYSTERESIS if previous_dark is False else -OVERLAY_POLARITY_HYSTERESIS if previous_dark is True else 0)
    dark_text = previous_dark if hold_style and previous_dark is not None else luminance >= threshold
    if dark_text:
        lettering = Image.new("RGB", background.size)
    else:
        contrast = overlay_contrast_fraction(luminance)
        color = mix((205, 218, 231), (255, 255, 255), contrast)
        opacity = OVERLAY_NIGHT_OPACITY + (1 - OVERLAY_NIGHT_OPACITY) * contrast
        lettering = Image.blend(background, Image.new("RGB", background.size, color), opacity)
    image.paste(lettering, (x, 0), mask)
    return dark_text


def draw_corner_label(image: Image.Image, text: str, *, right: bool = False, previous_dark: bool | None = None, hold_style: bool = False) -> bool | None:
    mask = overlay_text_mask(text)
    return draw_overlay(image, mask, WIDTH - mask.width if right else 0, previous_dark=previous_dark, hold_style=hold_style)


def outside_notice(environment: "OutsideEnvironment") -> str:
    """Forecast conditions while scrubbing ahead, otherwise data-status notices."""
    weather = environment.weather
    notices = []
    if environment.offset_minutes:
        if weather.status in ("FORECAST", "FORECAST_CACHED") and weather.code in WEATHER_DESCRIPTIONS:
            notices.append(WEATHER_DESCRIPTIONS[weather.code].upper() + ("~" if weather.status == "FORECAST_CACHED" else ""))
        else:
            notices.append("FCST?")
    elif weather.status != "LIVE":
        notices.append("WX~" if weather.status == "CACHED" else "WX?")
    if environment.sky_status != "READY":
        notices.append("SKY..." if environment.sky_status == "LOADING" else "SKY?")
    return " ".join(notices)


@lru_cache(maxsize=64)
def notice_strip(text: str) -> Image.Image:
    mask = overlay_text_mask(text)
    strip = Image.new("L", (mask.width * 2 + NOTICE_SCROLL_SPACING, mask.height))
    strip.paste(mask, (0, 0))
    strip.paste(mask, (mask.width + NOTICE_SCROLL_SPACING, 0))
    return strip


def draw_notice(image: Image.Image, text: str, left: int, right: int, elapsed: float, *, previous_dark: bool | None = None, hold_style: bool = False) -> bool | None:
    """Center `text` between the corner labels, scrolling it when it does not fit."""
    mask = overlay_text_mask(text)
    width = right - left
    if width <= 0:
        return previous_dark
    if mask.width <= width:
        x = max(left, min(right - mask.width, WIDTH // 2 - mask.width // 2))
        return draw_overlay(image, mask, x, previous_dark=previous_dark, hold_style=hold_style)
    period = mask.width + NOTICE_SCROLL_SPACING
    moment = elapsed % (NOTICE_SCROLL_PAUSE + period / NOTICE_SCROLL_SPEED)
    offset = round(max(0, moment - NOTICE_SCROLL_PAUSE) * NOTICE_SCROLL_SPEED) % period
    return draw_overlay(image, notice_strip(text).crop((offset, 0, offset + width, mask.height)), left, previous_dark=previous_dark, hold_style=hold_style)


def draw_outside_frame(sign, environment: "OutsideEnvironment", elapsed: float, seed: int = 0, *, moment: datetime, military_time: bool, previous_text_styles: tuple[bool | None, ...] = (None, None, None)) -> tuple[bool | None, bool | None, bool | None]:
    image = render_outside_frame(environment, elapsed, seed)
    clock = moment.strftime("%H:%M" if military_time else "%-I:%M%p")
    temperature = environment.weather.temperature
    temperature_text = f"{round(temperature)}°F" if temperature is not None and environment.weather.status in ("LIVE", "CACHED", "FORECAST", "FORECAST_CACHED") else "--°F"
    previous_clock, previous_temperature, previous_notice = (*previous_text_styles, None, None, None)[:3]
    # Lightning flashes last a few frames; keep the labels' black/white style steady through them.
    flashing = lightning_at(environment, elapsed, seed) is not None
    clock_dark = draw_corner_label(image, clock, previous_dark=previous_clock, hold_style=flashing)
    temperature_dark = draw_corner_label(image, temperature_text, right=True, previous_dark=previous_temperature, hold_style=flashing)
    notice = outside_notice(environment)
    notice_dark = None
    if notice:
        left = overlay_text_mask(clock).width + OVERLAY_GAP
        right = WIDTH - overlay_text_mask(temperature_text).width - OVERLAY_GAP
        notice_dark = draw_notice(image, notice, left, right, elapsed, previous_dark=previous_notice, hold_style=flashing)
    sign.canvas.SetImage(image)
    return clock_dark, temperature_dark, notice_dark
