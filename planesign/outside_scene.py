"""Quiet Valley pixel art. Static geometry is cached; only intended motion changes."""

import math
import os
import random
from dataclasses import dataclass, fields, replace
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
import shared_config
from emulated_matrix import graphics as bitmap_graphics
from emulated_matrix.core import Canvas
from PIL import Image, ImageDraw, ImageStat
from rgbmatrix import graphics

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


def draw_sky(image: Image.Image, environment: "OutsideEnvironment", palette: Palette, elapsed: float):
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
    if altitude is not None and altitude > -0.833:
        cx, cy = celestial_position(altitude, environment.sun_azimuth)
        sun = mix((255, 164, 94), (255, 235, 170), altitude / 20)
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=mix(palette.middle, sun, 0.23))
        d.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=sun)
    if environment.moon_altitude is not None and environment.moon_altitude > 0:
        cx, cy = celestial_position(environment.moon_altitude, environment.moon_azimuth)
        phase = math.radians(environment.moon_phase)
        fraction = (1 - math.cos(phase)) / 2
        strength = max(0.18, night) * (1 - cover * 0.5)
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
    wind = environment.weather.wind or 0
    cloud_count = 1 + round(cover * 5)
    for index in range(cloud_count):
        width = 16 + (index * 7) % 19
        x = round(((index * 37 + 12 + elapsed * (0.18 + min(30, wind) * 0.02)) % (128 + width)) - width)
        y = 3 + (index * 5) % 11
        color = mix(palette.middle, palette.horizon, 0.22 + index * 0.07)
        if cover > 0.65:
            color = mix(color, palette.roof, cover * 0.35)
        d.line((x + 3, y, x + width - 5, y), fill=color)
        d.line((x + 7, y - 1, x + width - 9, y - 1), fill=mix(color, palette.top, 0.1))
        d.line((x, y + 1, x + width, y + 1), fill=mix(color, palette.middle, 0.2))


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


def render_outside_frame(environment: "OutsideEnvironment", elapsed: float, seed: int = 0) -> Image.Image:
    palette = scene_palette(environment)
    image = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(image)
    for y in range(HEIGHT):
        t = min(1, y / 21)
        color = mix(palette.top, palette.middle, t / 0.55) if t < 0.55 else mix(palette.middle, palette.horizon, (t - 0.55) / 0.45)
        d.line((0, y, 127, y), fill=color)
    draw_sky(image, environment, palette, elapsed)
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
    for kind, rate in (("rain", rain), ("snow", snow)):
        if rate <= 0:
            continue
        count = min(70 if kind == "rain" else 40, round(10 + rate * 9))
        for index, (x0, y0, pace, phase) in enumerate(PARTICLES[:count]):
            falling = 8 * pace if kind == "rain" else 1.6 * pace
            y = int((y0 + elapsed * falling) % 36) - 2
            drift = min(wind, 25) * elapsed * (0.1 if kind == "rain" else 0.035)
            x = int((x0 + drift + (math.sin(elapsed * 0.7 + phase) * 2 if kind == "snow" else 0)) % 128)
            if 0 <= y < HEIGHT:
                base = image.getpixel((x, y))
                color = mix(base, (192, 209, 220) if kind == "rain" else (234, 235, 225), (0.25 if kind == "rain" else 0.65) + (phase % 5) * 0.025)
                d.point((x, y), fill=color)
                if kind == "rain" and index % 3 == 0:
                    d.point((max(0, x - 1), min(31, y + 1)), fill=mix(base, color, 0.6))
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


def draw_corner_label(image: Image.Image, text: str, *, right: bool = False, previous_dark: bool | None = None) -> bool:
    mask = overlay_text_mask(text)
    x = WIDTH - mask.width if right else 0
    background = image.crop((x, 0, x + mask.width, mask.height))
    luminance = overlay_relative_luminance(background, mask)
    threshold = OVERLAY_POLARITY_LUMINANCE + (OVERLAY_POLARITY_HYSTERESIS if previous_dark is False else -OVERLAY_POLARITY_HYSTERESIS if previous_dark is True else 0)
    dark_text = luminance >= threshold
    if dark_text:
        lettering = Image.new("RGB", background.size)
    else:
        contrast = overlay_contrast_fraction(luminance)
        color = mix((205, 218, 231), (255, 255, 255), contrast)
        opacity = OVERLAY_NIGHT_OPACITY + (1 - OVERLAY_NIGHT_OPACITY) * contrast
        lettering = Image.blend(background, Image.new("RGB", background.size, color), opacity)
    image.paste(lettering, (x, 0), mask)
    return dark_text


def draw_outside_frame(sign, environment: "OutsideEnvironment", elapsed: float, seed: int = 0, *, moment: datetime, military_time: bool, previous_text_styles: tuple[bool | None, bool | None] = (None, None)) -> tuple[bool, bool]:
    image = render_outside_frame(environment, elapsed, seed)
    clock = moment.strftime("%H:%M" if military_time else "%-I:%M%p")
    temperature = environment.weather.temperature
    temperature_text = f"{round(temperature)}°F" if temperature is not None and environment.weather.status in ("LIVE", "CACHED", "FORECAST", "FORECAST_CACHED") else "--°F"
    clock_dark = draw_corner_label(image, clock, previous_dark=previous_text_styles[0])
    temperature_dark = draw_corner_label(image, temperature_text, right=True, previous_dark=previous_text_styles[1])
    sign.canvas.SetImage(image)
    notices = []
    if environment.offset_minutes:
        notices.append("FCST" if environment.weather.status == "FORECAST" else "FCST~" if environment.weather.status == "FORECAST_CACHED" else "FCST?")
    elif environment.weather.status != "LIVE":
        notices.append("WX~" if environment.weather.status == "CACHED" else "WX?")
    if environment.sky_status != "READY":
        notices.append("SKY..." if environment.sky_status == "LOADING" else "SKY?")
    if notices:
        color = graphics.Color(145, 152, 156)
        text = " ".join(notices)
        graphics.DrawText(sign.canvas, sign.font46, WIDTH // 2 - len(text) * 2, 5, color, text)
    return clock_dark, temperature_dark
