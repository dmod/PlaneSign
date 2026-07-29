#!/usr/bin/python3
# -*- coding: utf-8 -*-

###
# Arcade style horse race. Four horses, a random race every time, no predetermined winner.
###

import logging
import math
import os
import random
import subprocess
import time

from PIL import Image, ImageDraw, ImageEnhance
from rgbmatrix import graphics

import shared_config
import utilities
import __main__
from modes import DisplayMode


WIDTH = 128
HEIGHT = 32
LANE_H = 8
NUM_HORSES = 4

HUD_W = 5  # left strip reserved for the lane numbers

RACE_LENGTH = 1000.0  # track length in world units
TARGET_DURATION = 20.0  # seconds the race should take
BASE_SPEED = RACE_LENGTH / TARGET_DURATION

PX_PER_UNIT = 1.5  # world units -> screen pixels
LEADER_X = 95  # where the leader's nose sits once the camera is scrolling
START_X = 30  # where the noses sit at the gate
FINISH_X = 104  # where the finish line parks itself, leaving room to pull up after it

LEAD_UNITS = (LEADER_X - HUD_W) / PX_PER_UNIT
CAMERA_START = -(START_X - HUD_W) / PX_PER_UNIT
CAMERA_FINISH = RACE_LENGTH - (FINISH_X - HUD_W) / PX_PER_UNIT

FRAME_DT = 1.0 / 30.0

COUNTDOWN_STEP = 0.9  # seconds per "3" / "2" / "1"
GO_FLASH_TIME = 0.8  # how long "GO!" flashes once they break
FINISH_HOLD = 1.7  # seconds of racing after the winner crosses
BANNER_INTRO = 0.35  # fade in before the winner banner flashes

PHOTO_FINISH_GAP = 5.0  # world units between 1st and 2nd for a photo finish
SLOWMO_ZONE = 26.0  # units from the line where the slow motion kicks in
SLOWMO_SCALE = 0.28
HOMESTRETCH_SCALE = 0.7  # every finish gets a little drama on the run in
PULL_UP_DECAY = 0.82  # per frame speed decay once a horse is over the line

DIRT_COLOR = (26, 15, 9)
HUD_COLOR = (7, 6, 8)
RAIL_COLOR = (70, 58, 46)
DUST_COLOR = (150, 122, 86)
WHITE = (255, 255, 255)

# Lane identity: the saddle cloth, the jockey silks and the lane number all use this.
# Deliberately not horse coloured so it never blends into a coat.
LANE_ACCENTS = [(235, 70, 45), (60, 140, 255), (70, 225, 100), (255, 80, 210)]

# Real horse coats, one drawn at random per horse. "sock" is the leg marking, kept light
# so the gallop still reads against the dirt.
COAT_STYLES = [
    {"name": "chestnut", "body": (165, 82, 38), "mane": (205, 130, 65), "sock": (235, 200, 165)},
    {"name": "bay", "body": (128, 68, 32), "mane": (58, 46, 42), "sock": (225, 205, 180)},
    {"name": "cream", "body": (233, 214, 176), "mane": (250, 242, 224), "sock": (250, 244, 230)},
    {"name": "buckskin", "body": (206, 158, 82), "mane": (62, 50, 44), "sock": (232, 214, 180)},
    {"name": "dun", "body": (186, 154, 100), "mane": (70, 58, 48), "sock": (228, 214, 186)},
    {"name": "silver dapple", "body": (124, 100, 96), "mane": (214, 206, 202), "sock": (222, 214, 210)},
    {"name": "roan", "body": (192, 134, 118), "mane": (128, 66, 50), "sock": (236, 216, 206)},
    {"name": "grey", "body": (178, 178, 186), "mane": (238, 238, 244), "sock": (245, 245, 250)},
]

CONFETTI_COLORS = [(255, 70, 70), (255, 200, 40), (70, 220, 120), (80, 160, 255), (240, 100, 230), (255, 255, 255)]

# Chiptune backing, see sounds/horse_race/generate_music.py
FFPLAY = "/usr/bin/ffplay"
MUSIC_DIR = os.path.join(shared_config.sounds_dir, "horse_race")
POST_CALL = "post_call.mp3"  # bugle over the countdown
RACE_LOOP = "race_gallop.mp3"  # gallop groove, looped for as long as they are running
WIN_FANFARE = "win_fanfare.mp3"  # victory sting as the winner hits the line

# Pixel art, 9 wide x 6 tall, facing right, muzzle on column 8 and hooves on row 5.
#   H = coat, M = mane / tail, B = saddle cloth (lane accent), J = jockey silk, D = sock
GALLOP_FRAMES = [
    ("...J..MHH", "...JJJHHH", "MHBBBHHH.", ".HHHHHH..", ".H....H..", "D......D."),
    ("...J..MHH", "...JJJHHH", "MHBBBHHH.", ".HHHHHH..", "..H..H...", ".D....D.."),
    ("...J..MHH", "M..JJJHHH", "MHBBBHHH.", ".HHHHHH..", "..H.H....", "..DD....."),
    ("...J..MHH", "M..JJJHHH", "MHBBBHHH.", ".HHHHHH..", ".H...H...", "D...D...."),
]

