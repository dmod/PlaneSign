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
# One prominent peak right of center keeps the rest of the horizon low so the night sky stays open.
MOUNTAIN = ((62, 23), (66, 22), (70, 20), (74, 18), (77, 16), (80, 15), (83, 14), (86, 15), (89, 16), (92, 18), (96, 20), (100, 21), (106, 23), (127, 23))
# The sunlit face runs from the summit down this spur to the foot of the mountain.
MOUNTAIN_LIT_FACE = ((83, 14), (80, 15), (77, 16), (74, 18), (70, 20), (66, 22), (62, 23), (78, 23), (80, 19), (82, 16))
TREE_X, TREE_CANOPY_Y = 111, 15
# Small conifers flanking the hut: (trunk x, base row, height); the apex is at row base - height.
CONIFERS = ((4, 28, 12), (38, 25, 7))
HUT_ROOF = ((19, 20), (27, 15), (28, 15), (36, 20))
HUT_DOOR = (26, 21, 29, 25)
HUT_KNOB = (28, 23)
LAMP_POST_X = 14
LAMP_LENS = (17, 17)
LAMP_GROUND_Y = 26
LAMP_SECONDS = 3 * 3600
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
# The temperature label owns rows 0-4; leaves never start above this row.
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
TREE_FOLIAGE = LEAFY_TREE.point([value if value in (INDEX["leaf"], INDEX["leaf_light"], INDEX["leaf_dark"]) else 0 for value in range(256)])
TREE_WOOD = LEAFY_TREE.point([value if value == INDEX["trunk"] else 0 for value in range(256)])
# The Big Dipper (Ursa Major) right of the mountain, projected from the real stars at 0.7 px per degree in its
# autumn-evening pose (bowl upright, handle to the left), turned 20 degrees to level the handle:
# (x, y, peak brightness from magnitude, color). Dubhe and Merak, the pointers, form the bowl's right edge.
BIG_DIPPER = (
    (83, 7, 0.98, (232, 240, 255)),  # Alkaid
    (87, 6, 0.87, (232, 240, 255)),  # Mizar
    (90, 6, 1.0, (232, 240, 255)),  # Alioth
    (94, 7, 0.55, (232, 240, 255)),  # Megrez
    (95, 10, 0.81, (232, 240, 255)),  # Phecda
    (101, 9, 0.83, (232, 240, 255)),  # Merak
    (101, 5, 1.0, (255, 222, 180)),  # Dubhe
)
# Random field stars keep a 3 px berth around the constellation so its shape reads cleanly.
DIPPER_BOUNDS = (min(s[0] for s in BIG_DIPPER) - 3, min(s[1] for s in BIG_DIPPER) - 3, max(s[0] for s in BIG_DIPPER) + 3, max(s[1] for s in BIG_DIPPER) + 3)
STARS = tuple(
    (x, y, grain(x, y, 5))
    for y in range(1, 21)
    for x in range(2, 126)
    if grain(x, y, 9) < 2 and not (DIPPER_BOUNDS[0] <= x <= DIPPER_BOUNDS[2] and DIPPER_BOUNDS[1] <= y <= DIPPER_BOUNDS[3])
)
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
            if grain(x, 26, 1) < 25 and LAND.getpixel((x, 26)) not in (0, INDEX["water"], INDEX["hut"], INDEX["door"]):
                d.point((x, 26), fill=palette.grass)
        d.line((19, 19, 27, 15, 28, 15, 36, 19), fill=palette.trim)
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


def draw_shooting_star(image: Image.Image, elapsed: float, visibility: float, seed: int):
    star = shooting_star(math.floor(elapsed / SHOOTING_STAR_SLOT_SECONDS), seed)
    if star is None or not star.start <= elapsed < star.start + star.duration:
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
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            fade = (1 - back / SHOOTING_STAR_TRAIL) ** 1.6
            strengths[(x, y)] = max(strengths.get((x, y), 0), fade)
    d = ImageDraw.Draw(image)
    for (x, y), fade in strengths.items():
        d.point((x, y), fill=mix(image.getpixel((x, y)), SHOOTING_STAR_COLOR, min(1, visibility * envelope * fade)))


