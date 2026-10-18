"""Quiet Valley pixel art. Static geometry is cached; only intended motion changes."""

import math
import os
import random
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import date, datetime, timedelta
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
# Labels sit this many pixels in from the top and outer edges, so sky frames black text that would
# otherwise merge into the unlit border around the panel.
OVERLAY_MARGIN = 1
# Stars stay this many pixels clear of the clock and temperature glyphs, so a twinkle never reads as part of a digit.
LABEL_STAR_MARGIN = 2
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
    hut: Color
    trim: Color
    water: Color
    glint: Color
    animal: Color
    snowcap: Color
    shingle: Color
    door: Color
    dog: Color


DUSK = Palette(
    (24, 46, 82),
    (99, 105, 136),
    (241, 162, 110),
    (95, 99, 125),
    (43, 71, 81),
    (62, 88, 76),
    (22, 48, 48),
    (116, 132, 94),
    (85, 84, 73),
    (159, 130, 78),
    (35, 56, 59),
    (32, 42, 49),
    (57, 47, 60),
    (190, 138, 98),
    (235, 198, 139),
    (68, 102, 121),
    (220, 163, 122),
    (170, 155, 122),
    (238, 196, 186),
    (76, 50, 46),
    (66, 42, 36),
    (242, 212, 174),
)
DAY = Palette(
    (48, 130, 175),
    (100, 175, 191),
    (194, 213, 181),
    (99, 147, 143),
    (54, 106, 91),
    (104, 153, 79),
    (43, 94, 53),
    (164, 183, 86),
    (63, 125, 65),
    (148, 181, 74),
    (40, 86, 57),
    (80, 62, 47),
    (67, 65, 72),
    (200, 154, 106),
    (239, 220, 171),
    (55, 147, 169),
    (167, 219, 208),
    (166, 119, 73),
    (232, 238, 245),
    (96, 62, 44),
    (84, 54, 36),
    (238, 228, 198),
)
NIGHT = Palette(
    (5, 11, 28),
    (16, 29, 55),
    (53, 67, 91),
    (36, 48, 70),
    (23, 42, 55),
    (29, 51, 51),
    (13, 30, 35),
    (59, 79, 60),
    (46, 62, 60),
    (83, 98, 70),
    (26, 44, 47),
    (18, 26, 34),
    (23, 28, 43),
    (86, 72, 64),
    (139, 149, 146),
    (34, 65, 85),
    (129, 159, 171),
    (122, 127, 108),
    (122, 137, 162),
    (34, 27, 31),
    (30, 23, 22),
    (116, 114, 106),
)
MATERIALS = tuple(field.name for field in fields(Palette))
INDEX = {name: index + 1 for index, name in enumerate(MATERIALS)}
INDEX["hill"] = len(MATERIALS) + 1
INDEX["peak"] = len(MATERIALS) + 2
INDEX["chimney"] = len(MATERIALS) + 3
# One prominent peak right of center keeps the rest of the horizon low so the night sky stays open.
MOUNTAIN = ((62, 23), (66, 22), (70, 20), (74, 17), (77, 15), (80, 14), (83, 13), (86, 14), (89, 15), (92, 17), (96, 20), (100, 21), (106, 23), (127, 23))
# The sunlit face runs from the summit down this spur to the foot of the mountain.
MOUNTAIN_LIT_FACE = ((83, 13), (80, 14), (77, 15), (74, 17), (70, 20), (66, 22), (62, 23), (78, 23), (80, 19), (82, 15))
# The mountain is darkened in linear light so it stands out from the bright horizon behind it;
# its sunlit face is then lifted back toward the horizon color.
MOUNTAIN_SHADE, MOUNTAIN_LIT = 0.3, 0.16
TREE_X, TREE_CANOPY_Y = 111, 15
# Small conifers flanking the hut: (trunk x, base row, height); the apex is at row base - height.
CONIFERS = ((4, 28, 12), (38, 25, 7))
HUT_ROOF = ((19, 20), (27, 15), (28, 15), (36, 20))
HUT_DOOR = (26, 21, 29, 25)
HUT_KNOB = (28, 23)
# A small stone chimney on the right roof slope: body box, cap row, and the flue mouth the smoke leaves from.
CHIMNEY = (31, 14, 32, 17)
CHIMNEY_CAP = (31, 13, 32, 13)
CHIMNEY_FLUE = (31.5, 12.5)
LAMP_POST_X = 14
LAMP_LENS = (17, 17)
LAMP_GROUND_Y = 26
LAMP_SECONDS = 3 * 3600
LAMP_WARMUP_SECONDS = 40
# Sun altitude (degrees) at which the scene palette becomes pure night.
NIGHT_ALTITUDE = -10
LAMP_LIGHT = (255, 200, 120)
LAMP_GLOW = (255, 236, 190)
# A full, lobed maple: a 2 px trunk forks into limbs ((points), width) under a shaded core crown
# ringed by nine small lobes, which gives a scalloped edge instead of one smooth blob.
TREE_LIMBS = (
    (((111, 31), (111, 22)), 2),
    (((111, 23), (107, 19), (104, 16), (102, 13)), 1),
    (((112, 23), (116, 19), (119, 16), (120, 13)), 1),
    (((111, 22), (111, 16), (110, 11)), 1),
    (((111, 18), (115, 14), (116, 11)), 1),
    (((111, 18), (107, 15), (106, 11)), 1),
    (((107, 19), (103, 19)), 1),
    (((116, 19), (120, 19)), 1),
)
TREE_FLARE = ((109, 31), (114, 31))
TREE_TWIG_LENGTH = 2.34
TREE_CROWN = (111, 14.8)
# Foliage clumps, back to front: (x, y, rx, ry).
TREE_CLUMPS = (
    (*TREE_CROWN, 6.84, 4.32),
    *((TREE_CROWN[0] + 7.38 * math.cos(angle), TREE_CROWN[1] + 4.14 * math.sin(angle), 2.61, 2.16) for angle in (-math.pi / 2 + i * 2 * math.pi / 9 for i in range(9))),
)
# The temperature label owns rows 1-6; leaves never start above this row.
TREE_FOLIAGE_TOP = 7
TREE_BLOSSOMS = ((-8, -3), (-2, -5), (5, 1), (4, 2), (7, -3))


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
        palette = blend_palette(NIGHT, DUSK, 1 - altitude / NIGHT_ALTITUDE)
        illumination = moonlight(environment) * max(0, min(1, altitude / NIGHT_ALTITUDE))
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
    if HALLOWEEN in holiday_features(environment):
        eerie = holiday_darkness(environment)
        palette = replace(palette, top=mix(palette.top, HALLOWEEN_SKY_TOP, eerie * 0.55), middle=mix(palette.middle, HALLOWEEN_SKY_MIDDLE, eerie * 0.45))
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
    # Wood hut: plank walls with corner posts, a shingled roof and a front door with a knob.
    d.rectangle((21, 20, 34, 25), fill=INDEX["hut"])
    for y in (22, 24):
        d.line((21, y, 34, y), fill=INDEX["trunk"])
    d.line((21, 20, 21, 25), fill=INDEX["trunk"])
    d.line((34, 20, 34, 25), fill=INDEX["trunk"])
    d.polygon(HUT_ROOF, fill=INDEX["shingle"])
    for y in (17, 19):
        inset = math.ceil((20 - y) * 8 / 5)
        d.line((19 + inset, y, 36 - inset, y), fill=INDEX["trunk"])
    d.line(HUT_ROOF[:2], fill=INDEX["trunk"])
    d.line((19, 20, 36, 20), fill=INDEX["trunk"])
    d.rectangle(CHIMNEY, fill=INDEX["chimney"])
    d.rectangle(CHIMNEY_CAP, fill=INDEX["roof"])
    d.rectangle(HUT_DOOR, fill=INDEX["door"])
    d.point(HUT_KNOB, fill=INDEX["trim"])
    # Yard lamp: a post with an arm reaching toward the hut and a hood that shines down.
    lens_x, lens_y = LAMP_LENS
    d.line((LAMP_POST_X, lens_y - 1, LAMP_POST_X, LAMP_GROUND_Y), fill=INDEX["roof"])
    d.line((LAMP_POST_X - 1, LAMP_GROUND_Y, LAMP_POST_X + 1, LAMP_GROUND_Y), fill=INDEX["roof"])
    d.line((LAMP_POST_X, lens_y - 1, lens_x + 1, lens_y - 1), fill=INDEX["roof"])
    d.line((lens_x - 1, lens_y, lens_x + 1, lens_y), fill=INDEX["roof"])
    for x, base, height in CONIFERS:
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
    trunk = INDEX["trunk"]
    for mask in (leafy, bare):
        td = ImageDraw.Draw(mask)
        for points, width in TREE_LIMBS:
            td.line(points, fill=trunk, width=width)
            if width > 1:
                # PIL centers wide lines; fill the joints so bends stay solid.
                for x, y in points[1:-1]:
                    td.rectangle((x, y, x + width - 1, y), fill=trunk)
        td.line(TREE_FLARE, fill=trunk)
    # Winter twigs: two fan out from each limb tip, and one leaves the last bend of longer limbs.
    td = ImageDraw.Draw(bare)
    for points, width in TREE_LIMBS:
        if width > 1:
            continue
        (x0, y0), (x1, y1) = points[-2:]
        angle = math.atan2(y1 - y0, x1 - x0)
        for turn in (-0.62, 0.55):
            td.line((x1, y1, round(x1 + math.cos(angle + turn) * TREE_TWIG_LENGTH), round(y1 + math.sin(angle + turn) * TREE_TWIG_LENGTH)), fill=trunk)
        if len(points) >= 3:
            (mx, my), (nx, ny) = points[-3:-1]
            angle = math.atan2(ny - my, nx - mx) + (-0.9 if nx < TREE_X else 0.9)
            td.line((nx, ny, round(nx + math.cos(angle) * TREE_TWIG_LENGTH * 0.8), round(ny + math.sin(angle) * TREE_TWIG_LENGTH * 0.8)), fill=trunk)
    # Foliage: each pixel belongs to the front-most clump containing it. Clumps are shaded from the
    # upper left, a front lobe casts a dark rim onto the clump behind it, and a few pixels open to the sky.
    owner = {}
    for y in range(TREE_FOLIAGE_TOP, HEIGHT):
        for x in range(TREE_X - 14, min(WIDTH, TREE_X + 15)):
            for index, (cx, cy, rx, ry) in enumerate(TREE_CLUMPS):
                nx, ny = (x - cx) / rx, (y - cy) / ry
                if nx * nx + ny * ny < 1 + (grain(x, y, 12 + index) - 48) / 210:
                    owner[x, y] = (index, nx, ny)
    pixels = leafy.load()
    for (x, y), (index, nx, ny) in owner.items():
        n = grain(x, y, 31)
        shade = -(0.55 * nx + 0.85 * ny) + (n - 48) / 160
        material = "leaf_light" if shade > 0.42 else "leaf_dark" if shade < -0.38 else "leaf"
        above, left = owner.get((x, y - 1)), owner.get((x - 1, y))
        if (above and above[0] > index) or (left and left[0] > index and n < 60):
            material = "leaf_dark"
        if owner.get((x, y + 1)) is None and material == "leaf_light":
            material = "leaf"
        if n < 4 and shade < 0.2:
            continue
        pixels[x, y] = INDEX[material]
    return land, leafy, bare


LAND, LEAFY_TREE, BARE_TREE = geometry()
CHIMNEY_MASK = Image.new("L", (WIDTH, HEIGHT), 0)
ImageDraw.Draw(CHIMNEY_MASK).rectangle(CHIMNEY, fill=255)
ImageDraw.Draw(CHIMNEY_MASK).rectangle(CHIMNEY_CAP, fill=255)
TREE_FOLIAGE = LEAFY_TREE.point([value if value in (INDEX["leaf"], INDEX["leaf_light"], INDEX["leaf_dark"]) else 0 for value in range(256)])
TREE_WOOD = LEAFY_TREE.point([value if value == INDEX["trunk"] else 0 for value in range(256)])
# The Big Dipper (Ursa Major) right of the mountain, projected from the real stars at 0.7 px per degree in its
# autumn-evening pose (bowl upright, handle to the left), turned 20 degrees to level the handle:
# (x, y, peak brightness from magnitude, color). Dubhe and Merak, the pointers, form the bowl's right edge.
BIG_DIPPER = (
    (81, 5, 0.98, (232, 240, 255)),  # Alkaid
    (85, 4, 0.87, (232, 240, 255)),  # Mizar
    (88, 4, 1.0, (232, 240, 255)),  # Alioth
    (92, 5, 0.55, (232, 240, 255)),  # Megrez
    (93, 8, 0.81, (232, 240, 255)),  # Phecda
    (99, 7, 0.83, (232, 240, 255)),  # Merak
    (99, 3, 1.0, (255, 222, 180)),  # Dubhe
)
# The other constellations use the Dipper's brightness scale, peak = min(1, 1 - 0.29 * (magnitude - 1.8)), and are
# drawn as seen when facing them. Orion's three belt stars sit just left of center, projected at 2.2 px per degree
# (larger than the Dipper so they separate) with the spacing evened out.
ORION_BELT = (
    (54, 11, 1.0, (218, 230, 255)),  # Alnitak
    (57, 9, 1.0, (218, 230, 255)),  # Alnilam
    (60, 7, 0.87, (218, 230, 255)),  # Mintaka
)
# South of the equator Orion stands on his head: the belt is the base of "the Saucepan" and the sword its handle,
# rising above the belt. The same projection turned 180 degrees, set lower to leave room for the handle.
SAUCEPAN = (
    (54, 15, 0.87, (218, 230, 255)),  # Mintaka
    (57, 13, 1.0, (218, 230, 255)),  # Alnilam
    (60, 11, 1.0, (218, 230, 255)),  # Alnitak
    (56, 5, 0.25, (218, 230, 255)),  # 42 Orionis
    (56, 4, 0.36, (232, 222, 236)),  # The Orion Nebula's Trapezium
    (56, 3, 0.72, (218, 230, 255)),  # Iota Orionis, the handle's tip
)
# The Southern Cross (Crux) where the Dipper stands in the north, upright as it is when highest, with its
# Pointers (Alpha and Beta Centauri) leading up to it from the lower left. Projected at 1.4 px per degree, turned 10 degrees.
SOUTHERN_CROSS = (
    (94, 2, 1.0, (255, 196, 150)),  # Gacrux, a red giant
    (91, 5, 1.0, (222, 232, 255)),  # Mimosa
    (97, 5, 0.71, (222, 232, 255)),  # Delta Crucis
    (95, 7, 0.48, (232, 240, 255)),  # Epsilon Crucis
    (94, 10, 1.0, (222, 232, 255)),  # Acrux
)
POINTERS = (
    (71, 9, 1.0, (255, 240, 214)),  # Alpha Centauri
    (78, 7, 1.0, (222, 232, 255)),  # Hadar (Beta Centauri)
)
# Each hemisphere's star groups; the hemisphere comes from SENSOR_LAT (or the Outside lab). The Pointers share the
# Cross's field-star clearing, so no stray star breaks the line between them.
CONSTELLATIONS = {"north": (BIG_DIPPER, ORION_BELT), "south": (SOUTHERN_CROSS + POINTERS, SAUCEPAN)}
# Haze near the horizon hides faint stars, so field stars stay more than this many pixels from any land.
STAR_HORIZON_CLEARANCE = 4
LAND_ROWS, LAND_COLUMNS = np.nonzero(np.asarray(LAND))


def field_stars(groups) -> tuple[tuple[int, int, int], ...]:
    # Random field stars keep a 3 px berth around each star group so its shape reads cleanly.
    bounds = [(min(s[0] for s in g) - 3, min(s[1] for s in g) - 3, max(s[0] for s in g) + 3, max(s[1] for s in g) + 3) for g in groups]
    return tuple(
        (x, y, grain(x, y, 5))
        for y in range(1, 21)
        for x in range(2, 126)
        if grain(x, y, 9) < 2
        and not any(left <= x <= right and top <= y <= bottom for left, top, right, bottom in bounds)
        and np.min(np.hypot(LAND_COLUMNS - x, LAND_ROWS - y)) > STAR_HORIZON_CLEARANCE
    )


STARS = {hemisphere: field_stars(groups) for hemisphere, groups in CONSTELLATIONS.items()}
CONSTELLATION_STARS = {hemisphere: tuple(star for group in groups for star in group) for hemisphere, groups in CONSTELLATIONS.items()}
STAR_COLORS = ((232, 244, 255), (255, 239, 207), (225, 231, 255))
RIPPLES = ((60, 27, 15, 0), (55, 28, 9, 2.3), (68, 29, 7, 4.5))
PARTICLES = tuple((grain(i, 3) / 97 * 128, grain(i, 9) / 97 * 35, 0.7 + grain(i, 5) / 97, grain(i, 7)) for i in range(80))
MOON_DIAMETER = 7
# Photo samples per sign pixel along each axis; the phase is cut at this resolution and averaged
# down, so the limb and terminator land on partial pixels instead of stepping on and off.
MOON_SUPERSAMPLE = 32
MOON_LIT = (239, 226, 186)
MOON_EARTHSHINE = (76, 82, 94)
# How much of the photo's albedo range survives: 1 keeps the full maria contrast, 0 paints a flat disk.
MOON_TEXTURE_CONTRAST = 0.7


@lru_cache(maxsize=1)
def moon_textures() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Linear albedo of the sunlit and earthshine photos (1 = bright highlands) and the disk coverage, supersampled."""
    size = MOON_DIAMETER * MOON_SUPERSAMPLE
    lit = Image.open(f"{shared_config.icons_dir}/moon/moon.png").convert("RGBA")
    disk = lit.getchannel("A").getbbox()
    lit = lit.crop(disk).resize((size, size), Image.LANCZOS)
    dark = Image.open(f"{shared_config.icons_dir}/moon/moonbg.png").convert("RGB").crop(disk).resize((size, size), Image.LANCZOS)
    coverage = np.asarray(lit.getchannel("A"), dtype=np.float64) / 255

    def albedo(photo: Image.Image) -> np.ndarray:
        luminance = SRGB_TO_LINEAR_ARRAY[np.asarray(photo)[..., :3]] @ (0.2126, 0.7152, 0.0722)
        relative = np.clip(luminance / np.percentile(luminance[coverage > 0.99], 98), 0, 1)
        return 1 - MOON_TEXTURE_CONTRAST * (1 - relative)

    return albedo(lit), albedo(dark), coverage


@lru_cache(maxsize=64)
def moon_sprite(phase: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Premultiplied linear color and coverage of the sunlit and earthshine sides for a phase in whole degrees
    (0 new, 180 full), shrunk from the photos. The sunlit side faces right while waxing."""
    lit_albedo, dark_albedo, coverage = moon_textures()
    size = MOON_DIAMETER * MOON_SUPERSAMPLE
    axis = (np.arange(size) + 0.5) / size * 2 - 1
    across, down = axis[None, :], axis[:, None]
    edge = np.sqrt(np.clip(1 - down * down, 0, None))
    angle = math.radians(phase)
    sunlit = across >= math.cos(angle) * edge if angle <= math.pi else across <= -math.cos(angle) * edge
    lit_coverage = coverage * sunlit
    dark_coverage = coverage - lit_coverage

    def shrink(values: np.ndarray) -> np.ndarray:
        return values.reshape(MOON_DIAMETER, MOON_SUPERSAMPLE, MOON_DIAMETER, MOON_SUPERSAMPLE).mean(axis=(1, 3))

    def tint(color: Color) -> np.ndarray:
        return SRGB_TO_LINEAR_ARRAY[np.array(color)]

    return (
        shrink(lit_albedo * lit_coverage)[..., None] * tint(MOON_LIT),
        shrink(lit_coverage),
        shrink(dark_albedo * dark_coverage)[..., None] * tint(MOON_EARTHSHINE),
        shrink(dark_coverage),
    )


def draw_moon(image: Image.Image, cx: int, cy: int, phase: float, lit_strength: float, earthshine_strength: float):
    """Blend the moon sprite over the sky in linear light; the earthshine side also hides the stars behind it."""
    lit_color, lit_alpha, dark_color, dark_alpha = moon_sprite(round(phase) % 360)
    left, top = cx - MOON_DIAMETER // 2, cy - MOON_DIAMETER // 2
    box = (max(0, left), max(0, top), min(WIDTH, left + MOON_DIAMETER), min(HEIGHT, top + MOON_DIAMETER))
    if box[0] >= box[2] or box[1] >= box[3]:
        return
    window = (slice(box[1] - top, box[3] - top), slice(box[0] - left, box[2] - left))
    sky = SRGB_TO_LINEAR_ARRAY[np.asarray(image.crop(box))]
    alpha = lit_alpha[window] * lit_strength + dark_alpha[window] * earthshine_strength
    linear = sky * (1 - alpha[..., None]) + lit_color[window] * lit_strength + dark_color[window] * earthshine_strength
    image.paste(Image.fromarray(linear_to_srgb_array(linear), "RGB"), box)


@lru_cache(maxsize=96)
def landscape(palette: Palette, bare: bool, snow: bool, snowcap: bool):
    mountain = mix(palette.far, (0, 0, 0), MOUNTAIN_SHADE)
    table = [0, 0, 0]
    for name in MATERIALS:
        table.extend(mountain if name == "far" else getattr(palette, name))
    table.extend(mix(palette.far, palette.ridge, 0.6))
    table.extend(mix(mountain, palette.horizon, MOUNTAIN_LIT))
    table.extend(mix(palette.roof, palette.trim, 0.3))
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
        for x in range(128):
            if grain(x, 26, 1) < 25 and LAND.getpixel((x, 26)) not in (0, INDEX["water"], INDEX["hut"], INDEX["door"]):
                d.point((x, 26), fill=palette.grass)
        chimney = land.copy()
        d.line((19, 19, 27, 15, 28, 15, 36, 19), fill=palette.trim)
        # The roof's snow stops at the chimney, which carries its own cap of snow.
        land.paste(chimney, (0, 0), CHIMNEY_MASK)
        d.line((CHIMNEY_CAP[0], CHIMNEY_CAP[1] - 1, CHIMNEY_CAP[2], CHIMNEY_CAP[1] - 1), fill=palette.trim)
        d.line((3, 27, 40, 27), fill=palette.grass)
    if snowcap:
        d = ImageDraw.Draw(land)
        summit = min(y for _, y in MOUNTAIN)
        for y in range(summit, summit + 4):
            for x in range(WIDTH):
                material = LAND.getpixel((x, y))
                if material in (INDEX["far"], INDEX["peak"]) and y < summit + 2 + grain(x, y, 4) % 2:
                    d.point((x, y), fill=palette.snowcap if material == INDEX["peak"] else mix(palette.snowcap, mountain, 0.35))
    return land, foliage, wood


SET_ALTITUDE = -0.833
CELESTIAL_CENTER_X, CELESTIAL_SWING_X = 68.5, 89.5
CELESTIAL_SET_Y, CELESTIAL_ZENITH_Y = 25.5, 2


def celestial_position(altitude: float, azimuth: float) -> tuple[int, int]:
    # Half the azimuth from south keeps the mapping monotonic, so a setting body keeps moving
    # right past the tree instead of folding back at due west; due east and west land near the
    # edges, and the center is clamped so a summer sun slides down the edge rather than leaving.
    swing = math.sin(math.radians((azimuth % 360 - 180) / 2))
    x = min(WIDTH - 2, max(1, CELESTIAL_CENTER_X + CELESTIAL_SWING_X * swing))
    # The square root spreads low altitudes out, so bodies visibly sink into the land and are
    # fully below the right-hand horizon (y=23) at SET_ALTITUDE.
    height = math.sqrt(max(0, altitude - SET_ALTITUDE) / (90 - SET_ALTITUDE))
    return round(x), round(CELESTIAL_SET_Y - (CELESTIAL_SET_Y - CELESTIAL_ZENITH_Y) * height)


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


SHOOTING_STAR_SLOT_SECONDS = 30
SHOOTING_STAR_CHANCE = 0.35
SHOOTING_STAR_TRAIL = 8
SHOOTING_STAR_LOWEST_ROW = 17
SHOOTING_STAR_COLOR = (238, 244, 255)


@dataclass(frozen=True)
class ShootingStar:
    start: float
    duration: float
    origin: tuple[float, float]
    velocity: tuple[float, float]
    peak: float


@lru_cache(maxsize=16)
def shooting_star(slot: int, seed: int) -> ShootingStar | None:
    """At most one meteor per slot, streaking down and across the upper sky."""
    rng = random.Random(seed * 7919 + slot * 104729 + 11)
    if rng.random() > SHOOTING_STAR_CHANCE:
        return None
    duration = rng.uniform(0.45, 0.9)
    direction = rng.choice((-1, 1))
    x = rng.uniform(12, 88) if direction > 0 else rng.uniform(40, 116)
    y = rng.uniform(3, 9)
    angle = math.radians(rng.uniform(15, 38))
    distance = min(rng.uniform(18, 34), (SHOOTING_STAR_LOWEST_ROW - y) / math.sin(angle))
    start = slot * SHOOTING_STAR_SLOT_SECONDS + rng.uniform(0, SHOOTING_STAR_SLOT_SECONDS - duration)
    velocity = (direction * distance * math.cos(angle) / duration, distance * math.sin(angle) / duration)
    return ShootingStar(start, duration, (x, y), velocity, rng.uniform(0.75, 1.0))


Box = tuple[int, int, int, int]


def in_boxes(x: int, y: int, boxes: tuple[Box, ...]) -> bool:
    return any(left <= x <= right and top <= y <= bottom for left, top, right, bottom in boxes)


def shooting_star_state(elapsed: float, seed: int) -> ShootingStar | None:
    """The meteor streaking at `elapsed`, if any; it only shows where stars do."""
    star = shooting_star(math.floor(elapsed / SHOOTING_STAR_SLOT_SECONDS), seed)
    return star if star is not None and star.start <= elapsed < star.start + star.duration else None


def starlight(environment: "OutsideEnvironment") -> float:
    """How strongly stars show: 0 in daylight, dimmed by cloud cover and moonlight."""
    altitude = environment.sun_altitude
    night = max(0, min(1, -(altitude + 4) / 7)) if altitude is not None else 0
    return night * (1 - cloud_cover(environment) * 0.92) * (1 - moonlight(environment) * 0.25)


def draw_shooting_star(image: Image.Image, elapsed: float, visibility: float, seed: int, clearings: tuple[Box, ...] = ()):
    star = shooting_star_state(elapsed, seed)
    if star is None:
        return
    age = elapsed - star.start
    progress = age / star.duration
    # Flares quickly, then burns out toward the end of its path.
    envelope = star.peak * min(1, progress / 0.15) * min(1, (1 - progress) / 0.45)
    speed = math.hypot(*star.velocity)
    trail = min(SHOOTING_STAR_TRAIL, speed * age)
    head_x, head_y = star.origin[0] + star.velocity[0] * age, star.origin[1] + star.velocity[1] * age
    strengths: dict[tuple[int, int], float] = {}
    samples = max(1, math.ceil(trail * 2))
    for index in range(samples + 1):
        back = trail * index / samples
        x = round(head_x - star.velocity[0] / speed * back)
        y = round(head_y - star.velocity[1] / speed * back)
        if 0 <= x < WIDTH and 0 <= y < HEIGHT and not in_boxes(x, y, clearings):
            fade = (1 - back / SHOOTING_STAR_TRAIL) ** 1.6
            strengths[(x, y)] = max(strengths.get((x, y), 0), fade)
    d = ImageDraw.Draw(image)
    for (x, y), fade in strengths.items():
        d.point((x, y), fill=mix(image.getpixel((x, y)), SHOOTING_STAR_COLOR, min(1, visibility * envelope * fade)))


def draw_sky(image: Image.Image, environment: "OutsideEnvironment", palette: Palette, elapsed: float, lightning: "tuple[LightningEvent, float] | None" = None, seed: int = 0, star_clearings: tuple[Box, ...] = ()) -> np.ndarray:
    """Draw the sky and return the mask of cloud pixels. Stars skip `star_clearings`; the sky color does not."""
    d = ImageDraw.Draw(image)
    altitude = environment.sun_altitude
    night = max(0, min(1, -(altitude + 4) / 7)) if altitude is not None else 0
    cover = cloud_cover(environment)
    visibility = starlight(environment)
    for x, y, phase in STARS[environment.hemisphere]:
        if star_clearings and in_boxes(x, y, star_clearings):
            continue
        swell = 0.5 + 0.5 * math.sin(elapsed * (0.65 + phase / 160) + phase)
        sparkle = 0.85 + 0.15 * (0.5 + 0.5 * math.sin(elapsed * (1.8 + phase / 110) + phase * 0.37))
        shimmer = 0.04 + 0.96 * swell * swell * sparkle
        strength = visibility * shimmer
        if strength > 0:
            d.point((x, y), fill=mix(image.getpixel((x, y)), STAR_COLORS[phase % len(STAR_COLORS)], strength))
    # Constellations twinkle only gently so their shapes never drop out.
    for index, (x, y, peak, color) in enumerate(CONSTELLATION_STARS[environment.hemisphere]):
        strength = visibility * peak * (0.85 + 0.15 * math.sin(elapsed * (1.1 + index * 0.23) + index * 1.7))
        if strength > 0:
            d.point((x, y), fill=mix(image.getpixel((x, y)), color, strength))
    if visibility > 0:
        draw_shooting_star(image, elapsed, visibility, seed, star_clearings)
    glows = []
    if altitude is not None and altitude > SET_ALTITUDE:
        cx, cy = celestial_position(altitude, environment.sun_azimuth)
        sun = mix((255, 164, 94), (255, 235, 170), altitude / 20)
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=mix(palette.middle, sun, 0.23))
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=sun)
        glows.append((cx, cy, sun, 0.8))
    if environment.moon_altitude is not None and environment.moon_altitude > SET_ALTITUDE:
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
        # Daylight scatters over the earthshine side, so it only shows once night falls.
        draw_moon(image, cx, cy, environment.moon_phase, strength, night * (1 - cover * 0.5))
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


def wildlife_allowed(environment: "OutsideEnvironment") -> bool:
    """Nothing comes out on Halloween, turkeys take the meadow on Thanksgiving, the hotdog mascot has it to himself on
    July 4, animals keep away from a burning campfire, and heavy rain or snow keeps them away."""
    holidays = holiday_features(environment)
    rain, snow = precipitation(environment)
    return HALLOWEEN not in holidays and THANKSGIVING not in holidays and HOTDOG not in holidays and rain < 3 and snow < 2 and campfire_state(environment) is None