# Airborne bounce for the tucked up frames of the gallop cycle
GALLOP_BOB = [0, -1, -1, 0]

IDLE_FRAMES = [("...J..MHH", "...JJJHHH", "MHBBBHHH.", ".HHHHHH..", ".H...H...", ".D...D..."), ("...J..MHH", "M..JJJHHH", "MHBBBHHH.", ".HHHHHH..", ".H...H...", ".D...D..."), ("...J..M.H", "M..JJJHHH", "MHBBBHHH.", ".HHHHHH..", ".H...H...", ".D..D....")]

SPRITE_W = 9
SPRITE_H = 6
NOSE_DX = 8

# Winner's enclosure portrait, 26 wide x 21 tall, standing and facing right.
#   H = coat, M = mane / tail, B = saddle cloth, D = sock, S = smile
#   E = open eye only, P = pupil, W = closed eye only
WINNER_FRAME = (
    "...................H.H....",
    "..................MHHHHH..",
    "..................MHEEHHH.",
    ".................MHWPWHHHH",
    "...............MMHHHHHHHHS",
    "..............MMHHHHHHHSS.",
    ".............MMHHHHHHH....",
    "............MMHHHHHHH.....",
    "...........MMHHHHHHH......",
    "......HHHHHHHHHHHHHHH.....",
    "..MMHHHHHHHHHHHHHHHHHH....",
    "..MHHHHHHHBBBBBHHHHHHH....",
    "..MHHHHHHHBBBBBHHHHHHH....",
    "..MHHHHHHHHHHHHHHHHHH.....",
    ".MM.HHHHHHHHHHHHHHHH......",
    ".MM..HHH........HHH.......",
    "..M..HHH........HHH.......",
    ".....HHH........HHH.......",
    ".....HHH........HHH.......",
    ".....HHH........HHH.......",
    ".....DDD........DDD.......",
)
WINNER_H = 21

# The groom who brings the garland out, 6 wide x 10 tall, facing left
#   C = cap, K = skin, A = arm, J = jacket, T = trousers, O = boots
GROOM_FRAMES = [
    ("..CC..", ".CCCC.", "..KK..", ".JJJJ.", "AJJJJ.", ".JJJJ.", ".JJJJ.", ".TT.TT", ".TT.TT", ".OO.OO"),
    ("..CC..", ".CCCC.", "..KK..", ".JJJJ.", ".JJJJ.", "AJJJJ.", ".JJJJ.", "..TT..", "..TT..", ".OOOO."),
    ("A.CC..", "ACCCC.", "A.KK..", "AJJJJ.", ".JJJJ.", ".JJJJ.", ".JJJJ.", ".TT.TT", ".TT.TT", ".OO.OO"),
    ("..CC..", ".CCCC.", "A.KK..", "AJJJJ.", ".JJJJ.", ".JJJJ.", ".JJJJ.", ".TT.TT", ".TT.TT", ".OO.OO"),
]
GROOM_WALK = (0, 1)
GROOM_REACH = 2
GROOM_WAVE = (2, 3)
GROOM_H = 10

# Ring of flowers, coloured per pixel from GARLAND_COLORS
GARLAND_FRAME = ("..FFFFF..", ".F.....F.", "F.......F", "F.......F", "F.......F", ".F.....F.", "..FFFFF..")
GARLAND_COLORS = [(235, 45, 70), (255, 250, 245), (250, 205, 70), (235, 45, 70), (110, 195, 95), (255, 250, 245), (250, 205, 70), (110, 195, 95)]

# Winner's pennant numerals, 5 wide x 7 tall.
# Only 1-4 can come up today but the whole set keeps it safe if the field ever grows.
FLAG_DIGITS = {
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "...#.", "..##.", "....#", "#...#", ".###."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
}
FLAG_DIGIT_H = 7


def _compile_frames(frames):
    compiled = []
    for frame in frames:
        pixels = []
        for dy, row in enumerate(frame):
            for dx, code in enumerate(row):
                if code != ".":
                    pixels.append((dx, dy, code))
        compiled.append(pixels)
    return compiled


GALLOP_SPRITES = _compile_frames(GALLOP_FRAMES)
IDLE_SPRITES = _compile_frames(IDLE_FRAMES)
WINNER_SPRITE = _compile_frames([WINNER_FRAME])[0]
WINNER_W = max(dx for dx, dy, _ in WINNER_SPRITE) + 1
GROOM_SPRITES = _compile_frames(GROOM_FRAMES)
GARLAND_PIXELS = _compile_frames([GARLAND_FRAME])[0]
FLAG_DIGIT_PIXELS = {digit: _compile_frames([rows])[0] for digit, rows in FLAG_DIGITS.items()}

