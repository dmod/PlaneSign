###
# Physarum slime mould
# Agents sense the trail ahead of them, steer toward the strongest scent and deposit more, so random
# wandering organises itself into a living network of glowing veins.
# https://uwe-repository.worktribe.com/output/980579 (Jones, "Characteristics of pattern formation
# and evolution in approximations of Physarum transport networks")
###

import logging
import math
import random
import time
from dataclasses import dataclass

import numpy as np
import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image

WIDTH = 128
HEIGHT = 32
# Simulate at twice the panel resolution and average down, so veins get anti-aliased edges and
# sub-pixel motion instead of stepping a whole LED at a time.
SCALE = 2
SIM_WIDTH = WIDTH * SCALE
SIM_HEIGHT = HEIGHT * SCALE

FRAME_INTERVAL = 1 / 30
FADE_SECONDS = 1.6
# Sensor angles sway by this fraction over BREATH_PERIOD seconds, so a mature network keeps rerouting.
BREATH_DEPTH = 0.25
BREATH_PERIOD = 23.0
# Display normalisation chases the bright end of the trail so every preset fills the palette.
NORM_PERCENTILE = 99.3
NORM_SMOOTHING = 0.04


def _palette(*stops):
    """256-entry RGB lookup table interpolated between (position, (r, g, b)) stops."""
    positions = [p for p, _ in stops]
    colors = np.array([c for _, c in stops], dtype=np.float32)
    t = np.linspace(0.0, 1.0, 256)
    return np.stack([np.interp(t, positions, colors[:, ch]) for ch in range(3)], axis=1).astype(np.float32)


# Every palette starts black so empty space stays dark and the veins glow against it.
PALETTES = {
    "bioluminescent": _palette((0, (0, 0, 0)), (0.18, (22, 0, 48)), (0.45, (110, 0, 170)), (0.72, (235, 40, 220)), (0.9, (255, 150, 240)), (1, (255, 240, 255))),
    "abyss": _palette((0, (0, 0, 0)), (0.18, (0, 14, 40)), (0.45, (0, 80, 150)), (0.72, (0, 200, 200)), (0.9, (120, 255, 220)), (1, (230, 255, 250))),
    "ember": _palette((0, (0, 0, 0)), (0.18, (40, 4, 0)), (0.45, (170, 30, 0)), (0.72, (255, 120, 0)), (0.9, (255, 210, 60)), (1, (255, 250, 210))),
    "aurora": _palette((0, (0, 0, 0)), (0.18, (0, 30, 18)), (0.45, (0, 140, 70)), (0.72, (60, 240, 120)), (0.9, (190, 255, 120)), (1, (245, 255, 220))),
    "gold": _palette((0, (0, 0, 0)), (0.18, (30, 16, 0)), (0.45, (150, 90, 0)), (0.72, (255, 190, 20)), (0.9, (255, 235, 130)), (1, (255, 255, 235))),
    # Single-hue ramps for competing species: their overlap mixes additively, so they stay dimmer.
    "magenta": _palette((0, (0, 0, 0)), (0.25, (40, 0, 30)), (0.6, (200, 0, 140)), (1, (255, 120, 220))),
    "cyan": _palette((0, (0, 0, 0)), (0.25, (0, 24, 40)), (0.6, (0, 170, 210)), (1, (130, 255, 255))),
    "amber": _palette((0, (0, 0, 0)), (0.25, (40, 14, 0)), (0.6, (230, 110, 0)), (1, (255, 220, 110))),
    "lime": _palette((0, (0, 0, 0)), (0.25, (12, 34, 0)), (0.6, (100, 220, 0)), (1, (210, 255, 140))),
    "violet": _palette((0, (0, 0, 0)), (0.25, (20, 0, 50)), (0.6, (110, 40, 255)), (1, (200, 170, 255))),
}


@dataclass(frozen=True)
class Preset:
    name: str
    palettes: tuple  # one palette name per species
    agents: int  # per species
    sensor_angle: float  # degrees
    sensor_distance: float  # simulation pixels
    turn_angle: float  # degrees
    speed: float  # simulation pixels per step
    deposit: float
    decay: float  # trail kept per step
    diffuse: float  # 0 = no blur, 1 = full 3x3 blur per step
    jitter: float = 0.05  # radians of random wobble per step
    repel: float = 0.0  # how strongly a species avoids the others' trails
    scouts: float = 0.002  # fraction of agents respawned at random each step
    crowd: int = 1  # agents allowed per simulation cell before others are blocked
    spawn: str = "random"
    duration: float = 70.0  # seconds before fading to the next preset