def draw_sky(image: Image.Image, environment: "OutsideEnvironment", palette: Palette, elapsed: float, lightning: "tuple[LightningEvent, float] | None" = None, seed: int = 0) -> np.ndarray:
    """Draw the sky and return the mask of cloud pixels."""
    d = ImageDraw.Draw(image)
    altitude = environment.sun_altitude
    night = max(0, min(1, -(altitude + 4) / 7)) if altitude is not None else 0
    cover = cloud_cover(environment)
    visibility = night * (1 - cover * 0.92) * (1 - moonlight(environment) * 0.25)
    for x, y, phase in STARS:
        swell = 0.5 + 0.5 * math.sin(elapsed * (0.65 + phase / 160) + phase)
        sparkle = 0.85 + 0.15 * (0.5 + 0.5 * math.sin(elapsed * (1.8 + phase / 110) + phase * 0.37))
        shimmer = 0.04 + 0.96 * swell * swell * sparkle
        strength = visibility * shimmer
        if strength > 0:
            d.point((x, y), fill=mix(image.getpixel((x, y)), STAR_COLORS[phase % len(STAR_COLORS)], strength))
    # The constellation twinkles only gently so its shape never drops out.
    for index, (x, y, peak, color) in enumerate(BIG_DIPPER):
        strength = visibility * peak * (0.85 + 0.15 * math.sin(elapsed * (1.1 + index * 0.23) + index * 1.7))
        if strength > 0:
            d.point((x, y), fill=mix(image.getpixel((x, y)), color, strength))
    if visibility > 0:
        draw_shooting_star(image, elapsed, visibility, seed)
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
    """Deer, foxes and rabbits stay away whenever their visit would overlap the dog's time outside."""
    d = ImageDraw.Draw(image)
    rain, snow = precipitation(environment)
    slot, age = divmod(elapsed, 100)
    present, species, start, duration, target, pair = wildlife_visit(int(slot), seed)
    visit = slot * 100 + start
    dog_nearby = dog_allowed(environment) and next(dog_outings_between(seed, visit, visit + duration), None) is not None
    if present and start <= age < start + duration and rain < 3 and snow < 2 and not dog_nearby:
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
    rain, snow = precipitation(environment)
    return environment.sun_altitude is not None and environment.sun_altitude > -0.833 and rain == 0 and snow == 0


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
OWL_FLIGHT_SPEED = 17
OWL_LANDING_SECONDS = 0.4
OWL_EYES = (255, 208, 40)
OWL_BLINK_WINDOW = 4.0
OWL_BLINK_SECONDS = 0.2
# Facing the viewer unless noted: u ear tufts, e eyes, k beak, f feathers, c chest, t talons.
OWL_SPRITES = {
    "perch": (("u.u", "eke", "fff", "fcf", "fcf", ".t."), "t"),
    # Head turned to the right; mirrored to look left.
    "look": (("u.u", "fek", "fff", "fcf", "fcf", ".t."), "t"),
    "flare": (("f...f", "fekef", ".fff.", ".fcf.", ".fcf.", "..t.."), "t"),
    "up": (("f...f", ".fef.", "..f.."), "e"),
    "glide": (("ffeff", "..f.."), "e"),
    "down": ((".fef.", "f.f.f"), "e"),
}


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
    entry = (rng.choice((-6, WIDTH + 5)), rng.uniform(8, 12))
    exit = (rng.choice((-6, WIDTH + 5)), rng.uniform(6, 10))
    land = arrive + math.dist(entry, OWL_PERCH) / OWL_FLIGHT_SPEED
    leave = land + rng.uniform(150, 220)
    return OwlVisit(arrive, land, leave, leave + math.dist(OWL_PERCH, exit) / OWL_FLIGHT_SPEED, entry, exit)