def wildlife_state(environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Return (species, visit age, duration, target x, pair) for the visit under way, or None. Deer, foxes and rabbits
    stay away whenever their visit would overlap the dog's time outside."""
    if not wildlife_allowed(environment):
        return None
    slot, age = divmod(elapsed, 100)
    present, species, start, duration, target, pair = wildlife_visit(int(slot), seed)
    if not present or not start <= age < start + duration:
        return None
    visit = slot * 100 + start
    if dog_allowed(environment) and next(dog_outings_between(seed, visit, visit + duration), None) is not None:
        return None
    return species, age - start, duration, target, pair


def birds_allowed(environment: "OutsideEnvironment") -> bool:
    """The songbird flock, or Thanksgiving's geese, fly by day in light weather, but not on Halloween or July 4."""
    rain, snow = precipitation(environment)
    sun_altitude = environment.sun_altitude
    holidays = holiday_features(environment)
    return sun_altitude is not None and sun_altitude > -5 and rain < 1.5 and snow < 1 and HALLOWEEN not in holidays and HOTDOG not in holidays


def draw_wildlife(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Deer, foxes and rabbits, then the songbird flock. Nothing comes out on Halloween; on Thanksgiving turkeys and geese
    take their places."""
    holidays = holiday_features(environment)
    if HALLOWEEN in holidays:
        return
    thanksgiving = THANKSGIVING in holidays
    d = ImageDraw.Draw(image)
    wildlife = wildlife_state(environment, elapsed, seed)
    if wildlife is not None:
        species, visit_age, duration, target, pair = wildlife
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
    if birds_allowed(environment):
        if thanksgiving:
            draw_geese(image, palette, environment, elapsed, seed)
            return
        flock_age = (elapsed + seed % 30) % 85
        flock_start = elapsed - flock_age
        # Small birds keep clear of the sky while an eagle is hunting.
        eagle_near = next(eagle_visits_present(environment, seed, flock_start, flock_start + 35), None) is not None
        if flock_age < 35 and not eagle_near:
            for index in range(3 if environment.season != "winter" else 2):
                x = round(-12 + flock_age * 4.5 - index * 7)
                y = 7 + index % 2 + round(math.sin(elapsed * 0.2 + index) * 1.5)
                wing = 1 if math.sin(elapsed * 7 + index) > 0 else -1
                d.line((x - 1, y - wing, x, y, x + 1, y - wing), fill=palette.roof)


DOG_SLOT_SECONDS = 120
DOG_OUTING_CHANCE = 0.275
DOG_DOOR_SECONDS = 0.6
DOG_DOORWAY = (27.5, 25)
DOG_PORCH = (27.5, 26)
# The fenced yard in front of the hut connects to the meadow past the fence's end.
DOG_GATE = ((44, 26), (47, 29))
DOG_DARK = (30, 24, 22)
# Soft-coated wheaten terrier, facing right: c coat, s shaded coat, t wagging tail, e eye, n nose.
DOG_SPRITES = {
    "run": ("t.....ec", ".ccccccn", ".cccccs.", "s.....s."),
    "gather": ("......ec", "tccccccn", ".cccccs.", "..s.s..."),
    "sit": (".....ec.", ".....ccn", "t..cccs.", ".ccccs.."),
    "sniff": ("........", "tcccc...", ".cccccec", ".s..s.cn"),
    "bow": ("t.......", ".cc.....", ".cccc.ec", ".s..cccn"),
}


@dataclass(frozen=True)
class DogStep:
    start: float
    end: float
    pose: str
    origin: tuple[float, float]
    target: tuple[float, float]
    facing: int
    leap: float


@dataclass(frozen=True)
class DogOuting:
    start: float
    end: float
    steps: tuple[DogStep, ...]


@lru_cache(maxsize=16)
def dog_outing(slot: int, seed: int) -> DogOuting | None:
    """One energetic trip outside: out the door, zoomies around the yard and meadow, then home."""
    rng = random.Random(seed * 6151 + slot * 92821 + 5)
    if rng.random() > DOG_OUTING_CHANCE:
        return None
    start = slot * DOG_SLOT_SECONDS + rng.uniform(2, 18)
    t = start + DOG_DOOR_SECONDS
    steps: list[DogStep] = []
    position, facing, zone = DOG_DOORWAY, 1, "yard"

    def hold(pose: str, seconds: float):
        nonlocal t
        steps.append(DogStep(t, t + seconds, pose, position, position, facing, 0))
        t += seconds

    def go(target: tuple[float, float], speed: float, pose: str = "run"):
        nonlocal t, position, facing
        distance = math.dist(position, target)
        if target[0] != position[0]:
            facing = 1 if target[0] > position[0] else -1
        leap = rng.uniform(2.5, 4) if pose == "run" and distance > 18 and rng.random() < 0.3 else 0
        seconds = max(0.05, distance / speed)
        steps.append(DogStep(t, t + seconds, pose, position, target, facing, leap))
        t += seconds
        position = target

    hold("gather", 0.5)
    go(DOG_PORCH, 10, "trot")
    play_until = t + rng.uniform(35, 65)
    while t < play_until:
        meadow = rng.random() < 0.7
        target = (rng.uniform(48, 100), rng.randint(29, 31)) if meadow else (rng.uniform(9, 40), 26)
        if meadow != (zone == "meadow"):
            for gate in DOG_GATE if meadow else reversed(DOG_GATE):
                go(gate, rng.uniform(22, 30))
        go(target, rng.uniform(22, 34))
        zone = "meadow" if meadow else "yard"
        roll = rng.random()
        if roll < 0.15:
            hold("sniff", rng.uniform(1, 2.5))
        elif roll < 0.27:
            hold("sit", rng.uniform(1.5, 3))
        elif roll < 0.37:
            hold("bow", rng.uniform(0.6, 1))
    if zone == "meadow":
        for gate in reversed(DOG_GATE):
            go(gate, 26)
    go(DOG_PORCH, 24)
    go(DOG_DOORWAY, 8, "trot")
    t += 0.3
    return DogOuting(start, t + DOG_DOOR_SECONDS, tuple(steps))


def dog_allowed(environment: "OutsideEnvironment") -> bool:
    """Dry daylight only, and the dog stays in on Halloween."""
    rain, snow = precipitation(environment)
    return environment.sun_altitude is not None and environment.sun_altitude > -0.833 and rain == 0 and snow == 0 and HALLOWEEN not in holiday_features(environment)


def dog_outings_between(seed: int, first: float, last: float):
    for slot in range(math.floor(first / DOG_SLOT_SECONDS) - 1, math.floor(last / DOG_SLOT_SECONDS) + 1):
        outing = dog_outing(slot, seed)
        if outing is not None and outing.start < last and outing.end > first:
            yield outing


def dog_state(environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Return (door openness, dog pose or None) at `elapsed`."""
    if not dog_allowed(environment):
        return 0.0, None
    outing = next(dog_outings_between(seed, elapsed, elapsed), None)
    if outing is None:
        return 0.0, None
    door = max(0.0, min(1.0, (elapsed - outing.start) / DOG_DOOR_SECONDS, (outing.end - elapsed) / DOG_DOOR_SECONDS))
    step = next((step for step in outing.steps if step.start <= elapsed < step.end), None)
    if step is None:
        return door, None
    progress = (elapsed - step.start) / (step.end - step.start)
    x = step.origin[0] + (step.target[0] - step.origin[0]) * progress
    y = step.origin[1] + (step.target[1] - step.origin[1]) * progress
    pose = step.pose
    if pose in ("run", "trot"):
        stride = int(math.dist(step.origin, (x, y)) / 2.5) % 2
        pose = "gather" if stride else "run"
        if step.leap:
            y -= step.leap * math.sin(math.pi * progress)
        elif step.pose == "run" and stride:
            y -= 1
    # How much of the dog has emerged from the doorway: it steps out gradually and back in the same way.
    reveal = 1.0
    if step.origin == DOG_DOORWAY:
        reveal = 0.0 if step.target == DOG_DOORWAY else progress
    elif step.target == DOG_DOORWAY:
        reveal = 1 - progress
    return door, (x, y, step.facing, pose, reveal)


# The fireplace is lit below this temperature (°F); colder days burn a thicker plume.
SMOKE_MAX_TEMPERATURE = 45
# Cartoon smoke: the flue pops out a round puff every SMOKE_INTERVAL seconds, and each puff
# swells and rises on its own path, so the plume reads as a chain of separate puffs.
SMOKE_INTERVAL = 0.9
SMOKE_LIFETIME = 4.5
# Buoyant rise (px/s at the flue) decays over SMOKE_RISE_SECONDS; wind bends it over, so by
# SMOKE_BEND_WIND mph the rise has halved and puffs leave the flue nearly sideways.
SMOKE_RISE = 4.0
SMOKE_RISE_SECONDS = 2.0
SMOKE_BEND_WIND = 4
# Puffs leave the flue at SMOKE_RADIUS px and swell by SMOKE_GROWTH px/s up to SMOKE_MAX_RADIUS;
# each is up to ±SMOKE_LUMP larger or smaller, so the chain looks hand-drawn.
SMOKE_RADIUS = 1.2
SMOKE_GROWTH = 0.8
SMOKE_MAX_RADIUS = 3.0
SMOKE_LUMP = 0.2
# Puffs hold their opacity, then dissolve over their last SMOKE_FADE_SECONDS.
SMOKE_FADE_SECONDS = 1.2
# The clock label (as wide as "12:59PM") sits right above the chimney on rows 1-6, so smoke
# thins out over SMOKE_CEILING_FADE rows and is gone by SMOKE_CEILING.
SMOKE_CEILING = 8
SMOKE_CEILING_FADE = 2
# Wind carries puffs right, like the flag, rain and snow, at this many px/s per mph; it also
# shreds them sooner.
SMOKE_WIND_DRIFT = 0.3
SMOKE_OPACITY = 0.85
SMOKE_COLOR = (214, 214, 220)
# Light from above: a puff's top is brightened and its underside shaded by up to this fraction.
SMOKE_SHADING = 0.3
# Puffs wider than SMOKE_RIM_RADIUS get a rim this much darker, which outlines each puff
# against the one behind it like an ink line.
SMOKE_RIM = 0.22
SMOKE_RIM_RADIUS = 1.3


def smoke_puffs(environment: "OutsideEnvironment", elapsed: float, seed: int) -> list[tuple[float, float, float, float]]:
    """(x, y, radius, opacity) for chimney smoke puffs, oldest first; none unless a known temperature is cold enough,
    except that the fire burns all Thanksgiving whatever the weather."""
    temperature = environment.weather.temperature
    cold = temperature is not None and temperature < SMOKE_MAX_TEMPERATURE
    if not cold and THANKSGIVING not in holiday_features(environment):
        return []
    wind = min(30, environment.weather.wind or 0)
    strength = 0.7 + 0.3 * min(1, (SMOKE_MAX_TEMPERATURE - temperature) / 25) if cold else 0.7
    life = SMOKE_LIFETIME / (1 + wind / 60)
    rise = SMOKE_RISE / (1 + wind / SMOKE_BEND_WIND)
    drift = wind * SMOKE_WIND_DRIFT
    newest = math.floor(elapsed / SMOKE_INTERVAL)
    puffs = []
    for n in range(newest - math.ceil(life / SMOKE_INTERVAL), newest + 1):
        age = elapsed - n * SMOKE_INTERVAL
        if not 0 <= age < life:
            continue
        phase = grain(n % 9973, 17, seed) / 97 * math.tau
        lump = 1 + SMOKE_LUMP * (grain(n % 9973, 29, seed) / 48.5 - 1)
        up = rise * SMOKE_RISE_SECONDS * (1 - math.exp(-age / SMOKE_RISE_SECONDS))
        # Puffs pick up the wind's speed within a fraction of a second of leaving the flue.
        across = drift * (age - 0.4 * (1 - math.exp(-age / 0.4)))
        # A faint sway keeps a calm column alive without leaning it; gusts toss puffs more.
        wobble = math.sin(age * 1.7 + phase) * (0.3 + wind / 40) * min(1, age)
        x = CHIMNEY_FLUE[0] + across + wobble
        y = CHIMNEY_FLUE[1] - up + math.cos(age * 2.3 + phase) * wind / 60 * min(1, age)
        opacity = SMOKE_OPACITY * strength * min(1, age / 0.15) * min(1, (life - age) / SMOKE_FADE_SECONDS)
        radius = min(SMOKE_MAX_RADIUS, SMOKE_RADIUS + SMOKE_GROWTH * age) * lump
        puffs.append((x, y, radius, opacity))
    return puffs


def draw_smoke(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int) -> Image.Image:
    puffs = smoke_puffs(environment, elapsed, seed)
    if not puffs:
        return image
    left = max(0, math.floor(min(x - r for x, _, r, _ in puffs)) - 1)
    right = min(WIDTH, math.ceil(max(x + r for x, _, r, _ in puffs)) + 1)
    top = max(SMOKE_CEILING, math.floor(min(y - r for _, y, r, _ in puffs)) - 1)
    bottom = min(HEIGHT, math.ceil(max(y + r for _, y, r, _ in puffs)) + 1)
    if left >= right or top >= bottom:
        return image
    columns = np.arange(left, right, dtype=np.float32)[None, :] + 0.5
    rows = np.arange(top, bottom, dtype=np.float32)[:, None] + 0.5
    ceiling = np.clip((rows - SMOKE_CEILING) / SMOKE_CEILING_FADE, 0, 1)
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    color = np.array(mix(palette.horizon, SMOKE_COLOR, 0.35 + 0.4 * illumination), dtype=np.float32) * (0.45 + 0.55 * illumination)
    pixels = np.array(image, dtype=np.float32)
    region = pixels[top:bottom, left:right]
    # Oldest first, so each newer puff overlaps the one above it and its lit top edge
    # separates the two.
    for x, y, radius, opacity in puffs:
        distance = np.hypot(columns - x, rows - y)
        # A crisp disc, antialiased over one pixel so it glides smoothly between pixels.
        cover = np.clip(radius + 0.5 - distance, 0, 1) * opacity * ceiling
        shade = 1 - SMOKE_SHADING * np.clip((rows - y) / radius, -1, 1)
        if radius > SMOKE_RIM_RADIUS:
            shade = shade * (1 - SMOKE_RIM * np.clip(distance - radius + 1.3, 0, 1))
        tint = np.clip(color[None, None, :] * shade[..., None], 0, 255)
        region += (tint - region) * cover[..., None]
    pixels[top:bottom, left:right] = region
    return Image.fromarray(np.round(pixels).astype(np.uint8), "RGB")


def draw_hut_and_dog(image: Image.Image, palette: Palette, door: float, dog, elapsed: float):
    d = ImageDraw.Draw(image)
    x0, y0, x1, y1 = HUT_DOOR
    if door > 0:
        d.rectangle(HUT_DOOR, fill=mix(palette.door, (6, 4, 4), 0.75))
        panel = round((x1 - x0 + 1) * (1 - door))
        if panel > 0:
            d.rectangle((x0, y0, x0 + panel - 1, y1), fill=palette.door)
            if panel >= 3:
                d.point((x0 + panel - 1, HUT_KNOB[1]), fill=palette.trim)
        else:
            # The open door, seen edge-on at its hinge.
            d.line((x0, y0, x0, y1), fill=mix(palette.door, palette.trunk, 0.5))
    if dog is None:
        return
    x, y, facing, pose, reveal = dog
    coat, shade = palette.dog, mix(palette.dog, palette.trunk, 0.3)
    colors = {"c": coat, "s": shade, "t": coat, "e": DOG_DARK, "n": DOG_DARK}
    wag = int(elapsed * 7) % 2
    sprite = DOG_SPRITES[pose]
    left, top = round(x) - 4, round(y) - len(sprite) + 1
    for row, line in enumerate(sprite):
        for column, char in enumerate(line):
            if char == ".":
                continue
            px = left + (column if facing > 0 else len(line) - 1 - column)
            py = top + row - (wag if char == "t" else 0)
            # Only the part of the dog that has come out through the doorway shows.
            if reveal < 1 and not (x0 - reveal * 10 <= px <= x1 + reveal * 10 and py >= y0):
                continue
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                d.point((px, py), fill=colors[char])


def draw_sprite(image: Image.Image, rows: tuple[str, ...], anchor: str, x: float, y: float, facing: int, colors: dict[str, Color]):
    """Draw a right-facing character sprite (mirrored when facing left) with its anchor pixel at (x, y)."""
    anchor_y = next(row for row, line in enumerate(rows) if anchor in line)
    anchor_x = rows[anchor_y].index(anchor)
    d = ImageDraw.Draw(image)
    for row, line in enumerate(rows):
        for column, char in enumerate(line):
            if char == ".":
                continue
            px = round(x) + (column - anchor_x) * (1 if facing >= 0 else -1)
            py = round(y) + row - anchor_y
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                d.point((px, py), fill=colors[char])


OWL_SLOT_SECONDS = 300
OWL_VISIT_CHANCE = 0.65
# Owls come out once civil twilight has ended.
OWL_SUN_ALTITUDE = -6
# Feet on the tip of the tree's lower-left limb, clear of the temperature label.
OWL_PERCH = (103, 19)
# Where the flying owl's body meets the perched owl's chest, so landing and takeoff do not jump.
OWL_PERCH_BODY = (OWL_PERCH[0], OWL_PERCH[1] - 3)
OWL_FLIGHT_SPEED = 17
OWL_LANDING_SECONDS = 0.4
OWL_EYES = (255, 208, 40)
OWL_BLINK_WINDOW = 4.0
OWL_BLINK_SECONDS = 0.2
# Slow, deep wingbeats in bursts, then a short glide on level wings.
OWL_WINGBEAT_SECONDS = 0.75
OWL_WINGBEATS = 3
OWL_GLIDE_SECONDS = 1.1
# Perched sprites face the viewer: u ear tufts, e eyes, k beak, f feathers, c chest, t talons.
# Flight sprites face right (mirrored for left), anchored on the body b, with h the head and no eyeshine.
OWL_SPRITES = {
    "perch": (("u.u", "eke", "fff", "fcf", "fcf", ".t."), "t"),
    "flare": (("f...f", "fekef", ".fff.", ".fcf.", ".fcf.", "..t.."), "t"),
    "up": (("f...........f", "ff.........ff", ".fff.....fff.", "...fff.fhh...", "....ffbfhh...", ".....ccc....."), "b"),
    "lift": (("ff.........ff", ".ffff...ffff.", "....ff.f.hh..", "....ffbfhh...", ".....ccc....."), "b"),
    "glide": (("f...........f", ".fffff.fffff.", "....ffbfhh...", ".....ccc....."), "b"),
    "stroke": ((".........hh..", "...fffbfhhf..", ".fff.ccc.fff.", "ff.........ff"), "b"),
    "down": ((".........hh..", "....ffbfhh...", "...ffcccff...", "..ff.....ff..", ".ff.......ff.", "f...........f"), "b"),
}
# Wing positions from fully raised to fully lowered.
OWL_STROKE = ("up", "lift", "glide", "stroke", "down")


@dataclass(frozen=True)
class OwlVisit:
    arrive: float
    land: float
    leave: float
    gone: float
    entry: tuple[float, float]
    exit: tuple[float, float]


@lru_cache(maxsize=16)
def owl_visit(slot: int, seed: int) -> OwlVisit | None:
    """Glide in from either edge, perch on the tree for a few minutes, then fly off. Never spans two slots."""
    rng = random.Random(seed * 7919 + slot * 104729 + 11)
    if rng.random() > OWL_VISIT_CHANCE:
        return None
    arrive = slot * OWL_SLOT_SECONDS + rng.uniform(5, 40)
    # Low enough that raised wings stay clear of the corner labels.
    entry = (rng.choice((-7, WIDTH + 6)), rng.uniform(11, 14))
    exit = (rng.choice((-7, WIDTH + 6)), rng.uniform(10, 13))
    land = arrive + math.dist(entry, OWL_PERCH_BODY) / OWL_FLIGHT_SPEED
    leave = land + rng.uniform(150, 220)
    return OwlVisit(arrive, land, leave, leave + math.dist(OWL_PERCH_BODY, exit) / OWL_FLIGHT_SPEED, entry, exit)


@lru_cache(maxsize=64)
def owl_blinks(window: int, seed: int) -> tuple[float, ...]:
    """Blink start times within a window: usually one, sometimes a quick double."""
    rng = random.Random(seed * 3571 + window * 7307 + 3)
    first = rng.uniform(0.2, OWL_BLINK_WINDOW - 0.8)
    return (first, first + 0.38) if rng.random() < 0.3 else (first,)


def owl_allowed(environment: "OutsideEnvironment") -> bool:
    rain, snow = precipitation(environment)
    return environment.sun_altitude is not None and environment.sun_altitude < OWL_SUN_ALTITUDE and rain == 0 and snow < 1 and (environment.weather.wind or 0) < 25 and HALLOWEEN not in holiday_features(environment) and HOTDOG not in holiday_features(environment) and not tree_ornaments_shown(environment)


def owl_flight(origin: tuple[float, float], target: tuple[float, float], progress: float, age: float):
    """A swooping flight: bursts of slow, deep wingbeats between short glides on level wings."""
    x = origin[0] + (target[0] - origin[0]) * progress
    y = origin[1] + (target[1] - origin[1]) * progress + 3 * math.sin(math.pi * progress)
    flapping = OWL_WINGBEATS * OWL_WINGBEAT_SECONDS
    beat = age % (flapping + OWL_GLIDE_SECONDS)
    # Wing height from 1 (raised) to -1 (lowered). Each beat starts and ends level, so glides join it smoothly.
    lift = math.sin(2 * math.pi * beat / OWL_WINGBEAT_SECONDS) if beat < flapping else 0.0
    pose = OWL_STROKE[round((1 - lift) * 2)]
    # The downstroke heaves the body up; it sinks again as the wings rise.
    return x, y + 0.6 * lift, 1 if target[0] > origin[0] else -1, pose


def owl_state(environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Return (x, y, facing, pose, eye openness) or None while the owl is away."""
    if not owl_allowed(environment):
        return None
    visit = owl_visit(math.floor(elapsed / OWL_SLOT_SECONDS), seed)
    if visit is None or not visit.arrive <= elapsed < visit.gone:
        return None
    if elapsed < visit.land:
        # Eyeshine only shows once the owl has settled on the branch and faces the viewer.
        if elapsed >= visit.land - OWL_LANDING_SECONDS:
            return *OWL_PERCH, 1, "flare", 0.0
        progress = (elapsed - visit.arrive) / (visit.land - OWL_LANDING_SECONDS - visit.arrive)
        return *owl_flight(visit.entry, OWL_PERCH_BODY, progress, elapsed - visit.arrive), 0.0
    if elapsed >= visit.leave:
        progress = (elapsed - visit.leave) / (visit.gone - visit.leave)
        return *owl_flight(OWL_PERCH_BODY, visit.exit, progress, elapsed - visit.leave), 0.0
    window, moment = divmod(elapsed, OWL_BLINK_WINDOW)
    openness = 1.0
    for blink in owl_blinks(int(window), seed):
        if blink <= moment < blink + OWL_BLINK_SECONDS:
            # The lids snap shut, stay closed briefly, then open again.
            phase = (moment - blink) / OWL_BLINK_SECONDS
            openness = 0.35 if phase < 0.25 or phase >= 0.75 else 0.0
    return *OWL_PERCH, 1, "perch", openness


def draw_owl(image: Image.Image, palette: Palette, owl):
    if owl is None:
        return
    x, y, facing, pose, openness = owl
    feathers = mix(palette.animal, palette.trunk, 0.2)
    colors = {
        "u": mix(feathers, palette.trunk, 0.3),
        "f": feathers,
        "c": mix(palette.animal, palette.trim, 0.35),
        "b": feathers,
        # A pale facial disc picks the head out against the dark back.
        "h": mix(palette.animal, palette.trim, 0.5),
        "k": mix(feathers, palette.trunk, 0.5),
        "t": mix(palette.animal, palette.trim, 0.5),
        # Eyeshine stays bright in the dark; a blink dims it to the surrounding feathers.
        "e": mix(feathers, OWL_EYES, openness),
    }
    rows, anchor = OWL_SPRITES[pose]
    draw_sprite(image, rows, anchor, x, y, facing, colors)


EAGLE_SLOT_SECONDS = 240
EAGLE_VISIT_CHANCE = 0.5
EAGLE_SUN_ALTITUDE = 5
# Seconds the dog must be indoors, door shut, before and after an eagle visit.
EAGLE_DOG_CLEARANCE = 10
# Soaring circles over the pond: center x, center y and vertical radius of the orbit ellipse.
EAGLE_ORBIT = (66, 10, 2.5)
EAGLE_GLIDE_SPEED = 15
EAGLE_DIVE_SECONDS = 1.3
EAGLE_STRIKE_SECONDS = 0.55
EAGLE_CLIMB_SPEED = 15
# Body row while the talons are in the pond.
EAGLE_STRIKE_Y = 25
EAGLE_WATER_Y = 27
EAGLE_SPLASH_SECONDS = 0.8
EAGLE_RIPPLE_SECONDS = 2.2
EAGLE_DARK = (74, 50, 34)
EAGLE_WHITE = (242, 240, 228)
EAGLE_GOLD = (238, 182, 52)
FISH_SILVER = (214, 226, 228)
# Bald eagle facing right: d dark plumage, b body (anchor), w white head and tail, y beak and talons.
EAGLE_SPRITES = {
    "glide": ("d.......d", ".ddddddd.", "...wbwy.."),
    "up": (".d.....d.", "..dd.dd..", "...wbwy.."),
    "down": ("...wbwy..", "..dd.dd..", ".d.....d."),
    "stoop": ("w...", ".dd.", "..bw", "...y"),
    "flare": ("d...d..", ".d.d...", "..wbwy.", "...y..."),
}
SPLASH_DROPS = ((-1.6, 13), (-0.8, 17), (0, 19), (0.8, 16), (1.7, 12), (-2.6, 9), (2.5, 10))


@dataclass(frozen=True)
class EagleVisit:
    start: float
    soar: float
    dive: float
    strike: float
    climb: float
    end: float
    heading: int
    entry: tuple[float, float]
    radius: float
    lap: float
    strike_x: float
    exit: tuple[float, float]

    def orbit_point(self, t: float) -> tuple[float, float, float]:
        """Position on the soaring circle and the sign of horizontal travel at time t."""
        cx, cy, ry = EAGLE_ORBIT
        angle = 2 * math.pi * (t - self.soar) / self.lap
        return cx + self.heading * self.radius * math.sin(angle), cy - ry * math.cos(angle), self.heading * math.cos(angle)


@lru_cache(maxsize=16)
def eagle_visit(slot: int, seed: int) -> EagleVisit | None:
    """Glide in, circle over the pond, stoop to snatch a fish, then labor away with it. Never spans two slots."""
    rng = random.Random(seed * 4421 + slot * 65537 + 17)
    if rng.random() > EAGLE_VISIT_CHANCE:
        return None
    cx, cy, ry = EAGLE_ORBIT
    heading = rng.choice((-1, 1))
    entry = (-8 if heading > 0 else WIDTH + 7, rng.uniform(7, 9))
    start = slot * EAGLE_SLOT_SECONDS + rng.uniform(5, 60)
    soar = start + math.dist(entry, (cx, cy - ry)) / EAGLE_GLIDE_SPEED
    radius = rng.uniform(20, 26)
    lap = 2 * math.pi * radius / EAGLE_GLIDE_SPEED
    # Laps end at the far left or right of the circle, where the eagle turns and stoops toward the pond.
    dive = soar + lap * rng.choice((1.25, 1.75, 2.25))
    strike = dive + EAGLE_DIVE_SECONDS
    climb = strike + EAGLE_STRIKE_SECONDS
    strike_x = rng.uniform(58, 73)
    exit = (rng.choice((-8, WIDTH + 7)), rng.uniform(7, 10))
    return EagleVisit(start, soar, dive, strike, climb, climb + abs(exit[0] - strike_x) / EAGLE_CLIMB_SPEED, heading, entry, radius, lap, strike_x, exit)


def eagle_visits_between(seed: int, first: float, last: float):
    for slot in range(math.floor(first / EAGLE_SLOT_SECONDS), math.floor(last / EAGLE_SLOT_SECONDS) + 1):
        visit = eagle_visit(slot, seed)
        if visit is not None and visit.start < last and visit.end > first:
            yield visit


def eagle_visits_present(environment: "OutsideEnvironment", seed: int, first: float, last: float):
    """Visits that actually happen: the dog is scared of the eagle, so it skips any visit near a dog outing."""
    if not eagle_allowed(environment):
        return
    dog_out = dog_allowed(environment)
    for visit in eagle_visits_between(seed, first, last):
        if not dog_out or next(dog_outings_between(seed, visit.start - EAGLE_DOG_CLEARANCE, visit.end + EAGLE_DOG_CLEARANCE), None) is None:
            yield visit


def eagle_allowed(environment: "OutsideEnvironment") -> bool:
    """Daytime fair weather only: clear to broken clouds, dry, not too windy or foggy, and an unfrozen pond. The ghost owns
    Halloween's sky, and the eagle stays away on July 4."""
    w = environment.weather
    rain, snow = precipitation(environment)
    return (
        environment.sun_altitude is not None
        and environment.sun_altitude > EAGLE_SUN_ALTITUDE
        and HALLOWEEN not in holiday_features(environment)
        and HOTDOG not in holiday_features(environment)
        and w.code in (800, 801, 802, 803)
        and cloud_cover(environment) <= 0.75
        and rain == 0
        and snow == 0
        and (w.wind or 0) < 25
        and (w.visibility is None or w.visibility >= 5000)
        and (w.temperature is None or w.temperature > 32)
    )


def eagle_state(environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Return (visit, x, y, facing, pose, carrying a fish) or None while no eagle is about."""
    visit = next(eagle_visits_present(environment, seed, elapsed, elapsed), None)
    if visit is None:
        return None
    t = elapsed
    cx, cy, ry = EAGLE_ORBIT
    if t < visit.soar:
        progress = (t - visit.start) / (visit.soar - visit.start)
        x = visit.entry[0] + (cx - visit.entry[0]) * progress
        y = visit.entry[1] + (cy - ry - visit.entry[1]) * progress
        return visit, x, y, visit.heading, "glide", False
    if t < visit.dive:
        x, y, travel = visit.orbit_point(t)
        # A lazy wingbeat now and then between long glides.
        beat = (t - visit.soar) % 7
        pose = ("up", "glide", "down", "glide")[int(beat / 0.18) % 4] if beat < 0.72 else "glide"
        return visit, x, y, 1 if travel >= 0 else -1, pose, False
    if t < visit.strike:
        x0, y0, _ = visit.orbit_point(visit.dive)
        progress = (t - visit.dive) / EAGLE_DIVE_SECONDS
        x = x0 + (visit.strike_x - x0) * progress
        y = y0 + (EAGLE_STRIKE_Y - y0) * progress * progress
        return visit, x, y, 1 if visit.strike_x >= x0 else -1, "stoop" if progress > 0.2 else "glide", False
    x0, _, _ = visit.orbit_point(visit.dive)
    toward_pond = 1 if visit.strike_x >= x0 else -1
    if t < visit.climb:
        return visit, visit.strike_x, EAGLE_STRIKE_Y, toward_pond, "flare", False
    progress = (t - visit.climb) / (visit.end - visit.climb)
    x = visit.strike_x + (visit.exit[0] - visit.strike_x) * progress
    y = EAGLE_STRIKE_Y + (visit.exit[1] - EAGLE_STRIKE_Y) * (1 - (1 - progress) ** 2)
    # Hard, quick wingbeats carrying the catch.
    pose = ("up", "glide", "down", "glide")[int((t - visit.climb) / 0.12) % 4]
    return visit, x, y, 1 if visit.exit[0] > visit.strike_x else -1, pose, True


def draw_eagle(image: Image.Image, palette: Palette, eagle, elapsed: float):
    if eagle is None:
        return
    visit, x, y, facing, pose, fish = eagle
    d = ImageDraw.Draw(image)
    water = mix(palette.glint, (240, 246, 246), 0.5)
    since_strike = elapsed - visit.strike
    if 0 <= since_strike < EAGLE_RIPPLE_SECONDS:
        # Rings spread across the pond from where the talons hit the water.
        fade = 1 - since_strike / EAGLE_RIPPLE_SECONDS
        reach = 1.5 + since_strike * 5
        for dx, dy in ((-reach, 0), (reach, 0), (-reach * 0.7, 1), (reach * 0.7, 1)):
            px, py = round(visit.strike_x + dx), EAGLE_WATER_Y + dy
            if 0 <= px < WIDTH and LAND.getpixel((px, py)) == INDEX["water"]:
                d.point((px, py), fill=mix(image.getpixel((px, py)), water, fade * 0.7))
    lit = mix(EAGLE_DARK, palette.animal, 0.15)
    colors = {"d": lit, "b": lit, "w": mix(EAGLE_WHITE, palette.snowcap, 0.3), "y": EAGLE_GOLD}
    draw_sprite(image, EAGLE_SPRITES[pose], "b", x, y, facing, colors)
    if fish:
        # The catch hangs below the talons, its tail flicking.
        bx, by = round(x), round(y)
        flick = int(elapsed * 6) % 2
        for px, py, color in ((bx, by + 1, EAGLE_GOLD), (bx, by + 2, FISH_SILVER), (bx - facing, by + 2 + flick, mix(FISH_SILVER, palette.water, 0.4)), (bx + facing, by + 2, FISH_SILVER)):
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                d.point((px, py), fill=color)
    if 0 <= since_strike < EAGLE_SPLASH_SECONDS:
        fade = 1 - since_strike / EAGLE_SPLASH_SECONDS
        for vx, vy in SPLASH_DROPS:
            px = round(visit.strike_x + vx * since_strike * 4)
            py = round(EAGLE_WATER_Y - (vy * since_strike - 24 * since_strike * since_strike))
            if 0 <= px < WIDTH and 0 <= py <= EAGLE_WATER_Y:
                d.point((px, py), fill=mix(image.getpixel((px, py)), water, 0.9 * fade))


FIREFLY_COUNT = 12
# Fireflies rise from the grass at dusk and thin out a couple of hours after nightfall.
FIREFLY_DUSK_ALTITUDE = -3
FIREFLY_DUSK_RAMP = 3
FIREFLY_SECONDS = 2.25 * 3600
FIREFLY_FADE_SECONDS = 3600
FIREFLY_MIN_TEMPERATURE = 60
FIREFLY_WARM_TEMPERATURE = 75
FIREFLY_MAX_WIND = 10
FIREFLY_FLASH_SECONDS = 0.55
FIREFLY_FLASH_CHANCE = 0.85
FIREFLY_ANSWER_CHANCE = 0.8
FIREFLY_JITTER = 0.8
# Each flash is a short rising "J" stroke.
FIREFLY_RISE = 2
FIREFLY_ROWS = (20, 30)
FIREFLY_COLUMNS = (2, 102)
FIREFLY_LIGHT = (214, 255, 92)
FIREFLY_GLOW = (120, 170, 40)
# Followers answer the flash of the firefly they court.
FIREFLY_PAIRS = {1: 0, 6: 5}
# Pond reflections mirror about the water's top edge.
POND_MIRROR_Y = 51


@dataclass(frozen=True)
class Firefly:
    home: tuple[float, float]
    reach: tuple[float, float]
    rates: tuple[float, float]
    phases: tuple[float, float]
    period: float
    offset: float
    leader: int
    delay: float


def unit_hash(*values: int) -> float:
    """A cheap, stable hash of integers to [0, 1)."""
    h = 2166136261
    for value in values:
        h = ((h ^ (value & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 2246822519) & 0xFFFFFFFF
    h ^= h >> 13
    return h / 2**32


@lru_cache(maxsize=4)
def fireflies(seed: int) -> tuple[Firefly, ...]:
    """Fixed flight paths and flash rhythms, listed in the order they appear as activity rises."""
    rng = random.Random(seed * 6271 + 29)
    flies: list[Firefly] = []
    for index in range(FIREFLY_COUNT):
        leader = FIREFLY_PAIRS.get(index, index)
        if leader != index:
            hx = flies[leader].home[0]
            home = (min(FIREFLY_COLUMNS[1] - 4, max(FIREFLY_COLUMNS[0] + 4, hx + rng.choice((-1, 1)) * rng.uniform(6, 12))), rng.uniform(23, 28))
        else:
            home = (rng.uniform(FIREFLY_COLUMNS[0] + 4, FIREFLY_COLUMNS[1] - 4), rng.uniform(22, 28))
        flies.append(Firefly(
            home=home,
            reach=(rng.uniform(4, 9), rng.uniform(1, 2.2)),
            rates=(rng.uniform(0.05, 0.11), rng.uniform(0.12, 0.25)),
            phases=(rng.uniform(0, math.tau), rng.uniform(0, math.tau)),
            period=rng.uniform(2.5, 5),
            offset=rng.uniform(0, 5),
            leader=leader,
            delay=rng.uniform(0.5, 0.9) if leader != index else 0.0,
        ))
    return tuple(flies)


def firefly_activity(environment: "OutsideEnvironment") -> float:
    """0..1: warm, calm, dry summer evenings only, from dusk until a couple of hours after nightfall."""
    w = environment.weather
    altitude = environment.sun_altitude
    if environment.season != "summer" or altitude is None or w.code is None or w.temperature is None or HALLOWEEN in holiday_features(environment):
        return 0.0
    rain, snow = precipitation(environment)
    if rain > 0 or snow > 0 or (w.wind or 0) >= FIREFLY_MAX_WIND or w.temperature < FIREFLY_MIN_TEMPERATURE:
        return 0.0
    since = environment.since_nightfall
    if since is not None and since < 12 * 3600:
        evening = (FIREFLY_SECONDS - since) / FIREFLY_FADE_SECONDS
    elif altitude > NIGHT_ALTITUDE and environment.sun_azimuth >= 180:
        # Evening twilight before tonight's nightfall; the setting sun is always in the west.
        evening = 1.0
    else:
        return 0.0
    dusk = (FIREFLY_DUSK_ALTITUDE - altitude) / FIREFLY_DUSK_RAMP
    warmth = (w.temperature - FIREFLY_MIN_TEMPERATURE) / (FIREFLY_WARM_TEMPERATURE - FIREFLY_MIN_TEMPERATURE)
    return max(0.0, min(1.0, evening, dusk)) * (0.35 + 0.65 * max(0.0, min(1.0, warmth)))


def firefly_flash(index: int, fly: Firefly, flies: tuple[Firefly, ...], elapsed: float, seed: int) -> float | None:
    """Seconds into the current flash, or None while the firefly is dark."""
    source = flies[fly.leader]
    t = elapsed - fly.delay
    cycle = math.floor((t - source.offset) / source.period)
    if unit_hash(seed, fly.leader, cycle, 1) > FIREFLY_FLASH_CHANCE:
        return None
    if index != fly.leader and unit_hash(seed, index, cycle, 2) > FIREFLY_ANSWER_CHANCE:
        return None
    age = t - (source.offset + cycle * source.period + unit_hash(seed, fly.leader, cycle, 3) * FIREFLY_JITTER)
    return age if 0 <= age < FIREFLY_FLASH_SECONDS else None


def firefly_glows(environment: "OutsideEnvironment", elapsed: float, seed: int) -> list[tuple[float, float, float]]:
    """Return (x, y, brightness) for each firefly currently lit."""
    present = firefly_activity(environment) * FIREFLY_COUNT
    flies = fireflies(seed)
    lit = []
    for index, fly in enumerate(flies[:math.ceil(present)]):
        age = firefly_flash(index, fly, flies, elapsed, seed)
        if age is None:
            continue
        # A quick rise, a short hold, then a fading afterglow.
        envelope = age / 0.08 if age < 0.08 else 1.0 if age < 0.2 else ((FIREFLY_FLASH_SECONDS - age) / (FIREFLY_FLASH_SECONDS - 0.2)) ** 2
        (hx, hy), (ax, ay), (fx, fy), (px, py) = fly.home, fly.reach, fly.rates, fly.phases
        x = hx + ax * math.sin(elapsed * fx + px) + 0.4 * ax * math.sin(elapsed * fx * 2.3 + px * 1.7)
        y = hy + ay * math.sin(elapsed * fy + py) - FIREFLY_RISE * (age / FIREFLY_FLASH_SECONDS) ** 1.5
        x = min(FIREFLY_COLUMNS[1], max(FIREFLY_COLUMNS[0], x))
        y = min(FIREFLY_ROWS[1], max(FIREFLY_ROWS[0], y))
        lit.append((x, y, envelope * min(1.0, present - index)))
    return lit


def draw_fireflies(image: Image.Image, glows: list[tuple[float, float, float]]):
    d = ImageDraw.Draw(image)
    for fx, fy, strength in glows:
        x, y = round(fx), round(fy)
        if strength > 0.5:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                px, py = x + dx, y + dy
                if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                    d.point((px, py), fill=mix(image.getpixel((px, py)), FIREFLY_GLOW, (strength - 0.5) * 0.45))
        reflection = POND_MIRROR_Y - y
        if 0 <= reflection < HEIGHT and LAND.getpixel((x, reflection)) == INDEX["water"]:
            d.point((x, reflection), fill=mix(image.getpixel((x, reflection)), FIREFLY_LIGHT, strength * 0.35))
        d.point((x, y), fill=mix(image.getpixel((x, y)), FIREFLY_LIGHT, strength))


LEAF_SLOT_SECONDS = 45
LEAF_GUST_CHANCE = 0.72
LEAF_GUST_SIZE = 4
LEAF_BREEZE_MPH = 8
LEAF_GUST_MPH = 16
# A leaf fades in on the front of the canopy and trembles there before it lets go.
LEAF_HANG_SECONDS = 0.9
LEAF_TREMBLE_RATE = 3.2
LEAF_REST_SECONDS = 3
LEAF_FADE_SECONDS = 4
# Pendulum fall: the leaf dips through the middle of each swing and rises this many pixels toward its ends.
LEAF_SWING_RISE = 2.0
# Swings build up after the leaf lets go and die away over the end of its fall, so it settles onto the grass.
LEAF_SWING_EASE_IN = 1.2
LEAF_SETTLE_FROM = 0.72
LEAF_LOOP_CHANCE = 0.55
# On landing the tip bounces up twice before the leaf lies flat: (start, end) seconds after touchdown.
LEAF_PLOP = ((0, 0.14), (0.3, 0.4))
# Leaf centers on the rim of the canopy, so a trembling leaf shows before it falls.
TREE_LEAF_SPOTS = ((103, 17), (107, 20), (104, 12), (110, 10), (113, 20), (116, 19), (119, 15))
# 3x3 sprites around the leaf's center with the tip up and up-right; quarter turns give the other six headings.
# F is the lit half and D the shaded half. Slim and stemless: a round body with a stem reads as a drumstick, and
# a symmetric diamond for the straight headings reads as a plus-sign sparkle.
LEAF_SPRITE_UP = (".F.", ".FD", ".D.")
LEAF_SPRITE_UP_RIGHT = ("..F", ".FD", "FD.")
# Daylight colors before the frame grade, which deepens them a lot: (lit, alternate lit) for each hue; a leaf
# picks a shade between the two. Yellow and orange come up most, as on the tree, with some green and a little red.
AUTUMN_LEAF_HUES = (
    ((216, 192, 100), (222, 176, 92)),
    ((214, 146, 84), (220, 162, 86)),
    ((146, 168, 88), (178, 180, 92)),
    ((184, 104, 80), (200, 122, 82)),
)
AUTUMN_LEAF_WEIGHTS = (3, 3, 2, 1.5)
AUTUMN_LEAF_SHADE = (92, 52, 40)
SPRING_PETAL_COLORS = ((239, 186, 182), (215, 146, 166))
# Petals stay small: one or two pixels that tumble as they fall.
PETAL_SHAPES = (((0, 0), (1, 0)), ((0, 0),), ((0, 0), (1, 1)), ((0, 0),), ((0, 0), (0, 1)), ((0, 0),), ((0, 0), (-1, 1)), ((0, 0),))


def leaf_sprites() -> tuple[tuple[tuple[int, int, str], ...], ...]:
    """Pixels (dx, dy, part) for the eight headings, clockwise from tip-up."""
    poses = []
    for heading in range(8):
        grid = LEAF_SPRITE_UP if heading % 2 == 0 else LEAF_SPRITE_UP_RIGHT
        size = len(grid)
        for _ in range(heading // 2):
            grid = tuple("".join(grid[size - 1 - x][y] for x in range(size)) for y in range(size))
        poses.append(tuple((x - size // 2, y - size // 2, part) for y, row in enumerate(grid) for x, part in enumerate(row) if part != "."))
    return tuple(poses)


LEAF_SPRITES = leaf_sprites()


def smoothstep(edge0: float, edge1: float, value: float) -> float:
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def tree_sway(elapsed: float, wind: float) -> int:
    """How far the foliage leans in the wind, in whole pixels."""
    return round(math.sin(elapsed * 0.6) * min(1, wind / 12))


@dataclass(frozen=True)
class LeafDrift:
    # When the leaf lets go; it appears on the canopy LEAF_HANG_SECONDS earlier.
    release: float
    origin: tuple[int, int]
    flight_seconds: float
    ground_y: int
    phase: float
    hue: int
    tint: float
    swing: float
    swing_period: float
    # +1 when the first swing heads right.
    first_swing: int
    # Flight time at which a loop-the-loop starts, and its radius; 0 for none.
    loop_at: float
    loop_radius: float


def leaf_loop(rng: random.Random, origin: tuple[int, int], flight: float, ground_y: int, period: float, first_swing: int) -> tuple[float, float]:
    """A loop-the-loop starts mid-swing while the leaf glides left with the breeze, and rises over the top."""
    radius = rng.uniform(2.6, 3.8)
    first = 0.5 if first_swing > 0 else 1.0
    starts = []
    for cycle in range(12):
        start = (first + cycle) * period
        y = origin[1] + (ground_y - origin[1]) * start / flight
        if LEAF_SWING_EASE_IN <= start and start + 0.5 <= flight * LEAF_SETTLE_FROM and y - 2 * radius - 2 >= TREE_FOLIAGE_TOP:
            starts.append(start)
    if not starts or rng.random() > LEAF_LOOP_CHANCE:
        return 0.0, 0.0
    return rng.choice(starts), radius


@lru_cache(maxsize=16)
def leaf_gust(slot: int, seed: int, spring: bool) -> tuple[LeafDrift, ...]:
    """Fixed release order: wind adds leaves to a gust without reshuffling its paths."""
    rng = random.Random(seed * 7919 + slot * 104729 + 43)
    if rng.random() > LEAF_GUST_CHANCE:
        return ()
    start = slot * LEAF_SLOT_SECONDS + rng.uniform(4, 10)
    leaves = []
    for index in range(LEAF_GUST_SIZE):
        if spring:
            dx, dy = rng.choice(TREE_BLOSSOMS)
            origin = (TREE_X + dx, TREE_CANOPY_Y + dy)
        else:
            origin = rng.choice(TREE_LEAF_SPOTS)
        flight = rng.uniform(10, 13)
        ground_y = rng.randrange(29, 31)
        period = rng.uniform(2.6, 3.4)
        first_swing = rng.choice((-1, 1))
        # Neighbors in a gust never share a hue.
        hues = [hue for hue in range(len(AUTUMN_LEAF_HUES)) if not leaves or hue != leaves[-1].hue]
        hue = rng.choices(hues, [AUTUMN_LEAF_WEIGHTS[hue] for hue in hues])[0]
        loop_at, loop_radius = leaf_loop(rng, origin, flight, ground_y, period, first_swing)
        leaves.append(LeafDrift(
            release=start + index * rng.uniform(0.9, 1.4),
            origin=origin,
            flight_seconds=flight,
            ground_y=ground_y,
            phase=rng.uniform(0, math.tau),
            hue=hue,
            tint=rng.random(),
            swing=rng.uniform(3.5, 5.5),
            swing_period=period,
            first_swing=first_swing,
            loop_at=loop_at,
            loop_radius=loop_radius,
        ))
    return tuple(leaves)


def leaf_loop_seconds(leaf: LeafDrift, travel: float) -> float:
    """The loop keeps the speed the leaf enters it with, swing and breeze together, so it sweeps in and out without a jolt."""
    if not leaf.loop_radius:
        return 0.0
    speed = leaf.swing * math.tau / leaf.swing_period + travel / leaf.flight_seconds
    return math.tau * leaf.loop_radius / speed


def leaf_position(leaf: LeafDrift, travel: float, start_x: float, age: float) -> tuple[float, float]:
    """Where a leaf is `age` seconds after it lets go: the breeze carries it left while it swings like a pendulum."""
    loop_seconds = leaf_loop_seconds(leaf, travel)
    age = max(0.0, min(age, leaf.flight_seconds + loop_seconds))
    flight, loop_x, loop_y = age, 0.0, 0.0
    into = age - leaf.loop_at
    if loop_seconds and into > 0:
        # The fall pauses for the loop and picks up where it left off, so the loop stays round in any wind.
        flight = age - min(into, loop_seconds)
        if into < loop_seconds:
            turn = math.tau * into / loop_seconds
            loop_x, loop_y = -leaf.loop_radius * math.sin(turn), -leaf.loop_radius * (1 - math.cos(turn))
    progress = flight / leaf.flight_seconds
    omega = math.tau / leaf.swing_period
    envelope = smoothstep(0, LEAF_SWING_EASE_IN, flight) * (1 - smoothstep(LEAF_SETTLE_FROM, 1, progress))
    x = start_x - travel * progress + leaf.first_swing * leaf.swing * envelope * math.sin(omega * flight) + loop_x
    y = leaf.origin[1] + (leaf.ground_y - leaf.origin[1]) * progress - LEAF_SWING_RISE * envelope * (1 - math.cos(2 * omega * flight)) / 2 + loop_y
    return x, y


def leaf_heading(dx: float, dy: float) -> int:
    """The nearest of the eight sprite headings, clockwise from up, for a direction of travel."""
    return round(math.atan2(dx, -dy) / (math.pi / 4)) % 8


def leaves_allowed(environment: "OutsideEnvironment") -> bool:
    """Dry autumn leaves or spring blossom petals fall in a known wind; the tree holds its leaves on Halloween."""
    weather = environment.weather
    if environment.season not in ("autumn", "spring") or weather.code is None or weather.wind is None or HALLOWEEN in holiday_features(environment):
        return False
    rain, snow = precipitation(environment)
    return rain == 0 and snow == 0


def leaf_particles(environment: "OutsideEnvironment", elapsed: float, seed: int) -> list[tuple[int, int, int, LeafDrift, float]]:
    """(x, y, heading, leaf, opacity) for each falling leaf or petal."""
    if not leaves_allowed(environment):
        return []
    wind = min(30, environment.weather.wind)
    count = 2 + (wind >= LEAF_BREEZE_MPH) + (wind >= LEAF_GUST_MPH)
    particles = []
    for leaf in leaf_gust(math.floor(elapsed / LEAF_SLOT_SECONDS), seed, environment.season == "spring")[:count]:
        age = elapsed - leaf.release
        if age < -LEAF_HANG_SECONDS:
            continue
        opacity = min(1.0, (age + LEAF_HANG_SECONDS) / 0.3)
        if age < 0:
            # Hanging tip down, it trembles in the swaying foliage.
            tremble = 1 if math.sin(age * math.tau * LEAF_TREMBLE_RATE + leaf.phase) > 0 else -1
            particles.append((leaf.origin[0] + tree_sway(elapsed, wind), leaf.origin[1], 4 + tremble, leaf, opacity))
            continue
        # The breeze carries leaves left into the meadow; only strong gusts reach the yard.
        travel = min(leaf.origin[0] - 3, 3 + wind * 4)
        start_x = leaf.origin[0] + tree_sway(leaf.release, wind)
        airborne = leaf.flight_seconds + leaf_loop_seconds(leaf, travel)
        end = airborne + LEAF_REST_SECONDS + LEAF_FADE_SECONDS
        if age >= end:
            continue
        opacity = min(opacity, (end - age) / LEAF_FADE_SECONDS)
        x, y = leaf_position(leaf, travel, start_x, age)
        if age < airborne:
            ahead, behind = leaf_position(leaf, travel, start_x, age + 0.05), leaf_position(leaf, travel, start_x, age - 0.05)
            heading = leaf_heading(ahead[0] - behind[0], ahead[1] - behind[1])
        else:
            # It lands flat, tip toward where it was headed, and the tip bounces up twice.
            last = leaf_position(leaf, travel, start_x, airborne - 0.1)
            flat = 6 if last[0] >= x else 2
            since = age - airborne
            heading = (flat + (1 if flat == 6 else -1)) % 8 if any(a <= since < b for a, b in LEAF_PLOP) else flat
        particles.append((round(x), round(y), heading, leaf, opacity))
    return particles


def draw_leaves(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    particles = leaf_particles(environment, elapsed, seed)
    if not particles:
        return
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))

    def lit(color: Color) -> Color:
        return (round(color[0] * illumination), round(color[1] * illumination), round(color[2] * illumination))

    d = ImageDraw.Draw(image)
    for x, y, heading, leaf, opacity in particles:
        if environment.season == "spring":
            color = lit(mix(*SPRING_PETAL_COLORS, leaf.tint))
            age = elapsed - leaf.release
            pixels = ((dx, dy, color) for dx, dy in PETAL_SHAPES[int(age * 2.5 + leaf.phase) % len(PETAL_SHAPES)])
        else:
            face = mix(*AUTUMN_LEAF_HUES[leaf.hue], leaf.tint)
            colors = {"F": lit(face), "D": lit(mix(face, AUTUMN_LEAF_SHADE, 0.3))}
            pixels = ((dx, dy, colors[part]) for dx, dy, part in LEAF_SPRITES[heading])
        for dx, dy, color in pixels:
            px, py = x + dx, y + dy
            if 0 <= px < WIDTH and TREE_FOLIAGE_TOP <= py < HEIGHT:
                d.point((px, py), fill=mix(image.getpixel((px, py)), color, opacity))


def lamp_level(environment: "OutsideEnvironment") -> float:
    """The yard lamp comes on once the sky is pure night, warming up over 40 s, and switches off three hours later."""
    since = environment.since_nightfall
    if since is None or not 0 <= since < LAMP_SECONDS:
        return 0.0
    return min(1.0, since / LAMP_WARMUP_SECONDS, (LAMP_SECONDS - since) / 20)


def lamp_light_mask() -> np.ndarray:
    """A faint downward cone from the lamp's lens, a pool of light on the ground, and a small halo."""
    lens_x, lens_y = LAMP_LENS
    rows, columns = np.arange(HEIGHT)[:, None], np.arange(WIDTH)[None, :]
    depth = (rows - lens_y) / (LAMP_GROUND_Y - lens_y)
    across = np.clip(1 - np.abs(columns - lens_x) / (0.6 + depth * 4.4), 0, 1)
    cone = np.where((depth > 0) & (depth <= 1.15), across**0.7 * (0.3 - 0.16 * np.clip(depth, 0, 1)), 0)
    reach = ((columns - lens_x) / 6.5) ** 2 + ((rows - (LAMP_GROUND_Y + 0.5)) / 1.8) ** 2
    pool = np.clip(1 - reach, 0, 1) * 0.38
    halo = np.clip(1 - np.hypot(columns - lens_x, (rows - lens_y) * 1.3) / 2.6, 0, 1) * 0.55
    return np.maximum(np.maximum(cone, pool), halo).astype(np.float32)


LAMP_MASK = lamp_light_mask()


def draw_lamp_light(image: Image.Image, level: float) -> Image.Image:
    pixels = np.asarray(image, dtype=np.float32)
    pixels = pixels + (np.array(LAMP_LIGHT, dtype=np.float32) - pixels) * (LAMP_MASK * level)[..., None]
    lit = Image.fromarray(np.round(pixels).astype(np.uint8), "RGB")
    lit.putpixel(LAMP_LENS, mix(image.getpixel(LAMP_LENS), LAMP_GLOW, level))
    return lit


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


def holiday_span_matches(day: date, span: tuple[int, ...]) -> bool:
    month, first, last, *weekday = span
    return day.month == month and first <= day.day <= last and (not weekday or day.weekday() == weekday[0])


def holiday_span_start(span: tuple[int, ...], year: int) -> date:
    """The first day of `year` that a HOLIDAYS span covers."""
    month, first, last, *_ = span
    return next(day for day in (date(year, month, number) for number in range(first, last + 1)) if holiday_span_matches(day, span))


def holiday_features(environment: "OutsideEnvironment") -> frozenset[str]:
    """Holiday easter eggs for the displayed local date, plus an overnight holiday's until the next sunrise."""
    day = environment.local_date
    if day is None:
        return frozenset()
    days = [day]
    yesterday = day - timedelta(days=1)
    if environment.before_sunrise and (yesterday.month, yesterday.day) in HOLIDAY_NIGHTS:
        days.append(yesterday)
    return frozenset(feature for feature, (_, spans) in HOLIDAYS.items() if any(holiday_span_matches(moment, span) for moment in days for span in spans))


def holiday_darkness(environment: "OutsideEnvironment") -> float:
    """0 in daylight to 1 once dusk deepens; emitted holiday light glows into its surroundings only after dark."""
    altitude = environment.sun_altitude
    return max(0, min(1, -(altitude + 2) / 8)) if altitude is not None else 0


# Christmas lights stay up from December 1 through the day after Christmas.
CHRISTMAS_LAST_DAY = 26
# US Thanksgiving, the fourth Thursday of November, always falls on November 22-28 (weekday 3 is Thursday).
THANKSGIVING_SPAN = (11, 22, 28, 3)
# Holiday easter eggs, active all day on the displayed local date: feature -> (label, (month, first day, last day[, weekday])
# spans). A span with a weekday covers only that weekday within its days. The Outside lab builds its holiday shortcuts
# from this table.
HOLIDAYS = {
    "christmas_lights": ("Christmas lights", ((12, 1, CHRISTMAS_LAST_DAY),)),
    "santa": ("Santa", ((12, 24, 24),)),
    "fireworks": ("Fireworks", ((12, 31, 31), (1, 1, 1), (7, 4, 4))),
    "flag": ("Flag", ((7, 4, 4),)),
    "cannon": ("Cannon", ((7, 4, 4),)),
    "fountains": ("Fountains", ((7, 4, 4),)),
    "hotdog": ("Hotdog mascot", ((7, 4, 4),)),
    "halloween": ("Halloween", ((10, 31, 31),)),
    "thanksgiving": ("Thanksgiving", (THANKSGIVING_SPAN,)),
}
# (month, day) of holidays whose whole scene stays up through the following night, until sunrise the next morning.
HOLIDAY_NIGHTS = frozenset({(7, 4)})
CHRISTMAS_COLORS = ((255, 28, 28), (24, 255, 64), (40, 96, 255), (255, 172, 16), (255, 52, 196))
TOPPER_GOLD = (255, 206, 60)
TOPPER_CORE = (255, 250, 214)


def christmas_bulbs() -> tuple[tuple[int, int], ...]:
    """Bulbs strung along the hut's gable (passing behind the chimney) and wound around each conifer."""
    bulbs = [point for point in trace(list(HUT_ROOF))[::2] if not CHIMNEY_MASK.getpixel(point)]
    foliage = (INDEX["leaf"], INDEX["leaf_dark"])
    for cx, base, height in CONIFERS:
        top = base - height
        for y in range(top + 2, base):
            row = [x for x in range(cx - 3, cx + 4) if LAND.getpixel((x, y)) in foliage]
            # Garlands spiral down the tree: one bulb per row, swinging from side to side.
            if row and (y - top) % 2 == 0:
                bulbs.append((row[0] if (y - top) % 4 == 0 else row[-1], y))
    return tuple(dict.fromkeys(bulbs))


CHRISTMAS_BULBS = christmas_bulbs()
CHRISTMAS_BULB_ROWS = np.array([y for _, y in CHRISTMAS_BULBS])
CHRISTMAS_BULB_COLUMNS = np.array([x for x, _ in CHRISTMAS_BULBS])
CHRISTMAS_BULB_INDEX = np.arange(len(CHRISTMAS_BULBS))
CHRISTMAS_BULB_LIGHT = SRGB_TO_LINEAR_ARRAY[np.array([CHRISTMAS_COLORS[index % len(CHRISTMAS_COLORS)] for index in range(len(CHRISTMAS_BULBS))])]
# Each bulb's neighbors catch a little of its color after dark: (row, column, bulb index).
CHRISTMAS_HALO = np.array([(y + dy, x + dx, index) for index, (x, y) in enumerate(CHRISTMAS_BULBS) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)) if (x + dx, y + dy) not in CHRISTMAS_BULBS and 0 <= x + dx < WIDTH and 0 <= y + dy < HEIGHT])
# A star sits just above each conifer's apex.
TREE_TOPPERS = tuple((cx, base - height - 2) for cx, base, height in CONIFERS)
# A sparse, lopsided handful of glass balls hangs from the bare maple's twigs: (left x, top row) of each 2x2 ball,
# just under a twig. The wood never sways, so neither do they.
TREE_ORNAMENTS = ((100, 13), (122, 12), (116, 15), (100, 21), (118, 20))
TREE_ORNAMENT_COLORS = ((236, 22, 34), (52, 98, 255), (255, 170, 20), (30, 206, 82), (238, 50, 170))
# After dark the unlit glass fades toward this dim, cool gray instead of glowing like the Christmas lights.
TREE_ORNAMENT_NIGHT = (34, 38, 56)
# Shading across each ball, lit from the upper left: (dx, dy, brightness).
TREE_ORNAMENT_SHADE = ((1, 0, 0.92), (0, 1, 0.78), (1, 1, 0.5))
# Each ball catches a brief glint once per cycle, at its own moment.
TREE_ORNAMENT_GLINT_SECONDS, TREE_ORNAMENT_GLINT_LENGTH = 7.0, 0.5


def linear_to_srgb_array(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0, 1)
    return np.round(np.where(linear <= 0.0031308, linear * 12.92, 1.055 * np.power(linear, 1 / 2.4) - 0.055) * 255).astype(np.uint8)


def draw_christmas_lights(image: Image.Image, environment: "OutsideEnvironment", elapsed: float) -> Image.Image:
    night = holiday_darkness(environment)
    twinkle = 0.5 + 0.5 * np.sin(elapsed * (1.1 + (CHRISTMAS_BULB_INDEX % 7) * 0.23) + CHRISTMAS_BULB_INDEX * 2.4)
    # Blend in linear light, converting only the pixels the lights touch.
    pixels = np.array(image)
    if night > 0:
        rows, columns, bulbs = CHRISTMAS_HALO.T
        halo = SRGB_TO_LINEAR_ARRAY[pixels[rows, columns]]
        halo += (CHRISTMAS_BULB_LIGHT[bulbs] - halo) * (0.28 * night * (0.72 + 0.28 * twinkle[bulbs]))[:, None]
        pixels[rows, columns] = linear_to_srgb_array(halo)
    bulb = SRGB_TO_LINEAR_ARRAY[pixels[CHRISTMAS_BULB_ROWS, CHRISTMAS_BULB_COLUMNS]]
    bulb += (CHRISTMAS_BULB_LIGHT - bulb) * 0.9
    pixels[CHRISTMAS_BULB_ROWS, CHRISTMAS_BULB_COLUMNS] = linear_to_srgb_array(bulb + (1 - bulb) * (0.12 * twinkle)[:, None])
    image = Image.fromarray(pixels, "RGB")
    d = ImageDraw.Draw(image)
    for index, (x, y) in enumerate(TREE_TOPPERS):
        shine = 0.5 + 0.5 * math.sin(elapsed * 2.1 + index * 1.9)
        if night > 0:
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (-1, -1), (1, -1), (-1, 1), (1, 1)):
                point = (x + dx, y + dy)
                d.point(point, fill=mix(image.getpixel(point), TOPPER_GOLD, night * (0.16 + 0.1 * shine)))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            d.point((x + dx, y + dy), fill=mix(image.getpixel((x + dx, y + dy)), TOPPER_GOLD, 0.8 + 0.2 * shine))
        d.point((x, y), fill=TOPPER_CORE)
        # Now and then the star glints with a brief diagonal sparkle.
        glint = (elapsed + index * 1.7) % 3.2
        if glint < 0.35:
            strength = math.sin(math.pi * glint / 0.35)
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                point = (x + dx, y + dy)
                d.point(point, fill=mix(image.getpixel(point), TOPPER_CORE, 0.7 * strength))
    return image


def tree_ornaments_shown(environment: "OutsideEnvironment") -> bool:
    """Ornaments hang only on the bare winter maple while the Christmas lights are up; the owl stays away then."""
    return environment.season == "winter" and "christmas_lights" in holiday_features(environment)


def draw_tree_ornaments(image: Image.Image, night: float, elapsed: float):
    """Glass balls on the bare maple; each highlight shimmers slowly and now and then glints white."""
    d = ImageDraw.Draw(image)
    for index, ((x, y), color) in enumerate(zip(TREE_ORNAMENTS, TREE_ORNAMENT_COLORS)):
        body = mix(color, TREE_ORNAMENT_NIGHT, 0.62 * night)
        shimmer = 0.5 + 0.5 * math.sin(elapsed * (0.9 + index * 0.17) + index * 2.3)
        moment = (elapsed + index * TREE_ORNAMENT_GLINT_SECONDS * 0.37) % TREE_ORNAMENT_GLINT_SECONDS
        glint = math.sin(math.pi * moment / TREE_ORNAMENT_GLINT_LENGTH) if moment < TREE_ORNAMENT_GLINT_LENGTH else 0
        for dx, dy, shade in TREE_ORNAMENT_SHADE:
            d.point((x + dx, y + dy), fill=mix(mix(body, (0, 0, 0), 1 - shade), body, 0.3 * glint))
        # The highlight and glint soften after dark too, so the glass only catches a little of the lights.
        d.point((x, y), fill=mix(body, (255, 255, 255), (0.22 + 0.18 * shimmer + 0.5 * glint) * (1 - 0.45 * night)))


SANTA_SLOT_SECONDS = 30
SANTA_REINDEER = 4
SANTA_REINDEER_SPACING = 9
SANTA_SLEIGH_GAP = 3
SANTA_SPRITE_WIDTH = {"sleigh": 10, "reindeer": 7}
SANTA_LENGTH = SANTA_SPRITE_WIDTH["sleigh"] + SANTA_SLEIGH_GAP + SANTA_REINDEER * SANTA_REINDEER_SPACING
SANTA_TRAIL_SECONDS = 0.9
SANTA_DUST_SPACING = 2.5
# Facing right. Santa: w pompom, r suit, f face, W beard, k toy sack, s sleigh, g gold trim, y runners.
SANTA_SLEIGH = ("...w......", "..rr......", "kkrf.....y", "kkrW.....y", "gsrrssssgy", "sssssssss.", "yyyyyyyyy.")
# Reindeer in two gallop frames: a antlers, b coat, t tail, l legs, n nose (Rudolph's glows red).
SANTA_REINDEER_SPRITES = (("....a.a", ".....bn", "tbbbbb.", ".bbbb..", "l....l."), ("....a.a", ".....bn", "tbbbbb.", ".bbbb..", "..l.l.."))
SANTA_COLORS = {"w": (255, 255, 255), "r": (240, 44, 44), "f": (250, 196, 160), "W": (245, 245, 245), "k": (128, 86, 52), "s": (150, 14, 26), "g": (255, 196, 54), "y": (255, 204, 70), "a": (205, 170, 120), "b": (150, 96, 54), "t": (235, 225, 205), "l": (105, 64, 36)}
RUDOLPH_NOSE = (255, 36, 28)
SANTA_REINS = (200, 160, 60)
SANTA_DUST = ((255, 236, 150), (255, 255, 255), (255, 200, 90))


@dataclass(frozen=True)
class SantaPass:
    start: float
    duration: float
    speed: float
    direction: int
    altitude: float
    climb: float


@lru_cache(maxsize=8)
def santa_pass(slot: int, seed: int) -> SantaPass:
    """Santa's sleigh streaks across the sky once per slot on Christmas Eve."""
    rng = random.Random(seed * 3571 + slot * 65537 + 23)
    speed = rng.uniform(40, 52)
    duration = (WIDTH + SANTA_LENGTH + SANTA_TRAIL_SECONDS * speed) / speed
    start = slot * SANTA_SLOT_SECONDS + rng.uniform(0, SANTA_SLOT_SECONDS - duration)
    return SantaPass(start, duration, speed, rng.choice((-1, 1)), rng.uniform(9.5, 11), rng.uniform(-1.5, 1.5))


def santa_path(santa: SantaPass, distance: float) -> tuple[float, float]:
    """Position along the flight path `distance` px after the team's front entered the sky."""
    x = distance - 1 if santa.direction > 0 else WIDTH - distance
    y = santa.altitude + santa.climb * distance / (WIDTH + SANTA_LENGTH) + math.sin(distance * 0.07)
    return x, y


def draw_santa_sprite(image: Image.Image, rows: tuple[str, ...], center_x: float, top: float, direction: int, colors: dict[str, Color]):
    width = len(rows[0])
    left, top = round(center_x - (width - 1) / 2), round(top)
    points: dict[str, list[tuple[int, int]]] = {}
    for row, line in enumerate(rows):
        for column, char in enumerate(line):
            if char == ".":
                continue
            x, y = left + (column if direction > 0 else width - 1 - column), top + row
            if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                points.setdefault(char, []).append((x, y))
    d = ImageDraw.Draw(image)
    for char, pixels in points.items():
        d.point(pixels, fill=colors[char])


def santa_state(elapsed: float, seed: int) -> SantaPass | None:
    """The pass under way at `elapsed`; the caller shows it only on Christmas Eve."""
    santa = santa_pass(math.floor(elapsed / SANTA_SLOT_SECONDS), seed)
    return santa if 0 <= elapsed - santa.start < santa.duration else None


def draw_santa(image: Image.Image, environment: "OutsideEnvironment", elapsed: float, seed: int):
    santa = santa_state(elapsed, seed)
    if santa is None:
        return
    age = elapsed - santa.start
    night = holiday_darkness(environment)
    traveled = age * santa.speed
    sleigh_width = SANTA_SPRITE_WIDTH["sleigh"]
    sleigh_back = traveled - SANTA_LENGTH
    d = ImageDraw.Draw(image)
    # Magic dust trails off the back of the sleigh, drifting down and twinkling out.
    newest = math.floor(sleigh_back / SANTA_DUST_SPACING)
    for index in range(newest, newest - math.ceil(SANTA_TRAIL_SECONDS * santa.speed / SANTA_DUST_SPACING), -1):
        emitted = index * SANTA_DUST_SPACING
        if emitted < -sleigh_width:
            break
        since = (sleigh_back - emitted) / santa.speed
        x, y = santa_path(santa, emitted)
        x += (unit_hash(index, seed, 1) - 0.5) * 2
        y += 4 + (unit_hash(index, seed, 2) - 0.5) * 4 + since * 4
        sparkle = unit_hash(index, math.floor(elapsed * 14), 3)
        strength = (1 - since / SANTA_TRAIL_SECONDS) * (0.45 + 0.55 * sparkle)
        px, py = round(x), round(y)
        if strength > 0 and 0 <= px < WIDTH and 0 <= py < HEIGHT:
            d.point((px, py), fill=mix(image.getpixel((px, py)), SANTA_DUST[index % len(SANTA_DUST)], strength))
    sleigh_x, sleigh_y = santa_path(santa, sleigh_back + sleigh_width / 2)
    front = traveled - SANTA_SPRITE_WIDTH["reindeer"] / 2
    lead_x, lead_y = santa_path(santa, front)
    # Reins run from the sleigh's dash to the lead reindeer; the team is drawn over them.
    reins = trace([(round(sleigh_x + santa.direction * sleigh_width / 2), round(sleigh_y) - 1), (round(lead_x), round(lead_y))])
    d.point(reins, fill=SANTA_REINS)
    draw_santa_sprite(image, SANTA_SLEIGH, sleigh_x, sleigh_y - 4, santa.direction, SANTA_COLORS)
    for index in range(SANTA_REINDEER):
        x, y = santa_path(santa, front - index * SANTA_REINDEER_SPACING)
        frame = (math.floor(elapsed * 8) + index) % 2
        lead = index == 0
        colors = {**SANTA_COLORS, "n": RUDOLPH_NOSE if lead else SANTA_COLORS["b"]}
        draw_santa_sprite(image, SANTA_REINDEER_SPRITES[frame], x, y - 3 + frame, santa.direction, colors)
        if lead and night > 0:
            nose_x, nose_y = round(x + santa.direction * 3), round(y - 2 + frame)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                point = (nose_x + dx, nose_y + dy)
                if 0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT and point != (nose_x - santa.direction, nose_y):
                    d.point(point, fill=mix(image.getpixel(point), RUDOLPH_NOSE, 0.35 * night))


FIREWORK_SLOT_SECONDS = 0.7
FIREWORK_CHANCE = 0.9
# Each cycle ends with a finale that fires several shells per slot.
FIREWORK_FINALE_PERIOD = 75
FIREWORK_FINALE_SECONDS = 7
FIREWORK_MAX_SECONDS = 4.2
FIREWORK_HORIZON = 24
FIREWORK_COLORS = ((255, 40, 40), (255, 190, 40), (40, 255, 90), (60, 130, 255), (200, 80, 255), (255, 255, 255), (255, 110, 200), (40, 230, 255))
FIREWORK_PATRIOTIC = ((255, 30, 40), (255, 255, 255), (80, 150, 255))
FIREWORK_WILLOW = (255, 176, 70)
FIREWORK_GLITTER = (255, 244, 210)
FIREWORK_ROCKET = (255, 214, 150)
FIREWORK_X, FIREWORK_Y = np.meshgrid(np.arange(WIDTH, dtype=np.float32), np.arange(HEIGHT, dtype=np.float32))
WATER = np.asarray(LAND) == INDEX["water"]
WATER_ROWS = (int(np.flatnonzero(WATER.any(axis=1))[0]), int(np.flatnonzero(WATER.any(axis=1))[-1]) + 1)


@dataclass(frozen=True, eq=False)
class FireworkShell:
    launch: float
    rise: float
    origin: float
    burst: tuple[float, float]
    kind: str
    life: float
    gravity: float
    radius: float
    salt: int
    angles: np.ndarray
    speeds: np.ndarray
    colors: np.ndarray


@lru_cache(maxsize=32)
def firework_shells(slot: int, seed: int, patriotic: bool) -> tuple[FireworkShell, ...]:
    rng = random.Random(seed * 2741 + slot * 48611 + 31)
    start = slot * FIREWORK_SLOT_SECONDS
    finale = start % FIREWORK_FINALE_PERIOD >= FIREWORK_FINALE_PERIOD - FIREWORK_FINALE_SECONDS
    count = rng.choice((1, 2, 2, 3)) if finale else int(rng.random() < FIREWORK_CHANCE)
    palette = FIREWORK_PATRIOTIC if patriotic else FIREWORK_COLORS
    shells = []
    for _ in range(count):
        kind = rng.choice(("peony", "peony", "ring", "willow", "crackle"))
        radius = rng.uniform(4.5, 7.5) if kind != "ring" else rng.uniform(5, 7)
        burst = (rng.uniform(10, 118), rng.uniform(radius + 5, 15))
        stars = round(radius * (3.6 if kind != "ring" else 2.8))
        angles = np.array([2 * math.pi * (i + rng.uniform(-0.25, 0.25)) / stars for i in range(stars)], dtype=np.float32)
        if kind == "ring":
            speeds = np.full(stars, radius, dtype=np.float32)
        else:
            # Shells read as filled spheres: most stars fly near full radius, some stay in the core.
            speeds = np.array([radius * (rng.uniform(0.85, 1.05) if rng.random() < 0.7 else rng.uniform(0.35, 0.65)) for _ in range(stars)], dtype=np.float32)
        outer, inner = rng.sample(palette, 2)
        if kind == "willow":
            colors = np.tile(np.array(FIREWORK_WILLOW, dtype=np.float32) / 255, (stars, 1))
        else:
            colors = np.where((speeds < radius * 0.7)[:, None], np.array(inner, dtype=np.float32) / 255, np.array(outer, dtype=np.float32) / 255)
        life = rng.uniform(2.4, 2.9) if kind == "willow" else rng.uniform(1.5, 2.1)
        shells.append(
            FireworkShell(
                launch=start + rng.uniform(0, FIREWORK_SLOT_SECONDS), rise=rng.uniform(0.7, 1.1), origin=burst[0] + rng.uniform(-4, 4), burst=burst, kind=kind, life=life, gravity=3.2 if kind == "willow" else 1.4, radius=radius, salt=rng.randrange(2**30), angles=angles, speeds=speeds, colors=colors
            )
        )
    return tuple(shells)


def splat(light: np.ndarray, xs: np.ndarray, ys: np.ndarray, colors: np.ndarray, weights: np.ndarray):
    columns, rows = np.rint(xs).astype(int), np.rint(ys).astype(int)
    keep = (columns >= 0) & (columns < WIDTH) & (rows >= 0) & (rows < HEIGHT) & (weights > 0.004)
    np.add.at(light, (rows[keep], columns[keep]), colors[keep] * weights[keep, None])


def firework_light(elapsed: float, seed: int, patriotic: bool, night: float) -> np.ndarray | None:
    """Light from distant fireworks, as a (row, column, rgb) array in 0..1, or None when the sky is quiet."""
    light = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    active = False
    for slot in range(math.floor((elapsed - FIREWORK_MAX_SECONDS) / FIREWORK_SLOT_SECONDS), math.floor(elapsed / FIREWORK_SLOT_SECONDS) + 1):
        for shell in firework_shells(slot, seed, patriotic):
            age = elapsed - shell.launch
            if not 0 <= age < shell.rise + shell.life:
                continue
            active = True
            bx, by = shell.burst
            if age < shell.rise:
                # The rocket climbs from behind the hills, slowing as it nears the top, with a short spark trail.
                for back, weight in ((0, 0.9), (0.05, 0.45), (0.1, 0.22), (0.15, 0.1)):
                    progress = max(0, age - back) / shell.rise
                    climb = 1 - (1 - progress) ** 2
                    x = shell.origin + (bx - shell.origin) * climb + math.sin(age * 23 + shell.salt) * 0.4
                    y = FIREWORK_HORIZON + (by - FIREWORK_HORIZON) * climb
                    splat(light, np.array([x]), np.array([y]), np.array([FIREWORK_ROCKET], dtype=np.float32) / 255, np.array([weight]))
                continue
            age -= shell.rise
            fade = 1.0 if age < 0.15 else max(0.0, 1 - (age - 0.15) / (shell.life - 0.15)) ** 1.3
            # The burst opens with a white-hot flash that briefly lights the sky around it after dark.
            heat = max(0.0, 1 - age / 0.2)
            colors = shell.colors + (1 - shell.colors) * heat * 0.8
            glow = 0.42 * math.exp(-age / 0.3) * (0.15 + 0.85 * night)
            if glow > 0.01:
                distance = (FIREWORK_X - bx) ** 2 + (FIREWORK_Y - by) ** 2
                tint = shell.colors.mean(axis=0) * 0.6 + 0.4
                light += np.exp(-distance / (2 * (shell.radius * 1.3) ** 2))[..., None] * tint * glow
            trail = 6 if shell.kind == "willow" else 3
            for step in range(trail + 1):
                at = age - step * 0.05
                if at < 0:
                    break
                reach = shell.speeds * (1 - math.exp(-at / 0.28))
                xs = bx + reach * np.cos(shell.angles)
                ys = by + reach * np.sin(shell.angles) * 0.9 + shell.gravity * at * at
                weights = np.full(len(xs), fade * (0.72 if shell.kind == "willow" else 0.5) ** step, dtype=np.float32)
                if shell.kind == "crackle" and age > shell.life * 0.45:
                    # Crackle shells end in strobing white glitter.
                    flicker = np.array([unit_hash(shell.salt, index, math.floor(elapsed * 16)) for index in range(len(xs))], dtype=np.float32)
                    sparkle = np.array(FIREWORK_GLITTER, dtype=np.float32) / 255
                    splat(light, xs, ys, np.tile(sparkle, (len(xs), 1)), weights * (flicker > 0.45) * 1.3)
                    continue
                splat(light, xs, ys, colors, weights)
            if age < 0.08:
                splat(light, np.array([bx]), np.array([by]), np.ones((1, 3), dtype=np.float32), np.array([1.0]))
    return light if active else None


def composite_light(image: Image.Image, light: np.ndarray) -> Image.Image:
    """Lay emitted light over the scene as premultiplied color, so stars keep their saturation even against a daytime sky."""
    light = np.clip(light, 0, 1)
    base = np.asarray(image, dtype=np.float32) / 255
    return Image.fromarray(np.round((base * (1 - light.max(axis=-1, keepdims=True)) + light) * 255).astype(np.uint8), "RGB")


def reflect_fireworks(image: Image.Image, light: np.ndarray, elapsed: float) -> Image.Image:
    """Bursts shimmer on the pond below them."""
    top, bottom = WATER_ROWS
    shimmer = 0.5 + 0.5 * np.sin(FIREWORK_X[top:bottom] * 0.9 + FIREWORK_Y[top:bottom] * 2.3 - elapsed * 4)
    reflection = np.clip(light.max(axis=0), 0, 1)[None, :, :] * (WATER[top:bottom] * shimmer * 0.5)[..., None]
    pond = image.crop((0, top, WIDTH, bottom))
    image.paste(composite_light(pond, reflection), (0, top))
    return image


FLAG_POLE_X = 43
FLAG_TOP = 6
FLAG_GROUND = 26
# Seven stripes and a starred canton, 13 x 7 like the real flag's 1.9:1 proportions.
FLAG_ROWS = ("sbsbsbRRRRRRR", "bbbbbbWWWWWWW", "bsbsbsRRRRRRR", "bbbbbbWWWWWWW", "RRRRRRRRRRRRR", "WWWWWWWWWWWWW", "RRRRRRRRRRRRR")
FLAG_COLORS = {"R": (206, 22, 44), "W": (246, 246, 240), "b": (28, 46, 150), "s": (246, 246, 240)}
FLAG_POLE = (196, 200, 206)
FLAG_FINIAL = (255, 204, 70)
# A ground floodlight at the pole's foot, aimed up at the flag; it switches on and off with the yard lamp.
FLAG_FLOOD_HOUSING = ((45, 26), (46, 26))
FLAG_FLOOD_LENS = (46, 25)
FLAG_FLOOD_AIM = (50, 9)
# Beam half-width gained per pixel of travel; wide enough to take in the whole fly by the flag's rows.
FLAG_FLOOD_SPREAD = 0.5
FLAG_FLOOD_LIGHT = (255, 244, 222)
FLAG_FLOOD_GLOW = (255, 250, 236)


def flag_flood_masks() -> tuple[np.ndarray, np.ndarray]:
    """How strongly the floodlight falls on the flag and pole at each pixel, and the faint beam it leaves in the air."""
    lens_x, lens_y = FLAG_FLOOD_LENS
    axis = np.array(FLAG_FLOOD_AIM, dtype=np.float32) - FLAG_FLOOD_LENS
    reach = float(np.hypot(*axis))
    ux, uy = axis / reach
    rows, columns = np.arange(HEIGHT)[:, None] - lens_y, np.arange(WIDTH)[None, :] - lens_x
    along = columns * ux + rows * uy
    across = np.abs(columns * uy - rows * ux)
    inside = np.clip(1 - across / (0.6 + np.maximum(along, 0) * FLAG_FLOOD_SPREAD), 0, 1)
    ahead = (along > 0) & (along <= reach + 5)
    # The flag is lit nearly evenly across the cone, a little brighter nearer the lamp.
    surface = np.where(ahead, np.clip(inside * 2.2, 0, 1) * (1 - 0.25 * np.clip(along / reach, 0, 1)), 0)
    haze = np.where(ahead, inside * (0.1 + 0.3 * np.clip(1 - along / reach, 0, 1)), 0)
    halo = np.clip(1 - np.hypot(columns, rows * 1.3) / 2.2, 0, 1) * 0.5
    return surface.astype(np.float32), np.maximum(haze, halo).astype(np.float32)


FLAG_FLOOD_SURFACE, FLAG_FLOOD_HAZE = flag_flood_masks()
FLAG_FLOOD_TINT = np.array(FLAG_FLOOD_LIGHT, dtype=np.float32) / 255
FLAG_FLOOD_FIXTURE_COLUMNS, FLAG_FLOOD_FIXTURE_ROWS = (np.array(axis) for axis in zip(*FLAG_FLOOD_HOUSING, FLAG_FLOOD_LENS))
FLAG_CLOTH = np.array([[FLAG_COLORS[char] for char in line] for line in FLAG_ROWS], dtype=np.float32)
FLAG_CLOTH_ROWS = FLAG_TOP + np.arange(len(FLAG_ROWS))[:, None]
FLAG_CLOTH_COLUMNS = np.arange(len(FLAG_ROWS[0]))
# The pole from its gold finial down to the ground.
FLAG_STAFF_ROWS = np.arange(FLAG_TOP - 1, FLAG_GROUND + 1)
FLAG_STAFF = np.array([FLAG_FINIAL, *[FLAG_POLE] * (len(FLAG_STAFF_ROWS) - 1)], dtype=np.float32)


def draw_flag(image: Image.Image, palette: Palette, wind: float, elapsed: float, flood: float = 0.0):
    """A big American flag rippling on a pole beside the hut, floodlit from the ground after dark."""
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))

    def lit(colors: np.ndarray, rows: np.ndarray, columns: np.ndarray) -> np.ndarray:
        light = np.minimum(1.0, illumination + (flood * FLAG_FLOOD_SURFACE[rows, columns])[..., None] * FLAG_FLOOD_TINT)
        return colors * light

    breeze = 0.6 + min(wind, 25) / 25
    speed = 3.5 + min(wind, 25) * 0.15
    phase = FLAG_CLOTH_COLUMNS * 0.75 - elapsed * speed
    # Ripples grow away from the hoist; their slopes catch more or less light.
    lift = np.round(breeze * np.sin(phase) * FLAG_CLOTH_COLUMNS / 12).astype(int)
    shade = 1 + 0.2 * np.cos(phase) * np.minimum(1, FLAG_CLOTH_COLUMNS / 3)
    rows = FLAG_CLOTH_ROWS + lift
    columns = np.broadcast_to(FLAG_POLE_X + 1 + FLAG_CLOTH_COLUMNS, rows.shape)
    pixels = np.array(image)
    pixels[FLAG_STAFF_ROWS, FLAG_POLE_X] = np.round(np.minimum(255, lit(FLAG_STAFF, FLAG_STAFF_ROWS, np.full_like(FLAG_STAFF_ROWS, FLAG_POLE_X))))
    pixels[FLAG_FLOOD_FIXTURE_ROWS, FLAG_FLOOD_FIXTURE_COLUMNS] = palette.roof
    pixels[rows, columns] = np.round(np.minimum(255, lit(FLAG_CLOTH, rows, columns) * shade[:, None]))
    image.paste(Image.fromarray(pixels, "RGB"))