PRESETS = (
    Preset("neural", ("bioluminescent",), 1800, 25, 9, 40, 1.0, 1.0, 0.90, 0.6),
    Preset("rivers", ("abyss",), 2100, 40, 15, 20, 1.1, 1.0, 0.94, 0.5, jitter=0.03, spawn="ring"),
    Preset("lace", ("ember",), 1600, 30, 5, 35, 0.8, 1.0, 0.86, 0.7, spawn="center"),
    Preset("cells", ("aurora",), 2200, 60, 8, 55, 1.0, 1.0, 0.88, 0.5, jitter=0.08),
    Preset("veins", ("gold",), 2000, 22.5, 12, 22.5, 1.2, 1.0, 0.92, 0.4, spawn="line"),
    Preset("rivals", ("magenta", "cyan"), 1200, 30, 10, 35, 1.0, 1.0, 0.90, 0.6, repel=1.0, spawn="sides"),
    # Three species eventually settle into static vertical stripes, so this one moves on sooner.
    Preset("colonies", ("amber", "cyan", "violet"), 900, 30, 9, 40, 1.0, 1.0, 0.90, 0.6, repel=0.7, spawn="sides", duration=30.0),
    Preset("tangle", ("lime", "magenta"), 1200, 45, 7, 45, 1.0, 1.0, 0.89, 0.6, repel=0.35, spawn="center"),
)


class SlimeSim:
    def __init__(self, preset, rng):
        self.preset = preset
        self.rng = rng
        species = len(preset.palettes)
        n = preset.agents * species
        self.species = np.repeat(np.arange(species), preset.agents)
        self.trail = np.zeros((species, SIM_HEIGHT, SIM_WIDTH), dtype=np.float32)
        self.x, self.y, self.heading = self._spawn(preset.spawn, n, species)
        self.norm = None
        # Offset of each agent's species plane in the flattened trail, for sensing and deposits.
        self.plane_offset = (self.species * SIM_WIDTH * SIM_HEIGHT).astype(np.intp)

    def _spawn(self, pattern, n, species):
        rng = self.rng
        cx, cy = SIM_WIDTH / 2, SIM_HEIGHT / 2
        if pattern == "center":
            angle = rng.uniform(0, 2 * math.pi, n)
            radius = np.sqrt(rng.uniform(0, 1, n)) * SIM_HEIGHT * 0.3
            x = cx + np.cos(angle) * radius * 2
            y = cy + np.sin(angle) * radius
            heading = angle
        elif pattern == "ring":
            angle = rng.uniform(0, 2 * math.pi, n)
            x = cx + np.cos(angle) * SIM_WIDTH * 0.42
            y = cy + np.sin(angle) * SIM_HEIGHT * 0.42
            heading = np.arctan2(cy - y, cx - x)
        elif pattern == "line":
            x = rng.uniform(0, SIM_WIDTH, n)
            y = cy + rng.normal(0, 1.5, n)
            heading = np.where(rng.random(n) < 0.5, -math.pi / 2, math.pi / 2) + rng.normal(0, 0.6, n)
        elif pattern == "sides":
            # Each species starts in its own vertical band, so the colonies collide in the middle.
            band = SIM_WIDTH / species
            x = (self.species + rng.uniform(0.15, 0.85, n)) * band
            y = rng.uniform(0, SIM_HEIGHT, n)
            heading = rng.uniform(0, 2 * math.pi, n)
        else:
            x = rng.uniform(0, SIM_WIDTH, n)
            y = rng.uniform(0, SIM_HEIGHT, n)
            heading = rng.uniform(0, 2 * math.pi, n)
        return (x % SIM_WIDTH).astype(np.float32), (y % SIM_HEIGHT).astype(np.float32), heading.astype(np.float32)

    def _sense(self, field, angle, distance):
        sx = (self.x + np.cos(angle) * distance).astype(np.intp) % SIM_WIDTH
        sy = (self.y + np.sin(angle) * distance).astype(np.intp) % SIM_HEIGHT
        return field[self.plane_offset + sy * SIM_WIDTH + sx]

    def _cells(self, x, y):
        # float32 modulo can round a tiny negative up to exactly SIM_WIDTH, so wrap the index too.
        return self.plane_offset + (y.astype(np.intp) % SIM_HEIGHT) * SIM_WIDTH + x.astype(np.intp) % SIM_WIDTH

    def step(self, breath):
        p = self.preset
        rng = self.rng
        n = self.x.size

        field = self.trail
        if p.repel and field.shape[0] > 1:
            field = field * (1 + p.repel) - field.sum(axis=0) * p.repel
        field = field.ravel()

        sensor_angle = math.radians(p.sensor_angle) * breath
        left = self._sense(field, self.heading - sensor_angle, p.sensor_distance)
        front = self._sense(field, self.heading, p.sensor_distance)
        right = self._sense(field, self.heading + sensor_angle, p.sensor_distance)

        coin = np.where(rng.random(n) < 0.5, -1.0, 1.0)
        turn = np.where((front >= left) & (front >= right), 0.0, np.where((front < left) & (front < right), coin, np.where(right > left, 1.0, -1.0)))
        self.heading += (turn * math.radians(p.turn_angle) + rng.normal(0, p.jitter, n)).astype(np.float32)

        # Occupancy exclusion (Jones's rule): an agent whose next cell is already crowded stays put
        # and picks a new heading. This keeps veins a few agents wide, so the network stays
        # reticulated instead of collapsing into a handful of lines.
        here = self._cells(self.x, self.y)
        new_x = (self.x + np.cos(self.heading) * p.speed) % SIM_WIDTH
        new_y = (self.y + np.sin(self.heading) * p.speed) % SIM_HEIGHT
        there = self._cells(new_x, new_y)
        occupancy = np.bincount(here, minlength=self.trail.size)
        moved = (there == here) | (occupancy[there] < p.crowd)
        self.x = np.where(moved, new_x, self.x)
        self.y = np.where(moved, new_y, self.y)
        stuck = ~moved
        self.heading[stuck] = rng.uniform(0, 2 * math.pi, int(stuck.sum()))

        # Scouts: a few agents restart somewhere random each step and seed fresh branches.
        scouts = rng.random(n) < p.scouts
        count = int(scouts.sum())
        if count:
            self.x[scouts] = rng.uniform(0, SIM_WIDTH, count)
            self.y[scouts] = rng.uniform(0, SIM_HEIGHT, count)
            self.heading[scouts] = rng.uniform(0, 2 * math.pi, count)

        deposits = np.bincount(there[moved], minlength=self.trail.size).astype(np.float32)
        self.trail += deposits.reshape(self.trail.shape) * p.deposit

        # Separable 3x3 box blur on a torus, blended in by `diffuse`, then evaporation.
        t = self.trail
        horizontal = t + np.roll(t, 1, axis=2) + np.roll(t, -1, axis=2)
        blurred = (horizontal + np.roll(horizontal, 1, axis=1) + np.roll(horizontal, -1, axis=1)) * (1 / 9)
        t += (blurred - t) * p.diffuse
        t *= p.decay

    def render(self, brightness=1.0):
        species = self.trail.shape[0]
        small = self.trail.reshape(species, HEIGHT, SCALE, WIDTH, SCALE).mean(axis=(2, 4))

        target = np.percentile(small.reshape(species, -1), NORM_PERCENTILE, axis=1)
        target = np.maximum(target, 1e-3)
        self.norm = target if self.norm is None else self.norm + (target - self.norm) * NORM_SMOOTHING

        # Soft saturation keeps faint fog visible without blowing the trunks out to white.
        tone = 1.0 - np.exp(-small / (self.norm[:, None, None] * 0.8))
        index = np.clip(tone * 255, 0, 255).astype(np.intp)
        rgb = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
        for s, name in enumerate(self.preset.palettes):
            rgb += PALETTES[name][index[s]]
        if brightness < 1.0:
            rgb *= brightness
        return np.clip(rgb, 0, 255).astype(np.uint8)


