"""Pixel artwork for Moon mode. Astronomy is recomputed separately from decorative motion."""

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from skyfield.constants import AU_KM

WIDTH, HEIGHT = 128, 32
CHART_LEFT = 74
# Unlit LEDs: any tint here lights the whole panel and reads as grey haze rather than space.
BACKGROUND = (0, 0, 0)
SUN_CORE = np.array((255, 238, 168))
SUN_LIMB = np.array((255, 150, 24))
SUN_GLOW = np.array((235, 86, 12))
SUN_RADIUS = 9
SUN_SHOWN = 12  # pixels of the disk inside the chart, measured from its edge toward the true Sun
SUN_CLEAR_X = 73  # the longest readouts end at x=71; keep a 1px gap


@dataclass
class OrbitLayout:
    sun: np.ndarray
    earth: np.ndarray
    moon: np.ndarray
    moon_sunward: np.ndarray
    annual_track: np.ndarray
    lunar_track: np.ndarray


def orbit_layout(year_path, earth_au, moon_km, lunar_path):
    """Orthographic view from ecliptic north; positive longitude turns left from twelve o'clock."""
    x, y = year_path[:, 0] / np.linalg.norm(year_path[:, 0])
    basis = np.array(((y, -x), (-x, -y)))
    # Uniform scales within each orbit preserve bearings, inclination foreshortening and eccentricity.
    annual = basis * 43  # pixels/AU
    lunar = basis * (18 / 384400)  # pixels/km
    offset = lunar @ moon_km
    # Translate both bodies together, never squash the orbit to fit the 32-row display.
    earth = np.array((104, 15.5 - 0.46 * offset[1]))
    sun = earth - annual @ earth_au
    # Lighting uses true vectors, not the greatly exaggerated Earth-Moon gap on the sign.
    moon_sunward = basis @ (-earth_au - moon_km / AU_KM)
    return OrbitLayout(sun, earth, earth + offset, moon_sunward, (annual @ year_path).T + sun, (lunar @ lunar_path).T + earth)


@dataclass
class MoonView:
    layout: OrbitLayout
    phase: str
    phase_angle: float
    limb_angle: float
    pole_angle: float
    direction: str
    altitude: int
    distance: int
    full_date: str


def sphere(radius):
    y, x = np.mgrid[-radius : radius + 1, -radius : radius + 1] / (radius + 0.18)
    depth = 1 - x * x - y * y
    return x, y, np.sqrt(np.maximum(0, depth)), depth >= 0


