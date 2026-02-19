#!/usr/bin/python3
# -*- coding: utf-8 -*-

import time
import math
import random
import logging
from PIL import Image, ImageDraw
import shared_config
import __main__
from modes import DisplayMode


# ── Pixel-art flower definitions (small enough for 32px height) ──────────

def draw_flower(image, cx, cy, petal_color, center_color, size=3):
    """Draw a small flower at (cx, cy) on a PIL Image."""
    draw = ImageDraw.Draw(image)
    # Petals (a ring of small circles around the center)
    for angle_deg in range(0, 360, 60):
        angle = math.radians(angle_deg)
        px = cx + int(round(size * math.cos(angle)))
        py = cy + int(round(size * math.sin(angle)))
        r = max(1, size // 2)
        draw.ellipse([px - r, py - r, px + r, py + r], fill=petal_color)
    # Center dot
    cr = max(1, size // 3)
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=center_color)


def draw_leaf(image, x, y, color):
    """Draw a tiny leaf."""
    draw = ImageDraw.Draw(image)
    draw.polygon([(x, y), (x + 2, y - 1), (x + 4, y), (x + 2, y + 1)], fill=color)


def build_flower_strip():
    """Build a 24×32 RGBA image with a floral arrangement for the left side."""
    strip = Image.new('RGBA', (24, 32), (0, 0, 0, 0))

    # Stem lines
    draw = ImageDraw.Draw(strip)
    stem_color = (40, 120, 40, 255)
    draw.line([(12, 30), (12, 6)], fill=stem_color, width=1)
    draw.line([(6, 28), (6, 12)], fill=stem_color, width=1)
    draw.line([(18, 28), (18, 10)], fill=stem_color, width=1)

    # Leaves along stems
    leaf_green = (60, 160, 50, 255)
    draw_leaf(strip, 10, 20, leaf_green)
    draw_leaf(strip, 14, 24, leaf_green)
    draw_leaf(strip, 4, 22, leaf_green)
    draw_leaf(strip, 16, 18, leaf_green)
    draw_leaf(strip, 3, 16, leaf_green)
    draw_leaf(strip, 19, 22, leaf_green)

    # Flowers — blue, light blue, pale yellow, and white
    flower_palette = [
        ((60, 100, 220, 255),  (200, 220, 255, 255)),   # blue petals, pale center
        ((100, 180, 255, 255), (220, 240, 255, 255)),   # light blue petals
        ((255, 255, 180, 255), (255, 255, 230, 255)),   # pale yellow petals
        ((255, 255, 255, 255), (200, 220, 255, 255)),   # white petals, blue-tint center
    ]

    positions = [
        (12, 5, 3), (6, 10, 2), (18, 8, 3),
        (9, 14, 2), (17, 15, 2), (5, 20, 2),
        (20, 22, 2), (12, 18, 2),
    ]

    for i, (fx, fy, sz) in enumerate(positions):
        petal_c, center_c = flower_palette[i % len(flower_palette)]
        draw_flower(strip, fx, fy, petal_c, center_c, size=sz)

    return strip


# ── Shimmer effect helpers ───────────────────────────────────────────────

def shimmer_color(base_r, base_g, base_b, char_index, t):
    """Return a shimmering version of the base color.
    Each character gets a slightly different phase so the shimmer
    appears to travel across the text like a sparkle wave."""
    # Combine a slow sine wave with a faster sparkle
    wave = 0.5 + 0.5 * math.sin(2.0 * t + char_index * 0.55)
    sparkle = 0.5 + 0.5 * math.sin(5.0 * t - char_index * 0.9)
    brightness = 0.45 + 0.55 * (0.7 * wave + 0.3 * sparkle)

    r = min(255, int(base_r * brightness + 60 * wave))
    g = min(255, int(base_g * brightness + 40 * wave))
    b = min(255, int(base_b * brightness + 50 * sparkle))
    return (r, g, b)


# ── Shooting star ────────────────────────────────────────────────────────

class ShootingStar:
    """A bright shooting star that streaks across the display."""

    def __init__(self, auto_spawn=True):
        self.active = False
        self.auto_spawn = auto_spawn  # if True, respawns on its own after cooldown
        self.x = 0.0
        self.y = 0.0
        self.dx = 0.0
        self.dy = 0.0
        self.trail = []        # list of (x, y) past positions
        self.trail_len = 8
        self.cooldown = 2.0  # seconds until first star
        self.last_end = 0.0  # must match the relative 't' timescale passed to update()

    def update(self, t):
        if not self.active:
            if self.auto_spawn and t - self.last_end >= self.cooldown:
                self._launch(t)
            return

        self.trail.append((self.x, self.y))
        if len(self.trail) > self.trail_len:
            self.trail.pop(0)

        self.x += self.dx
        self.y += self.dy

        # Off screen?
        if self.x > 140 or self.x < -10 or self.y > 40 or self.y < -6:
            logging.debug(f"Shooting star ended at ({self.x:.0f}, {self.y:.0f})")
            self.active = False
            self.trail.clear()
            self.last_end = t
            self.cooldown = 3.0 + random.random() * 3.0

    def _launch(self, t):
        self.active = True
        self.trail.clear()

        # Pick a random direction to enter from
        direction = random.choice(['top-left', 'top-right', 'left', 'right'])

        if direction == 'top-left':
            self.x = float(random.randint(15, 60))
            self.y = float(random.randint(-3, 1))
            angle = math.radians(random.randint(15, 40))
            self.dx = random.uniform(2.0, 3.5) * math.cos(angle)
            self.dy = random.uniform(2.0, 3.5) * math.sin(angle)
        elif direction == 'top-right':
            self.x = float(random.randint(70, 120))
            self.y = float(random.randint(-3, 1))
            angle = math.radians(random.randint(140, 165))
            speed = random.uniform(2.0, 3.5)
            self.dx = speed * math.cos(angle)
            self.dy = -speed * math.sin(angle)  # sin of obtuse angle is positive, flip for downward
        elif direction == 'left':
            self.x = float(random.randint(-3, 1))
            self.y = float(random.randint(2, 20))
            angle = math.radians(random.randint(-15, 15))
            speed = random.uniform(2.0, 3.5)
            self.dx = speed * math.cos(angle)
            self.dy = speed * math.sin(angle)
        else:  # right
            self.x = float(random.randint(128, 133))
            self.y = float(random.randint(2, 20))
            angle = math.radians(random.randint(165, 195))
            speed = random.uniform(2.0, 3.5)
            self.dx = speed * math.cos(angle)
            self.dy = speed * math.sin(angle)

        logging.info(f"Shooting star launched from {direction} at ({self.x:.0f}, {self.y:.0f}) "
                     f"dx={self.dx:.1f} dy={self.dy:.1f} t={t:.1f}s")

    def draw_on_canvas(self, canvas):
        """Draw the shooting star directly on the RGB matrix canvas so it
        renders on top of everything (flowers + text)."""
        if not self.active and not self.trail:
            return

        # Draw trail from dimmest to brightest, 1px wide
        for i, (tx, ty) in enumerate(self.trail):
            frac = (i + 1) / self.trail_len
            r = int(255 * frac)
            g = int(255 * frac)
            b = min(255, int(200 * frac + 55))
            ix, iy = int(round(tx)), int(round(ty))
            if 0 <= ix < 128 and 0 <= iy < 32:
                canvas.SetPixel(ix, iy, r, g, b)

        # Bright head — 3×3 glow
        hx, hy = int(round(self.x)), int(round(self.y))
        for ox in range(-1, 2):
            for oy in range(-1, 2):
                px, py = hx + ox, hy + oy
                if 0 <= px < 128 and 0 <= py < 32:
                    dist = abs(ox) + abs(oy)
                    if dist == 0:
                        canvas.SetPixel(px, py, 255, 255, 255)
                    elif dist == 1:
                        canvas.SetPixel(px, py, 200, 210, 255)


# ── Main handler ─────────────────────────────────────────────────────────

@__main__.planesign_mode_handler(DisplayMode.WEDDING)
def wedding(sign):
    """Display 'Welcome to our Wedding' with shimmering text and flowers."""

    flower_strip = build_flower_strip()

    # Base text color — elegant warm gold
    base_r, base_g, base_b = (255, 200, 100)

    # Pre-split text into two lines for the 128×32 display
    line1 = "Welcome to"
    line2 = "our Wedding"

    # Use the 5x7 font for line measurements
    font = sign.fontbig  # 6x13 – fits two lines in 32px height
    char_w = 6

    # Center positions (offset slightly right to account for flower strip on left)
    text_area_start = 24
    text_area_width = 128 - text_area_start
    line1_x = text_area_start + (text_area_width - len(line1) * char_w) // 2
    line2_x = text_area_start + (text_area_width - len(line2) * char_w) // 2
    line1_y = 13   # baseline y for 6x13 font, top line
    line2_y = 27   # baseline y for 6x13 font, bottom line

    from rgbmatrix import graphics

    shooting_stars = [ShootingStar()]  # start with one auto-spawning star
    start_time = time.perf_counter()

    while shared_config.shared_mode.value == DisplayMode.WEDDING.value:
        t = time.perf_counter() - start_time

        # Build background image with flowers
        frame = Image.new('RGB', (128, 32), (0, 0, 0))

        # Paste flowers on left edge
        frame.paste(flower_strip, (0, 0), flower_strip)

        # Twinkling star dots scattered across the background
        random.seed(42)  # deterministic positions
        for _ in range(55):
            sx = random.randint(24, 127)
            sy = random.randint(0, 31)
            phase = random.random() * 6.28
            speed = 1.5 + random.random() * 2.5
            brightness = int(45 + 35 * math.sin(t * speed + phase))
            if brightness > 0:
                frame.putpixel((sx, sy), (brightness, brightness, min(255, brightness + 15)))
        random.seed()  # restore randomness

        # Update all shooting stars and remove dead ones
        for star in shooting_stars:
            star.update(t)
        # Keep the first (auto-spawning) star always; prune finished extras
        shooting_stars = [shooting_stars[0]] + [s for s in shooting_stars[1:] if s.active or s.trail]

        # Check for user-triggered shooting star — spawn a new one immediately
        if shared_config.data_dict.get("trigger_shooting_star", False):
            shared_config.data_dict["trigger_shooting_star"] = False
            new_star = ShootingStar(auto_spawn=False)
            new_star._launch(t)
            shooting_stars.append(new_star)
            logging.info(f"User triggered shooting star (total active: {len(shooting_stars)})")

        sign.canvas.SetImage(frame, 0, 0)

        # Draw shimmering text character by character using the matrix graphics
        global_idx = 0
        x_pos = line1_x
        for ch in line1:
            r, g, b = shimmer_color(base_r, base_g, base_b, global_idx, t)
            color = graphics.Color(r, g, b)
            graphics.DrawText(sign.canvas, font, x_pos, line1_y, color, ch)
            x_pos += char_w
            global_idx += 1

        x_pos = line2_x
        for ch in line2:
            r, g, b = shimmer_color(base_r, base_g, base_b, global_idx, t)
            color = graphics.Color(r, g, b)
            graphics.DrawText(sign.canvas, font, x_pos, line2_y, color, ch)
            x_pos += char_w
            global_idx += 1

        # Draw shooting stars ON TOP of everything so they're clearly visible
        for star in shooting_stars:
            star.draw_on_canvas(sign.canvas)

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.wait_loop(0.03)  # ~30 fps for smooth shimmer