@lru_cache(maxsize=64)
def owl_glances(window: int, seed: int):
    """Blink times within a window, plus an occasional head turn: (blinks, look direction, look start, look end)."""
    rng = random.Random(seed * 3571 + window * 7307 + 3)
    first = rng.uniform(0.2, OWL_BLINK_WINDOW - 0.8)
    blinks = (first, first + 0.38) if rng.random() < 0.3 else (first,)
    look_start = rng.uniform(0, OWL_BLINK_WINDOW - 2.5)
    look = rng.choice((-1, 1)) if rng.random() < 0.2 else 0
    return blinks, look, look_start, look_start + rng.uniform(1.2, 2.5)


def owl_allowed(environment: "OutsideEnvironment") -> bool:
    rain, snow = precipitation(environment)
    return environment.sun_altitude is not None and environment.sun_altitude < OWL_SUN_ALTITUDE and rain == 0 and snow < 1 and (environment.weather.wind or 0) < 25


def owl_flight(origin: tuple[float, float], target: tuple[float, float], progress: float, age: float):
    """A silent swooping glide with short bursts of slow wingbeats."""
    x = origin[0] + (target[0] - origin[0]) * progress
    y = origin[1] + (target[1] - origin[1]) * progress + 3 * math.sin(math.pi * progress)
    beat = age % 1.6
    pose = ("up", "glide", "down", "glide")[int(beat / 0.2) % 4] if beat < 0.8 else "glide"
    return x, y, 1 if target[0] > origin[0] else -1, pose