def flag_flood_level(environment: "OutsideEnvironment") -> float:
    """The floodlight comes on with the yard lamp at nightfall, warming up the same way, and burns until sunrise."""
    altitude = environment.sun_altitude
    if altitude is None or not (altitude < NIGHT_ALTITUDE or environment.before_sunrise):
        return 0.0
    since = environment.since_nightfall
    return min(1.0, since / LAMP_WARMUP_SECONDS) if since is not None and 0 <= since < LAMP_WARMUP_SECONDS else 1.0


def draw_flag_flood(image: Image.Image, level: float) -> Image.Image:
    """The floodlight's faint beam through the night air and the glow of its lens."""
    pixels = np.asarray(image, dtype=np.float32)
    pixels = pixels + (np.array(FLAG_FLOOD_LIGHT, dtype=np.float32) - pixels) * (FLAG_FLOOD_HAZE * level)[..., None]
    lit = Image.fromarray(np.round(pixels).astype(np.uint8), "RGB")
    lit.putpixel(FLAG_FLOOD_LENS, mix(image.getpixel(FLAG_FLOOD_LENS), FLAG_FLOOD_GLOW, level))
    return lit


# A cartoon cannon left of the tree fires salutes: a fuse that sputters down to the breech, a blinding blast, a ball
# that streaks out of frame, and a shower of embers that smolder on the ground.
CANNON_MUZZLE_X = 90
CANNON_GROUND = 29
# Barrel elevation as rise per pixel; the ball leaves along it.
CANNON_SLOPE = 0.8
CANNON_BARREL_LENGTH = 11
CANNON_BARREL_RADIUS = 1.6
CANNON_MUZZLE_SWELL = 0.4
# The wheel's hub, as (distance along the barrel, offset below it).
CANNON_HUB = (9.5, 2.4)
CANNON_WHEEL = ("..www..", ".wdwdw.", "wddwddw", "wwwowww", "wddwddw", ".wdwdw.", "..www..")
CANNON_TRAIL_LENGTH = 7
CANNON_COLORS = {"O": (14, 14, 18), "R": (96, 98, 112), "H": (150, 154, 170), "K": (58, 60, 70), "k": (26, 27, 32), "b": (230, 184, 64), "w": (146, 104, 62), "d": (66, 44, 28), "o": (230, 184, 64), "C": (120, 84, 50)}
CANNON_SLOT_SECONDS = 14
CANNON_FIRE_CHANCE = 0.8
# Blast, flight, embers and smoke; a shot, with the fuse burning before it, never crosses its slot.
CANNON_SHOT_SECONDS = 6.0
# The fuse burns down for this long before the cannon fires, so the blast can be seen coming.
CANNON_FUSE_SECONDS = 2.5
# Its sparks flare up over the last moments before the blast.
CANNON_FUSE_FLARE_SECONDS = 0.6
# The wick curls up and back from the touch hole, listed from the hole to its tip.
CANNON_FUSE = ((0, 0), (0, -1), (1, -2), (2, -2))
CANNON_FUSE_COLOR = (170, 140, 92)
CANNON_FUSE_SPARKS = 7
CANNON_RECOIL_SECONDS = 0.45
# Px/s along the barrel; the ball clears the top of the frame in about a third of a second.
CANNON_BALL_SPEED = 110
CANNON_BALL = (40, 40, 46)
CANNON_BALL_SHINE = (150, 152, 166)
# After dark the red-hot ball still shows against the sky.
CANNON_BALL_HOT = (255, 120, 40)
CANNON_SMOKE = (226, 226, 228)
CANNON_SMOKE_SECONDS = 4.0
# Smoke puffs: (angle from the barrel in radians, reach in px, final radius in px).
CANNON_PUFFS = ((0.0, 7.5, 3.4), (-0.45, 5.5, 2.8), (0.45, 5.5, 2.8), (-0.9, 3.5, 2.4), (0.9, 3.5, 2.4), (0.2, 2.0, 2.2), (-0.2, 9.5, 2.4))
CANNON_FLASH_SECONDS = 0.9
# Decay time constant of the blast's light.
CANNON_FLASH_DECAY = 0.2
# A ring of fire bursts out from the muzzle at this many px/s and is gone after CANNON_SHOCK_SECONDS.
CANNON_SHOCK_SPEED = 70
CANNON_SHOCK_SECONDS = 0.35
FLASH_CORE = (255, 252, 230)
FLASH_FIRE = (255, 196, 60)
FLASH_TIP = (255, 110, 30)
CANNON_EMBERS = 36
CANNON_EMBER_GRAVITY = 14
CANNON_EMBER_DRAG = 1.6
# Embers that land settle on the meadow at this row and smolder; those over the pond go out.
CANNON_EMBER_GROUND = 27
CANNON_MUZZLE_SMOLDER_SECONDS = 1.5
EMBER_HOT = np.array((255, 236, 170), dtype=np.float32) / 255
EMBER_WARM = np.array((255, 130, 30), dtype=np.float32) / 255
EMBER_COOL = np.array((190, 34, 8), dtype=np.float32) / 255