def paste_disk(layer, center, rgb, mask):
    sprite = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    origin = tuple(np.rint(center).astype(int) - sprite.width // 2)
    layer.paste(sprite, origin, Image.fromarray(mask))


def draw_portrait(layer, view, texture):
    x, y, z, mask = sphere(9)
    # Skyfield's horizon position angle is positive toward the viewer's LEFT.
    light = -math.sin(view.phase_angle) * (x * math.sin(view.limb_angle) + y * math.cos(view.limb_angle)) + z * math.cos(view.phase_angle)
    albedo = np.asarray(texture.rotate(view.pole_angle, Image.Resampling.BICUBIC).resize((19, 19), Image.Resampling.LANCZOS))
    night = 11 + 0.025 * albedo
    day = 75 + 0.81 * albedo
    level = night + (day - night) * np.maximum(0, light) ** 0.38
    paste_disk(layer, (13, 16), np.stack((level - 2, level, level + 8), axis=-1), mask)


def draw_body(layer, center, sunward, radius, terrestrial):
    x, y, _, mask = sphere(radius)
    dx, dy = sunward / np.linalg.norm(sunward)
    light = np.maximum(0, dx * x + dy * y) ** 0.6
    if terrestrial:
        land = np.sin(5.1 * x + 2 * y) + 0.64 * np.cos(7 * y - 2.2 * x) + 0.4 * np.sin(9 * (x + y)) > 0.52
        night = (6, 14, 34) + land[..., None] * (2, 5, 8)
        day = (35, 95, 184) + land[..., None] * (10, 31, 27)
        rgb = night + light[..., None] * (day - night)
    else:
        grain = np.sin(4 * x + y)
        night = 17 + 2 * grain
        day = 218 + 9 * grain
        tone = night + (day - night) * light
        rgb = np.stack((tone, tone + 2, tone + 9), axis=-1)
    paste_disk(layer, center, rgb, mask)


def star_catalog():
    rng = np.random.default_rng(421)
    count = 64
    positions = rng.choice(WIDTH * HEIGHT, count, replace=False)
    # Mostly faint dust with a scattering of brighter points; tints stay close to white.
    brightness = 14 + 150 * rng.uniform(0, 1, count) ** 5
    tint = np.array(((1, 1, 1), (0.78, 0.88, 1), (1, 0.88, 0.72)))[rng.choice(3, count, p=(0.55, 0.3, 0.15))]
    return positions % WIDTH, positions // WIDTH, rng.uniform(0, math.tau, count), rng.uniform(0.55, 1.5, count), brightness[:, None] * tint


STARS = star_catalog()

# Hand-placed in the gaps between the readouts so their glints never touch text: (x, y, rgb, spike length).
HERO_STARS = ((66, 3, (205, 225, 255), 2), (67, 19, (255, 214, 150), 1), (124, 28, (190, 240, 255), 2), (25, 16, (255, 196, 214), 1), (90, 2, (255, 246, 220), 1), (79, 12, (200, 220, 255), 1), (117, 5, (255, 226, 180), 1), (100, 30, (235, 240, 255), 1))


def draw_hero_star(pixels, x, y, rgb, spikes, phase, elapsed):
    shine = 0.8 + 0.2 * math.sin(phase + 0.9 * elapsed)
    # A brief, sharp glint every few seconds stretches the spikes like a lens flare.
    glint = max(0.0, math.sin(phase * 3 + 0.45 * elapsed)) ** 24
    rgb = np.asarray(rgb, dtype=float)
    reach = spikes + (1 if glint > 0.3 else 0)
    for distance in range(1, reach + 1):
        level = shine * (0.5 if distance == 1 else 0.2 / (distance - 1)) * (1 + glint)
        for dx, dy in ((distance, 0), (-distance, 0), (0, distance), (0, -distance)):
            if 0 <= x + dx < WIDTH and 0 <= y + dy < HEIGHT:
                pixels[y + dy, x + dx] = np.maximum(pixels[y + dy, x + dx], np.minimum(255, rgb * level))
    if spikes > 1:
        for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            if 0 <= x + dx < WIDTH and 0 <= y + dy < HEIGHT:
                pixels[y + dy, x + dx] = np.maximum(pixels[y + dy, x + dx], rgb * 0.1 * shine)
    pixels[y, x] = np.minimum(255, rgb * (shine + 0.25 * glint))


def sun_center(layout, radius):
    """Where to draw the Sun's disk: on the chart edge nearest the true Sun, which always lies beyond it.

    Showing more than half the disk keeps it round. When Earth sits too close to that edge,
    slide along the edge to the closest clear spot rather than overlapping Earth or showing a sliver.
    """
    out = radius - SUN_SHOWN
    nearest = np.clip(layout.sun, (CHART_LEFT, 0), (WIDTH - 1, HEIGHT - 1))
    away = layout.sun - nearest
    ideal = nearest + away / np.linalg.norm(away) * out
    xs, ys = np.arange(CHART_LEFT, WIDTH, 0.5), np.arange(0, HEIGHT, 0.5)
    candidates = np.concatenate((np.column_stack((xs, np.full_like(xs, -out))), np.column_stack((xs, np.full_like(xs, HEIGHT - 1 + out))), np.column_stack((np.full_like(ys, WIDTH - 1 + out), ys)), np.column_stack((np.full_like(ys, CHART_LEFT - out), ys))))
    candidates[:, 0] = np.maximum(candidates[:, 0], SUN_CLEAR_X + radius)
    clear = np.linalg.norm(candidates - layout.earth, axis=1) >= 6 + radius + 2
    if not clear.any():
        return ideal
    candidates = candidates[clear]
    return candidates[np.argmin(np.linalg.norm(candidates - ideal, axis=1))]


class MoonScene:
    def __init__(self, view, texture):
        self.view = view
        layout = view.layout
        tracks = Image.new("RGBA", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(tracks)
        for path, color in ((layout.annual_track, "#2c3e62"), (layout.lunar_track, "#223f66")):
            draw.line([tuple(p) for p in path], fill=color)
        jx, jy = np.rint(layout.annual_track[0]).astype(int)
        draw.line((jx, jy - 1, jx, jy + 1), fill="#cb975b")
        draw.rectangle((0, 0, CHART_LEFT - 1, HEIGHT - 1), fill=(0, 0, 0, 0))
        tracks = np.asarray(tracks)
        self.track_pixels = tracks[..., 3] > 0
        self.track_colors = tracks[self.track_pixels][:, :3]
        self.ink = Image.new("RGBA", (WIDTH, HEIGHT))
        draw_body(self.ink, layout.earth, layout.sun - layout.earth, 6, True)
        draw_body(self.ink, layout.moon, layout.moon_sunward, 3, False)
        draw_portrait(self.ink, view, texture)

        radius = SUN_RADIUS
        sx, sy = sun_center(layout, radius)
        yy, xx = np.mgrid[:HEIGHT, CHART_LEFT - 10 : WIDTH]
        depth = np.hypot(xx - sx, yy - sy) - radius
        near = depth < 14
        self.solar_pixels = yy[near], xx[near]
        h = depth[near]
        # Limb darkening: pale gold in the middle, deepening to orange at the edge.
        mu = np.sqrt(np.clip(1 - ((h + radius) / radius) ** 2, 0, 1))[:, None]
        self.disk = SUN_LIMB + (SUN_CORE - SUN_LIMB) * mu**0.7
        self.coverage = np.clip(0.5 - h, 0, 1)[:, None]
        outside = np.maximum(h - 0.5, 0)[:, None]
        # The corona starts well below the limb's brightness so the surface edge stays crisp.
        self.halo = np.exp(-outside / 1.2)
        self.corona = np.exp(-outside / 4)
        smooth = np.clip((xx[near] - CHART_LEFT + 10) / 12, 0, 1)
        self.fade = (smooth * smooth * (3 - 2 * smooth))[:, None]

    def frame(self, elapsed):
        pixels = np.full((HEIGHT, WIDTH, 3), BACKGROUND, dtype=np.uint8)
        x, y, phase, speed, color = STARS
        pixels[y, x] = color * (0.78 + 0.22 * np.sin(phase + elapsed * speed))[:, None]
        for i, star in enumerate(HERO_STARS):
            draw_hero_star(pixels, *star, phase[i], elapsed)
        pixels[self.track_pixels] = self.track_colors

        breath = 0.5 - 0.5 * math.cos(math.tau * elapsed / 6)
        glow = (0.3 * self.halo + (0.16 + 0.05 * breath) * self.corona) * SUN_GLOW
        lit = np.maximum(pixels[self.solar_pixels], self.fade * glow)
        pixels[self.solar_pixels] = lit + self.coverage * (self.disk - lit)
        image = Image.fromarray(pixels)
        image.paste(self.ink, mask=self.ink.getchannel("A"))
        return image