# Winner's enclosure layout, everything stands on the bottom row
GROOM_SCALE = 2  # the groom is drawn twice life size so he reads next to the horse
BANNER_HORSE_X = 48
BANNER_HORSE_Y = HEIGHT - WINNER_H
BANNER_GROOM_X = BANNER_HORSE_X + WINNER_W + 3  # a little breathing room beside the horse
BANNER_GROOM_Y = HEIGHT - GROOM_H * GROOM_SCALE
GARLAND_HOME = (BANNER_HORSE_X + 12, BANNER_HORSE_Y + 5)
GARLAND_CARRY = (BANNER_GROOM_X - 10, BANNER_GROOM_Y + 3)
GROOM_WALK_SPEED = 46.0
CROWN_TIME = 0.85
WINK_START = 0.25
WINK_END = 0.6
FLIP_DELAY = 0.3  # pause after the garland lands before the victory flip
FLIP_DURATION = 0.9  # seconds for the full 360
FLIP_JUMP_HEIGHT = 8.0  # px of hop while spinning

# Winner's pennant. It lives in the empty strip left of the horse: the winner sprite starts at x 49
# and the "HORSE N WINS!" caption starts at x 31, so staying at x <= 30 buys the full panel height.
FLAG_POLE_X = 2
FLAG_POLE_COLORS = ((152, 148, 160), (92, 88, 102))
FLAG_FINIAL_COLOR = (250, 205, 70)
FLAG_FABRIC_X = FLAG_POLE_X + 2  # fabric hangs off the right hand side of the pole
FLAG_LEN = 14  # pole to apex, leaving more open space beside the winner
FLAG_H = 14  # base height where it is lashed to the pole
FLAG_TOP_Y = 3  # the smaller flag occupies only the upper portion of the pole
FLAG_STOWED_Y = HEIGHT + 4  # starts below the panel so it climbs into view
FLAG_HOIST_DELAY = 0.25
FLAG_HOIST_TIME = 1.4
FLAG_SETTLE = 3.0  # px of recoil as the halyard snaps taut at the top
FLAG_WAVE_AMP = 2.0  # px of flap at the free end
FLAG_WAVE_SPEED = 6.5  # radians per second
FLAG_WAVE_FREQ = 0.42  # radians per column, so the ripple travels out along the fabric
FLAG_DIGIT_DX = 1  # digit columns 1..5, where the triangle still clears the 7px glyph


def _scale_color(color, factor):
    return (min(255, max(0, int(color[0] * factor))), min(255, max(0, int(color[1] * factor))), min(255, max(0, int(color[2] * factor))))


def _ink_color(color):
    """Eye and smile shade that stays readable on any coat."""
    luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    return (28, 22, 26) if luminance > 110 else (245, 238, 232)


def _put(pix, x, y, color):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        pix[x, y] = color


def _put_scaled(pix, x, y, scale, color):
    for ox in range(scale):
        for oy in range(scale):
            _put(pix, x + ox, y + oy, color)