def cannon_sprite() -> tuple[dict[tuple[int, int], str], tuple[float, float], tuple[float, float]]:
    """Absolute pixels -> material key, the muzzle's center, and the unit vector from the muzzle back to the breech."""
    ux, uy = 1 / math.hypot(1, CANNON_SLOPE), CANNON_SLOPE / math.hypot(1, CANNON_SLOPE)
    length, radius = CANNON_BARREL_LENGTH, CANNON_BARREL_RADIUS
    barrel = {}
    for y in range(-4, length + 4):
        for x in range(-4, length + 4):
            along, below = x * ux + y * uy, -x * uy + y * ux
            reach = radius + (CANNON_MUZZLE_SWELL if along < 1.6 else 0)
            if -0.5 <= along <= length and abs(below) <= reach:
                barrel[(x, y)] = "R" if along < 1 else "H" if below < -reach * 0.35 else "k" if below > reach * 0.4 else "K"
    barrel[(round((length + 0.9) * ux), round((length + 0.9) * uy))] = "b"
    hub_along, hub_below = CANNON_HUB
    hub = (round(hub_along * ux - hub_below * uy), round(hub_along * uy + hub_below * ux))
    ground = hub[1] + len(CANNON_WHEEL) // 2
    sprite = {}
    # The carriage's trail runs from the axle back to the ground, two pixels thick.
    for step in range(CANNON_TRAIL_LENGTH * 4 + 1):
        x = hub[0] + step / 4
        y = round(hub[1] + (ground - hub[1]) * step / (CANNON_TRAIL_LENGTH * 4))
        sprite[(round(x), y)] = sprite[(round(x), y - 1)] = "C"
    # A dark outline keeps the barrel readable against the hills.
    for x, y in barrel:
        for point in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if point not in barrel:
                sprite[point] = "O"
    sprite.update(barrel)
    for row, line in enumerate(CANNON_WHEEL):
        for column, key in enumerate(line):
            if key != ".":
                sprite[(hub[0] - len(line) // 2 + column, hub[1] - len(CANNON_WHEEL) // 2 + row)] = key
    shift_x, shift_y = CANNON_MUZZLE_X, CANNON_GROUND - ground
    return {(x + shift_x, y + shift_y): key for (x, y), key in sprite.items()}, (float(shift_x), float(shift_y)), (ux, uy)


CANNON_PIXELS, CANNON_MUZZLE, CANNON_AXIS = cannon_sprite()
CANNON_GROUPS = {key: [point for point, value in CANNON_PIXELS.items() if value == key] for key in CANNON_COLORS}
# The ball leaves just past the muzzle, along the barrel.
CANNON_LAUNCH = (CANNON_MUZZLE[0] - CANNON_AXIS[0], CANNON_MUZZLE[1] - CANNON_AXIS[1])


def cannon_fuse_pixels() -> tuple[tuple[int, int], ...]:
    """The wick's pixels, from the touch hole on top of the breech out to its tip."""
    ux, uy = CANNON_AXIS
    along, above = CANNON_BARREL_LENGTH - 2, CANNON_BARREL_RADIUS + 1
    # (uy, -ux) points up, off the barrel's top.
    hole = (round(CANNON_MUZZLE[0] + ux * along + uy * above), round(CANNON_MUZZLE[1] + uy * along - ux * above))
    return tuple((hole[0] + dx, hole[1] + dy) for dx, dy in CANNON_FUSE)


CANNON_FUSE_PIXELS = cannon_fuse_pixels()


@dataclass(frozen=True)
class CannonShot:
    slot: int
    fire: float


def cannon_shot(slot: int, seed: int) -> CannonShot | None:
    if unit_hash(seed, slot, 401) >= CANNON_FIRE_CHANCE:
        return None
    return CannonShot(slot, slot * CANNON_SLOT_SECONDS + CANNON_FUSE_SECONDS + unit_hash(seed, slot, 402) * (CANNON_SLOT_SECONDS - CANNON_SHOT_SECONDS - CANNON_FUSE_SECONDS))


def cannon_state(elapsed: float, seed: int) -> tuple[CannonShot, float] | None:
    """The shot under way and seconds since it fired (negative while the fuse burns), or None between shots."""
    shot = cannon_shot(math.floor(elapsed / CANNON_SLOT_SECONDS), seed)
    if shot is None or not -CANNON_FUSE_SECONDS <= elapsed - shot.fire < CANNON_SHOT_SECONDS:
        return None
    return shot, elapsed - shot.fire


def cannon_fuse_left(state: tuple[CannonShot, float] | None) -> float:
    """How much of the wick is left, 1 when it is unlit; it is gone once the cannon fires and is replaced after the shot."""
    if state is None:
        return 1.0
    return max(0.0, -state[1] / CANNON_FUSE_SECONDS)


def draw_cannon(image: Image.Image, palette: Palette, state: tuple[CannonShot, float] | None):
    """The cannon itself, jumping back a pixel as it fires."""
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    recoil = 1 if state is not None and 0 <= state[1] < CANNON_RECOIL_SECONDS else 0
    d = ImageDraw.Draw(image)
    for key, points in CANNON_GROUPS.items():
        color = tuple(round(value * (0.25 + 0.75 * illumination)) for value in CANNON_COLORS[key])
        d.point([(x + recoil, y) for x, y in points], fill=color)
    left = cannon_fuse_left(state)
    if left > 0:
        wick = CANNON_FUSE_PIXELS[: math.ceil(left * len(CANNON_FUSE_PIXELS))]
        d.point(wick, fill=tuple(round(value * (0.25 + 0.75 * illumination)) for value in CANNON_FUSE_COLOR))


def draw_cannon_smoke(image: Image.Image, palette: Palette, state: tuple[CannonShot, float] | None, wind: float) -> Image.Image:
    """The blast's billowing smoke."""
    if state is None or state[1] < 0:
        return image
    _, age = state
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    if age < CANNON_SMOKE_SECONDS:
        smoke = Image.new("RGBA", (WIDTH, HEIGHT))
        sd = ImageDraw.Draw(smoke)
        gray = tuple(round(value * (0.25 + 0.75 * illumination)) for value in CANNON_SMOKE)
        # The puffs are lit orange by the blast for an instant.
        color = mix(gray, FLASH_FIRE, max(0.0, 1 - age / 0.25) * 0.7)
        heading = math.atan2(-CANNON_AXIS[1], -CANNON_AXIS[0])
        burst = 1 - math.exp(-age / 0.3)
        opacity = 0.85 * (1 - age / CANNON_SMOKE_SECONDS) ** 1.5
        for angle, reach, radius in CANNON_PUFFS:
            x = CANNON_LAUNCH[0] + math.cos(heading + angle) * reach * burst + min(wind, 25) * age * SMOKE_WIND_DRIFT
            y = CANNON_LAUNCH[1] + math.sin(heading + angle) * reach * burst - age * 0.8
            r = 0.8 + (radius - 0.8) * (1 - math.exp(-age / 0.5))
            sd.ellipse((x - r, y - r, x + r, y + r), fill=(*color, round(255 * opacity)))
        image = Image.alpha_composite(image.convert("RGBA"), smoke).convert("RGB")
    return image


def draw_cannon_ball(image: Image.Image, palette: Palette, state: tuple[CannonShot, float] | None, night: float):
    """The ball bursting out of the blast and streaking out of frame; drawn over the blast's light so the flash
    cannot hide it."""
    if state is None or state[1] < 0:
        return
    age = state[1]
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    travel = age * CANNON_BALL_SPEED
    x, y = CANNON_LAUNCH[0] - CANNON_AXIS[0] * travel, CANNON_LAUNCH[1] - CANNON_AXIS[1] * travel
    if x < -2 or y < -2:
        return
    d = ImageDraw.Draw(image)
    ball = mix(tuple(round(value * (0.5 + 0.5 * illumination)) for value in CANNON_BALL), CANNON_BALL_HOT, 0.75 * night)
    shine = mix(tuple(round(value * (0.4 + 0.6 * illumination)) for value in CANNON_BALL_SHINE), FLASH_CORE, 0.6 * night)
    # A smear behind the ball, about one frame long, sells its speed; it leaves no lasting path.
    for back, opacity in ((5.0, 0.15), (3.5, 0.3), (2.0, 0.5)):
        if travel > back:
            px, py = round(x + CANNON_AXIS[0] * back), round(y + CANNON_AXIS[1] * back)
            for point in ((px, py), (px + 1, py), (px, py + 1)):
                if 0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT:
                    d.point(point, fill=mix(image.getpixel(point), ball, opacity))
    # A round 3x3 ball: half-blended corners, and a glint near its top.
    bx, by = round(x), round(y)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            point = (bx + dx, by + dy)
            if 0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT:
                color = shine if (dx, dy) == (0, -1) else ball
                d.point(point, fill=mix(image.getpixel(point), color, 0.55 if dx and dy else 1.0))


def cannon_flash_rays() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """A cartoon starburst: spiky rays, longest along the barrel, as (along, x, y, color) samples from the muzzle."""
    heading = math.atan2(-CANNON_AXIS[1], -CANNON_AXIS[0])
    alongs, xs, ys, colors = [], [], [], []
    for ray in range(12):
        angle = heading + ray * 2 * math.pi / 12
        forward = math.cos(angle - heading)
        length = 4.5 + 4.5 * max(0.0, forward) + 7 * max(0.0, forward) ** 6 + (2.0 if ray % 2 else 0)
        for step in np.arange(0, length + 0.01, 0.5):
            fraction = step / length
            alongs.append(fraction)
            xs.append(math.cos(angle) * step)
            ys.append(math.sin(angle) * step)
            colors.append(FLASH_CORE if fraction < 0.35 else FLASH_FIRE if fraction < 0.75 else FLASH_TIP)
    # A solid white-hot ball of fire at the heart of the burst.
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            if dx * dx + dy * dy <= 9:
                alongs.append(0.0)
                xs.append(float(dx))
                ys.append(float(dy))
                colors.append(FLASH_CORE)
    return np.array(alongs, dtype=np.float32), np.array(xs, dtype=np.float32), np.array(ys, dtype=np.float32), np.array(colors, dtype=np.float32) / 255


CANNON_FLASH_RAYS = cannon_flash_rays()
CANNON_FLASH_DISTANCE = (FIREWORK_X - CANNON_LAUNCH[0]) ** 2 + (FIREWORK_Y - CANNON_LAUNCH[1]) ** 2
CANNON_FLASH_GLOW = np.exp(-CANNON_FLASH_DISTANCE / (2 * 14.0**2))[..., None] * (np.array(FLASH_FIRE, dtype=np.float32) / 255)
# The blast floods the right side of the scene with light, by day as well as by night.
CANNON_FLASH_WASH = np.exp(-CANNON_FLASH_DISTANCE / (2 * 36.0**2))[..., None] * (np.array((255, 214, 150), dtype=np.float32) / 255)


@lru_cache(maxsize=4)
def cannon_embers(slot: int, seed: int) -> tuple[np.ndarray, ...]:
    """Each shot's burning embers: (heading cos, heading sin, speed px/s, lifetime s, flicker salt)."""
    rng = random.Random(seed * 7919 + slot * 104729 + 17)
    heading = math.atan2(-CANNON_AXIS[1], -CANNON_AXIS[0])
    embers = []
    for _ in range(CANNON_EMBERS):
        angle = heading + rng.gauss(0, 0.7)
        embers.append((math.cos(angle), math.sin(angle), rng.uniform(6, 32), rng.uniform(1.4, 3.6), rng.randrange(2**20)))
    return tuple(np.array(values, dtype=np.float32 if index < 4 else np.int64) for index, values in enumerate(zip(*embers)))


def cannon_light(state: tuple[CannonShot, float] | None, night: float, wind: float, seed: int) -> np.ndarray | None:
    """The fuse's sputtering sparks; then the muzzle blast's blinding starburst and ring of fire, and embers that drift
    down, cool from yellow to red and smolder where they land, as emitted light."""
    if state is None:
        return None
    shot, age = state
    light = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    if age < 0:
        return cannon_fuse_light(light, age, seed)
    if age < CANNON_FLASH_SECONDS:
        strength = math.exp(-age / CANNON_FLASH_DECAY)
        grow = min(1.0, 0.45 + age / 0.05)
        light += CANNON_FLASH_GLOW * (strength * (0.7 + 0.5 * night)) + CANNON_FLASH_WASH * (strength * (0.55 + 0.25 * night))
        alongs, xs, ys, colors = CANNON_FLASH_RAYS
        splat(light, CANNON_LAUNCH[0] + xs * grow, CANNON_LAUNCH[1] + ys * grow, colors, strength * 1.8 * (1 - 0.4 * alongs) * (alongs <= grow))
    if age < CANNON_SHOCK_SECONDS:
        radius = 3 + age * CANNON_SHOCK_SPEED
        angles = np.linspace(0, math.tau, max(24, round(radius * 7)), endpoint=False, dtype=np.float32)
        fade = 1 - age / CANNON_SHOCK_SECONDS
        color = (np.array(FLASH_FIRE, dtype=np.float32) + (np.array(FLASH_CORE, dtype=np.float32) - np.array(FLASH_FIRE, dtype=np.float32)) * fade) / 255
        splat(light, CANNON_LAUNCH[0] + np.cos(angles) * radius, CANNON_LAUNCH[1] + np.sin(angles) * radius * 0.8, np.tile(color, (len(angles), 1)), np.full(len(angles), 0.5 * fade, dtype=np.float32))
    if age < CANNON_MUZZLE_SMOLDER_SECONDS:
        smolder = 1 - age / CANNON_MUZZLE_SMOLDER_SECONDS
        splat(light, np.array([CANNON_MUZZLE[0] - 0.5]), np.array([CANNON_MUZZLE[1]]), (EMBER_COOL + (EMBER_WARM - EMBER_COOL) * smolder)[None], np.array([0.7 * smolder]))
    cos, sin, speed, life, salt = cannon_embers(shot.slot, seed)
    heat = np.clip(1 - age / life, 0, 1)
    travel = speed / CANNON_EMBER_DRAG * (1 - math.exp(-CANNON_EMBER_DRAG * age))
    xs = CANNON_LAUNCH[0] + cos * travel + min(wind, 25) * SMOKE_WIND_DRIFT * 0.5 * age
    ys = CANNON_LAUNCH[1] + sin * travel + 0.5 * CANNON_EMBER_GRAVITY * age * age
    landed = ys >= CANNON_EMBER_GROUND
    ys = np.minimum(ys, CANNON_EMBER_GROUND)
    columns = np.clip(np.rint(xs).astype(int), 0, WIDTH - 1)
    # Embers that drop into the pond hiss out; the rest glow on in the grass.
    doused = landed & WATER[CANNON_EMBER_GROUND, columns]
    flicker = 0.55 + 0.45 * np.array([unit_hash(int(value), math.floor(age * 12)) for value in salt], dtype=np.float32)
    weights = (0.25 + 0.75 * heat) * flicker * (heat > 0) * ~doused * np.where(landed, 0.8, 1.0)
    colors = np.where((heat > 0.6)[:, None], EMBER_WARM + (EMBER_HOT - EMBER_WARM) * ((heat - 0.6) / 0.4)[:, None], EMBER_COOL + (EMBER_WARM - EMBER_COOL) * (heat / 0.6)[:, None])
    splat(light, xs, ys, colors, weights.astype(np.float32))
    return light if light.any() else None


def cannon_fuse_light(light: np.ndarray, age: float, seed: int) -> np.ndarray:
    """The lit fuse: a white-hot point at the end of the wick throwing sparks, which flare up just before the blast."""
    left = -age / CANNON_FUSE_SECONDS
    # The burning point creeps from the wick's tip down to the touch hole.
    position = left * (len(CANNON_FUSE_PIXELS) - 1)
    low = CANNON_FUSE_PIXELS[math.floor(position)]
    high = CANNON_FUSE_PIXELS[min(len(CANNON_FUSE_PIXELS) - 1, math.floor(position) + 1)]
    fraction = position - math.floor(position)
    x, y = low[0] + (high[0] - low[0]) * fraction, low[1] + (high[1] - low[1]) * fraction
    flare = 1 + 1.5 * max(0.0, 1 - -age / CANNON_FUSE_FLARE_SECONDS)
    frame = math.floor(age * 15)
    glow = np.exp(-((FIREWORK_X - x) ** 2 + (FIREWORK_Y - y) ** 2) / (2 * 2.5**2))[..., None]
    light += glow * (np.array(FLASH_FIRE, dtype=np.float32) / 255 * 0.25 * flare)
    count = round(CANNON_FUSE_SPARKS * flare)
    angles = np.array([unit_hash(seed, frame, 411, index) for index in range(count)], dtype=np.float32) * math.tau
    reach = np.array([unit_hash(seed, frame, 412, index) for index in range(count)], dtype=np.float32) * (1.5 + flare)
    # Sparks spray mostly upward.
    xs = x + np.cos(angles) * reach
    ys = y - np.abs(np.sin(angles)) * reach
    colors = np.tile(np.array(FLASH_FIRE, dtype=np.float32) / 255, (count, 1))
    splat(light, xs, ys, colors, np.full(count, 0.8, dtype=np.float32))
    splat(light, np.array([x]), np.array([y]), np.array([FLASH_CORE], dtype=np.float32) / 255, np.array([1.0], dtype=np.float32))
    return light


# Ground fountains on the pond's far bank, red, white and blue: they burn in turns while the fireworks fly, and all
# together through each finale. (column, spark color)
FOUNTAINS = ((58, (255, 52, 44)), (66, (255, 240, 214)), (74, (70, 140, 255)))
FOUNTAIN_ROW = 24
FOUNTAIN_HEIGHT = 8
FOUNTAIN_GRAVITY = 30
FOUNTAIN_SPARKS = 40
FOUNTAIN_SLOT_SECONDS = 12
FOUNTAIN_CHANCE = 0.6
FOUNTAIN_BURN = (5, 9)
FOUNTAIN_IGNITE_SECONDS = 0.5
FOUNTAIN_DIE_SECONDS = 1.0
FOUNTAIN_HOT = np.array((255, 250, 225), dtype=np.float32) / 255


def fountain_sparks() -> dict[str, np.ndarray]:
    """Every fountain's fixed spark streams in one flat table, each spark listed twice: itself and a dimmer point
    trailing it."""
    columns: dict[str, list] = {name: [] for name in ("owner", "x", "phase", "life", "sin", "cos", "speed", "tint", "spark")}
    for index, (x, color) in enumerate(FOUNTAINS):
        rng = random.Random(7301 + index * 31)
        for spark in range(FOUNTAIN_SPARKS):
            angle = rng.uniform(-0.5, 0.5)
            values = {"owner": index, "x": x, "phase": rng.random(), "life": rng.uniform(0.9, 1.5), "sin": math.sin(angle), "cos": math.cos(angle), "speed": rng.uniform(0.8, 1.02), "tint": np.array(color) / 255, "spark": index * FOUNTAIN_SPARKS + spark}
            for name, value in values.items():
                columns[name].append(value)
    table = {name: np.array(values * 2, dtype=np.int64 if name in ("owner", "spark") else np.float32) for name, values in columns.items()}
    count = len(FOUNTAINS) * FOUNTAIN_SPARKS
    table["back"] = np.repeat(np.array((0.0, 0.04), dtype=np.float32), count)
    table["streak"] = np.repeat(np.array((1.0, 0.45), dtype=np.float32), count)
    return table


FOUNTAIN_SPARK_TABLE = fountain_sparks()
FOUNTAIN_MOUTHS = np.array([x for x, _ in FOUNTAINS], dtype=np.float32)
# Each fountain's glow on the bank, kept to a small box around its base: (columns, glow) within FOUNTAIN_GLOW_ROWS.
FOUNTAIN_GLOW_ROWS = slice(FOUNTAIN_ROW - 7, FOUNTAIN_ROW + 6)
FOUNTAIN_GLOWS = tuple((slice(x - 9, x + 10), (np.exp(-((FIREWORK_X - x) ** 2 + ((FIREWORK_Y - FOUNTAIN_ROW) * 1.6) ** 2) / (2 * 3.0**2))[..., None] * (np.array(color, dtype=np.float32) / 255 * 0.5 + 0.5))[FOUNTAIN_GLOW_ROWS, x - 9 : x + 10]) for x, color in FOUNTAINS)


def burn_window(t: float, start: float, end: float) -> float:
    """0..1 for a fountain lit at `start` and spent at `end`: it flares up, then sputters out."""
    if t < start or t >= end + FOUNTAIN_DIE_SECONDS:
        return 0.0
    return min(1.0, (t - start) / FOUNTAIN_IGNITE_SECONDS, 1 - (t - end) / FOUNTAIN_DIE_SECONDS)


def fountain_level(index: int, elapsed: float, seed: int) -> float:
    cycle = elapsed % FIREWORK_FINALE_PERIOD
    finale = FIREWORK_FINALE_PERIOD - FIREWORK_FINALE_SECONDS - 1
    level = max(burn_window(cycle, finale, FIREWORK_FINALE_PERIOD), burn_window(cycle + FIREWORK_FINALE_PERIOD, finale, FIREWORK_FINALE_PERIOD))
    slot = math.floor(elapsed / FOUNTAIN_SLOT_SECONDS)
    if unit_hash(seed, slot, index, 501) < FOUNTAIN_CHANCE:
        burn = FOUNTAIN_BURN[0] + unit_hash(seed, slot, index, 502) * (FOUNTAIN_BURN[1] - FOUNTAIN_BURN[0])
        start = slot * FOUNTAIN_SLOT_SECONDS + unit_hash(seed, slot, index, 503) * (FOUNTAIN_SLOT_SECONDS - burn - FOUNTAIN_DIE_SECONDS)
        level = max(level, burn_window(elapsed, start, start + burn))
    return level


def draw_fountain_tubes(image: Image.Image, palette: Palette):
    d = ImageDraw.Draw(image)
    for x, _ in FOUNTAINS:
        d.point(((x, FOUNTAIN_ROW), (x, FOUNTAIN_ROW + 1)), fill=palette.roof)


def fountain_light(elapsed: float, seed: int, night: float) -> np.ndarray | None:
    """Sparks gushing up from each lit fountain and falling back, as emitted light."""
    levels = np.array([fountain_level(index, elapsed, seed) for index in range(len(FOUNTAINS))], dtype=np.float32)
    if not levels.any():
        return None
    light = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    sparks = FOUNTAIN_SPARK_TABLE
    level = levels[sparks["owner"]]
    # Fountains flare up to full height as they ignite and shrink as they sputter out.
    speed = sparks["speed"] * math.sqrt(2 * FOUNTAIN_GRAVITY * FOUNTAIN_HEIGHT) * (0.35 + 0.65 * level)
    life = sparks["life"]
    age = (elapsed / life + sparks["phase"]) % 1 * life - sparks["back"]
    xs = sparks["x"] + sparks["sin"] * speed * age
    ys = FOUNTAIN_ROW - sparks["cos"] * speed * age + 0.5 * FOUNTAIN_GRAVITY * age * age
    # Sparks crackle on and off, a different set each tick.
    crackle = 0.35 + 0.65 * (np.modf(np.sin(sparks["spark"] * 12.9898 + math.floor(elapsed * 15) * 78.233) * 43758.5453)[0] ** 2 > 0.1)
    colors = np.where((age < 0.08)[:, None], FOUNTAIN_HOT, sparks["tint"])
    weights = level * sparks["streak"] * crackle * np.clip(1 - age / life, 0, 1) ** 1.2 * (age >= 0) * (ys <= FOUNTAIN_ROW)
    # The white-hot mouth of each tube.
    splat(light, np.concatenate((xs, FOUNTAIN_MOUTHS)), np.concatenate((ys, np.full(len(FOUNTAINS), FOUNTAIN_ROW, dtype=np.float32))), np.vstack((colors, np.tile(FOUNTAIN_HOT, (len(FOUNTAINS), 1)))), np.concatenate((weights, levels)))
    for (columns, glow), lit in zip(FOUNTAIN_GLOWS, levels):
        if lit > 0:
            light[FOUNTAIN_GLOW_ROWS, columns] += glow * (lit * (0.12 + 0.3 * night))
    return light


HALLOWEEN = "halloween"
# The night sky turns a bruised violet as dusk deepens.
HALLOWEEN_SKY_TOP = (34, 10, 54)
HALLOWEEN_SKY_MIDDLE = (60, 26, 78)
# Ground mist: two noise layers drifting in opposite directions, (tile, px/s, weight).
HALLOWEEN_MIST_TOP = 15
HALLOWEEN_MIST_DEPTH = 9
HALLOWEEN_MIST_BREATH = 1.5
# The first row the mist can reach at the top of its breath.
HALLOWEEN_MIST_ROW = math.floor(HALLOWEEN_MIST_TOP - HALLOWEEN_MIST_BREATH)
HALLOWEEN_MIST_ROWS = np.arange(HALLOWEEN_MIST_ROW, HEIGHT, dtype=np.float32)[:, None]
# Tiles are doubled horizontally so a scrolled window is a plain slice.
HALLOWEEN_MIST_LAYERS = tuple((np.tile(periodic_noise(cell_x, cell_y, salt)[HALLOWEEN_MIST_ROW:], 2).astype(np.float32), speed, weight) for cell_x, cell_y, salt, speed, weight in ((32, 5, 61, 1.7, 0.6), (16, 3, 62, -2.6, 0.4)))
HALLOWEEN_MIST_DAY = (178, 188, 198)
HALLOWEEN_MIST_NIGHT = (98, 136, 126)
# Carved pumpkins facing the viewer: s stem, p rind, r rib shadow; e eyes and nose and m mouth glow with the candle inside.
JACK_SPRITES = {
    "big": ("....s....", "..prprp..", ".ppppppp.", "ppepppepp", "peepepeep", "pmmmmmmmp", "ppmpmpmpp", ".ppppppp."),
    "small": ("...s...", ".prprp.", "pepppep", "pppeppp", "pmmmmmp", ".pmpmp."),
}
# (center column, bottom row, size): two sit in the meadow and one beside the tree, clear of the hut and the cobweb.
JACK_O_LANTERNS = ((87, 31, "big"), (95, 31, "small"), (104, 31, "big"))
PUMPKIN_RIND = (240, 132, 26)
PUMPKIN_RIB = (170, 78, 16)
PUMPKIN_STEM = (84, 104, 40)
PUMPKIN_CARVED = (46, 16, 6)
CANDLE_FLAME = (255, 204, 70)
CANDLE_GLOW = (255, 136, 32)
# Now and then an end pumpkin rolls away along the ground, wraps around the screen and settles back upright in its
# spot: pumpkin index -> direction (-1 rolls left).
JACK_ROLLERS = {0: -1, 2: 1}
JACK_ROLL_SLOT_SECONDS = 60
JACK_ROLL_CHANCE = 0.5
# Average speed in px/s; each roll eases out of its spot and back into it.
JACK_ROLL_SPEED = 18
JACK_ROLL_STEPS = 16
# The candle gutters while the pumpkin tumbles.
JACK_ROLL_FLAME = 0.6
# The yard lamp burns all Halloween evening on a dying bulb: dim against daylight, it buzzes unsteadily the whole
# time and, during some slots, keeps cutting out at LAMP_FLICKER_RATE Hz.
LAMP_HALLOWEEN_DAYLIGHT = 0.3
LAMP_FLICKER_SLOT_SECONDS = 2.5
LAMP_FLICKER_CHANCE = 0.5
LAMP_FLICKER_RATE = 14
LAMP_DROPOUT_CHANCE = (0.08, 0.45)
LAMP_DROPOUT_LEVEL = 0.12
GHOST_SLOT_SECONDS = 20
GHOST_CHANCE = 0.95
# Peak speed (px/s) of a swoop; the ghost eases into and out of each one.
GHOST_PEAK_SPEED = (60, 85)
GHOST_HOVER_SECONDS = (1.6, 3.2)
GHOST_BOO_SECONDS = 0.8
GHOST_COLUMNS = (8, 120)
# Anchor rows keep the 7 px sprite below the corner labels and above the ground.
GHOST_ROWS = (10, 21)
GHOST_TRAIL = 4
GHOST_TRAIL_SPACING = 0.04
GHOST_OPACITY = 0.88
GHOST_WHITE = (236, 246, 255)
GHOST_EYES = (12, 6, 24)
GHOST_GLOW = (120, 255, 190)
# Facing right, anchored on the center pixel: w sheet, k eyes and mouth. Each pose has two tail frames.
GHOST_BODIES = {
    "hover": ("..www..", ".wwwww.", ".wkwkw.", ".wwwww.", "wwwkwww", ".wwwww."),
    "fly": ("...www.", "..wwwww", "..wwkwk", ".wwwwww", "wwwwwkw", "wwwww.."),
    "boo": ("..www..", "wwwwwww", "wwkwkww", ".wwwww.", ".wkkkw.", ".wwkww."),
}
GHOST_TAILS = {"hover": ("ww.w.ww", ".w.w.w."), "fly": ("w.w....", ".w.w..."), "boo": ("ww.w.ww", ".w.w.w.")}
# A cobweb strung between the tree's right limb, its low spur, the trunk and the ground: radials run clockwise from
# the hub to anchors under the spur, the spur tip, the open air, the ground (three), the trunk and the limb.
COBWEB_HUB = (119, 24)
COBWEB_RADIALS = ((119, 20), (123, 20), (126, 23), (124, 28), (119, 28), (114, 28), (112, 25), (115, 20))
# Radials start this far out, leaving the open free zone around the hub that keeps it from reading as a blob.
COBWEB_FREE_ZONE = 2
# One ring at this radius; at 1 px a smaller ring merges into the radials and more rings fill the web in solid.
COBWEB_RING = 4
# Guy lines tie the radial that ends in the air to the spur tip and to the ground.
COBWEB_GUYS = (((126, 23), (121, 19)), ((126, 23), (127, 28)))
COBWEB_SILK = (212, 220, 232)
COBWEB_OPACITY = {"radial": 0.8, "ring": 0.65, "guy": 0.6}
COBWEB_NIGHT_FADE = 0.25
COBWEB_DEW = (240, 248, 255)
COBWEB_DEW_DROPS = 5
# The web's resident, waiting on the ring below and right of the hub: l legs, b body.
COBWEB_SPIDER = ("l.l", ".b.", "l.l")
SHADOW_SLOT_SECONDS = 45
SHADOW_CHANCE = 0.85
# Where the figure lurks, (center column, feet row): between the conifer and the lamp, past the fence's end, and on
# the pond's far shore. It glides only between neighbouring spots right of the hut, so it never crosses in front of it.
SHADOW_SPOTS = ((9, 26), (46, 27), (61, 25), (76, 25))
SHADOW_GLIDES = {1: (2,), 2: (1, 3), 3: (2,)}
SHADOW_GLIDE_SPEED = 2.5
SHADOW_FADE_SECONDS = 2.0
SHADOW_LOOK_SECONDS = (1.6, 2.8)
SHADOW_EYE_FADE_SECONDS = 0.25
SHADOW_COLOR = (12, 8, 16)
SHADOW_OPACITY = 0.9
SHADOW_HEM_OPACITY = 0.55
SHADOW_EYES = (255, 34, 20)
# A hooded figure seen from behind, and turned to look back: s shadow, r eyes. Its ragged hem has two frames.
SHADOW_BODIES = {
    "away": ("..s..", ".sss.", ".sss.", ".sss.", "sssss", "sssss", "sssss", "sssss", "sssss", "sssss"),
    "toward": ("..s..", ".sss.", ".rsr.", ".sss.", "sssss", "sssss", "sssss", "sssss", "sssss", "sssss"),
}
SHADOW_HEMS = ("s.s.s", ".s.s.")
SPIDER_SLOT_SECONDS = 40
SPIDER_CHANCE = 0.8
# The silk hangs from above the frame into the open sky between the hut and the mountain.
SPIDER_COLUMNS = (46, 56)
# Rows of the abdomen's top while hanging; the legs then end above the hills.
SPIDER_REST_ROWS = (9, 12)
SPIDER_DROP_SECONDS = 0.6
SPIDER_HANG_SECONDS = (12, 22)
SPIDER_CLIMB_SPEED = 5
SPIDER_LUNGE_SECONDS = 0.7
SPIDER_LUNGE_DEPTH = 4
SPIDER_COLORS = {"b": (82, 70, 102), "l": (126, 114, 148), "c": (98, 86, 118), "h": (230, 28, 28), "r": (255, 36, 24), "f": (186, 182, 196)}
SPIDER_SILK = (200, 206, 220)
# A black widow hanging head down, anchored where the silk meets the abdomen: l legs, b abdomen, h hourglass,
# c head, r eyes, f fangs.
SPIDER_SPRITES = {
    "spread": ("l.....bbb.....l", ".l...bbbbb...l.", "..l.bbhhhbb.l..", "...lbbbhbbbl...", "llllbbhhhbbllll", "....l.bbb.l....", "...l.lcccl.l...", "..l.l.rcr.l.l..", ".l..l.f.f.l..l.", "l...l.....l...l"),
    "flex": ("......bbb......", "l....bbbbb....l", ".l..bbhhhbb..l.", "..llbbbhbbbll..", "....bbhhhbb....", "lllll.bbb.lllll", "....llcccll....", "...l..rcr..l...", "..l...f.f...l..", ".l...........l."),
    "climb": ("..l...bbb...l..", "...l.bbbbb.l...", "....bbhhhbb....", "..llbbbhbbbll..", ".l..bbhhhbb..l.", "l..l..bbb..l..l", "..l..lcccl..l..", ".l..l.rcr.l..l.", "....l.f.f.l....", "...l.......l..."),
}
SPIDER_HEIGHT = len(SPIDER_SPRITES["spread"])


def sprite_overlay(groups) -> Image.Image:
    """An RGBA layer from groups of (points as an (n, 2) array of x, y, color, opacity); later groups cover earlier ones."""
    layer = np.zeros((HEIGHT, WIDTH, 4), dtype=np.uint8)
    for points, color, opacity in groups:
        points = points[(points[:, 0] >= 0) & (points[:, 0] < WIDTH) & (points[:, 1] >= 0) & (points[:, 1] < HEIGHT)]
        layer[points[:, 1], points[:, 0]] = (*color, round(255 * min(1.0, opacity)))
    return Image.fromarray(layer, "RGBA")


def paste_overlay(image: Image.Image, groups):
    overlay = sprite_overlay(groups)
    image.paste(overlay, (0, 0), overlay)


def draw_halloween_mist(image: Image.Image, night: float, elapsed: float) -> Image.Image:
    """A low bank of mist creeping across the valley floor, pale by day and ghostly green after dark."""
    density = 0
    for tile, speed, weight in HALLOWEEN_MIST_LAYERS:
        offset = elapsed * speed % CLOUD_TILE
        start = math.floor(offset)
        window = tile[:, start : start + WIDTH + 1]
        density = density + weight * (window[:, :-1] + (window[:, 1:] - window[:, :-1]) * (offset - start))
    # The bank breathes up and down; its top edge stays ragged where the noise thins out.
    depth = np.clip((HALLOWEEN_MIST_ROWS - HALLOWEEN_MIST_TOP - HALLOWEEN_MIST_BREATH * math.sin(elapsed * 0.3)) / HALLOWEEN_MIST_DEPTH, 0, 1)
    thickness = np.clip((density * (0.5 + 0.5 * depth) - 0.25) / 0.4, 0, 1)
    alpha = thickness * thickness * (3 - 2 * thickness) * depth * (0.36 + 0.08 * night)
    pixels = np.array(image)
    band = pixels[HALLOWEEN_MIST_ROW:].astype(np.float32)
    band += (np.array(mix(HALLOWEEN_MIST_DAY, HALLOWEEN_MIST_NIGHT, night), dtype=np.float32) - band) * alpha[..., None]
    pixels[HALLOWEEN_MIST_ROW:] = np.round(band).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


def jack_center(index: int) -> tuple[float, float]:
    """The middle of a pumpkin's sprite at its spot; it rolls about this point."""
    cx, bottom, size = JACK_O_LANTERNS[index]
    rows = JACK_SPRITES[size]
    return cx - len(rows[0]) // 2 + (len(rows[0]) - 1) / 2, bottom - (len(rows) - 1) / 2


@lru_cache(maxsize=len(JACK_SPRITES))
def jack_rotations(size: str) -> tuple[tuple[tuple[int, int, str], ...], ...]:
    """Per rotation step (counterclockwise), the sprite's pixels as integer offsets from the pixel at or just above
    and left of its middle. Each screen pixel samples the sprite through the inverse rotation, so no pixel is lost
    when an even side puts the middle between pixels."""
    rows = JACK_SPRITES[size]
    width, height = len(rows[0]), len(rows)
    middle_x, middle_y = (width - 1) / 2, (height - 1) / 2
    reach = math.ceil(math.hypot(width, height) / 2) + 1
    frames = []
    for step in range(JACK_ROLL_STEPS):
        angle = math.tau * step / JACK_ROLL_STEPS
        cos, sin = math.cos(angle), math.sin(angle)
        pixels = []
        for j in range(-reach, reach + 1):
            for i in range(-reach, reach + 1):
                # Screen y points down, so a counterclockwise turn on screen maps back through the transpose.
                dx, dy = i - middle_x % 1, j - middle_y % 1
                column, row = math.floor(cos * dx - sin * dy + middle_x + 0.5), math.floor(sin * dx + cos * dy + middle_y + 0.5)
                if 0 <= column < width and 0 <= row < height and rows[row][column] != ".":
                    pixels.append((i, j, rows[row][column]))
        frames.append(tuple(pixels))
    return tuple(frames)


@lru_cache(maxsize=8)
def jack_roll(slot: int, seed: int) -> tuple[int, float, float] | None:
    """(pumpkin index, start, duration) of the roll in this slot, if any. Never spans two slots."""
    rng = random.Random(seed * 4073 + slot * 60013 + 67)
    if rng.random() > JACK_ROLL_CHANCE:
        return None
    duration = WIDTH / JACK_ROLL_SPEED
    return rng.choice(tuple(JACK_ROLLERS)), slot * JACK_ROLL_SLOT_SECONDS + rng.uniform(1, JACK_ROLL_SLOT_SECONDS - duration - 1), duration


def jack_roll_state(elapsed: float, seed: int) -> tuple[int, float, int] | None:
    """(pumpkin index, horizontal travel so far, rotation step) while a pumpkin rolls, else None."""
    roll = jack_roll(math.floor(elapsed / JACK_ROLL_SLOT_SECONDS), seed)
    if roll is None or not roll[1] <= elapsed < roll[1] + roll[2]:
        return None
    index, start, duration = roll
    progress = (elapsed - start) / duration
    travel = WIDTH * (progress - math.sin(math.tau * progress) / math.tau)
    # A whole number of turns over the trip, so it comes to rest upright.
    width = len(JACK_SPRITES[JACK_O_LANTERNS[index][2]][0])
    turns = max(1, round(WIDTH / (math.pi * width)))
    step = round(travel / WIDTH * turns * JACK_ROLL_STEPS) * -JACK_ROLLERS[index] % JACK_ROLL_STEPS
    return index, JACK_ROLLERS[index] * travel, step


def jack_pixels(index: int, roll) -> list[tuple[int, int, str]]:
    """A pumpkin's pixels where it is now, wrapping around the screen's sides while it rolls."""
    cx, cy = jack_center(index)
    step, travel = 0, 0.0
    if roll is not None and roll[0] == index:
        travel, step = roll[1], roll[2]
    anchor_x, anchor_y = math.floor(cx) + math.floor(travel + 0.5), math.floor(cy)
    return [((anchor_x + i) % WIDTH, anchor_y + j, char) for i, j, char in jack_rotations(JACK_O_LANTERNS[index][2])[step] if 0 <= anchor_y + j < HEIGHT]


def candle_glow_mask(cx: float, face_y: float, reach: float) -> np.ndarray:
    # Horizontal distance wraps, so a pumpkin rolling off one side lights the other.
    dx = (FIREWORK_X - cx + WIDTH / 2) % WIDTH - WIDTH / 2
    return np.exp(-(dx**2 + ((FIREWORK_Y - face_y) * 1.4) ** 2) / (2 * reach**2)) * 0.6


def jack_glow(index: int, roll) -> np.ndarray:
    """How strongly a pumpkin's candle lights the pixels around it (zero on the pumpkin itself)."""
    cx, cy = jack_center(index)
    size = JACK_O_LANTERNS[index][2]
    mask = candle_glow_mask(cx + (roll[1] if roll is not None and roll[0] == index else 0), cy, 4.2 if size == "big" else 3.4)
    for x, y, _ in jack_pixels(index, roll):
        mask[y, x] = 0
    return mask


JACK_GLOW = np.stack([jack_glow(index, None) for index in range(len(JACK_O_LANTERNS))])
# Candlelight only reaches the rows from here down.
JACK_GLOW_ROW = int(np.flatnonzero((JACK_GLOW > 0.004).any(axis=(0, 2)))[0])
JACK_GLOW = JACK_GLOW[:, JACK_GLOW_ROW:]


def candle_flicker(index: int, elapsed: float, roll=None) -> float:
    """0..1 candle brightness: a restless flame that now and then gutters."""
    level = 0.82 + 0.1 * math.sin(elapsed * 11.3 + index * 1.9) + 0.08 * math.sin(elapsed * 17.9 + index * 4.3)
    if roll is not None and roll[0] == index:
        level *= JACK_ROLL_FLAME
    return level * 0.55 if unit_hash(index, math.floor(elapsed * 5), 71) < 0.08 else level


def draw_jack_o_lanterns(image: Image.Image, palette: Palette, night: float, elapsed: float, roll):
    d = ImageDraw.Draw(image)
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))

    def lit(color: Color) -> Color:
        return tuple(round(value * illumination) for value in color)

    # A rolling pumpkin passes behind the ones still sitting in their spots.
    order = sorted(range(len(JACK_O_LANTERNS)), key=lambda index: roll is None or roll[0] != index)
    for index in order:
        flame = candle_flicker(index, elapsed, roll)
        # By day the carved face reads dark with a faint candle; after dark it blazes and warms the rind from inside.
        face = mix(PUMPKIN_CARVED, CANDLE_FLAME, flame * (0.2 + 0.8 * night))
        warmth = 0.35 * night * flame
        colors = {"p": mix(lit(PUMPKIN_RIND), CANDLE_GLOW, warmth), "r": mix(lit(PUMPKIN_RIB), CANDLE_GLOW, warmth * 0.6), "s": lit(PUMPKIN_STEM), "e": face, "m": face}
        for x, y, char in jack_pixels(index, roll):
            d.point((x, y), fill=colors[char])


