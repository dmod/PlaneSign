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


def _scale_color(color, factor):
    return (min(255, max(0, int(color[0] * factor))), min(255, max(0, int(color[1] * factor))), min(255, max(0, int(color[2] * factor))))


def _put(pix, x, y, color):
    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
        pix[x, y] = color


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
        """Flash the winner and keep celebrating until the sign is sent somewhere else."""
        self.confetti = [Confetti(seeded=True) for _ in range(70)]
        winner = self.winner
        text = f"HORSE {winner.number} WINS!"
        text_x = int(utilities.get_centered_text_x_offset_value(6, text))
        start = time.perf_counter()
        self.last_frame_time = start
        scroll = 0.0
        gallop = 0.0
        screen_dust = []

        while self.alive():
            dt = self.tick()
            elapsed = time.perf_counter() - start
            scroll = (scroll + dt * 70.0) % 6.0
            gallop += dt * 11.0

            image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
            pix = image.load()

            for particle in self.confetti:
                particle.update(dt, elapsed)
                particle.draw(pix, elapsed)

            # Ground streaking past under the celebrating winner
            for x in range(WIDTH):
                if (x + int(scroll)) % 6 < 3:
                    _put(pix, x, HEIGHT - 1, _scale_color(RAIL_COLOR, 0.8))

            screen_dust = [(dx - dt * 55.0, dy, age + dt) for dx, dy, age in screen_dust if age + dt < 0.4 and dx > 0]
            if random.random() < 0.5:
                screen_dust.append((62.0, HEIGHT - 2 - random.choice([0, 1]), 0.0))
            for dx, dy, age in screen_dust:
                _put(pix, int(dx), int(dy), _scale_color(DUST_COLOR, 0.25 + 0.5 * (1.0 - age / 0.4)))

            index = int(gallop) % len(GALLOP_SPRITES)
            left = 72 - NOSE_DX
            top = HEIGHT - SPRITE_H + GALLOP_BOB[index]
            for dx, dy, code in GALLOP_SPRITES[index]:
                _put(pix, left + dx, top + dy, winner.colors[code])

            texts = []
            if elapsed > BANNER_INTRO:
                flash = int(elapsed * 3) % 2 == 0
                color = WHITE if flash else winner.color
                texts.append((self.sign.fontbig, text_x, 13, graphics.Color(*color), text))
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