def owl_state(environment: "OutsideEnvironment", elapsed: float, seed: int):
    """Return (x, y, facing, pose, eye openness) or None while the owl is away."""
    if not owl_allowed(environment):
        return None
    visit = owl_visit(math.floor(elapsed / OWL_SLOT_SECONDS), seed)
    if visit is None or not visit.arrive <= elapsed < visit.gone:
        return None
    if elapsed < visit.land:
        progress = (elapsed - visit.arrive) / (visit.land - visit.arrive)
        if elapsed >= visit.land - OWL_LANDING_SECONDS:
            return *OWL_PERCH, 1, "flare", 1.0
        return *owl_flight(visit.entry, OWL_PERCH, progress, elapsed - visit.arrive), 1.0
    if elapsed >= visit.leave:
        progress = (elapsed - visit.leave) / (visit.gone - visit.leave)
        return *owl_flight(OWL_PERCH, visit.exit, progress, elapsed - visit.leave), 1.0
    window, moment = divmod(elapsed, OWL_BLINK_WINDOW)
    blinks, look, look_start, look_end = owl_glances(int(window), seed)
    openness = 1.0
    for blink in blinks:
        if blink <= moment < blink + OWL_BLINK_SECONDS:
            # The lids snap shut, stay closed briefly, then open again.
            phase = (moment - blink) / OWL_BLINK_SECONDS
            openness = 0.35 if phase < 0.25 or phase >= 0.75 else 0.0
    if look and look_start <= moment < look_end:
        return *OWL_PERCH, look, "look", openness
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
    """Daytime fair weather only: clear to broken clouds, dry, not too windy or foggy, and an unfrozen pond."""
    w = environment.weather
    rain, snow = precipitation(environment)
    return (
        environment.sun_altitude is not None
        and environment.sun_altitude > EAGLE_SUN_ALTITUDE
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
    if environment.season != "summer" or altitude is None or w.code is None or w.temperature is None:
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
LEAF_REST_SECONDS = 3
LEAF_FADE_SECONDS = 4
LEAF_BREEZE_MPH = 8
LEAF_GUST_MPH = 16
LEAF_SHAPES = (((0, 0), (1, 0)), ((0, 0),), ((0, 0), (1, 1)), ((0, 0),), ((0, 0), (0, 1)), ((0, 0),), ((0, 0), (-1, 1)), ((0, 0),))


@dataclass(frozen=True)
class LeafDrift:
    release: float
    origin: tuple[int, int]
    flight_seconds: float
    ground_y: int
    phase: float
    tint: float


@lru_cache(maxsize=16)
def leaf_gust(slot: int, seed: int) -> tuple[LeafDrift, ...]:
    """Fixed release order: wind adds leaves to a gust without reshuffling its paths."""
    rng = random.Random(seed * 7919 + slot * 104729 + 43)
    if rng.random() > LEAF_GUST_CHANCE:
        return ()
    start = slot * LEAF_SLOT_SECONDS + rng.uniform(4, 10)
    leaves = []
    for index in range(3):
        dx, dy = rng.choice(TREE_BLOSSOMS)
        leaves.append(LeafDrift(
            release=start + index * rng.uniform(0.65, 1.2),
            origin=(TREE_X + dx, TREE_CANOPY_Y + dy),
            flight_seconds=rng.uniform(8, 12),
            ground_y=rng.randrange(29, 31),
            phase=rng.uniform(0, math.tau),
            tint=rng.random(),
        ))
    return tuple(leaves)


def leaf_particles(environment: "OutsideEnvironment", elapsed: float, seed: int) -> list[tuple[int, int, int, float, float]]:
    """(x, y, pose, tint, opacity) for dry autumn leaves or spring blossom petals."""
    weather = environment.weather
    if environment.season not in ("autumn", "spring") or weather.code is None or weather.wind is None:
        return []
    rain, snow = precipitation(environment)
    if rain > 0 or snow > 0:
        return []
    wind = min(30, weather.wind)
    count = 1 + (wind >= LEAF_BREEZE_MPH) + (wind >= LEAF_GUST_MPH)
    particles = []
    for leaf in leaf_gust(math.floor(elapsed / LEAF_SLOT_SECONDS), seed)[:count]:
        age = elapsed - leaf.release
        end = leaf.flight_seconds + LEAF_REST_SECONDS + LEAF_FADE_SECONDS
        if not 0 <= age < end:
            continue
        progress = min(1.0, age / leaf.flight_seconds)
        # The scene's breeze carries leaves left into the meadow; only strong gusts reach the yard.
        travel = min(leaf.origin[0] - 3, 3 + wind * 4)
        sway = round(math.sin(leaf.release * 0.6) * min(1, wind / 12))
        flutter = (math.sin(age * 1.65 + leaf.phase) - math.sin(leaf.phase)) * (1 - progress) * (1.2 + wind / 30)
        x = round(leaf.origin[0] + sway - travel * progress + flutter)
        y = round(leaf.origin[1] + (leaf.ground_y - leaf.origin[1]) * progress)
        pose = int(age * 2.5 + leaf.phase) % len(LEAF_SHAPES) if progress < 1 else 0
        opacity = min(1.0, age / 0.3, (end - age) / LEAF_FADE_SECONDS)
        particles.append((x, y, pose, leaf.tint, opacity))
    return particles


def draw_leaves(image: Image.Image, palette: Palette, environment: "OutsideEnvironment", elapsed: float, seed: int):
    particles = leaf_particles(environment, elapsed, seed)
    if not particles:
        return
    colors = ((239, 186, 182), (215, 146, 166)) if environment.season == "spring" else ((231, 153, 63), (176, 82, 40))
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))
    d = ImageDraw.Draw(image)
    for x, y, pose, tint, opacity in particles:
        color = mix(*colors, tint)
        color = (round(color[0] * illumination), round(color[1] * illumination), round(color[2] * illumination))
        for dx, dy in LEAF_SHAPES[pose]:
            px, py = x + dx, y + dy
            if 0 <= px < WIDTH and 5 <= py < HEIGHT:
                d.point((px, py), fill=mix(image.getpixel((px, py)), color, opacity))