def preset_order(rng):
    """Shuffled presets, repeated forever, without the same preset twice in a row."""
    last = None
    while True:
        order = list(PRESETS)
        rng.shuffle(order)
        if order[0] is last:
            order.append(order.pop(0))
        yield from order
        last = order[-1]


@planesign_mode_handler(DisplayMode.SLIME)
def slime(sign):
    seed = random.randrange(2**32)
    rng = np.random.default_rng(seed)
    presets = preset_order(random.Random(seed))
    sim = SlimeSim(next(presets), rng)
    logging.info(f"Slime preset: {sim.preset.name}")

    start = time.perf_counter()
    preset_started = start
    fading_since = None
    next_frame = start

    while shared_config.shared_mode.value == DisplayMode.SLIME.value:
        now = time.perf_counter()
        breath = 1.0 + BREATH_DEPTH * math.sin((now - start) * 2 * math.pi / BREATH_PERIOD)

        brightness = min(1.0, (now - preset_started) / FADE_SECONDS)
        if fading_since is None and now - preset_started >= sim.preset.duration:
            fading_since = now
        if fading_since is not None:
            brightness = max(0.0, 1.0 - (now - fading_since) / FADE_SECONDS)
            if brightness == 0.0:
                sim = SlimeSim(next(presets), rng)
                logging.info(f"Slime preset: {sim.preset.name}")
                preset_started = now
                fading_since = None

        sim.step(breath)
        frame = Image.fromarray(sim.render(brightness), "RGB")
        sign.canvas.SetImage(frame, 0, 0)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        next_frame = max(next_frame + FRAME_INTERVAL, time.perf_counter() - FRAME_INTERVAL)
        if sign.wait_loop(max(0.0, next_frame - time.perf_counter())):
            return
