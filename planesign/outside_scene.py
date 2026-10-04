"""Quiet Valley pixel art. Static geometry is cached; only intended motion changes."""

import math
import os
import random
from dataclasses import dataclass, fields, replace
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING

import shared_config
from emulated_matrix import graphics as bitmap_graphics
from emulated_matrix.core import Canvas
from PIL import Image, ImageDraw
from rgbmatrix import graphics

if TYPE_CHECKING:
    from outside import OutsideEnvironment

Color = tuple[int, int, int]
WIDTH, HEIGHT = 128, 32


def mix(a: Color, b: Color, fraction: float) -> Color:
    fraction = max(0, min(1, fraction))
    return (round(a[0] + (b[0] - a[0]) * fraction), round(a[1] + (b[1] - a[1]) * fraction), round(a[2] + (b[2] - a[2]) * fraction))


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


DUSK = Palette(
    (24, 46, 82), (99, 105, 136), (241, 162, 110), (95, 99, 125), (43, 71, 81), (62, 88, 76), (22, 48, 48), (116, 132, 94),
    (85, 84, 73), (159, 130, 78), (35, 56, 59), (32, 42, 49), (57, 47, 60), (156, 62, 51), (235, 198, 139), (68, 102, 121), (220, 163, 122), (170, 155, 122),
)
DAY = Palette(
    (48, 130, 175), (100, 175, 191), (194, 213, 181), (99, 147, 143), (54, 106, 91), (104, 153, 79), (43, 94, 53), (164, 183, 86),
    (63, 125, 65), (148, 181, 74), (40, 86, 57), (80, 62, 47), (67, 65, 72), (171, 62, 51), (239, 220, 171), (55, 147, 169), (167, 219, 208), (166, 119, 73),
)
NIGHT = Palette(
    (5, 11, 28), (16, 29, 55), (53, 67, 91), (36, 48, 70), (23, 42, 55), (29, 51, 51), (13, 30, 35), (59, 79, 60),
    (46, 62, 60), (83, 98, 70), (26, 44, 47), (18, 26, 34), (23, 28, 43), (78, 47, 50), (139, 149, 146), (34, 65, 85), (129, 159, 171), (122, 127, 108),
)
MATERIALS = tuple(field.name for field in fields(Palette))
INDEX = {name: index + 1 for index, name in enumerate(MATERIALS)}
INDEX["hill"] = len(MATERIALS) + 1


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
    dim = cloud_cover(environment) * (0.16 if rain or snow else 0.09)
    return Palette(*(mix(getattr(palette, name), (45, 60, 75), dim) for name in MATERIALS))


def geometry() -> tuple[Image.Image, Image.Image, Image.Image]:
    land = Image.new("P", (WIDTH, HEIGHT), 0)
    d = ImageDraw.Draw(land)

    def hill(points, material):
        d.polygon([(0, 31), *points, (127, 31)], fill=INDEX[material])

    hill([(0, 21), (14, 17), (28, 19), (43, 16), (57, 18), (72, 14), (91, 17), (108, 16), (127, 20)], "far")
    hill([(0, 23), (20, 21), (35, 22), (57, 20), (76, 22), (97, 19), (127, 23)], "hill")
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
    for mask in (leafy, bare):
        td = ImageDraw.Draw(mask)
        td.line((116, 14, 116, 31), fill=INDEX["trunk"], width=2)
        for dx, dy in [(-8, -3), (7, -2), (-2, -8), (3, -6)]:
            td.line((116, 28, 116 + dx, 16 + dy), fill=INDEX["trunk"])
            if mask is bare:
                td.line((116 + dx, 16 + dy, 115 + dx, 14 + dy), fill=INDEX["trunk"])
    td = ImageDraw.Draw(leafy)
    for y in range(8, 21):
        for x in range(107, 126):
            n = grain(x, y, 12)
            if ((x - 116) / 8.5) ** 2 + ((y - 16) / 6.4) ** 2 < 0.8 + n / 290:
                material = "leaf_dark" if n <= 37 else "leaf"
                if y < 15 and x < 119 and n > 48:
                    material = "leaf_light"
                td.point((x, y), fill=INDEX[material])
    td.line((116, 27, 114, 18), fill=INDEX["trunk"])
    td.line((116, 26, 119, 18), fill=INDEX["trunk"])
    return land, leafy, bare


LAND, LEAFY_TREE, BARE_TREE = geometry()
TREE_FOLIAGE = LEAFY_TREE.point([value if value in (INDEX["leaf"], INDEX["leaf_light"], INDEX["leaf_dark"]) else 0 for value in range(256)])
TREE_WOOD = LEAFY_TREE.point([value if value == INDEX["trunk"] else 0 for value in range(256)])
STARS = tuple((x, y, grain(x, y, 5)) for y in range(1, 14) for x in range(2, 126) if grain(x, y, 9) < 2)
STAR_COLORS = ((232, 244, 255), (255, 239, 207), (225, 231, 255))
RIPPLES = ((60, 27, 15, 0), (55, 28, 9, 2.3), (68, 29, 7, 4.5))
PARTICLES = tuple((grain(i, 3) / 97 * 128, grain(i, 9) / 97 * 35, 0.7 + grain(i, 5) / 97, grain(i, 7)) for i in range(80))
MOON_PIXELS = tuple((x, y, math.sqrt(9 - y * y)) for y in range(-3, 4) for x in range(-3, 4) if x * x + y * y <= 9)


@lru_cache(maxsize=96)
def landscape(palette: Palette, bare: bool, snow: bool):
    table = [0, 0, 0]
    for name in MATERIALS:
        table.extend(getattr(palette, name))
    table.extend(mix(palette.far, palette.ridge, 0.6))
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
    land, foliage, wood = landscape(palette, environment.season == "winter", snow > 0)
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
        for x, y in [(110, 12), (118, 10), (121, 14), (113, 16), (119, 17)]:
            if environment.sun_altitude is not None and environment.sun_altitude > -5:
                d.point((x + sway, y), fill=mix(palette.leaf_light, (239, 186, 182), 0.45))
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
    return image


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


def draw_corner_label(image: Image.Image, text: str, *, right: bool = False):
    mask = overlay_text_mask(text)
    x = WIDTH - mask.width if right else 0
    background = image.crop((x, 0, x + mask.width, mask.height))
    lettering = Image.blend(background, Image.new("RGB", background.size, (205, 218, 231)), 0.28)
    image.paste(lettering, (x, 0), mask)


def draw_outside_frame(sign, environment: "OutsideEnvironment", elapsed: float, seed: int = 0, *, moment: datetime, military_time: bool):
    image = render_outside_frame(environment, elapsed, seed)
    clock = moment.strftime("%H:%M" if military_time else "%-I:%M%p")
    temperature = environment.weather.temperature
    temperature_text = f"{round(temperature)}°F" if temperature is not None and environment.weather.status in ("LIVE", "CACHED") else "--°F"
    draw_corner_label(image, clock)
    draw_corner_label(image, temperature_text, right=True)
    sign.canvas.SetImage(image)
    notices = []
    if environment.weather.status != "LIVE":
        notices.append("WX~" if environment.weather.status == "CACHED" else "WX?")
    if environment.sky_status != "READY":
        notices.append("SKY..." if environment.sky_status == "LOADING" else "SKY?")
    if notices:
        color = graphics.Color(145, 152, 156)
        text = " ".join(notices)
        graphics.DrawText(sign.canvas, sign.font46, WIDTH // 2 - len(text) * 2, 5, color, text)