def lamp_level(environment: "OutsideEnvironment") -> float:
    """The yard lamp comes on once the sky is pure night, warming up over 40 s, and switches off three hours later."""
    since = environment.since_nightfall
    if since is None or not 0 <= since < LAMP_SECONDS:
        return 0.0
    return min(1.0, since / 40, (LAMP_SECONDS - since) / 20)


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


def holiday_features(environment: "OutsideEnvironment") -> frozenset[str]:
    """Holiday easter eggs for the displayed local date."""
    day = environment.local_date
    if day is None:
        return frozenset()
    return frozenset(feature for feature, (_, spans) in HOLIDAYS.items() if any(day.month == month and first <= day.day <= last for month, first, last in spans))


def holiday_darkness(environment: "OutsideEnvironment") -> float:
    """0 in daylight to 1 once dusk deepens; emitted holiday light glows into its surroundings only after dark."""
    altitude = environment.sun_altitude
    return max(0, min(1, -(altitude + 2) / 8)) if altitude is not None else 0


# Christmas lights stay up from December 1 through the day after Christmas.
CHRISTMAS_LAST_DAY = 26
# Holiday easter eggs, active all day on the displayed local date: feature -> (label, (month, first day, last day) spans).
# The Outside lab builds its holiday shortcuts from this table.
HOLIDAYS = {
    "christmas_lights": ("Christmas lights", ((12, 1, CHRISTMAS_LAST_DAY),)),
    "santa": ("Santa", ((12, 24, 24),)),
    "fireworks": ("Fireworks", ((12, 31, 31), (1, 1, 1), (7, 4, 4))),
    "flag": ("Flag", ((7, 4, 4),)),
}
CHRISTMAS_COLORS = ((255, 28, 28), (24, 255, 64), (40, 96, 255), (255, 172, 16), (255, 52, 196))
TOPPER_GOLD = (255, 206, 60)
TOPPER_CORE = (255, 250, 214)


def christmas_bulbs() -> tuple[tuple[int, int], ...]:
    """Bulbs strung along the hut's gable and wound around each conifer."""
    bulbs = trace(list(HUT_ROOF))[::2]
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


def draw_santa(image: Image.Image, environment: "OutsideEnvironment", elapsed: float, seed: int):
    santa = santa_pass(math.floor(elapsed / SANTA_SLOT_SECONDS), seed)
    age = elapsed - santa.start
    if not 0 <= age < santa.duration:
        return
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
FIREWORK_CHANCE = 0.75
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


def draw_flag(image: Image.Image, palette: Palette, wind: float, elapsed: float):
    """A big American flag rippling on a pole beside the hut."""
    d = ImageDraw.Draw(image)
    illumination = min(1.0, max(palette.leaf_light) / max(DAY.leaf_light))

    def lit(color: Color, shade: float = 1.0) -> Color:
        return tuple(min(255, round(value * illumination * shade)) for value in color)

    d.line((FLAG_POLE_X, FLAG_TOP, FLAG_POLE_X, FLAG_GROUND), fill=lit(FLAG_POLE))
    d.point((FLAG_POLE_X, FLAG_TOP - 1), fill=lit(FLAG_FINIAL))
    breeze = 0.6 + min(wind, 25) / 25
    speed = 3.5 + min(wind, 25) * 0.15
    for column in range(len(FLAG_ROWS[0])):
        phase = column * 0.75 - elapsed * speed
        # Ripples grow away from the hoist; their slopes catch more or less light.
        lift = round(breeze * math.sin(phase) * column / 12)
        shade = 1 + 0.2 * math.cos(phase) * min(1, column / 3)
        x = FLAG_POLE_X + 1 + column
        points: dict[str, list[tuple[int, int]]] = {}
        for row, line in enumerate(FLAG_ROWS):
            points.setdefault(line[column], []).append((x, FLAG_TOP + row + lift))
        for char, pixels in points.items():
            d.point(pixels, fill=lit(FLAG_COLORS[char], shade))