def draw_jack_o_lantern_glow(image: Image.Image, night: float, elapsed: float, roll) -> Image.Image:
    """After dark each candle throws a flickering orange glow onto the ground, the mist and anything passing by."""
    if night <= 0:
        return image
    masks = JACK_GLOW
    if roll is not None:
        masks = masks.copy()
        masks[roll[0]] = jack_glow(roll[0], roll)[JACK_GLOW_ROW:]
    flames = np.array([candle_flicker(index, elapsed, roll) for index in range(len(JACK_O_LANTERNS))], dtype=np.float32)
    light = np.clip(np.tensordot(flames, masks, axes=1) * night, 0, 0.6)
    pixels = np.array(image)
    band = pixels[JACK_GLOW_ROW:].astype(np.float32)
    band += (np.array(CANDLE_GLOW, dtype=np.float32) - band) * light[..., None]
    pixels[JACK_GLOW_ROW:] = np.round(band).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


def halloween_lamp(night: float, elapsed: float, seed: int) -> float:
    hum = 0.84 + 0.09 * math.sin(elapsed * 23.7) + 0.07 * math.sin(elapsed * 37.1 + 1.3)
    stormy = unit_hash(seed, math.floor(elapsed / LAMP_FLICKER_SLOT_SECONDS), 91) < LAMP_FLICKER_CHANCE
    if unit_hash(seed, math.floor(elapsed * LAMP_FLICKER_RATE), 93) < LAMP_DROPOUT_CHANCE[stormy]:
        hum *= LAMP_DROPOUT_LEVEL
    return (LAMP_HALLOWEEN_DAYLIGHT + (1 - LAMP_HALLOWEEN_DAYLIGHT) * night) * hum


@dataclass(frozen=True, eq=False)
class GhostVisit:
    start: float
    arrive: float
    leave: float
    end: float
    swoop_in: tuple[np.ndarray, np.ndarray]
    swoop_out: tuple[np.ndarray, np.ndarray]
    hover: tuple[float, float]
    boo: bool


def ghost_path(points: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
    """A Catmull-Rom curve through the points, sampled as (points, cumulative distance)."""
    padded = [points[0], *points, points[-1]]
    samples = []
    for p0, p1, p2, p3 in zip(padded, padded[1:], padded[2:], padded[3:]):
        for step in range(12):
            t = step / 12
            samples.append(tuple(0.5 * (2 * b + (c - a) * t + (2 * a - 5 * b + 4 * c - d) * t * t + (3 * b - a - 3 * c + d) * t**3) for a, b, c, d in zip(p0, p1, p2, p3)))
    samples.append(points[-1])
    xy = np.array(samples)
    return xy, np.concatenate(([0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))))