class Music:
    """Fire and forget soundtrack. Stays quiet unless the sign itself has a speaker to play it."""

    def __init__(self):
        self.process = None
        self.enabled = shared_config.audio_device is not None and not shared_config.emulated_display and os.path.exists(FFPLAY)

    def play(self, filename, loop=False):
        self.stop()
        if not self.enabled:
            return
        path = os.path.join(MUSIC_DIR, filename)
        if not os.path.exists(path):
            logging.warning(f"Horse race music missing: {path}")
            return
        command = [FFPLAY, path, "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "error"]
        if loop:
            command += ["-loop", "0"]
        try:
            self.process = subprocess.Popen(command, env={"SDL_AUDIODRIVER": "alsa", "AUDIODEV": shared_config.audio_device})
        except OSError:
            logging.exception("Could not start the horse race music")
            self.enabled = False

    def stop(self):
        try:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
        except OSError:
            logging.exception("Could not stop the horse race music")
        self.process = None


class Dust:
    def __init__(self, u, y):
        self.u = u
        self.y = y
        self.vy = random.uniform(-3.5, -0.5)
        self.drift = random.uniform(4.0, 11.0)
        self.life = random.uniform(0.25, 0.45)
        self.age = 0.0

    def update(self, dt):
        self.age += dt
        self.u -= self.drift * dt
        self.y += self.vy * dt
        return self.age < self.life

    def draw(self, pix, camera):
        fade = max(0.0, 1.0 - self.age / self.life)
        x = int(round(HUD_W + (self.u - camera) * PX_PER_UNIT))
        _put(pix, x, int(round(self.y)), _scale_color(DUST_COLOR, 0.25 + 0.55 * fade))


class Confetti:
    def __init__(self, seeded=False):
        self.color = random.choice(CONFETTI_COLORS)
        self.flip = random.uniform(2.5, 7.0)
        self.phase = random.random() * math.pi * 2
        self.x = random.uniform(0, WIDTH)
        self.y = random.uniform(0, HEIGHT) if seeded else random.uniform(-24, -1)
        self.vx = random.uniform(-7.0, 7.0)
        self.vy = random.uniform(10.0, 26.0)

    def update(self, dt, t):
        self.x += self.vx * dt + math.sin(t * self.flip + self.phase) * 0.5
        self.y += self.vy * dt
        if self.y > HEIGHT:
            self.__init__()

    def draw(self, pix, t):
        # tumbling paper flickers as it turns edge on
        if math.sin(t * self.flip + self.phase) > -0.35:
            _put(pix, int(round(self.x)), int(round(self.y)), self.color)


class WinnerFlag:
    """Winner's pennant: a triangular flag that is hoisted up its pole and then flaps in the wind."""

    def __init__(self, winner):
        self.fabric = winner.color
        self.ink = _ink_color(winner.color)
        self.digit = FLAG_DIGIT_PIXELS.get(str(winner.number), FLAG_DIGIT_PIXELS["1"])

    def _hoist(self, elapsed):
        """0 while it is still stowed on the ground, 1 once it is home at the top of the pole."""
        return min(1.0, max(0.0, (elapsed - FLAG_HOIST_DELAY) / FLAG_HOIST_TIME))

    def _base_top(self, hoist, elapsed):
        # Near enough a steady haul on the rope rather than a soft ease, so it has some pace
        top = FLAG_STOWED_Y + (FLAG_TOP_Y - FLAG_STOWED_Y) * hoist**0.85
        if hoist >= 1.0:
            # Damped recoil once it hits the stop at the top of the pole
            settled = elapsed - (FLAG_HOIST_DELAY + FLAG_HOIST_TIME)
            top += FLAG_SETTLE * math.exp(-4.5 * settled) * math.sin(12.0 * settled)
        return top

    def _wave(self, column, elapsed, strength):
        """Vertical offset of the fabric at this column. Pinned at the pole, loose at the tip."""
        amplitude = FLAG_WAVE_AMP * strength * (column / FLAG_LEN) ** 1.3
        phase = elapsed * FLAG_WAVE_SPEED - column * FLAG_WAVE_FREQ
        return amplitude * (math.sin(phase) + 0.35 * math.sin(phase * 1.7 + 1.1)) / 1.35, phase

    def draw(self, pix, elapsed):
        for offset, color in enumerate(FLAG_POLE_COLORS):
            for y in range(HEIGHT):
                _put(pix, FLAG_POLE_X + offset, y, color)
        _put(pix, FLAG_POLE_X, 0, FLAG_FINIAL_COLOR)
        _put(pix, FLAG_POLE_X + 1, 0, FLAG_FINIAL_COLOR)

        hoist = self._hoist(elapsed)
        if hoist <= 0.0:
            return

        top = self._base_top(hoist, elapsed)
        center = top + FLAG_H / 2.0
        # Only half catches the wind while it is still climbing, and the gust breathes in and out
        strength = (0.35 + 0.65 * hoist) * (0.82 + 0.18 * math.sin(elapsed * 0.7))

        spans = []
        for column in range(FLAG_LEN + 1):
            offset, phase = self._wave(column, elapsed, strength)
            half = (FLAG_H / 2.0) * (1.0 - column / FLAG_LEN)
            top_y = int(round(center + offset - half))
            bottom_y = int(round(center + offset + half))
            spans.append((offset, top_y, bottom_y))

            shade = 0.72 + 0.28 * (0.5 + 0.5 * math.cos(phase))
            body = _scale_color(self.fabric, shade)
            hem = _scale_color(self.fabric, shade * 0.55)
            x = FLAG_FABRIC_X + column
            for y in range(top_y, bottom_y + 1):
                _put(pix, x, y, hem if y in (top_y, bottom_y) else body)

        # The number rides the same ripple as the cloth instead of sitting flat on top of it
        digit_top = center - FLAG_DIGIT_H / 2.0
        for dx, dy, _ in self.digit:
            column = FLAG_DIGIT_DX + dx
            offset, span_top, span_bottom = spans[column]
            y = int(round(digit_top + offset + dy))
            if span_top < y < span_bottom:
                _put(pix, FLAG_FABRIC_X + column, y, self.ink)


def _draw_winner_flip(image, coat, hidden, flip_t):
    """Paste the winner mid victory flip: one full rotation with a little hang time, garland along for the ride."""
    sprite = Image.new("RGBA", (WINNER_W, WINNER_H), (0, 0, 0, 0))
    for dx, dy, code in WINNER_SPRITE:
        sprite.putpixel((dx, dy), (*(coat["H"] if code in hidden else coat[code]), 255))
    garland_x, garland_y = GARLAND_HOME[0] - BANNER_HORSE_X, GARLAND_HOME[1] - BANNER_HORSE_Y
    for index, (dx, dy, _) in enumerate(GARLAND_PIXELS):
        x, y = garland_x + dx, garland_y + dy
        if 0 <= x < WINNER_W and 0 <= y < WINNER_H:
            sprite.putpixel((x, y), (*GARLAND_COLORS[index % len(GARLAND_COLORS)], 255))

    rotated = sprite.rotate(360.0 * flip_t, resample=Image.NEAREST, expand=True)
    hop = FLIP_JUMP_HEIGHT * 4.0 * flip_t * (1.0 - flip_t)
    paste_x = int(round(BANNER_HORSE_X + WINNER_W / 2.0 - rotated.width / 2.0))
    paste_y = int(round(BANNER_HORSE_Y + WINNER_H / 2.0 - rotated.height / 2.0 - hop))
    image.paste(rotated, (paste_x, paste_y), rotated)


class Horse:
    def __init__(self, lane, coat):
        self.lane = lane
        self.number = lane + 1
        self.color = LANE_ACCENTS[lane]  # lane identity, not the horse itself
        self.coat = coat["name"]
        self.colors = {"H": coat["body"], "M": coat["mane"], "D": coat["sock"], "B": self.color, "J": self.color}

        self.progress = 0.0
        self.speed = 0.0

        # Small spread in raw ability so no single horse runs away with it
        self.base_factor = min(1.022, max(0.978, random.gauss(1.0, 0.008)))
        self.waves = [(random.uniform(0.05, 0.10), random.uniform(3.0, 7.0), random.uniform(0, math.pi * 2)) for _ in range(2)]
        self.event_mult = 1.0
        self.event_until = -1.0
        self.kick = random.uniform(0.95, 1.07)

        self.gallop_phase = random.random() * len(GALLOP_SPRITES)
        self.idle_phase = random.random() * len(IDLE_SPRITES)
        self.finish_time = None

    @property
    def feet_y(self):
        return self.lane * LANE_H + 6

    def update(self, dt, race_time, dust):
        if self.finish_time is not None:
            # Over the line, pull up and coast to a stop in front of the crowd
            self.speed *= PULL_UP_DECAY ** (dt / FRAME_DT)
            self.progress += self.speed * dt
            self.gallop_phase += dt * 11.0 * (self.speed / BASE_SPEED)
            return

        mult = self.base_factor
        for amplitude, period, phase in self.waves:
            mult += amplitude * math.sin(race_time / period * math.pi * 2 + phase)

        # Burst out of the gate
        if race_time < 1.0:
            mult *= 0.3 + 0.7 * (race_time / 1.0) ** 0.6

        # Random surges and stumbles keep the order churning
        if race_time > self.event_until and random.random() < 0.005 * (dt / FRAME_DT):
            self.event_mult = random.choice([1.13, 1.08, 0.92, 0.87])
            self.event_until = race_time + random.uniform(0.6, 1.2)
        if race_time < self.event_until:
            mult *= self.event_mult

        # Everybody finds a different late kick, so the ending stays undecided
        fraction = self.progress / RACE_LENGTH
        if fraction > 0.78:
            mult *= 1.0 + (self.kick - 1.0) * min(1.0, (fraction - 0.78) / 0.12)

        self.speed = BASE_SPEED * max(0.4, mult)
        self.progress += self.speed * dt

        self.gallop_phase += dt * 11.0 * (self.speed / BASE_SPEED)
        if random.random() < 0.4 and self.speed > 5:
            dust.append(Dust(self.progress - SPRITE_W / PX_PER_UNIT, self.feet_y + random.choice([0, 0, -1])))

    def gallop_sprite(self):
        index = int(self.gallop_phase) % len(GALLOP_SPRITES)
        return GALLOP_SPRITES[index], GALLOP_BOB[index]

    def idle_sprite(self, elapsed):
        index = int(elapsed * 2.5 + self.idle_phase) % len(IDLE_SPRITES)
        return IDLE_SPRITES[index], 0

    def screen_x(self, camera):
        return HUD_W + (self.progress - camera) * PX_PER_UNIT

    def draw(self, pix, sprite, bob, nose_x, dim=1.0):
        left = int(round(nose_x)) - NOSE_DX
        top = self.feet_y - (SPRITE_H - 1) + bob
        for dx, dy, code in sprite:
            color = self.colors[code]
            if dim != 1.0:
                color = _scale_color(color, dim)
            _put(pix, left + dx, top + dy, color)


class Race:
    def __init__(self, sign, music):
        self.sign = sign
        self.music = music
        coats = random.sample(COAT_STYLES, NUM_HORSES)
        self.horses = [Horse(lane, coats[lane]) for lane in range(NUM_HORSES)]
        self.dust = []
        self.confetti = []
        self.camera = CAMERA_START
        self.race_time = 0.0
        self.winner = None
        self.finish_gap = None
        self.speckles = self._make_speckles()
        self.last_frame_time = time.perf_counter()

    def _make_speckles(self):
        speckles = []
        span = RACE_LENGTH + 120
        for _ in range(int(span * PX_PER_UNIT / 3.0)):
            y = random.randrange(HEIGHT)
            if y % LANE_H == 7:  # leave the lane dividers alone
                continue
            speckles.append((random.uniform(-40, span), y, random.randint(1, 3)))
        speckles.sort(key=lambda s: s[0])
        return speckles

    # --- frame plumbing -------------------------------------------------

    def alive(self):
        return shared_config.shared_mode.value == DisplayMode.HORSE_RACE.value

    def tick(self):
        """Advance the wall clock, returns the real seconds since the previous frame."""
        now = time.perf_counter()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        return min(max(dt, 0.0), 0.1)

    def present(self, image, texts=()):
        """Blit the frame, overlay the text and pace the loop. False means bail out."""
        self.sign.canvas.SetImage(image, 0, 0)
        for font, x, y, color, text in texts:
            graphics.DrawText(self.sign.canvas, font, x, y, color, text)
        self.sign.canvas = self.sign.matrix.SwapOnVSync(self.sign.canvas)

        spent = time.perf_counter() - self.last_frame_time
        if self.sign.wait_loop(max(0.0, FRAME_DT - spent)):
            return False  # the mode button was hit again, start a fresh race
        return self.alive()

    # --- drawing --------------------------------------------------------

    def new_frame(self):
        image = Image.new("RGB", (WIDTH, HEIGHT), DIRT_COLOR)
        draw = ImageDraw.Draw(image)
        draw.rectangle([0, 0, HUD_W - 1, HEIGHT - 1], fill=HUD_COLOR)
        return image, image.load()

    def draw_track(self, pix):
        camera = self.camera

        # Scrolling dirt speckles anchored to the world so the ground really moves
        left_u = camera
        right_u = camera + (WIDTH - HUD_W) / PX_PER_UNIT
        for u, y, shade in self.speckles:
            if u < left_u:
                continue
            if u > right_u:
                break
            x = int(HUD_W + (u - camera) * PX_PER_UNIT)
            if HUD_W <= x < WIDTH:
                pix[x, y] = _scale_color(DIRT_COLOR, 1.0 + shade * 0.55)

        # Dashed lane dividers
        dash_spacing = 7.0
        start = math.floor(left_u / dash_spacing) * dash_spacing
        u = start
        while u < right_u:
            x = int(round(HUD_W + (u - camera) * PX_PER_UNIT))
            for lane in range(1, NUM_HORSES):
                y = lane * LANE_H - 1
                for offset in range(3):
                    if x + offset >= HUD_W:
                        _put(pix, x + offset, y, RAIL_COLOR)
            u += dash_spacing

        self.draw_line_marker(pix, 0.0, (150, 150, 160), dashed=True)
        self.draw_finish_line(pix)

    def draw_line_marker(self, pix, u, color, dashed=False):
        x = int(round(HUD_W + (u - self.camera) * PX_PER_UNIT))
        if x < HUD_W or x >= WIDTH:
            return
        for y in range(HEIGHT):
            if dashed and y % 2:
                continue
            _put(pix, x, y, color)

    def draw_finish_line(self, pix):
        x = int(round(HUD_W + (RACE_LENGTH - self.camera) * PX_PER_UNIT))
        if x < HUD_W - 2 or x >= WIDTH + 2:
            return
        # Waving checkered flag: the checker pattern crawls so it reads as fabric
        wave = int(time.perf_counter() * 6) % 2
        for y in range(HEIGHT):
            block = ((y // 2) + wave) % 2
            for offset in range(3):
                color = WHITE if (block + offset // 2) % 2 == 0 else (25, 25, 30)
                _put(pix, x + offset - 1, y, color)

    def draw_horses(self, pix, running, elapsed):
        for horse in self.horses:
            if running and horse.speed > 8.0:
                sprite, bob = horse.gallop_sprite()
            else:
                sprite, bob = horse.idle_sprite(elapsed)

            nose_x = horse.screen_x(self.camera)
            dim = 1.0
            if nose_x < HUD_W + NOSE_DX + 1:
                # Trailing off the back of the pack, pin them on the rail and fade them out
                nose_x = HUD_W + NOSE_DX + 1
                dim = 0.45
            horse.draw(pix, sprite, bob, nose_x, dim)

    def draw_dust(self, pix):
        for particle in self.dust:
            particle.draw(pix, self.camera)

    def update_dust(self, dt):
        self.dust = [particle for particle in self.dust if particle.update(dt)]

    def hud_texts(self, blink_leader=True):
        texts = []
        leader = max(self.horses, key=lambda h: h.progress)
        flash_on = int(time.perf_counter() * 4) % 2 == 0
        for horse in self.horses:
            color = horse.color
            if blink_leader and horse is leader and flash_on:
                color = WHITE
            texts.append((self.sign.font46, 0, horse.lane * LANE_H + 6, graphics.Color(*color), str(horse.number)))
        return texts

    # --- phases ---------------------------------------------------------

    def run_countdown(self):
        """Horses fidget at the gate while 3 / 2 / 1 counts down."""
        start = time.perf_counter()
        total = COUNTDOWN_STEP * 3
        self.music.play(POST_CALL)

        while self.alive():
            self.tick()
            elapsed = time.perf_counter() - start
            if elapsed >= total:
                return True

            image, pix = self.new_frame()
            self.draw_track(pix)
            self.draw_horses(pix, running=False, elapsed=elapsed)
            image = ImageEnhance.Brightness(image).enhance(0.5)

            step = int(elapsed / COUNTDOWN_STEP)
            digit = str(3 - step)
            # Each number lands bright then eases off before the next one
            pulse = 1.0 - (elapsed % COUNTDOWN_STEP) / COUNTDOWN_STEP
            level = 0.35 + 0.65 * pulse**0.5
            color = graphics.Color(*_scale_color((255, 210, 60), level))
            x = int(utilities.get_centered_text_x_offset_value(9, digit))
            texts = self.hud_texts(blink_leader=False)
            texts.append((self.sign.fontreallybig, x, 25, color, digit))

            if not self.present(image, texts):
                return False

        return False

    def run_race(self):
        self.race_time = 0.0
        self.last_frame_time = time.perf_counter()
        finish_started = None
        photo_finish = False
        white_flash = 0.0
        self.music.play(RACE_LOOP, loop=True)

        while self.alive():
            dt = self.tick()
            time_scale = 1.0

            leader = max(self.horses, key=lambda h: h.progress)
            if self.winner is None:
                runner_up = sorted(self.horses, key=lambda h: h.progress, reverse=True)[1]
                to_go = RACE_LENGTH - leader.progress
                if to_go < SLOWMO_ZONE:
                    if leader.progress - runner_up.progress < PHOTO_FINISH_GAP:
                        time_scale = SLOWMO_SCALE
                    else:
                        time_scale = HOMESTRETCH_SCALE
            elif photo_finish:
                time_scale = SLOWMO_SCALE

            sim_dt = dt * time_scale
            self.race_time += sim_dt

            for horse in self.horses:
                horse.update(sim_dt, self.race_time, self.dust)
                if horse.finish_time is None and horse.progress >= RACE_LENGTH:
                    horse.finish_time = self.race_time
                    if self.winner is None:
                        self.winner = horse
                        others = [other.progress for other in self.horses if other is not horse]
                        self.finish_gap = horse.progress - max(others)
                        photo_finish = self.finish_gap < PHOTO_FINISH_GAP
                        finish_started = time.perf_counter()
                        white_flash = 0.85
                        self.music.play(WIN_FANFARE)

            self.update_dust(sim_dt)
            self.camera = min(max(leader.progress - LEAD_UNITS, CAMERA_START), CAMERA_FINISH)

            image, pix = self.new_frame()
            self.draw_track(pix)
            self.draw_dust(pix)
            self.draw_horses(pix, running=True, elapsed=self.race_time)

            texts = []
            zoomed = False
            if self.winner is not None and photo_finish:
                image = self.zoom_finish(image)
                zoomed = True
                if int(time.perf_counter() * 6) % 2 == 0:
                    label = "PHOTO FINISH"
                    x = int(utilities.get_centered_text_x_offset_value(4, label))
                    # Keep the caption clear of the blown up winner
                    y = 31 if self.winner.lane < 2 else 6
                    texts.append((self.sign.font46, x, y, graphics.Color(255, 240, 120), label))

            if white_flash > 0.01:
                image = Image.blend(image, Image.new("RGB", (WIDTH, HEIGHT), WHITE), min(1.0, white_flash))
                white_flash -= dt * 6.0

            if not zoomed:
                texts.extend(self.hud_texts())

            if self.race_time < GO_FLASH_TIME and int(self.race_time * 10) % 2 == 0:
                x = int(utilities.get_centered_text_x_offset_value(6, "GO!"))
                texts.append((self.sign.fontbig, x, 20, graphics.Color(90, 255, 110), "GO!"))

            if not self.present(image, texts):
                return False

            if finish_started is not None and time.perf_counter() - finish_started > FINISH_HOLD:
                return True

        return False

    def zoom_finish(self, image):
        """2x nearest neighbour blow up of the finish line for the photo finish replay."""
        lane_center = self.winner.lane * LANE_H + 4
        x0 = min(max(FINISH_X - 40, 0), WIDTH - WIDTH // 2)
        y0 = min(max(lane_center - HEIGHT // 4, 0), HEIGHT - HEIGHT // 2)
        crop = image.crop((x0, y0, x0 + WIDTH // 2, y0 + HEIGHT // 2))
        return crop.resize((WIDTH, HEIGHT), Image.NEAREST)

    def run_banner(self):
        """Winner's enclosure: a groom walks out and garlands the winner, then the party carries on."""
        self.confetti = [Confetti(seeded=True) for _ in range(70)]
        winner = self.winner
        flag = WinnerFlag(winner)
        text = f"HORSE {winner.number} WINS!"
        text_x = int(utilities.get_centered_text_x_offset_value(5, text))
        coat = dict(winner.colors)
        coat["E"] = coat["P"] = coat["W"] = coat["S"] = _ink_color(coat["H"])
        groom_colors = {"C": winner.color, "K": (238, 190, 152), "A": (238, 190, 152), "J": (240, 240, 246), "T": (72, 84, 126), "O": (126, 110, 98)}
        start = time.perf_counter()
        self.last_frame_time = start
        groom_x = float(WIDTH + 4)
        crown_start = None

        while self.alive():
            dt = self.tick()
            elapsed = time.perf_counter() - start

            if crown_start is None:
                groom_x = max(float(BANNER_GROOM_X), groom_x - dt * GROOM_WALK_SPEED)
                lift = 0.0
                if groom_x <= BANNER_GROOM_X:
                    crown_start = elapsed
            else:
                lift = min(1.0, (elapsed - crown_start) / CROWN_TIME)
            crowned = lift >= 1.0
            settled = (elapsed - crown_start - CROWN_TIME) if crowned else -1.0
            winking = WINK_START <= settled < WINK_END
            flip_elapsed = settled - FLIP_DELAY
            flip_t = flip_elapsed / FLIP_DURATION if 0.0 <= flip_elapsed < FLIP_DURATION else -1.0

            image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
            pix = image.load()

            for particle in self.confetti:
                particle.update(dt, elapsed)
                particle.draw(pix, elapsed)

            for x in range(WIDTH):
                if x % 7 < 5:
                    _put(pix, x, HEIGHT - 1, _scale_color(RAIL_COLOR, 0.8))

            flag.draw(pix, elapsed)

            # Once the flowers are on, the winner bobs along to the crowd (and takes a victory flip)
            bob = -1 if crowned and int(elapsed * 4) % 2 == 0 else 0
            hidden = {"E"} if winking else {"W"}
            if settled < WINK_END:
                hidden.add("S")
            if flip_t >= 0.0:
                _draw_winner_flip(image, coat, hidden, flip_t)
            else:
                for dx, dy, code in WINNER_SPRITE:
                    _put(pix, BANNER_HORSE_X + dx, BANNER_HORSE_Y + dy + bob, coat["H"] if code in hidden else coat[code])

            if crowned:
                groom = GROOM_SPRITES[GROOM_WAVE[int(elapsed * 4) % 2]]
            elif crown_start is not None:
                groom = GROOM_SPRITES[GROOM_REACH]
            else:
                groom = GROOM_SPRITES[GROOM_WALK[int(elapsed * 8) % 2]]
            for dx, dy, code in groom:
                _put_scaled(pix, int(groom_x) + dx * GROOM_SCALE, BANNER_GROOM_Y + dy * GROOM_SCALE, GROOM_SCALE, groom_colors[code])

            # Garland is carried in, lifted over the head and left hanging on the neck.
            # Once worn, it rides along inside the flip sprite instead of being drawn separately.
            if flip_t < 0.0:
                ease = lift * lift * (3.0 - 2.0 * lift)
                garland_x = int(groom_x) - 10 if crown_start is None else GARLAND_CARRY[0] + (GARLAND_HOME[0] - GARLAND_CARRY[0]) * ease
                garland_y = GARLAND_CARRY[1] + (GARLAND_HOME[1] - GARLAND_CARRY[1]) * ease - 5.0 * math.sin(math.pi * ease)
                for index, (dx, dy, _) in enumerate(GARLAND_PIXELS):
                    _put(pix, int(garland_x) + dx, int(garland_y) + dy + (bob if crowned else 0), GARLAND_COLORS[index % len(GARLAND_COLORS)])

            texts = []
            if elapsed > BANNER_INTRO:
                flash = int(elapsed * 3) % 2 == 0
                color = WHITE if flash else winner.color
                texts.append((self.sign.font57, text_x, 8, graphics.Color(*color), text))
            else:
                image = ImageEnhance.Brightness(image).enhance(elapsed / BANNER_INTRO)

            if not self.present(image, texts):
                return False

        return False


@__main__.planesign_mode_handler(DisplayMode.HORSE_RACE)
def horse_race(sign):
    sign.canvas.Clear()
    music = Music()

    try:
        while shared_config.shared_mode.value == DisplayMode.HORSE_RACE.value:
            race = Race(sign, music)
            if not race.run_countdown():
                continue
            if not race.run_race():
                continue
            race.run_banner()
    finally:
        music.stop()