def render_outside_frame(environment: "OutsideEnvironment", elapsed: float, seed: int = 0) -> Image.Image:
    palette = scene_palette(environment)
    image = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = min(1, y / 21)
        color = mix(palette.top, palette.middle, t / 0.55) if t < 0.55 else mix(palette.middle, palette.horizon, (t - 0.55) / 0.45)
        d.line((0, y, 127, y), fill=color)
    lightning = lightning_at(environment, elapsed, seed)
    clouds = draw_sky(image, environment, palette, elapsed, lightning, seed)
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
    if fireworks is not None:
        image = reflect_fireworks(image, fireworks, elapsed)
        d = ImageDraw.Draw(image)
    mist = environment.weather.visibility is not None and environment.weather.visibility < 5000
    if mist or environment.weather.code in (701, 711, 721, 741):
        fog = Image.new("RGBA", (WIDTH, HEIGHT))
        fd = ImageDraw.Draw(fog)
        for index in range(3):
            x = round((elapsed * 0.22 + index * 49) % 168) - 40
            fd.ellipse((x, 22 + index, x + 70, 25 + index), fill=(*palette.far, 90))
        image.paste(fog, (0, 0), fog)
    wind = environment.weather.wind or 0
    if "flag" in holidays:
        draw_flag(image, palette, wind, elapsed)
    draw_leaves(image, palette, environment, elapsed, seed)
    draw_wildlife(image, palette, environment, elapsed, seed)
    draw_eagle(image, palette, eagle_state(environment, elapsed, seed), elapsed)
    draw_hut_and_dog(image, palette, *dog_state(environment, elapsed, seed), elapsed)
    draw_fireflies(image, firefly_glows(environment, elapsed, seed))
    sway = round(math.sin(elapsed * 0.6) * min(1, wind / 12))
    if foliage is not None:
        image.paste(foliage, (sway, 0), foliage)
    d = ImageDraw.Draw(image)
    if environment.season == "spring":
        for dx, dy in TREE_BLOSSOMS:
            if environment.sun_altitude is not None and environment.sun_altitude > -5:
                d.point((TREE_X + dx + sway, TREE_CANOPY_Y + dy), fill=mix(palette.leaf_light, (239, 186, 182), 0.45))
    image.paste(wood, (0, 0), wood)
    # The owl perches on the fixed branch, in front of the swaying foliage.
    draw_owl(image, palette, owl_state(environment, elapsed, seed))
    if rain > 0:
        draw_rain(image, rain, wind, elapsed)
    if snow > 0:
        count = min(40, round(10 + snow * 9))
        for x0, y0, pace, phase in PARTICLES[:count]:
            y = int((y0 + elapsed * 1.6 * pace) % 36) - 2
            x = int((x0 + min(wind, 25) * elapsed * 0.035 + math.sin(elapsed * 0.7 + phase) * 2) % 128)
            if 0 <= y < HEIGHT:
                d.point((x, y), fill=mix(image.getpixel((x, y)), (234, 235, 225), 0.65 + (phase % 5) * 0.025))
    lamp = lamp_level(environment)
    if lamp > 0:
        image = draw_lamp_light(image, lamp)
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
    if weather.status == "OFFLINE" or environment.sky_status == "OFFLINE":
        notices.append("OFFLINE")
    if environment.offset_minutes:
        if weather.status in ("FORECAST", "FORECAST_CACHED") and weather.code in WEATHER_DESCRIPTIONS:
            notices.append(WEATHER_DESCRIPTIONS[weather.code].upper() + ("~" if weather.status == "FORECAST_CACHED" else ""))
        elif weather.status != "OFFLINE":
            notices.append("FCST?")
    elif weather.status not in ("LIVE", "OFFLINE"):
        notices.append("WX~" if weather.status == "CACHED" else "WX?")
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