@lru_cache(maxsize=8)
def ghost_visit(slot: int, seed: int) -> GhostVisit | None:
    """Swoop in along a looping path, hover (sometimes ending in a boo), then zoom away. Never spans two slots."""
    rng = random.Random(seed * 5167 + slot * 77003 + 41)
    if rng.random() > GHOST_CHANCE:
        return None

    def waypoint():
        return rng.uniform(*GHOST_COLUMNS), rng.uniform(*GHOST_ROWS)

    def edge():
        return rng.choice((-5, WIDTH + 4)), rng.uniform(9, 16)

    hover = (rng.uniform(28, 100), rng.uniform(14, 19))
    swoop_in = ghost_path([edge(), *(waypoint() for _ in range(rng.randint(1, 3))), hover])
    swoop_out = ghost_path([hover, *(waypoint() for _ in range(rng.randint(1, 3))), edge()])
    peak = rng.uniform(*GHOST_PEAK_SPEED)
    hold = rng.uniform(*GHOST_HOVER_SECONDS)
    # An eased swoop peaks at twice its average speed.
    fly_in, fly_out = 2 * float(swoop_in[1][-1]) / peak, 2 * float(swoop_out[1][-1]) / peak
    room = GHOST_SLOT_SECONDS - 1 - hold
    if fly_in + fly_out > room:
        fly_in, fly_out = fly_in * room / (fly_in + fly_out), fly_out * room / (fly_in + fly_out)
    start = slot * GHOST_SLOT_SECONDS + rng.uniform(0, room - fly_in - fly_out)
    return GhostVisit(start, start + fly_in, start + fly_in + hold, start + fly_in + hold + fly_out, swoop_in, swoop_out, hover, rng.random() < 0.5)


def ghost_along(path: tuple[np.ndarray, np.ndarray], progress: float) -> tuple[float, float]:
    xy, distance = path
    s = distance[-1] * (progress - math.sin(math.tau * progress) / math.tau)
    return float(np.interp(s, distance, xy[:, 0])), float(np.interp(s, distance, xy[:, 1]))


def ghost_state(elapsed: float, seed: int):
    """Return (x, y, facing, pose, speed) or None while no ghost is about."""
    visit = ghost_visit(math.floor(elapsed / GHOST_SLOT_SECONDS), seed)
    if visit is None or not visit.start <= elapsed < visit.end:
        return None
    if visit.arrive <= elapsed < visit.leave:
        held = elapsed - visit.arrive
        x, y = visit.hover[0] + 0.8 * math.sin(held * 2.1), visit.hover[1] + 1.2 * math.sin(held * 2.9)
        if visit.boo and elapsed >= visit.leave - GHOST_BOO_SECONDS:
            # Boo! It rears up and shudders.
            return x + (1 if math.sin(held * 45) > 0 else 0), y - 1, 1, "boo", 0.0
        return x, y, 1, "hover", 0.0
    path, first, last = (visit.swoop_in, visit.start, visit.arrive) if elapsed < visit.arrive else (visit.swoop_out, visit.leave, visit.end)
    x, y = ghost_along(path, (elapsed - first) / (last - first))
    px, py = ghost_along(path, max(0.0, (elapsed - 0.02 - first) / (last - first)))
    speed = math.hypot(x - px, y - py) / 0.02
    return x, y, 1 if x >= px else -1, "fly" if speed > 12 else "hover", speed


@lru_cache(maxsize=16)
def ghost_pixels(pose: str, frame: int, facing: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Offsets from the anchor of the sheet, the eyes and mouth, and the 1 px halo around the sprite."""
    rows = (*GHOST_BODIES[pose], GHOST_TAILS[pose][frame])
    cells = {((column - 3) * facing, row - 3): char for row, line in enumerate(rows) for column, char in enumerate(line) if char != "."}
    halo = {(x + dx, y + dy) for x, y in cells for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))} - cells.keys()
    return tuple(np.array(sorted(points), dtype=int).reshape(-1, 2) for points in ([p for p, c in cells.items() if c == "w"], [p for p, c in cells.items() if c == "k"], halo))


GHOST_TRAIL_COLOR = mix(GHOST_WHITE, GHOST_GLOW, 0.5)


def draw_ghost(image: Image.Image, night: float, elapsed: float, seed: int):
    ghost = ghost_state(elapsed, seed)
    if ghost is None:
        return
    x, y, facing, pose, speed = ghost
    frame = math.floor(elapsed * 6) % 2
    groups = []
    if pose == "fly":
        # Afterimages smear out behind it while it zooms.
        for back in range(GHOST_TRAIL, 0, -1):
            past = ghost_state(elapsed - back * GHOST_TRAIL_SPACING, seed)
            if past is not None:
                fade = 0.38 * (1 - back / (GHOST_TRAIL + 1)) * min(1, speed / 60)
                groups.append((ghost_pixels(past[3], frame, past[2])[0] + (round(past[0]), round(past[1])), GHOST_TRAIL_COLOR, fade))
    sheet, eyes, halo = (offsets + (round(x), round(y)) for offsets in ghost_pixels(pose, frame, facing))
    if night > 0:
        groups.append((halo, GHOST_GLOW, 0.3 * night))
    groups += [(sheet, GHOST_WHITE, GHOST_OPACITY), (eyes, GHOST_EYES, 0.95)]
    paste_overlay(image, groups)


@dataclass(frozen=True)
class ShadowVisit:
    start: float
    leave: float
    settle: float
    end: float
    origin: tuple[int, int]
    target: tuple[int, int]
    looks: tuple[tuple[float, float], ...]


@lru_cache(maxsize=8)
def shadow_visit(slot: int, seed: int) -> ShadowVisit | None:
    """Fade in at a lurking spot, maybe glide to a neighbouring one, look back now and then, fade away. Never spans two slots."""
    rng = random.Random(seed * 8231 + slot * 91873 + 59)
    if rng.random() > SHADOW_CHANCE:
        return None
    index = rng.randrange(len(SHADOW_SPOTS))
    glides = SHADOW_GLIDES.get(index, ())
    target_index = rng.choice(glides) if glides and rng.random() < 0.6 else index
    origin, target = SHADOW_SPOTS[index], SHADOW_SPOTS[target_index]
    first = rng.uniform(6, 12)
    glide = abs(target[0] - origin[0]) / SHADOW_GLIDE_SPEED
    second = rng.uniform(5, 10) if target_index != index else 0
    total = SHADOW_FADE_SECONDS * 2 + first + glide + second
    start = slot * SHADOW_SLOT_SECONDS + rng.uniform(0.5, SHADOW_SLOT_SECONDS - total - 0.5)
    leave = start + SHADOW_FADE_SECONDS + first
    settle = leave + glide
    looks = []
    # It only looks back while standing still and fully there.
    for begin, length in ((start + SHADOW_FADE_SECONDS, first), (settle, second)):
        if length > 4 and (not looks or rng.random() < 0.6):
            look = rng.uniform(*SHADOW_LOOK_SECONDS)
            at = begin + rng.uniform(0.8, length - look - 0.8)
            looks.append((at, at + look))
    return ShadowVisit(start, leave, settle, start + total, origin, target, tuple(looks))


def shadow_state(elapsed: float, seed: int):
    """Return (x, feet row, opacity, eye level 0..1) or None while nothing lurks."""
    visit = shadow_visit(math.floor(elapsed / SHADOW_SLOT_SECONDS), seed)
    if visit is None or not visit.start <= elapsed < visit.end:
        return None
    opacity = min(1.0, (elapsed - visit.start) / SHADOW_FADE_SECONDS, (visit.end - elapsed) / SHADOW_FADE_SECONDS)
    progress = 0.0 if elapsed < visit.leave else 1.0 if elapsed >= visit.settle else (elapsed - visit.leave) / (visit.settle - visit.leave)
    progress = progress * progress * (3 - 2 * progress)
    x = visit.origin[0] + (visit.target[0] - visit.origin[0]) * progress
    y = visit.origin[1] + (visit.target[1] - visit.origin[1]) * progress
    eyes = max((min(1.0, (elapsed - first) / SHADOW_EYE_FADE_SECONDS, (last - elapsed) / SHADOW_EYE_FADE_SECONDS) for first, last in visit.looks if first <= elapsed < last), default=0.0)
    return x, y, opacity, eyes


@lru_cache(maxsize=4)
def shadow_pixels(pose: str, frame: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Offsets from the feet of the body, the hem and the eyes."""
    rows = (*SHADOW_BODIES[pose], SHADOW_HEMS[frame])
    cells = {(column - 2, row - len(rows) + 1): char for row, line in enumerate(rows) for column, char in enumerate(line) if char != "."}
    hem = {point for point in cells if point[1] == 0}
    return tuple(np.array(sorted(points), dtype=int).reshape(-1, 2) for points in ([p for p, c in cells.items() if c == "s" and p not in hem], sorted(hem), [p for p, c in cells.items() if c == "r"]))


def draw_shadow_figure(image: Image.Image, shadow, elapsed: float):
    """The figure itself, among the scenery; its eyes are drawn later so no light tints them."""
    if shadow is None:
        return
    x, y, opacity, eyes = shadow
    body, hem, _ = shadow_pixels("toward" if eyes > 0 else "away", math.floor(elapsed * 3) % 2)
    feet = (round(x), round(y))
    paste_overlay(image, [(body + feet, SHADOW_COLOR, SHADOW_OPACITY * opacity), (hem + feet, SHADOW_COLOR, SHADOW_HEM_OPACITY * opacity)])


def draw_shadow_eyes(image: Image.Image, shadow, night: float, elapsed: float):
    if shadow is None or shadow[3] <= 0:
        return
    x, y, _, eyes = shadow
    pupils = shadow_pixels("toward", math.floor(elapsed * 3) % 2)[2] + (round(x), round(y))
    glow = np.array(sorted({(px + dx, py + dy) for px, py in pupils.tolist() for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))} - set(map(tuple, pupils.tolist()))), dtype=int).reshape(-1, 2)
    # A slow, menacing pulse.
    pulse = 0.85 + 0.15 * math.sin(elapsed * 5)
    paste_overlay(image, [(glow, SHADOW_EYES, 0.35 * eyes * (0.4 + 0.6 * night) * pulse), (pupils, SHADOW_EYES, eyes * pulse)])


@dataclass(frozen=True)
class SpiderVisit:
    start: float
    landed: float
    climb: float
    end: float
    x: int
    rest: float
    lunge: float


@lru_cache(maxsize=8)
def spider_visit(slot: int, seed: int) -> SpiderVisit | None:
    """Drop on a silk line, bounce, dangle and twitch, lunge once, then climb back out. Never spans two slots."""
    rng = random.Random(seed * 2903 + slot * 31337 + 53)
    if rng.random() > SPIDER_CHANCE:
        return None
    x, rest, hang = rng.randint(*SPIDER_COLUMNS), rng.uniform(*SPIDER_REST_ROWS), rng.uniform(*SPIDER_HANG_SECONDS)
    climb_seconds = (rest + SPIDER_HEIGHT) / SPIDER_CLIMB_SPEED
    start = slot * SPIDER_SLOT_SECONDS + rng.uniform(1, SPIDER_SLOT_SECONDS - SPIDER_DROP_SECONDS - hang - climb_seconds - 1)
    landed = start + SPIDER_DROP_SECONDS
    return SpiderVisit(start, landed, landed + hang, landed + hang + climb_seconds, x, rest, landed + rng.uniform(3, hang - 2))


def spider_state(elapsed: float, seed: int):
    """Return (silk column, x, abdomen top row, pose) or None while the spider is away."""
    visit = spider_visit(math.floor(elapsed / SPIDER_SLOT_SECONDS), seed)
    if visit is None or not visit.start <= elapsed < visit.end:
        return None
    if elapsed < visit.landed:
        progress = (elapsed - visit.start) / SPIDER_DROP_SECONDS
        return visit.x, visit.x, -SPIDER_HEIGHT + (visit.rest + SPIDER_HEIGHT) * progress * progress, "flex"
    if elapsed >= visit.climb:
        return visit.x, visit.x, visit.rest - (elapsed - visit.climb) * SPIDER_CLIMB_SPEED, ("climb", "spread")[math.floor(elapsed * 6) % 2]
    since = elapsed - visit.landed
    # The silk stretches and recoils after the drop; then the spider sways and breathes on it.
    y = visit.rest + 2.5 * math.exp(-since / 0.45) * math.sin(since * 11) + 0.5 * math.sin(since * 0.9)
    x = visit.x + 0.7 * math.sin(since * 0.55)
    lunge = elapsed - visit.lunge
    if 0 <= lunge < SPIDER_LUNGE_SECONDS:
        y += SPIDER_LUNGE_DEPTH * (lunge / 0.12 if lunge < 0.12 else 1 - (lunge - 0.12) / (SPIDER_LUNGE_SECONDS - 0.12))
        return visit.x, x, y, "spread"
    twitching = unit_hash(seed, math.floor(elapsed * 3), 7) < 0.3
    return visit.x, x, y, "flex" if twitching and math.floor(elapsed * 10) % 2 else "spread"


def cobweb_geometry() -> dict[str, np.ndarray]:
    """Pixels of the radials, the ring and the guy lines; each pixel belongs to its most visible thread."""
    hx, hy = COBWEB_HUB

    def along(end: tuple[int, int], radius: float) -> tuple[int, int]:
        reach = math.hypot(end[0] - hx, end[1] - hy)
        return round(hx + (end[0] - hx) * radius / reach), round(hy + (end[1] - hy) * radius / reach)

    ring = [along(end, COBWEB_RING) for end in COBWEB_RADIALS]
    threads = {
        "radial": [COBWEB_HUB, *(pixel for end in COBWEB_RADIALS for pixel in trace([along(end, COBWEB_FREE_ZONE), end]))],
        "ring": trace([*ring, ring[0]]),
        "guy": [pixel for guy in COBWEB_GUYS for pixel in trace(list(guy))],
    }
    taken: set[tuple[int, int]] = set()
    geometry = {}
    for name, pixels in threads.items():
        unique = [pixel for pixel in dict.fromkeys(pixels) if pixel not in taken]
        taken.update(unique)
        geometry[name] = np.array(unique, dtype=int).reshape(-1, 2)
    return geometry


COBWEB = cobweb_geometry()
COBWEB_SPIDER_AT = (COBWEB_HUB[0] + 2, COBWEB_HUB[1] + 3)
COBWEB_SPIDER_PIXELS = tuple(
    (np.array([(column - 1 + COBWEB_SPIDER_AT[0], row - 1 + COBWEB_SPIDER_AT[1]) for row, line in enumerate(COBWEB_SPIDER) for column, c in enumerate(line) if c == char], dtype=int).reshape(-1, 2), SPIDER_COLORS[char])
    for char in "lb"
)


def draw_cobweb(image: Image.Image, night: float, elapsed: float, seed: int):
    """The web catches the light by day and fades a little after dark; dew drops glint on the ring."""
    fade = 1 - COBWEB_NIGHT_FADE * night
    groups = [(COBWEB[name], COBWEB_SILK, opacity * fade) for name, opacity in COBWEB_OPACITY.items()]
    ring = COBWEB["ring"]
    for drop in range(COBWEB_DEW_DROPS):
        # Each drop twinkles briefly at a fixed spot, at its own pace.
        cycle, moment = divmod(elapsed + drop * 1.3, 2.6 + drop * 0.4)
        if moment < 0.5:
            index = int(unit_hash(seed, drop, int(cycle), 97) * len(ring))
            groups.append((ring[index : index + 1], COBWEB_DEW, 0.9 * math.sin(math.pi * moment / 0.5) * fade))
    groups += [(pixels, color, 1.0) for pixels, color in COBWEB_SPIDER_PIXELS]
    paste_overlay(image, groups)


@lru_cache(maxsize=len(SPIDER_SPRITES))
def spider_pixels(pose: str) -> tuple[tuple[np.ndarray, Color], ...]:
    """Offsets from the silk's attachment point per color, then the eye glow around the eyes, off the sprite."""
    rows = SPIDER_SPRITES[pose]
    cells = {(column - 7, row): char for row, line in enumerate(rows) for column, char in enumerate(line) if char != "."}
    eyes = [point for point, char in cells.items() if char == "r"]
    glow = {(x + dx, y + dy) for x, y in eyes for dx, dy in ((-1, 0), (1, 0), (0, 1))} - cells.keys()
    parts = tuple((np.array(sorted(p for p, c in cells.items() if c == char), dtype=int).reshape(-1, 2), color) for char, color in SPIDER_COLORS.items())
    return (*parts, (np.array(sorted(glow), dtype=int).reshape(-1, 2), SPIDER_COLORS["r"]))


def draw_spider(image: Image.Image, night: float, elapsed: float, seed: int):
    spider = spider_state(elapsed, seed)
    if spider is None:
        return
    silk, x, y, pose = spider
    anchor = (round(x), round(y))
    groups = []
    if anchor[1] > 0:
        groups.append((np.array(trace([(silk, 0), (anchor[0], anchor[1] - 1)]), dtype=int).reshape(-1, 2), SPIDER_SILK, 0.45))
    *parts, (glow, red) = spider_pixels(pose)
    groups += [(offsets + anchor, color, 1.0) for offsets, color in parts]
    if night > 0:
        # Its eyes glow red in the dark.
        groups.append((glow + anchor, red, 0.3 * night))
    paste_overlay(image, groups)


THANKSGIVING = "thanksgiving"
# A harvest display stands in the meadow between the pond and the maple, where Halloween's pumpkins sit:
# (sprite, left column, bottom row), back to front. A corn shock (c tassels, s/S stalks striped by column, t/T twine),
# a straw bale (H top, B straw, w twine) carrying a pumpkin and a lantern (m frame, L glass), and a big pumpkin
# (p rind, o ribs, g stem).
HARVEST_DISPLAY = (
    (("..c...c..", "c..c.c..c", ".c.cSc.c.", "..cSsSc..", "...sSs...", "...tTt...", "...SsS...", "..sSsSs..", "..sSsSs..", ".SsSsSsS.", ".SsSsSsS.", "sSsSsSsSs"), 82, 30),
    (("HHHHHHHHH", "BBwBBBwBB", "BBwBBBwBB", "BBwBBBwBB"), 91, 31),
    (("..g..", ".pop.", "popop", ".ppp."), 92, 27),
    ((".m.", "mLm", "mLm", "mmm"), 97, 27),
    (("...g...", ".poppo.", "popopop", "popopop", ".ppppp."), 101, 31),
)
HARVEST_COLORS = {
    "c": (232, 206, 128), "s": (196, 160, 86), "S": (142, 110, 58), "t": (120, 70, 40), "T": (90, 52, 30),
    "H": (230, 196, 110), "B": (192, 150, 70), "w": (140, 100, 50),
    "p": PUMPKIN_RIND, "o": PUMPKIN_RIB, "g": PUMPKIN_STEM, "m": (52, 46, 44),
}
# The lantern's glass by day, before the candle inside outshines it after dark.
LANTERN_DAY_GLASS = (150, 128, 84)
# Lantern candles flicker with the jack-o'-lantern flame model under this candle index.
LANTERN_CANDLE = 0
LANTERN_GLOW_REACH = 5.0


def harvest_pixels() -> tuple[tuple[str, np.ndarray], ...]:
    cells: dict[tuple[int, int], str] = {}
    for rows, left, bottom in HARVEST_DISPLAY:
        for row, line in enumerate(rows):
            for column, char in enumerate(line):
                if char != ".":
                    cells[left + column, bottom - len(rows) + 1 + row] = char
    return tuple((char, np.array(sorted(point for point, c in cells.items() if c == char), dtype=int).reshape(-1, 2)) for char in dict.fromkeys(cells.values()))


HARVEST_PIXELS = harvest_pixels()
LANTERN_GLASS = next(points for char, points in HARVEST_PIXELS if char == "L")


def lantern_glow() -> tuple[int, np.ndarray]:
    """(first row, mask) of how strongly the lantern's candle lights the pixels around it, leaving the glass itself."""
    cx, cy = LANTERN_GLASS.mean(axis=0)
    mask = candle_glow_mask(float(cx), float(cy), LANTERN_GLOW_REACH)
    mask[LANTERN_GLASS[:, 1], LANTERN_GLASS[:, 0]] = 0
    top = int(np.flatnonzero((mask > 0.004).any(axis=1))[0])
    return top, mask[top:]


LANTERN_GLOW_ROW, LANTERN_GLOW = lantern_glow()


def draw_harvest_display(image: Image.Image, palette: Palette, night: float, elapsed: float):
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    flame = candle_flicker(LANTERN_CANDLE, elapsed)
    groups = []
    for char, points in HARVEST_PIXELS:
        if char == "L":
            color = mix(tuple(round(value * illumination) for value in LANTERN_DAY_GLASS), CANDLE_FLAME, flame * (0.25 + 0.75 * night))
        else:
            color = tuple(round(value * illumination) for value in HARVEST_COLORS[char])
        groups.append((points, color, 1.0))
    paste_overlay(image, groups)


def draw_lantern_glow(image: Image.Image, night: float, elapsed: float) -> Image.Image:
    """After dark the lantern throws a flickering warm pool over the bale, the pumpkins and anything passing by."""
    if night <= 0:
        return image
    light = LANTERN_GLOW * (candle_flicker(LANTERN_CANDLE, elapsed) * night)
    pixels = np.array(image)
    band = pixels[LANTERN_GLOW_ROW:].astype(np.float32)
    band += (np.array(CANDLE_GLOW, dtype=np.float32) - band) * light[..., None]
    pixels[LANTERN_GLOW_ROW:] = np.round(band).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


# On Thanksgiving a tom turkey has the run of the meadow all day and night, and by day small flocks of hens wander
# through. Together they take the place of the deer, foxes and rabbits.
TURKEY_SPEED = 4.5
TURKEY_FEET_ROWS = (29, 31)
TURKEY_STRUT_SECONDS = (6, 12)
# While foraging, each bird picks what to do next every TURKEY_BEHAVIOR_SECONDS.
TURKEY_BEHAVIOR_SECONDS = 1.3
TURKEY_PECK_CHANCE = 0.55
TURKEY_TURN_CHANCE = 0.2
TURKEY_PECK_RATE = 3
# A strutting tom gobbles every TURKEY_GOBBLE_PERIOD seconds.
TURKEY_GOBBLE_PERIOD = 2.8
TURKEY_GOBBLE_SECONDS = 0.5
# The tom plans one slot at a time. Each slot starts and ends at a spot drawn from that slot alone, so any moment
# is a pure function of `elapsed` without replaying earlier slots.
TOM_SLOT_SECONDS = 60
TOM_COLUMNS = (42, 122)
# New activities stop starting this long before the slot ends, leaving time for the longest one plus the trip to the
# next slot's spot.
TOM_RESERVE_SECONDS = 26
# Chances of each activity when he picks the next one; the rest are short wanders.
TOM_ZOOMIES_CHANCE = 0.4
TOM_STRUT_CHANCE = 0.2
TOM_FORAGE_CHANCE = 0.25
TOM_FORAGE_SECONDS = (3, 8)
TOM_WANDER = (8, 25)
# Zoomies: a few zigzag dashes, wings flapping, then a moment to catch his breath.
TOM_RUN_SPEED = (26, 36)
TOM_RUN_LEGS = (2, 4)
TOM_RUN_DASH = (18, 45)
TOM_RUN_STRIDE = 2.5
TOM_RUN_REST = (0.6, 1.5)
# By day small flocks of hens wander through, entering on one side and leaving on the other.
TURKEY_SLOT_SECONDS = 150
TURKEY_VISIT_CHANCE = 0.7
# The lead hen stops to forage in the open meadow in front of the pond, clear of the pilgrims and the harvest display.
TURKEY_STOP_COLUMNS = (44, 62)
TURKEY_FORAGE_SECONDS = (8, 16)
# Each hen trails the one ahead by this many pixels and seconds, so the flock bunches up and strings out as it goes.
TURKEY_GAP = (7, 11)
TURKEY_LAG = (0.8, 2.0)
TURKEY_HENS = (2, 4)
# Facing right and standing on the bottom row: b body, i bronze sheen, t tail, h bare head, k beak, r wattle, l legs,
# W barred wing feathers. The tom faces the viewer to strut, his fan spread behind him: k buff tips, d dark band,
# T chestnut feathers.
TURKEY_SPRITES = {
    "tom": {
        "stand": (".....h..", ".....hk.", ".....r..", "..bbbr..", "tbbibbb.", "tbibibb.", ".bbbbb..", "..l..l.."),
        "step": (".....h..", ".....hk.", ".....r..", "..bbbr..", "tbbibbb.", "tbibibb.", ".bbbbb..", "...ll..."),
        "peck": ("........", "........", "........", "..bbb...", "tbbibbr.", "tbibibbr", ".bbbbb.h", "..l..l.k"),
        "strut": ("...kkkkkkk...", ".kkTTTTTTTkk.", "kTTdddddddTTk", "kTdTTThTTTdTk", "kTdTbbhbbTdTk", ".kdbbbrbbbdk.", "...bbbrbbb...", "....bbbbb....", "....l...l...."),
        "gobble": ("...kkkkkkk...", ".kkTTTTTTTkk.", "kTTdddhdddTTk", "kTdTTThTTTdTk", "kTdTbbrbbTdTk", ".kdbbbrbbbdk.", "...bbbrbbb...", "....bbbbb....", "....l...l...."),
        # Running flat out with his neck stretched forward, wings beating up and down.
        "run_up": ("..W.W...", "..WiW...", "...ii.hk", "tbbbbbh.", "tbibibr.", ".bbbbb..", "l....l.."),
        "run_down": ("........", "........", "......hk", "tbbbbbh.", "tWiWibr.", "WiWbbb..", "..ll...."),
    },
    "hen": {
        "stand": ("....h..", "....hk.", "...bb..", "tbbbb..", "tbibbb.", ".bbbb..", "..l.l.."),
        "step": ("....h..", "....hk.", "...bb..", "tbbbb..", "tbibbb.", ".bbbb..", "...ll.."),
        "peck": (".......", ".......", ".......", "tbbbb..", "tbibbb.", ".bbbbbh", "..l.l.k"),
    },
}
TURKEY_COLORS = {
    "tom": {"b": (56, 44, 38), "i": (118, 98, 64), "t": (110, 76, 50), "h": (176, 204, 232), "k": (226, 196, 140), "r": (222, 36, 36), "l": (214, 120, 84), "d": (40, 30, 26), "T": (150, 100, 60), "W": (196, 186, 166)},
    "hen": {"b": (98, 74, 52), "i": (140, 112, 74), "t": (110, 80, 54), "h": (150, 170, 190), "k": (210, 186, 140), "r": (170, 80, 80), "l": (200, 120, 90)},
}
# The wattle flushes bright while he gobbles.
TURKEY_GOBBLE_WATTLE = (255, 40, 52)


@dataclass(frozen=True)
class TomStep:
    start: float
    end: float
    # "walk", "run", "forage", "strut" or "stand".
    action: str
    origin: tuple[float, float]
    target: tuple[float, float]
    facing: int


def tom_spot(slot: int, seed: int) -> tuple[float, int]:
    """Where the tom is (x, feet row) as slot `slot` begins."""
    rng = random.Random(seed * 8513 + slot * 27277 + 61)
    return rng.uniform(*TOM_COLUMNS), rng.randint(*TURKEY_FEET_ROWS)


@lru_cache(maxsize=8)
def tom_plan(slot: int, seed: int) -> tuple[TomStep, ...]:
    """The tom's steps from this slot's spot to the next one's, covering the whole slot."""
    rng = random.Random(seed * 4691 + slot * 39119 + 53)
    t = slot * TOM_SLOT_SECONDS
    end = t + TOM_SLOT_SECONDS
    position: tuple[float, float] = tom_spot(slot, seed)
    facing = rng.choice((-1, 1))
    steps: list[TomStep] = []

    def hold(action: str, seconds: float):
        nonlocal t
        steps.append(TomStep(t, t + seconds, action, position, position, facing))
        t += seconds

    def move(target: tuple[float, float], speed: float, action: str):
        nonlocal t, position, facing
        if target[0] != position[0]:
            facing = 1 if target[0] > position[0] else -1
        seconds = max(0.1, math.dist(position, target) / speed)
        steps.append(TomStep(t, t + seconds, action, position, target, facing))
        t += seconds
        position = target

    def toward(reach: tuple[float, float], direction: int) -> tuple[float, int]:
        x = position[0] + direction * rng.uniform(*reach)
        if not TOM_COLUMNS[0] <= x <= TOM_COLUMNS[1]:
            x = position[0] - direction * rng.uniform(*reach)
        return max(TOM_COLUMNS[0], min(TOM_COLUMNS[1], x)), rng.randint(*TURKEY_FEET_ROWS)

    while t < end - TOM_RESERVE_SECONDS:
        roll = rng.random()
        if roll < TOM_ZOOMIES_CHANCE:
            direction = rng.choice((-1, 1))
            for _ in range(rng.randint(*TOM_RUN_LEGS)):
                move(toward(TOM_RUN_DASH, direction), rng.uniform(*TOM_RUN_SPEED), "run")
                direction = -facing
            hold("stand", rng.uniform(*TOM_RUN_REST))
        elif roll < TOM_ZOOMIES_CHANCE + TOM_STRUT_CHANCE:
            hold("strut", rng.uniform(*TURKEY_STRUT_SECONDS))
        elif roll < TOM_ZOOMIES_CHANCE + TOM_STRUT_CHANCE + TOM_FORAGE_CHANCE:
            hold("forage", rng.uniform(*TOM_FORAGE_SECONDS))
        else:
            move(toward(TOM_WANDER, rng.choice((-1, 1))), TURKEY_SPEED, "walk")
    # Make for the next slot's spot, hurrying if time is short, and forage there until the slot ends.
    target = tom_spot(slot + 1, seed)
    speed = max(TURKEY_SPEED, math.dist(position, target) / (end - t - 0.5))
    move(target, speed, "run" if speed > 3 * TURKEY_SPEED else "walk")
    hold("forage", end - t)
    return tuple(steps)


def tom_state(elapsed: float, seed: int) -> tuple[float, int, int, int, str]:
    """(x, feet row, rows lifted off the ground, facing, pose) of the resident tom."""
    slot = math.floor(elapsed / TOM_SLOT_SECONDS)
    plan = tom_plan(slot, seed)
    step = next((step for step in plan if elapsed < step.end), plan[-1])
    progress = max(0.0, min(1.0, (elapsed - step.start) / (step.end - step.start)))
    x = step.origin[0] + (step.target[0] - step.origin[0]) * progress
    feet = round(step.origin[1] + (step.target[1] - step.origin[1]) * progress)
    travelled = math.dist(step.origin, step.target) * progress
    if step.action == "run":
        # He bounds along, lifting off the ground on every upstroke.
        up = int(travelled / TOM_RUN_STRIDE) % 2 == 0
        return x, feet, int(up), step.facing, "run_up" if up else "run_down"
    if step.action == "walk":
        return x, feet, 0, step.facing, "step" if int(travelled / 2) % 2 else "stand"
    held = elapsed - step.start
    if step.action == "strut":
        return x, feet, 0, step.facing, "gobble" if held % TURKEY_GOBBLE_PERIOD > TURKEY_GOBBLE_PERIOD - TURKEY_GOBBLE_SECONDS else "strut"
    if step.action == "forage":
        beat = math.floor(elapsed / TURKEY_BEHAVIOR_SECONDS)
        facing = -step.facing if unit_hash(seed, beat, 9) < TURKEY_TURN_CHANCE else step.facing
        pecking = unit_hash(seed, beat, 11) < TURKEY_PECK_CHANCE and elapsed * TURKEY_PECK_RATE % 1 < 0.5
        return x, feet, 0, facing, "peck" if pecking else "stand"
    return x, feet, 0, step.facing, "stand"


@dataclass(frozen=True)
class TurkeyVisit:
    slot: int
    start: float
    end: float
    heading: int
    # The lead hen's walk: (start, end, from x, to x); a leg that stays put is a stop to forage.
    legs: tuple[tuple[float, float, float, float], ...]
    # (gap behind the leader in px, lag behind the leader in seconds, feet row), leader first.
    hens: tuple[tuple[float, float, int], ...]


@lru_cache(maxsize=8)
def turkey_visit(slot: int, seed: int) -> TurkeyVisit | None:
    """The hens wander in from one side, forage at two spots, then wander off the other side. Never spans two slots."""
    rng = random.Random(seed * 3571 + slot * 51787 + 23)
    if rng.random() > TURKEY_VISIT_CHANCE:
        return None
    heading = rng.choice((-1, 1))
    hens, gap, lag = [], 0.0, 0.0
    for index in range(rng.randint(*TURKEY_HENS)):
        if index:
            gap, lag = gap + rng.uniform(*TURKEY_GAP), lag + rng.uniform(*TURKEY_LAG)
        hens.append((gap, lag, rng.randint(*TURKEY_FEET_ROWS)))
    margin = 8
    entry = -margin if heading > 0 else WIDTH + margin
    exit_x = WIDTH + margin + gap if heading > 0 else -margin - gap
    stops = sorted((rng.uniform(*TURKEY_STOP_COLUMNS), rng.uniform(*TURKEY_STOP_COLUMNS)), reverse=heading < 0)
    plan, t, x = [], 0.0, float(entry)
    for stop in stops:
        plan.append((t, t + abs(stop - x) / TURKEY_SPEED, x, stop))
        t, x = plan[-1][1], stop
        hold = rng.uniform(*TURKEY_FORAGE_SECONDS)
        plan.append((t, t + hold, x, x))
        t += hold
    plan.append((t, t + abs(exit_x - x) / TURKEY_SPEED, x, exit_x))
    duration = plan[-1][1] + lag
    start = slot * TURKEY_SLOT_SECONDS + rng.uniform(1, TURKEY_SLOT_SECONDS - duration - 1)
    legs = tuple((start + a, start + b, x0, x1) for a, b, x0, x1 in plan)
    return TurkeyVisit(slot, start, start + duration, heading, legs, tuple(hens))


def turkeys_allowed(environment: "OutsideEnvironment") -> bool:
    """Hens visit in daylight on Thanksgiving, in anything short of a downpour or heavy snow."""
    rain, snow = precipitation(environment)
    return THANKSGIVING in holiday_features(environment) and environment.sun_altitude is not None and environment.sun_altitude > SET_ALTITUDE and rain < 3 and snow < 2


def turkey_state(environment: "OutsideEnvironment", elapsed: float, seed: int) -> TurkeyVisit | None:
    """The hens' visit under way, if any. Like the deer, they keep clear of the dog's outings and of the eagle."""
    if not turkeys_allowed(environment):
        return None
    visit = turkey_visit(math.floor(elapsed / TURKEY_SLOT_SECONDS), seed)
    if visit is None or not visit.start <= elapsed < visit.end:
        return None
    if dog_allowed(environment) and next(dog_outings_between(seed, visit.start, visit.end), None) is not None:
        return None
    if next(eagle_visits_present(environment, seed, visit.start, visit.end), None) is not None:
        return None
    return visit


def turkey_pose(visit: TurkeyVisit, index: int, elapsed: float, seed: int) -> tuple[float, int, int, str]:
    """(x, feet row, facing, pose) of one hen in the flock."""
    gap, lag, feet = visit.hens[index]
    t = elapsed - lag
    leg = next((leg for leg in visit.legs if t < leg[1]), visit.legs[-1])
    start, end, x0, x1 = leg
    progress = max(0.0, min(1.0, (t - start) / (end - start)))
    x = x0 + (x1 - x0) * progress - visit.heading * gap
    if x0 != x1 or t < visit.legs[0][0]:
        # Strides alternate every couple of pixels walked.
        return x, feet, visit.heading, "step" if int(abs(x - visit.legs[0][2]) / 2) % 2 else "stand"
    beat = math.floor(t / TURKEY_BEHAVIOR_SECONDS)
    facing = -visit.heading if unit_hash(seed, visit.slot, index, beat, 5) < TURKEY_TURN_CHANCE else visit.heading
    if unit_hash(seed, visit.slot, index, beat, 3) < TURKEY_PECK_CHANCE and t * TURKEY_PECK_RATE % 1 < 0.5:
        return x, feet, facing, "peck"
    return x, feet, facing, "stand"


def draw_standing_sprite(d: ImageDraw.ImageDraw, rows: tuple[str, ...], x: float, feet: int, facing: int, colors: dict[str, Color]):
    """Draw a right-facing sprite (mirrored when facing left) centered on column `x`, its bottom row on row `feet`."""
    width = len(rows[0])
    left = round(x) - (width - 1) // 2
    for row, line in enumerate(rows):
        for column, char in enumerate(line):
            if char == ".":
                continue
            px = left + (column if facing > 0 else width - 1 - column)
            py = feet - len(rows) + 1 + row
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                d.point((px, py), fill=colors[char])


# A pilgrim couple stands at the pond's near shore beside the harvest display. They are nearest the viewer, so they
# stand a little taller than the hut.
# Facing the viewer: K black hat and shoes, G gold buckles, H hair, S skin, E eyes, W white linen (collar, cuffs,
# coif, apron, stockings), C coat, B breeches, D dress. Each pose keeps its columns, so a gesture never shifts the body.
PILGRIM_SPRITES = {
    "man": {
        "stand": ("..KKK...", "..KGK...", "KKKKKKK.", "..ESE...", "..SSS...", ".WWWWW..", "CCWWWCC.", "CCCCCCC.", "CCCGCCC.", "WCCCCCW.", "SBBBBBS.", ".BB.BB..", ".WW.WW..", "KKK.KKK."),
        # Lifting his hat off his head with his left hand (on the viewer's right).
        "tip": ("..KKK...", "..KGK...", "KKKKKKK.", "..HHHSW.", "..ESE.C.", "..SSS.C.", ".WWWWWC.", "CCWWWCC.", "CCCCCC..", "CCCGCC..", "WCCCCC..", "SBBBBB..", ".BB.BB..", ".WW.WW..", "KKK.KKK."),
    },
    "woman": {
        "stand": ("..WWW...", ".WWWWW..", ".WESEW..", ".WSSSW..", ".WWWWW..", "DDWWWDD.", "DDDDDDD.", "WDWWWDW.", "SDWWWDS.", ".DWWWD..", "DDWWWDD.", "DDDDDDD.", ".K...K.."),
        # Waving her left hand (on the viewer's right) above her shoulder.
        "wave": ("..WWW..S", ".WWWWW.W", ".WESEW.D", ".WSSSWD.", ".WWWWWD.", "DDWWWDD.", "DDDDDDD.", "WDWWWD..", "SDWWWD..", ".DWWWD..", "DDWWWDD.", "DDDDDDD.", ".K...K.."),
    },
}
PILGRIM_COLORS = {"K": (26, 24, 30), "G": (236, 190, 64), "H": (110, 70, 40), "S": (232, 182, 140), "E": (54, 36, 30), "W": (236, 234, 222), "C": (40, 38, 46), "B": (34, 32, 38), "D": (70, 62, 66)}
# (kind, center column, feet row): the man just in front of his wife, beside the corn shock.
PILGRIMS = (("woman", 78, 30), ("man", 70, 31))
# Every PILGRIM_GESTURE_SECONDS each pilgrim may tip his hat or wave for part of the slot.
PILGRIM_GESTURE_SECONDS = 6.0
PILGRIM_GESTURE_CHANCE = 0.35
PILGRIM_GESTURE_LENGTH = (1.2, 2.2)


def pilgrims_out(environment: "OutsideEnvironment") -> bool:
    """Out on Thanksgiving from first light until the yard lamp goes off in the evening, unless it pours or snows hard."""
    altitude = environment.sun_altitude
    if THANKSGIVING not in holiday_features(environment) or altitude is None:
        return False
    rain, snow = precipitation(environment)
    since = environment.since_nightfall
    return rain < 3 and snow < 2 and (altitude > NIGHT_ALTITUDE or (since is not None and 0 <= since < LAMP_SECONDS))


def pilgrim_pose(index: int, elapsed: float, seed: int) -> str:
    kind = PILGRIMS[index][0]
    slot = math.floor(elapsed / PILGRIM_GESTURE_SECONDS)
    if unit_hash(seed, slot, index, 41) >= PILGRIM_GESTURE_CHANCE:
        return "stand"
    length = PILGRIM_GESTURE_LENGTH[0] + (PILGRIM_GESTURE_LENGTH[1] - PILGRIM_GESTURE_LENGTH[0]) * unit_hash(seed, slot, index, 43)
    start = (PILGRIM_GESTURE_SECONDS - length) * unit_hash(seed, slot, index, 47)
    if not start <= elapsed - slot * PILGRIM_GESTURE_SECONDS < start + length:
        return "stand"
    if kind == "woman":
        # The wave swings between raised and lowered.
        return "wave" if math.floor((elapsed - slot * PILGRIM_GESTURE_SECONDS - start) * 3) % 2 == 0 else "stand"
    return "tip"


def draw_thanksgiving_figures(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    """The tom, any visiting hens and the pilgrims, back to front by the row each stands on; on a shared row the pilgrims
    stand behind the birds."""
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))

    def lit(colors: dict[str, Color]) -> dict[str, Color]:
        return {char: tuple(round(value * illumination) for value in color) for char, color in colors.items()}

    x, feet, lift, facing, pose = tom_state(elapsed, seed)
    tom_colors = lit(TURKEY_COLORS["tom"])
    if pose == "gobble":
        tom_colors["r"] = TURKEY_GOBBLE_WATTLE
    # (feet row, layer on a shared row, sprite, x, drawn row, facing, colors)
    figures = [(feet, 1, TURKEY_SPRITES["tom"][pose], x, feet - lift, facing, tom_colors)]
    visit = turkey_state(environment, elapsed, seed)
    if visit is not None:
        hen_colors = lit(TURKEY_COLORS["hen"])
        for index in range(len(visit.hens)):
            x, feet, facing, pose = turkey_pose(visit, index, elapsed, seed)
            figures.append((feet, 1, TURKEY_SPRITES["hen"][pose], x, feet, facing, hen_colors))
    if pilgrims_out(environment):
        pilgrim_colors = lit(PILGRIM_COLORS)
        for index, (kind, x, feet) in enumerate(PILGRIMS):
            figures.append((feet, 0, PILGRIM_SPRITES[kind][pilgrim_pose(index, elapsed, seed)], x, feet, 1, pilgrim_colors))
    d = ImageDraw.Draw(image)
    for _, _, rows, x, row, facing, colors in sorted(figures, key=lambda figure: figure[:2]):
        draw_standing_sprite(d, rows, x, row, facing, colors)


# On July 4 a hotdog mascot in sunglasses now and then walks in along the front of the meadow, dances between the flag
# and the cannon, and walks off the other side.
# Deer, foxes, rabbits, songbirds, the eagle and the owl stay away for the whole July 4 scene.
HOTDOG = "hotdog"
HOTDOG_SLOT_SECONDS = 80
HOTDOG_CHANCE = 0.45
HOTDOG_SPEED = 10
HOTDOG_FEET_ROW = 31
HOTDOG_DANCE_COLUMNS = (58, 76)
HOTDOG_DANCE_SECONDS = (6.0, 10.0)
HOTDOG_STEP_SECONDS = 0.2
HOTDOG_BEAT_SECONDS = 0.3
# Facing the viewer: S sausage, B bun, b bun shade, M mustard, K sunglasses, G their glint, m mouth.
HOTDOG_BODY = (
    "....SSS....",
    "...SSSSS...",
    "..KKKKKKK..",
    "...GKSGK...",
    "...SSSSS...",
    "..BSmmmSB..",
    ".bBSSMSSBb.",
    ".bBSMSSSBb.",
    ".bBSSMSSBb.",
    ".bBSSSMSBb.",
    ".bBSSMSSBb.",
    ".bBBSSSBBb.",
    "..bbbbbbb..",
)
# l legs, R sneakers; "kick" swings his left leg out.
HOTDOG_LEGS = {"stand": ("....l.l....", "...RR.RR..."), "stride": ("...l...l...", "..RR...RR.."), "kick": ("....l..lRR.", "...RR......")}
# a arms ending in W white gloves, as (column, row) overlays on the body.
HOTDOG_ARMS = {
    "down": {(0, 7): "a", (0, 8): "W", (10, 7): "a", (10, 8): "W"},
    "swing_a": {(0, 6): "a", (0, 7): "W", (10, 8): "a", (10, 9): "W"},
    "swing_b": {(0, 8): "a", (0, 9): "W", (10, 6): "a", (10, 7): "W"},
    "up": {(1, 5): "a", (0, 4): "a", (0, 3): "W", (9, 5): "a", (10, 4): "a", (10, 3): "W"},
    "right_up": {(0, 7): "a", (0, 8): "W", (9, 5): "a", (10, 4): "a", (10, 3): "W"},
    "out": {(0, 6): "W", (10, 6): "W"},
}
HOTDOG_COLORS = {"S": (210, 74, 48), "B": (240, 184, 100), "b": (178, 116, 56), "M": (255, 222, 30), "K": (10, 10, 14), "G": (180, 220, 255), "m": (92, 20, 20), "a": (178, 116, 56), "W": (246, 246, 240), "l": (52, 36, 30), "R": (224, 28, 40)}
# The dance, one move per beat: (arms, legs, rows lifted, columns swayed, facing). A mirrored move swaps sides.
HOTDOG_DANCE = (
    ("up", "stride", 1, 0, 1),
    ("down", "stand", 0, 0, 1),
    ("up", "stride", 1, 0, 1),
    ("down", "stand", 0, 0, 1),
    ("right_up", "kick", 0, 1, 1),
    ("down", "stand", 0, 0, 1),
    ("right_up", "kick", 0, -1, -1),
    ("down", "stand", 0, 0, 1),
    ("out", "stand", 0, 1, 1),
    ("out", "stand", 0, -1, 1),
    ("out", "stand", 0, 1, 1),
    ("out", "stand", 0, -1, 1),
)


@dataclass(frozen=True)
class HotdogVisit:
    start: float
    enter: float
    spot: float
    leave: float
    dance: float

    @property
    def walk_in(self) -> float:
        return abs(self.spot - self.enter) / HOTDOG_SPEED

    @property
    def end(self) -> float:
        return self.start + self.walk_in + self.dance + abs(self.leave - self.spot) / HOTDOG_SPEED


@dataclass(frozen=True)
class HotdogPose:
    x: float
    lift: int
    facing: int
    arms: str
    legs: str


@lru_cache(maxsize=8)
def hotdog_visit(slot: int, seed: int) -> HotdogVisit | None:
    """The mascot's visit in this slot, if any; it never spans two slots."""
    rng = random.Random(seed * 6007 + slot * 90001 + 53)
    if rng.random() >= HOTDOG_CHANCE:
        return None
    # He starts and ends just out of frame, half his width past the edge.
    edges = (-6.0, WIDTH + 5.0)
    enter, leave = edges if rng.random() < 0.5 else edges[::-1]
    visit = HotdogVisit(0.0, enter, rng.uniform(*HOTDOG_DANCE_COLUMNS), leave, rng.uniform(*HOTDOG_DANCE_SECONDS))
    duration = visit.end
    return replace(visit, start=slot * HOTDOG_SLOT_SECONDS + rng.uniform(0, HOTDOG_SLOT_SECONDS - duration))


def hotdog_allowed(environment: "OutsideEnvironment") -> bool:
    rain, snow = precipitation(environment)
    return HOTDOG in holiday_features(environment) and rain < 3 and snow < 2


def hotdog_visit_shown(environment: "OutsideEnvironment", visit: HotdogVisit, seed: int) -> bool:
    return not dog_allowed(environment) or next(dog_outings_between(seed, visit.start, visit.end), None) is None


def hotdog_state(environment: "OutsideEnvironment", elapsed: float, seed: int) -> HotdogPose | None:
    """The mascot's pose, or None. He skips any visit that would overlap the dog's time outside."""
    if not hotdog_allowed(environment):
        return None
    visit = hotdog_visit(math.floor(elapsed / HOTDOG_SLOT_SECONDS), seed)
    if visit is None or not visit.start <= elapsed < visit.end or not hotdog_visit_shown(environment, visit, seed):
        return None
    age = elapsed - visit.start
    dancing = age - visit.walk_in
    if 0 <= dancing < visit.dance:
        arms, legs, lift, sway, facing = HOTDOG_DANCE[math.floor(dancing / HOTDOG_BEAT_SECONDS) % len(HOTDOG_DANCE)]
        return HotdogPose(visit.spot + sway, lift, facing, arms, legs)
    if dancing < 0:
        origin, target, walked = visit.enter, visit.spot, age
    else:
        origin, target, walked = visit.spot, visit.leave, dancing - visit.dance
    heading = 1 if target > origin else -1
    step = math.floor(walked / HOTDOG_STEP_SECONDS) % 2
    # A one-row bob on each stride.
    return HotdogPose(origin + heading * HOTDOG_SPEED * walked, step, heading, ("swing_a", "swing_b")[step], ("stand", "stride")[step])


@lru_cache(maxsize=32)
def hotdog_sprite(arms: str, legs: str) -> tuple[str, ...]:
    rows = [list(line) for line in (*HOTDOG_BODY, *HOTDOG_LEGS[legs])]
    for (column, row), char in HOTDOG_ARMS[arms].items():
        rows[row][column] = char
    return tuple("".join(line) for line in rows)


def draw_hotdog(image: Image.Image, palette: Palette, pose: HotdogPose | None):
    if pose is None:
        return
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    # He stays readable after dark, when the fireworks are flying.
    shade = 0.35 + 0.65 * illumination
    colors = {char: tuple(round(value * shade) for value in color) for char, color in HOTDOG_COLORS.items()}
    draw_standing_sprite(ImageDraw.Draw(image), hotdog_sprite(pose.arms, pose.legs), pose.x, HOTDOG_FEET_ROW - pose.lift, pose.facing, colors)


# On Thanksgiving a skein of geese flying in a V takes the place of the small songbird flock.
GEESE_SLOT_SECONDS = 75
GEESE_CHANCE = 0.55
GEESE_SPEED = 10
GEESE_COUNT = (5, 7)
# The leader's row; the V's arms then stay below the corner labels and above the treeline.
GEESE_ROW = 13
# Each rank back along an arm trails by this many columns and spreads by this many rows.
GEESE_RANK_SPACING = (5, 2)
GEESE_FLAP_RATE = 4.5
# Wingbeats ripple back along the arms, each rank this many radians behind the one ahead.
GEESE_FLAP_LAG = 0.7


@lru_cache(maxsize=8)
def geese_flight(slot: int, seed: int) -> tuple[float, float, int, int] | None:
    """(start, end, heading, count) of the skein crossing in this slot, if any. Never spans two slots."""
    rng = random.Random(seed * 2953 + slot * 70001 + 37)
    if rng.random() > GEESE_CHANCE:
        return None
    count = rng.randint(*GEESE_COUNT)
    length = (count // 2 + 1) * GEESE_RANK_SPACING[0]
    duration = (WIDTH + 2 * length + 4) / GEESE_SPEED
    start = slot * GEESE_SLOT_SECONDS + rng.uniform(1, GEESE_SLOT_SECONDS - duration - 1)
    return start, start + duration, rng.choice((-1, 1)), count


def geese_state(environment: "OutsideEnvironment", elapsed: float, seed: int) -> tuple[float, float, int, int] | None:
    """The skein crossing at `elapsed`, if any; like the songbirds, it keeps clear of the eagle."""
    flight = geese_flight(math.floor(elapsed / GEESE_SLOT_SECONDS), seed)
    if flight is None or not flight[0] <= elapsed < flight[1]:
        return None
    if next(eagle_visits_present(environment, seed, flight[0], flight[1]), None) is not None:
        return None
    return flight


def draw_geese(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    flight = geese_state(environment, elapsed, seed)
    if flight is None:
        return
    start, _, heading, count = flight
    length = (count // 2 + 1) * GEESE_RANK_SPACING[0]
    travel = (elapsed - start) * GEESE_SPEED - length
    lead_x = travel if heading > 0 else WIDTH - 1 - travel
    d = ImageDraw.Draw(image)
    for index in range(count):
        # Geese alternate between the two arms of the V, one rank further back each pair.
        rank, arm = (index + 1) // 2, 1 if index % 2 else -1
        x = round(lead_x - heading * rank * GEESE_RANK_SPACING[0])
        y = GEESE_ROW + arm * rank * GEESE_RANK_SPACING[1]
        wing = 1 if math.sin(elapsed * GEESE_FLAP_RATE - rank * GEESE_FLAP_LAG) > 0 else -1
        for px, py in ((x - 1, y - wing), (x, y), (x + 1, y - wing)):
            if 0 <= px < WIDTH and 0 <= py < HEIGHT:
                d.point((px, py), fill=palette.roof)


# The scene draws fog below this visibility (m).
FOG_VISIBILITY = 5000
# Comfortable beach weather puts a beach umbrella up on the pond's right bank: a temperature range (°F), the highest
# dew point (°F, which measures mugginess better than relative humidity), the most cloud cover and wind (mph), and the
# lowest sun altitude. Once up, it stays up until a reading passes its limit by the margin, so a reading hovering at a
# limit cannot flicker it on and off between weather refreshes.
BEACH_TEMPERATURE, BEACH_TEMPERATURE_MARGIN = (75, 95), 2.5
BEACH_DEW_POINT, BEACH_DEW_POINT_MARGIN = 68, 2
BEACH_CLOUDS, BEACH_CLOUDS_MARGIN = 0.4, 0.1
BEACH_WIND, BEACH_WIND_MARGIN = 15, 3
BEACH_SUN_ALTITUDE, BEACH_SUN_MARGIN = 10, 2
# Clear, few and scattered clouds; every other condition (drizzle, rain, storms, snow, haze, fog, heavy cloud) keeps it down.
BEACH_CODES = frozenset({800, 801, 802})
# The July 4 cannon, the Halloween jack-o'-lanterns and the Thanksgiving harvest display stand on the umbrella's spot.
BEACH_HOLIDAYS = frozenset({"cannon", HALLOWEEN, THANKSGIVING})
# A red and white striped beach umbrella leaning a little right, with "o" the foot of its pole at UMBRELLA_FOOT.
# R and W are the lit panels, r and w their shaded rim, T the finial and P the pole.
UMBRELLA_SPRITE = (
    ".......T.....",
    ".....RRRW....",
    "..RRWWRRWWR..",
    "RRRWWRRRRWWRR",
    "rr.wwRRRRWWRR",
    "......rr.ww.r",
    "......P......",
    ".....P.......",
    ".....P.......",
    "....P........",
    "....o........",
)
UMBRELLA_FOOT = (85, 28)
UMBRELLA_COLORS = {"R": (206, 70, 62), "r": (156, 50, 52), "W": (238, 236, 228), "w": (176, 178, 184), "T": (206, 70, 62), "P": (150, 146, 140), "o": (150, 146, 140)}
# Shade on the grass under the canopy: center, radii and darkness at the center.
UMBRELLA_SHADE = ((89, 28.6), (4.6, 1.1), 0.35)


def beach_weather(environment: "OutsideEnvironment", up: bool) -> bool:
    """Whether the beach umbrella stands: comfortable, dry, sunny daylight. Pass whether it stands now, for the margins.
    An unknown reading keeps it down."""
    weather = environment.weather
    if weather.code not in BEACH_CODES or weather.temperature is None or weather.dew_point is None or weather.wind is None or environment.sun_altitude is None:
        return False
    if holiday_features(environment) & BEACH_HOLIDAYS or (weather.visibility is not None and weather.visibility < FOG_VISIBILITY) or any(precipitation(environment)):
        return False
    slack = 1 if up else 0
    low, high = BEACH_TEMPERATURE
    return (
        low - slack * BEACH_TEMPERATURE_MARGIN <= weather.temperature <= high + slack * BEACH_TEMPERATURE_MARGIN
        and weather.dew_point <= BEACH_DEW_POINT + slack * BEACH_DEW_POINT_MARGIN
        and cloud_cover(environment) <= BEACH_CLOUDS + slack * BEACH_CLOUDS_MARGIN
        and weather.wind <= BEACH_WIND + slack * BEACH_WIND_MARGIN
        and environment.sun_altitude >= BEACH_SUN_ALTITUDE - slack * BEACH_SUN_MARGIN
    )


def umbrella_geometry() -> tuple[tuple[tuple[int, int, str], ...], tuple[tuple[int, int, float], ...]]:
    """The umbrella's pixels (x, y, part) and its shade on the grass (x, y, darkness)."""
    foot_x, foot_y = next((x, y) for y, row in enumerate(UMBRELLA_SPRITE) for x, part in enumerate(row) if part == "o")
    pixels = tuple((UMBRELLA_FOOT[0] + x - foot_x, UMBRELLA_FOOT[1] + y - foot_y, part) for y, row in enumerate(UMBRELLA_SPRITE) for x, part in enumerate(row) if part != ".")
    (cx, cy), (rx, ry), darkness = UMBRELLA_SHADE
    ground = (INDEX["field"], INDEX["foreground"], INDEX["grass"])
    shade = []
    for y in range(math.floor(cy - ry), math.ceil(cy + ry) + 1):
        for x in range(math.floor(cx - rx), math.ceil(cx + rx) + 1):
            reach = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if reach < 1 and 0 <= x < WIDTH and 0 <= y < HEIGHT and LAND.getpixel((x, y)) in ground:
                shade.append((x, y, darkness * (1 - reach)))
    return pixels, tuple(shade)


UMBRELLA_PIXELS, UMBRELLA_SHADOW = umbrella_geometry()


def draw_beach_umbrella(image: Image.Image, palette: Palette):
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    d = ImageDraw.Draw(image)
    for x, y, darkness in UMBRELLA_SHADOW:
        d.point((x, y), fill=mix(image.getpixel((x, y)), (0, 0, 0), darkness))
    for x, y, part in UMBRELLA_PIXELS:
        color = UMBRELLA_COLORS[part]
        d.point((x, y), fill=(round(color[0] * illumination), round(color[1] * illumination), round(color[2] * illumination)))


# On a crisp evening (clear, cold, dry and calm) a campfire burns between the pond and the maple from sunset until local
# midnight, but never on a holiday. Weather limits: a temperature range (°F), the least gap between temperature and dew point (°F,
# which keeps the air dry), and the most cloud cover and wind (mph). Like the beach umbrella's, each limit has a margin
# once the fire is lit, so a reading hovering at a limit cannot light and douse it between weather refreshes.
CRISP_TEMPERATURE, CRISP_TEMPERATURE_MARGIN = (25, 48), 2.5
CRISP_DEW_POINT_SPREAD, CRISP_DEW_POINT_MARGIN = 8, 2
CRISP_CLOUDS, CRISP_CLOUDS_MARGIN = 0.25, 0.1
CRISP_WIND, CRISP_WIND_MARGIN = 10, 3
CRISP_CODES = frozenset({800, 801, 802})
# The coals catch first, then the flames build as the sun sinks this many degrees below sunset. Over the last
# CAMPFIRE_BURN_DOWN_SECONDS before midnight the flames die down, and the coals go dark over the last CAMPFIRE_COALS_SECONDS.
CAMPFIRE_KINDLE_DEGREES = 1.5
CAMPFIRE_BURN_DOWN_SECONDS = 15 * 60
CAMPFIRE_COALS_SECONDS = 60
# Only the evening's half of the night counts; after midnight the fire stays out until the next sunset.
CAMPFIRE_EVENING_SECONDS = 12 * 3600
# A campfire in the meadow between the pond and the maple. Nothing stands in front of the flames: a teepee of sticks
# leans together behind them, showing only around their edges and through gaps between tongues, and a single log lies
# along the ground below their base, with a stone at either side. Logs are ((end), (end), thickness, in front of the
# flames); stones (x, y, radius); the coal bed (center, radii) glows behind the flames' base. Pixel centers are integers.
CAMPFIRE_LOGS = (((89, 30), (97, 20), 1.5, False), ((101, 30), (93, 20), 1.5, False), ((88, 30.5), (102, 30.5), 2, True))
# The top of each stick in the teepee is burnt black over this many px.
CAMPFIRE_CHARRED = 2.5
CAMPFIRE_STONES = ((85, 31, 1.3), (105, 31, 1.3))
CAMPFIRE_COAL_BED = ((95, 29), (4.5, 0.7))
# Parts: B/b lit and shaded bark, k ash and charred wood; S/s lit and shaded stone; c coals.
CAMPFIRE_COLORS = {"B": (124, 100, 80), "b": (80, 64, 52), "k": (38, 28, 24), "S": (132, 128, 122), "s": (84, 82, 82)}
# The flames rise from this point, just above the front log.
CAMPFIRE_X, CAMPFIRE_BASE = 95.0, 29.4
# Full-size flames: height and half-width at the base (px). Wind leans their tips right by this many px per mph.
CAMPFIRE_FLAME_HEIGHT = 12.0
CAMPFIRE_FLAME_WIDTH = 4.4
CAMPFIRE_WIND_LEAN = 0.12
# Turbulence rises through the flames at these speeds (px/s); faster small eddies ride on slower large ones.
CAMPFIRE_RISE = (7.0, 11.0)
# Heat to color, from the flames' dim red edges to their pale yellow core. Picked by their graded result on the panel.
CAMPFIRE_HEAT = (0.12, 0.26, 0.4, 0.55, 0.72, 0.92)
CAMPFIRE_FIRE = np.array(((120, 16, 2), (196, 38, 6), (246, 90, 12), (255, 146, 28), (255, 206, 76), (255, 244, 196)), dtype=np.float32) / 255
CAMPFIRE_COAL = (np.array((150, 18, 4), dtype=np.float32) / 255, np.array((255, 110, 20), dtype=np.float32) / 255)
# Firelight: a flickering warm wash reaching this far (px) over the ground, the trunk and the underside of the canopy.
# Open air catches only CAMPFIRE_AIR_GLOW of it, a faint halo rather than a lit box of sky.
CAMPFIRE_LIGHT = (255, 146, 58)
CAMPFIRE_LIGHT_REACH = 6.5
CAMPFIRE_LIGHT_STRENGTH = 0.5
CAMPFIRE_AIR_GLOW = 0.22
# A steady stream of embers rides the plume up, joined now and then by a burst when a log pops. Each ember slows over
# CAMPFIRE_EMBER_SLOW seconds and cools as it rises, and every ember is out by CAMPFIRE_EMBER_CEILING, below the
# temperature label.
CAMPFIRE_EMBER_INTERVAL = 0.22
CAMPFIRE_EMBER_CHANCE = 0.75
CAMPFIRE_EMBER_SPEED = (6.0, 13.0)
CAMPFIRE_EMBER_LIFE = (1.2, 3.0)
CAMPFIRE_EMBER_SLOW = 1.6
CAMPFIRE_EMBER_CEILING = 9
CAMPFIRE_POP_SECONDS = 5.0
CAMPFIRE_POP_CHANCE = 0.45
CAMPFIRE_POP_EMBERS = (3, 6)
CAMPFIRE_POP_SPEED = (12.0, 18.0)


def crisp_weather(environment: "OutsideEnvironment", lit: bool) -> bool:
    """Whether the evening is crisp enough for the campfire: clear, cold, dry and calm. Pass whether the fire is lit
    now, for the margins. An unknown reading keeps it out."""
    weather = environment.weather
    if weather.code not in CRISP_CODES or weather.temperature is None or weather.dew_point is None or weather.wind is None:
        return False
    if (weather.visibility is not None and weather.visibility < FOG_VISIBILITY) or any(precipitation(environment)):
        return False
    slack = 1 if lit else 0
    low, high = CRISP_TEMPERATURE
    return (
        low - slack * CRISP_TEMPERATURE_MARGIN <= weather.temperature <= high + slack * CRISP_TEMPERATURE_MARGIN
        and weather.temperature - weather.dew_point >= CRISP_DEW_POINT_SPREAD - slack * CRISP_DEW_POINT_MARGIN
        and cloud_cover(environment) <= CRISP_CLOUDS + slack * CRISP_CLOUDS_MARGIN
        and weather.wind <= CRISP_WIND + slack * CRISP_WIND_MARGIN
    )


def campfire_state(environment: "OutsideEnvironment") -> tuple[float, float] | None:
    """(flames, coals), each 0..1, while the campfire burns: on a crisp evening between sunset and local midnight, on
    no holiday."""
    altitude, left = environment.sun_altitude, environment.until_midnight
    if not environment.crisp or altitude is None or left is None or altitude >= SET_ALTITUDE or left > CAMPFIRE_EVENING_SECONDS:
        return None
    if holiday_features(environment):
        return None
    kindle = min(1.0, (SET_ALTITUDE - altitude) / CAMPFIRE_KINDLE_DEGREES)
    return min(kindle, left / CAMPFIRE_BURN_DOWN_SECONDS), min(1.0, kindle * 3, left / CAMPFIRE_COALS_SECONDS)


def campfire_pixels() -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], str]]:
    """The campfire's pixels by part (see CAMPFIRE_COLORS): those behind the flames, then those in front of them."""
    back: dict[tuple[int, int], str] = {}
    front: dict[tuple[int, int], str] = {}
    for (ax, ay), (bx, by), thickness, ahead in CAMPFIRE_LOGS:
        cells = front if ahead else back
        length = math.hypot(bx - ax, by - ay)
        dx, dy = (bx - ax) / length, (by - ay) / length
        # The normal pointing up the screen (or toward the fire for an upright stick), toward the log's lit side.
        nx, ny = (dy, -dx) if dx > 0 else (-dy, dx)
        if abs(dx) < abs(dy):
            nx, ny = (nx, ny) if nx * (CAMPFIRE_X - ax) > 0 else (-nx, -ny)
        half = thickness / 2
        for y in range(math.floor(min(ay, by) - thickness), math.ceil(max(ay, by) + thickness) + 1):
            for x in range(math.floor(min(ax, bx) - thickness), math.ceil(max(ax, bx) + thickness) + 1):
                along = (x - ax) * dx + (y - ay) * dy
                across = (x - ax) * nx + (y - ay) * ny
                if 0 <= along <= length and -half < across <= half:
                    cells[x, y] = "k" if not ahead and along > length - CAMPFIRE_CHARRED else "B" if across > 0 else "b"
    (cx, cy), (rx, ry) = CAMPFIRE_COAL_BED
    for y in range(math.floor(cy - ry), math.ceil(cy + ry) + 1):
        for x in range(math.floor(cx - rx), math.ceil(cx + rx) + 1):
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1:
                # Dark ash breaks up the glowing bed.
                back[x, y] = "k" if grain(x, y, 47) < 30 else "c"
    for sx, sy, radius in CAMPFIRE_STONES:
        for y in range(math.floor(sy - radius), math.ceil(sy + radius) + 1):
            for x in range(math.floor(sx - radius), math.ceil(sx + radius) + 1):
                if math.hypot(x - sx, y - sy) < radius + 0.3:
                    # Lit from the fire's side and from above.
                    front[x, y] = "S" if y < sy or (x - sx) * (CAMPFIRE_X - sx) > 0 else "s"
    back = {point: char for point, char in back.items() if point not in front}
    return tuple({point: char for point, char in cells.items() if 0 <= point[0] < WIDTH and 0 <= point[1] < HEIGHT} for cells in (back, front))


def campfire_layer(cells: dict[tuple[int, int], str]) -> tuple[np.ndarray, np.ndarray]:
    """(points, base colors) of a layer's solid pixels, leaving out the glowing coals."""
    solid = [(point, CAMPFIRE_COLORS[char]) for point, char in cells.items() if char != "c"]
    return np.array([point for point, _ in solid], dtype=int), np.array([color for _, color in solid], dtype=np.float32)


CAMPFIRE_BACK_CELLS, CAMPFIRE_FRONT_CELLS = campfire_pixels()
CAMPFIRE_COAL_PIXELS = np.array([point for point, char in CAMPFIRE_BACK_CELLS.items() if char == "c"], dtype=int)
CAMPFIRE_BACK, CAMPFIRE_BACK_COLORS = campfire_layer(CAMPFIRE_BACK_CELLS)
CAMPFIRE_FRONT, CAMPFIRE_FRONT_COLORS = campfire_layer(CAMPFIRE_FRONT_CELLS)
# The fire lights its own logs and stones this much: their colors brighten toward full and warm toward the firelight,
# rather than taking the ground's wash, which would flood them into one orange block.
CAMPFIRE_SELF_LIGHT, CAMPFIRE_SELF_WARMTH = 0.85, 0.08


def wrapping_noise(size: int, cell: int, salt: int) -> np.ndarray:
    """Smooth value noise on a square tile that wraps both ways, so it can scroll forever."""
    count = size // cell
    grid = np.random.default_rng(salt).random((count, count))
    steps = np.arange(size) / cell
    low = np.floor(steps).astype(int)
    fraction = steps - low
    fraction = fraction * fraction * (3 - 2 * fraction)
    high = (low + 1) % count
    rows = grid[low] + (grid[high] - grid[low]) * fraction[:, None]
    return (rows[:, low] + (rows[:, high] - rows[:, low]) * fraction[None, :]).astype(np.float32)


CAMPFIRE_NOISE_SIZE = 64
CAMPFIRE_NOISE = (wrapping_noise(CAMPFIRE_NOISE_SIZE, 4, 401), wrapping_noise(CAMPFIRE_NOISE_SIZE, 2, 402))


def sample_noise(tile: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Bilinear samples of a wrapping noise tile at fractional coordinates, so scrolling noise moves smoothly."""
    x0, y0 = np.floor(xs), np.floor(ys)
    fx, fy = xs - x0, ys - y0
    x0, y0 = x0.astype(int) % CAMPFIRE_NOISE_SIZE, y0.astype(int) % CAMPFIRE_NOISE_SIZE
    x1, y1 = (x0 + 1) % CAMPFIRE_NOISE_SIZE, (y0 + 1) % CAMPFIRE_NOISE_SIZE
    top = tile[y0, x0] + (tile[y0, x1] - tile[y0, x0]) * fx
    bottom = tile[y1, x0] + (tile[y1, x1] - tile[y1, x0]) * fx
    return top + (bottom - top) * fy


# The flames are evaluated in this box (rows, columns) around their base.
CAMPFIRE_FLAME_ROWS = np.arange(math.floor(CAMPFIRE_BASE - CAMPFIRE_FLAME_HEIGHT * 1.5), math.ceil(CAMPFIRE_BASE) + 1)
CAMPFIRE_FLAME_COLUMNS = np.arange(math.floor(CAMPFIRE_X) - 8, math.ceil(CAMPFIRE_X) + 9)
CAMPFIRE_FLAME_Y, CAMPFIRE_FLAME_X = np.meshgrid(CAMPFIRE_FLAME_ROWS.astype(np.float32), CAMPFIRE_FLAME_COLUMNS.astype(np.float32), indexing="ij")
CAMPFIRE_SURFACES = (np.asarray(LAND) != 0) | (np.asarray(LEAFY_TREE) != 0) | (np.asarray(BARE_TREE) != 0)
CAMPFIRE_GLOW = np.exp(-((FIREWORK_X - CAMPFIRE_X) ** 2 + ((FIREWORK_Y - (CAMPFIRE_BASE - 3)) * 1.3) ** 2) / (2 * CAMPFIRE_LIGHT_REACH**2)) * CAMPFIRE_LIGHT_STRENGTH * np.where(CAMPFIRE_SURFACES, 1.0, CAMPFIRE_AIR_GLOW)
CAMPFIRE_GLOW[CAMPFIRE_GLOW < 0.004] = 0
# Everything the fire lights, from the firelight to the farthest embers, falls in this corner (top row, left column),
# so only it is blended each frame.
CAMPFIRE_REGION = (min(int(np.flatnonzero(CAMPFIRE_GLOW.any(axis=1))[0]), CAMPFIRE_EMBER_CEILING - 1), min(int(np.flatnonzero(CAMPFIRE_GLOW.any(axis=0))[0]), math.floor(CAMPFIRE_X) - 18))
CAMPFIRE_GLOW = CAMPFIRE_GLOW[CAMPFIRE_REGION[0] :, CAMPFIRE_REGION[1] :, None].astype(np.float32)
# Heat to premultiplied flame color, as a lookup table over CAMPFIRE_HEAT's range.
CAMPFIRE_RAMP_HEAT = np.linspace(CAMPFIRE_HEAT[0], CAMPFIRE_HEAT[-1], 256)
CAMPFIRE_RAMP = (np.stack([np.interp(CAMPFIRE_RAMP_HEAT, CAMPFIRE_HEAT, CAMPFIRE_FIRE[:, channel]) for channel in range(3)], axis=-1) * np.clip((CAMPFIRE_RAMP_HEAT - CAMPFIRE_HEAT[0]) / (CAMPFIRE_HEAT[1] - CAMPFIRE_HEAT[0]), 0, 1)[:, None]).astype(np.float32)


def campfire_flicker(elapsed: float) -> float:
    """0..1 brightness of the whole fire: a slow breathing with quicker flutters on top, never a hard jump."""
    return 0.86 + 0.07 * math.sin(elapsed * 4.3) + 0.04 * math.sin(elapsed * 7.9 + 1.1) + 0.03 * math.sin(elapsed * 13.1 + 2.3)


def campfire_flames(light: np.ndarray, flames: float, elapsed: float, wind: float):
    """Add the flames to `light`: a teardrop of heat eroded by turbulence rising through it, so tongues lick up, split
    and break off as wisps. Everything is continuous in `elapsed`, so the motion is smooth at any frame rate."""
    if flames <= 0.02:
        return
    height = CAMPFIRE_FLAME_HEIGHT * (0.25 + 0.75 * flames) * (1 + 0.07 * math.sin(elapsed * 3.1) + 0.05 * math.sin(elapsed * 5.3 + 1.7))
    width = CAMPFIRE_FLAME_WIDTH * (0.55 + 0.45 * flames)
    xs, ys = CAMPFIRE_FLAME_X, CAMPFIRE_FLAME_Y
    rise = np.clip((CAMPFIRE_BASE - ys) / height, 0, None)
    large, small = CAMPFIRE_NOISE
    # The flames lean with the wind and sway on their own, and rising eddies bend each tongue, more toward the tips.
    sway = 0.45 * math.sin(elapsed * 1.7) + 0.3 * math.sin(elapsed * 2.9 + 0.7)
    warp = (sample_noise(large, xs * 0.7 + 31, ys * 0.6 + elapsed * CAMPFIRE_RISE[0]) - 0.5) * 2.6
    lean = min(wind, 20) * CAMPFIRE_WIND_LEAN * rise**1.5 + sway * rise**1.2 + warp * rise
    across = (xs - CAMPFIRE_X - lean) / (width * np.clip(1 - 0.7 * rise, 0.2, 1))
    body = np.clip(1 - across**2, 0, 1) * np.clip(1.1 - rise, 0, 1) ** 0.6
    turbulence = 0.55 * sample_noise(large, xs * 0.9, ys * 0.8 + elapsed * CAMPFIRE_RISE[0]) + 0.45 * sample_noise(small, xs * 2.2 + 17, ys * 0.7 + elapsed * CAMPFIRE_RISE[1])
    # Turbulence eats into the flames harder toward the tips, which breaks them into tongues and loose wisps; the
    # small eddies are stretched upright, so the tongues split along the way the flames rise.
    heat = body * (0.3 + 1.2 * turbulence) - (1 - turbulence) * (0.1 + 0.8 * rise)
    # The fire is hottest low down, where it feeds on the logs.
    heat = heat + 0.2 * body * np.clip(1 - 2 * rise, 0, 1)
    heat = heat * (0.75 + 0.25 * campfire_flicker(elapsed))
    index = np.clip((heat - CAMPFIRE_HEAT[0]) * (255 / (CAMPFIRE_HEAT[-1] - CAMPFIRE_HEAT[0])), 0, 255).astype(int)
    rows = slice(CAMPFIRE_FLAME_ROWS[0], CAMPFIRE_FLAME_ROWS[-1] + 1)
    columns = slice(CAMPFIRE_FLAME_COLUMNS[0], CAMPFIRE_FLAME_COLUMNS[-1] + 1)
    light[rows, columns] = np.maximum(light[rows, columns], CAMPFIRE_RAMP[index])


def campfire_coals(light: np.ndarray, coals: float, flames: float, elapsed: float):
    """The bed of coals glows and pulses unevenly, each coal on its own slow rhythm."""
    if coals <= 0:
        return
    xs, ys = CAMPFIRE_COAL_PIXELS[:, 0].astype(np.float32), CAMPFIRE_COAL_PIXELS[:, 1].astype(np.float32)
    pulse = sample_noise(CAMPFIRE_NOISE[1], xs * 3.7, ys * 5.3 + elapsed * 1.3)
    warmth = np.clip(0.25 + 0.75 * pulse * (0.6 + 0.4 * flames), 0, 1)[:, None]
    colors = (CAMPFIRE_COAL[0] + (CAMPFIRE_COAL[1] - CAMPFIRE_COAL[0]) * warmth) * (coals * (0.4 + 0.5 * warmth))
    light[CAMPFIRE_COAL_PIXELS[:, 1], CAMPFIRE_COAL_PIXELS[:, 0]] = np.maximum(light[CAMPFIRE_COAL_PIXELS[:, 1], CAMPFIRE_COAL_PIXELS[:, 0]], colors)


def campfire_embers(flames: float, elapsed: float, seed: int, wind: float) -> list[tuple[float, float, float, float]]:
    """(x, y, heat, brightness) of each ember in the air. Embers are numbered by when they leave the fire, and each
    one's path is a pure function of its number, so any moment can be drawn without replaying the ones before it.
    A smaller fire throws fewer embers, dropping them in a fixed order."""
    embers = []
    newest = math.floor(elapsed / CAMPFIRE_EMBER_INTERVAL)
    oldest = math.floor((elapsed - CAMPFIRE_EMBER_LIFE[1]) / CAMPFIRE_EMBER_INTERVAL) - 1
    # (launch time, ember number, hash salt, speed range, sideways spread)
    launches = [(n * CAMPFIRE_EMBER_INTERVAL + unit_hash(seed, n, 501) * CAMPFIRE_EMBER_INTERVAL, n, 0, CAMPFIRE_EMBER_SPEED, 1.0) for n in range(oldest, newest + 1) if unit_hash(seed, n, 502) < CAMPFIRE_EMBER_CHANCE * flames]
    # When a log pops it throws a quick burst of faster embers, spread wider.
    for slot in range(math.floor((elapsed - CAMPFIRE_EMBER_LIFE[1]) / CAMPFIRE_POP_SECONDS), math.floor(elapsed / CAMPFIRE_POP_SECONDS) + 1):
        if flames < 0.3 or unit_hash(seed, slot, 511) > CAMPFIRE_POP_CHANCE:
            continue
        at = (slot + 0.1 + 0.8 * unit_hash(seed, slot, 512)) * CAMPFIRE_POP_SECONDS
        count = CAMPFIRE_POP_EMBERS[0] + math.floor(unit_hash(seed, slot, 513) * (CAMPFIRE_POP_EMBERS[1] - CAMPFIRE_POP_EMBERS[0] + 1))
        launches += [(at + index * 0.03, slot * 16 + index, 50, CAMPFIRE_POP_SPEED, 2.5) for index in range(count)]
    for start, n, salt, (slowest, fastest), spread in launches:
        age = elapsed - start
        life = CAMPFIRE_EMBER_LIFE[0] + (CAMPFIRE_EMBER_LIFE[1] - CAMPFIRE_EMBER_LIFE[0]) * unit_hash(seed, n, salt + 503)
        if not 0 <= age < life:
            continue
        speed = slowest + (fastest - slowest) * unit_hash(seed, n, salt + 504)
        phase = unit_hash(seed, n, salt + 505) * math.tau
        x = CAMPFIRE_X + (unit_hash(seed, n, salt + 506) - 0.5) * 3 * (0.5 + 0.5 * flames)
        x += ((unit_hash(seed, n, salt + 507) - 0.5) * 3.2 * spread + min(wind, 25) * SMOKE_WIND_DRIFT * 0.6) * age
        x += 0.8 * math.sin(age * 3.1 + phase) * min(1.0, age)
        y = CAMPFIRE_BASE - 2 - 2 * flames - speed * CAMPFIRE_EMBER_SLOW * (1 - math.exp(-age / CAMPFIRE_EMBER_SLOW))
        heat = 1 - age / life
        ceiling = min(1.0, max(0.0, (y - CAMPFIRE_EMBER_CEILING) / 3))
        twinkle = 0.7 + 0.3 * math.sin(age * 15 + phase * 3)
        brightness = (0.35 + 0.65 * heat) * twinkle * ceiling * min(1.0, age / 0.08) * min(1.0, heat / 0.15)
        if brightness > 0.02:
            embers.append((x, y, heat, brightness))
    return embers


def draw_campfire(image: Image.Image, palette: Palette):
    """The coal bed's dark ashes; the logs, stones and the glow are drawn with the fire's light."""
    ash = tuple(round(value * min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))) for value in CAMPFIRE_COLORS["k"])
    paste_overlay(image, [(CAMPFIRE_COAL_PIXELS, ash, 1.0)])


def firelit(colors: np.ndarray, illumination: float, glow: float) -> np.ndarray:
    lit = colors * (illumination + (1 - illumination) * CAMPFIRE_SELF_LIGHT * glow)
    return lit + (np.array(CAMPFIRE_LIGHT, dtype=np.float32) - lit) * (CAMPFIRE_SELF_WARMTH * glow)


def draw_campfire_light(image: Image.Image, palette: Palette, state: tuple[float, float], night: float, elapsed: float, seed: int, wind: float) -> Image.Image:
    """Firelight washes over the ground, the trunk and the leaves above; the coals, flames and embers glow over it and
    over the sticks behind them, so they stay saturated, and the firelit front log and stones stand below the flames."""
    flames, coals = state
    glow = max(flames, 0.35 * coals) * campfire_flicker(elapsed) * (0.35 + 0.65 * night)
    top, left = CAMPFIRE_REGION
    pixels = np.array(image)
    region = pixels[top:, left:].astype(np.float32)
    region = np.round(region + (np.array(CAMPFIRE_LIGHT, dtype=np.float32) - region) * (CAMPFIRE_GLOW * glow))
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    region[CAMPFIRE_BACK[:, 1] - top, CAMPFIRE_BACK[:, 0] - left] = firelit(CAMPFIRE_BACK_COLORS, illumination, glow)
    light = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    campfire_coals(light, coals, flames, elapsed)
    campfire_flames(light, flames, elapsed, wind)
    embers = campfire_embers(flames, elapsed, seed, wind)
    if embers:
        xs, ys, heats, weights = (np.array(values, dtype=np.float32) for values in zip(*embers))
        colors = np.where((heats > 0.6)[:, None], EMBER_WARM + (EMBER_HOT - EMBER_WARM) * ((heats - 0.6) / 0.4)[:, None], EMBER_COOL + (EMBER_WARM - EMBER_COOL) * (heats / 0.6)[:, None])
        splat(light, xs, ys, colors, weights)
    # Laid over the scene as premultiplied light, like composite_light, within the fire's corner only.
    light = np.clip(light[top:, left:], 0, 1)
    region = region * (1 - light.max(axis=-1, keepdims=True)) + light * 255
    region[CAMPFIRE_FRONT[:, 1] - top, CAMPFIRE_FRONT[:, 0] - left] = firelit(CAMPFIRE_FRONT_COLORS, illumination, glow)
    pixels[top:, left:] = np.round(region).astype(np.uint8)
    return Image.fromarray(pixels, "RGB")


@dataclass(frozen=True)
class Summon:
    """An occasional event the lab can call up: it jumps the animation clock to the event's next natural start."""

    label: str
    # Shown when the current conditions rule the event out.
    requirement: str
    allowed: Callable[["OutsideEnvironment"], bool]
    active: Callable[["OutsideEnvironment", float, int], bool]
    # Seconds of build-up to show before the event starts.
    lead: float
    # Search resolution; shorter than the event's briefest appearance.
    step: float


def halloween_only(environment: "OutsideEnvironment") -> bool:
    return HALLOWEEN in holiday_features(environment)


# Every scheduled visitor and sky event the lab can summon. Add new occasional events here so they stay testable.
SUMMONS = {
    "owl": Summon("Owl", "Owls come out after dark in dry, calm weather, but not on Halloween or while ornaments hang on the tree.", owl_allowed, lambda e, t, s: owl_state(e, t, s) is not None, 1.0, 0.5),
    "eagle": Summon("Eagle", "The eagle hunts by day in fair, dry, calm weather above freezing, with good visibility and not on Halloween.", eagle_allowed, lambda e, t, s: eagle_state(e, t, s) is not None, 1.0, 0.5),
    "dog": Summon("Dog", "The dog goes out in dry daylight, but not on Halloween.", dog_allowed, lambda e, t, s: dog_state(e, t, s)[0] > 0, 0.5, 0.25),
    "wildlife": Summon("Deer, fox or rabbit", "Deer, foxes and rabbits stay away on Halloween and Thanksgiving, while the campfire burns, and in heavy rain or snow.", wildlife_allowed, lambda e, t, s: wildlife_state(e, t, s) is not None, 0.5, 0.5),
    "shooting_star": Summon("Shooting star", "Shooting stars need a dark night with stars showing through the clouds.", lambda e: starlight(e) >= 0.15, lambda e, t, s: shooting_star_state(t, s) is not None, 1.0, 0.1),
    "lightning": Summon("Lightning", "Lightning only strikes in a thunderstorm.", lambda e: e.weather.code is not None and 200 <= e.weather.code < 300, lambda e, t, s: lightning_at(e, t, s) is not None, 0.3, 0.05),
    "santa": Summon("Santa", "Santa only flies on Christmas Eve.", lambda e: "santa" in holiday_features(e), lambda e, t, s: santa_state(t, s) is not None, 0.5, 0.25),
    "hens": Summon("Turkey hens", "Hens visit by day on Thanksgiving, short of a downpour or heavy snow.", turkeys_allowed, lambda e, t, s: turkey_state(e, t, s) is not None, 0.5, 0.5),
    "geese": Summon("Geese", "Geese fly over by day on Thanksgiving in light weather.", lambda e: THANKSGIVING in holiday_features(e) and birds_allowed(e), lambda e, t, s: geese_state(e, t, s) is not None, 0.5, 0.5),
    "ghost": Summon("Ghost", "The ghost only haunts on Halloween.", halloween_only, lambda e, t, s: ghost_state(t, s) is not None, 0.5, 0.25),
    "shadow": Summon("Shadow figure", "The shadow figure only lurks on Halloween.", halloween_only, lambda e, t, s: shadow_state(t, s) is not None, 0.5, 0.25),
    "spider": Summon("Spider", "The spider only drops on Halloween.", halloween_only, lambda e, t, s: spider_state(t, s) is not None, 0.5, 0.25),
    "hotdog": Summon("Hotdog mascot", "The hotdog mascot only dances on July 4, and not in a downpour or heavy snow.", hotdog_allowed, lambda e, t, s: hotdog_state(e, t, s) is not None, 0.5, 0.5),
    "cannon": Summon("Cannon shot", "The cannon only fires on July 4.", lambda e: "cannon" in holiday_features(e), lambda e, t, s: cannon_state(t, s) is not None, 0.5, 0.25),
    "leaves": Summon("Falling leaves", "Leaves fall in autumn and blossom petals in spring, in dry weather with a known wind, but not on Halloween.", leaves_allowed, lambda e, t, s: bool(leaf_particles(e, t, s)), 0.5, 0.5),
}
SUMMON_HORIZON_SECONDS = 3600


class SummonUnavailable(ValueError):
    pass


def summon_start(name: str, environment: "OutsideEnvironment", elapsed: float, seed: int) -> float:
    """The `elapsed` at which the next occurrence of event `name` begins after now, under the current conditions."""
    summon = SUMMONS[name]
    if not summon.allowed(environment):
        raise SummonUnavailable(summon.requirement)
    before, t = elapsed, elapsed + summon.step
    was_active = summon.active(environment, before, seed)
    while t < elapsed + SUMMON_HORIZON_SECONDS:
        active = summon.active(environment, t, seed)
        if active and not was_active:
            # Narrow the start down between the last two probes.
            low, high = before, t
            for _ in range(8):
                middle = (low + high) / 2
                low, high = (low, middle) if summon.active(environment, middle, seed) else (middle, high)
            return high
        before, was_active, t = t, active, t + summon.step
    raise SummonUnavailable(f"No {summon.label.lower()} is due within the next {SUMMON_HORIZON_SECONDS // 60} minutes under these conditions.")


def render_outside_frame(environment: "OutsideEnvironment", elapsed: float, seed: int = 0, star_clearings: tuple[Box, ...] = ()) -> Image.Image:
    palette = scene_palette(environment)
    image = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = min(1, y / 21)
        color = mix(palette.top, palette.middle, t / 0.55) if t < 0.55 else mix(palette.middle, palette.horizon, (t - 0.55) / 0.45)
        d.line((0, y, 127, y), fill=color)
    lightning = lightning_at(environment, elapsed, seed)
    clouds = draw_sky(image, environment, palette, elapsed, lightning, seed, star_clearings)
    holidays = holiday_features(environment)
    # Fireworks and Santa fly in the distance, in front of the clouds but behind the land.
    night = holiday_darkness(environment)
    fireworks = firework_light(elapsed, seed, "flag" in holidays, night) if "fireworks" in holidays else None
    if fireworks is not None:
        image = composite_light(image, fireworks)
    if "santa" in holidays:
        draw_santa(image, environment, elapsed, seed)
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
    # Fountains burn on the far bank, in front of the land; they and the fireworks shimmer on the pond.
    sparkle = fireworks
    if "fountains" in holidays:
        draw_fountain_tubes(image, palette)
        fountains = fountain_light(elapsed, seed, night)
        if fountains is not None:
            image = composite_light(image, fountains)
            sparkle = fountains if sparkle is None else sparkle + fountains
    if sparkle is not None:
        image = reflect_fireworks(image, sparkle, elapsed)
        d = ImageDraw.Draw(image)
    mist = environment.weather.visibility is not None and environment.weather.visibility < FOG_VISIBILITY
    if mist or environment.weather.code in (701, 711, 721, 741):
        fog = Image.new("RGBA", (WIDTH, HEIGHT))
        fd = ImageDraw.Draw(fog)
        for index in range(3):
            x = round((elapsed * 0.22 + index * 49) % 168) - 40
            fd.ellipse((x, 22 + index, x + 70, 25 + index), fill=(*palette.far, 90))
        image.paste(fog, (0, 0), fog)
    halloween = HALLOWEEN in holidays
    shadow = shadow_state(elapsed, seed) if halloween else None
    roll = jack_roll_state(elapsed, seed) if halloween else None
    if halloween:
        image = draw_halloween_mist(image, night, elapsed)
        # The lurking figure stands farther back than the pumpkins, which roll in front of it.
        draw_shadow_figure(image, shadow, elapsed)
        draw_jack_o_lanterns(image, palette, night, elapsed, roll)
    thanksgiving = THANKSGIVING in holidays
    if thanksgiving:
        draw_harvest_display(image, palette, night, elapsed)
    wind = environment.weather.wind or 0
    flood = flag_flood_level(environment) if "flag" in holidays else 0.0
    if "flag" in holidays:
        draw_flag(image, palette, wind, elapsed, flood)
    cannon = cannon_state(elapsed, seed) if "cannon" in holidays else None
    if "cannon" in holidays:
        draw_cannon(image, palette, cannon)
    # The umbrella stands on the pond's right bank, behind visitors that wander under it.
    if environment.beach:
        draw_beach_umbrella(image, palette)
    campfire = campfire_state(environment)
    if campfire is not None:
        draw_campfire(image, palette)
    draw_wildlife(image, palette, environment, elapsed, seed)
    if thanksgiving:
        draw_thanksgiving_figures(image, palette, environment, elapsed, seed)
    draw_eagle(image, palette, eagle_state(environment, elapsed, seed), elapsed)
    draw_hut_and_dog(image, palette, *dog_state(environment, elapsed, seed), elapsed)
    image = draw_smoke(image, palette, environment, elapsed, seed)
    image = draw_cannon_smoke(image, palette, cannon, wind)
    draw_fireflies(image, firefly_glows(environment, elapsed, seed))
    sway = tree_sway(elapsed, wind)
    if foliage is not None:
        image.paste(foliage, (sway, 0), foliage)
    d = ImageDraw.Draw(image)
    if environment.season == "spring":
        for dx, dy in TREE_BLOSSOMS:
            if environment.sun_altitude is not None and environment.sun_altitude > -5:
                d.point((TREE_X + dx + sway, TREE_CANOPY_Y + dy), fill=mix(palette.leaf_light, (239, 186, 182), 0.45))
    image.paste(wood, (0, 0), wood)
    # Leaves let go from the front of the canopy, so they fall in front of the tree.
    draw_leaves(image, palette, environment, elapsed, seed)
    # The mascot walks along the front of the meadow, in front of everything that stands on it, the tree included.
    draw_hotdog(image, palette, hotdog_state(environment, elapsed, seed))
    if tree_ornaments_shown(environment):
        draw_tree_ornaments(image, night, elapsed)
    # The owl perches on the fixed branch, in front of the swaying foliage.
    draw_owl(image, palette, owl_state(environment, elapsed, seed))
    if halloween:
        draw_cobweb(image, night, elapsed, seed)
        draw_spider(image, night, elapsed, seed)
    if rain > 0:
        draw_rain(image, rain, wind, elapsed)
    if snow > 0:
        count = min(40, round(10 + snow * 9))
        for x0, y0, pace, phase in PARTICLES[:count]:
            y = int((y0 + elapsed * 1.6 * pace) % 36) - 2
            x = int((x0 + min(wind, 25) * elapsed * 0.035 + math.sin(elapsed * 0.7 + phase) * 2) % 128)
            if 0 <= y < HEIGHT:
                d.point((x, y), fill=mix(image.getpixel((x, y)), (234, 235, 225), 0.65 + (phase % 5) * 0.025))
    lamp = halloween_lamp(night, elapsed, seed) if halloween else lamp_level(environment)
    if lamp > 0:
        image = draw_lamp_light(image, lamp)
    if flood > 0:
        image = draw_flag_flood(image, flood)
    blast = cannon_light(cannon, night, wind, seed)
    if blast is not None:
        image = composite_light(image, blast)
    draw_cannon_ball(image, palette, cannon, night)
    if halloween:
        image = draw_jack_o_lantern_glow(image, night, elapsed, roll)
        draw_shadow_eyes(image, shadow, night, elapsed)
        draw_ghost(image, night, elapsed, seed)
    if thanksgiving:
        image = draw_lantern_glow(image, night, elapsed)
    # The campfire's light warms everything near it; its flames and embers are in front of the tree.
    if campfire is not None:
        image = draw_campfire_light(image, palette, campfire, holiday_darkness(environment), elapsed, seed, wind)
    # Christmas lights shine on top of the lamp's wash so they stay saturated.
    if "christmas_lights" in holidays:
        image = draw_christmas_lights(image, environment, elapsed)
    if lightning is not None:
        event, age = lightning
        if age >= 0 and event.intensity(age) > 0.01:
            image = flash_scene(image, event, event.intensity(age), clouds)
        draw_lightning(image, event, age)
    return grade_frame(image)


@lru_cache(maxsize=1)
def overlay_font() -> bitmap_graphics.Font:
    font = bitmap_graphics.Font()
    font.LoadFont(os.path.join(shared_config.font_dir, "5x7.bdf"))
    return font


@lru_cache(maxsize=128)
def overlay_text_mask(text: str) -> Image.Image:
    canvas = Canvas(len(text) * 5, 6)
    bitmap_graphics.DrawText(canvas, overlay_font(), 0, 6, bitmap_graphics.Color(255, 255, 255), text)
    mask = canvas._image.convert("L")
    bounds = mask.getbbox()
    if bounds is None:
        raise ValueError("Outside overlay text must contain visible glyphs")
    return mask.crop((bounds[0], 0, bounds[2], 6))


def overlay_relative_luminance(background: Image.Image, mask: Image.Image) -> float:
    channels = ImageStat.Stat(background.point(OVERLAY_LINEAR_LUT), mask).mean
    return sum(value * weight for value, weight in zip(channels, (0.2126, 0.7152, 0.0722))) / 255


def overlay_contrast_fraction(luminance: float) -> float:
    fraction = max(0, min(1, (luminance - OVERLAY_DARK_LUMINANCE) / (OVERLAY_BRIGHT_LUMINANCE - OVERLAY_DARK_LUMINANCE)))
    return fraction * fraction * (3 - 2 * fraction)


def draw_overlay(image: Image.Image, mask: Image.Image, x: int, *, previous_dark: bool | None = None, hold_style: bool = False) -> bool | None:
    if mask.getbbox() is None:
        return previous_dark
    background = image.crop((x, OVERLAY_MARGIN, x + mask.width, OVERLAY_MARGIN + mask.height))
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
    image.paste(lettering, (x, OVERLAY_MARGIN), mask)
    return dark_text


def draw_corner_label(image: Image.Image, text: str, *, right: bool = False, previous_dark: bool | None = None, hold_style: bool = False) -> bool | None:
    mask = overlay_text_mask(text)
    return draw_overlay(image, mask, WIDTH - OVERLAY_MARGIN - mask.width if right else OVERLAY_MARGIN, previous_dark=previous_dark, hold_style=hold_style)


def outside_notice(environment: "OutsideEnvironment") -> str:
    """Forecast conditions while scrubbing ahead, otherwise data-status notices."""
    weather = environment.weather
    notices = []
    if weather.status == "OFFLINE" or environment.sky_status == "OFFLINE":
        notices.append("OFFLINE")
    if environment.offset_minutes:
        # The condition text hides too much of the scene while the lab is in use; status notices stay.
        if environment.lab and weather.status in ("FORECAST", "FORECAST_CACHED"):
            if weather.status == "FORECAST_CACHED":
                notices.append("FCST~")
        elif weather.status in ("FORECAST", "FORECAST_CACHED") and weather.code in WEATHER_DESCRIPTIONS:
            notices.append(WEATHER_DESCRIPTIONS[weather.code].upper() + ("~" if weather.status == "FORECAST_CACHED" else ""))
        elif weather.status == "PENDING":
            notices.append("FCST...")
        elif weather.status != "OFFLINE":
            notices.append("FCST?")
    elif weather.status not in ("LIVE", "OFFLINE"):
        notices.append({"CACHED": "WX~", "PENDING": "WX..."}.get(weather.status, "WX?"))
    if environment.sky_status not in ("READY", "OFFLINE"):
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
    clock = moment.strftime("%H:%M" if military_time else "%-I:%M%p")
    temperature = environment.weather.temperature
    temperature_text = f"{round(temperature)}°F" if temperature is not None and environment.weather.status in ("LIVE", "CACHED", "FORECAST", "FORECAST_CACHED") else "--°F"
    clock_width, temperature_width = overlay_text_mask(clock).width, overlay_text_mask(temperature_text).width
    label_bottom = OVERLAY_MARGIN + overlay_text_mask(clock).height - 1 + LABEL_STAR_MARGIN
    star_clearings = ((0, 0, OVERLAY_MARGIN + clock_width - 1 + LABEL_STAR_MARGIN, label_bottom), (WIDTH - OVERLAY_MARGIN - temperature_width - LABEL_STAR_MARGIN, 0, WIDTH - 1, label_bottom))
    image = render_outside_frame(environment, elapsed, seed, star_clearings)
    previous_clock, previous_temperature, previous_notice = (*previous_text_styles, None, None, None)[:3]
    # Lightning flashes last a few frames; keep the labels' black/white style steady through them.
    flashing = lightning_at(environment, elapsed, seed) is not None
    clock_dark = draw_corner_label(image, clock, previous_dark=previous_clock, hold_style=flashing)
    temperature_dark = draw_corner_label(image, temperature_text, right=True, previous_dark=previous_temperature, hold_style=flashing)
    notice = outside_notice(environment)
    notice_dark = None
    if notice:
        left = OVERLAY_MARGIN + overlay_text_mask(clock).width + OVERLAY_GAP
        right = WIDTH - OVERLAY_MARGIN - overlay_text_mask(temperature_text).width - OVERLAY_GAP
        notice_dark = draw_notice(image, notice, left, right, elapsed, previous_dark=previous_notice, hold_style=flashing)
    sign.canvas.SetImage(image)
    return clock_dark, temperature_dark, notice_dark
