###
# Mandelbrot Set Zoom
# https://en.wikipedia.org/wiki/Mandelbrot_set
###

import math
import time

import numpy as np
import shared_config
from modes import DisplayMode

import __main__

_SCALAR_TAIL_SIZE = 32
_LOG_2 = np.log(2)


# Function to calculate whether a point is in the Mandelbrot set
def mandelbrot(x0, y0, max_iter):
    return _continue_mandelbrot(x0, y0, max_iter)


def _continue_mandelbrot(x0, y0, max_iter, x=0.0, y=0.0, tx=0.0, ty=0.0, iteration=0, power=1, lam=1):
    x0, y0, x, y, tx, ty = map(float, (x0, y0, x, y, tx, ty))
    x2, y2 = x * x, y * y
    while x2 + y2 <= 4 and iteration < max_iter:
        if iteration:
            dx, dy = tx - x, ty - y
            if dx * dx + dy * dy < 1e-32:
                return max_iter, 0.0

        if power == lam:
            tx, ty = x, y
            power *= 2
            lam = 0

        xtemp = x2 - y2 + x0
        y = 2 * x * y + y0
        x = xtemp
        x2, y2 = x * x, y * y
        lam += 1
        iteration += 1

    return iteration, math.sqrt(x2 + y2)


# Main cardioid checking (exact)
def is_inside_main_cardioid(x, y):
    q = (x - 0.25) ** 2 + y**2
    return q * (q + (x - 0.25)) < 0.25 * y**2


# Period-2 bulb checking (exact)
def is_inside_period_2_bulb(x, y):
    return (x + 1) ** 2 + y**2 < 0.0625


# Period-3 bulb checking (approximate)
def is_inside_period_3_bulb(x, y):
    if (x + 0.12256) ** 2 + (y + 0.74486) ** 2 < 0.00925926 or (x + 0.12256) ** 2 + (y - 0.74486) ** 2 < 0.00925926:
        return 1
    else:
        return 0


# Calculate the adaptive MAX_ITER value based on zoom level
def calculate_max_iter(zoom_factor):
    return int(1000 / math.sqrt(zoom_factor))


_PALETTES = {
    mode: (np.asarray(colors, dtype=np.float64), np.asarray(keypts, dtype=np.float64))
    for mode, (colors, keypts) in enumerate((
        # Saturated Rainbow
        (
            [(255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255), (0, 0, 255), (255, 0, 255), (255, 0, 0)],
            [0, 0.2, 0.33, 0.45, 0.6, 0.83, 1],
        ),
        # Sunrise
        (
            [(0, 0, 0), (14, 81, 181), (18, 218, 222), (255, 255, 248), (242, 210, 82), (207, 88, 29), (0, 0, 0)],
            [0, 0.16144, 0.351671, 0.501285, 0.620051, 0.8, 1],
        ),
        # Nova
        (
            [(0, 0, 0), (15, 50, 190), (255, 255, 255), (255, 200, 30), (111, 0, 255), (0, 0, 0)],
            [0, 0.2, 0.4, 0.6, 0.8, 1],
        ),
        # Vaporwave
        (
            [(48, 3, 80), (148, 22, 127), (246, 46, 151), (249, 172, 83), (5, 195, 221), (21, 60, 180), (48, 3, 80)],
            [0, 0.15, 0.3, 0.44, 0.73, 0.9, 1],
        ),
        # 70s
        (
            [(0, 18, 25), (0, 95, 115), (10, 147, 150), (148, 210, 189), (233, 216, 166), (238, 155, 0), (202, 103, 2), (174, 32, 18), (0, 18, 25)],
            [0, 0.1, 0.2, 0.35, 0.5, 0.6, 0.7, 0.8, 1],
        ),
        # Pastel Rainbow
        (
            [(255, 89, 94), (255, 202, 58), (138, 201, 38), (25, 130, 196), (106, 76, 147), (255, 89, 94)],
            [0, 0.2, 0.4, 0.6, 0.8, 1],
        ),
        # Neon
        (
            [(128, 0, 128), (255, 20, 147), (0, 0, 128), (0, 255, 255), (128, 0, 128)],
            [0, 0.2, 0.4, 0.7, 1],
        ),
        # Elemental
        (
            [(255, 69, 0), (255, 255, 0), (255, 255, 153), (173, 216, 230), (0, 0, 128), (25, 25, 112), (255, 69, 0)],
            [0, 0.15, 0.3, 0.5, 0.7, 0.85, 1],
        ),
        # Fire
        (
            [(255, 69, 0), (255, 128, 0), (255, 191, 0), (255, 215, 0), (255, 239, 204), (255, 204, 0), (255, 153, 0), (255, 102, 0), (255, 51, 0), (204, 0, 0), (153, 0, 0), (102, 0, 0), (51, 0, 0), (0, 0, 0), (255, 69, 0)],
            [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1],
        ),
        # Greyscale
        (
            [(0, 0, 0), (200, 200, 200), (0, 0, 0)],
            [0, 0.5, 1],
        ),
    ))
}


def _palette_colors(indices, mode):
    colors, keypts = _PALETTES.get(mode, _PALETTES[9])
    indices = indices % 1
    upper = np.searchsorted(keypts, indices, side="right")
    fraction = ((indices - keypts[upper - 1]) / (keypts[upper] - keypts[upper - 1]))[:, None]
    return (fraction * colors[upper] + (1 - fraction) * colors[upper - 1]).astype(np.uint8)


def setcolor(index, mode):
    r, g, b = _palette_colors(np.asarray([index]), mode)[0]
    return int(r), int(g), int(b)


def _mandelbrot_pixels(cx, cy, max_iter):
    counts = np.full(cx.size, max_iter, dtype=np.int64)
    modulus = np.zeros(cx.size, dtype=np.float64)
    inside = is_inside_main_cardioid(cx, cy) | is_inside_period_2_bulb(cx, cy)
    active = np.flatnonzero(~inside)
    cr, ci = cx[active], cy[active]
    x, y = np.zeros(active.size), np.zeros(active.size)
    tx, ty = np.zeros(active.size), np.zeros(active.size)
    # All active pixels advance together, so their cycle-checkpoint counters are shared.
    power = lam = 1
    iteration = 0

    while active.size and iteration < max_iter:
        if active.size <= _SCALAR_TAIL_SIZE:
            # Resume each orbit and checkpoint; restarting would repeat the expensive work.
            for offset, index in enumerate(active):
                counts[index], modulus[index] = _continue_mandelbrot(cr[offset], ci[offset], max_iter, x[offset], y[offset], tx[offset], ty[offset], iteration, power, lam)
            return counts, modulus

        if iteration:
            dx, dy = tx - x, ty - y
            cycling = dx * dx + dy * dy < 1e-32
            if cycling.any():
                keep = ~cycling
                active, cr, ci = active[keep], cr[keep], ci[keep]
                x, y, tx, ty = x[keep], y[keep], tx[keep], ty[keep]

        if power == lam:
            tx, ty = x.copy(), y.copy()
            power *= 2
            lam = 0

        old_x = x
        x = x * x - y * y + cr
        y = 2 * old_x * y + ci
        lam += 1
        iteration += 1
        squared = x * x + y * y
        escaped = squared > 4
        if escaped.any():
            done = active[escaped]
            counts[done] = iteration
            modulus[done] = np.sqrt(squared[escaped])
            keep = ~escaped
            active, cr, ci = active[keep], cr[keep], ci[keep]
            x, y, tx, ty = x[keep], y[keep], tx[keep], ty[keep]

    modulus[active] = np.sqrt(x * x + y * y)
    return counts, modulus


def draw_mandelbrot_frame(sign, xb, yb, frame, color_mode, color_scale):
    sign.canvas.Clear()
    zoom_factor = 2 ** (-0.05 * frame)
    half_width, half_height = 10.5, 2.625
    x = np.linspace(xb - half_width * zoom_factor, xb + half_width * zoom_factor, 128)
    y = np.linspace(yb - half_height * zoom_factor, yb + half_height * zoom_factor, 32)
    cx, cy = np.broadcast_arrays(x[None, :], y[:, None])
    max_iter = calculate_max_iter(zoom_factor)
    counts, modulus = _mandelbrot_pixels(cx.ravel(), cy.ravel(), max_iter)
    visible = (counts != max_iter) & (counts > 1)
    indices = np.log2(counts[visible] - np.log(np.log(modulus[visible])) / _LOG_2) / color_scale
    colors = _palette_colors(indices, color_mode)
    for index, color in zip(np.flatnonzero(visible).tolist(), colors.tolist()):
        sign.canvas.SetPixel(index % 128, index // 128, *color)
    return np.where(visible, counts, max_iter).reshape(32, 128), max_iter


def find_border_point(precision, max_iterations=100000):

    while True:
        x = np.random.uniform(-2, 1)
        y = np.random.uniform(-1.5, 1.5)
        if is_inside_main_cardioid(x, y) or is_inside_period_2_bulb(x, y) or is_inside_period_3_bulb(x, y):
            continue
        else:
            m, _ = mandelbrot(x, y, max_iterations)
        if m == max_iterations:
            break

    angle = 2 * np.pi * np.random.rand()

    delta = 0.1
    dx = delta * math.cos(angle)
    dy = delta * math.sin(angle)

    while True:
        m, _ = mandelbrot(x + dx, y + dy, max_iterations)
        if m < max_iterations:
            dx /= 2
            dy /= 2
        else:
            x += dx
            y += dy

        if dx * dx + dy * dy < precision * precision:
            break

    while True:
        tx = x - 2 * dx + 4 * dx * np.random.rand()
        ty = y - 2 * dy + 4 * dy * np.random.rand()
        m, _ = mandelbrot(tx, ty, max_iterations)
        if m > max_iterations / 2 and m < max_iterations:
            break
    # print(m)
    return tx, ty


@__main__.planesign_mode_handler(DisplayMode.MANDELBROT)
def mandelbrot_zoom(sign):
    sign.canvas.Clear()

    # Initialize an empty list to store tuples
    pois = []

    # Open the file for reading
    with open("datafiles/mandelbrot_poi.txt", "r") as file:
        # Iterate through each line in the file
        for line in file:
            # Split the line into two floats using tab as the delimiter
            parts = line.strip().split("\t")
            pois.append((float(parts[0]), float(parts[1])))

    lp = len(pois)

    while shared_config.shared_mode.value == DisplayMode.MANDELBROT.value:
        if np.random.rand() < 0.1:
            xb, yb = find_border_point(1e-3)
        else:
            xb, yb = pois[np.random.randint(0, high=lp)]

        frame = 0

        while frame < 900:
            tstart = time.perf_counter()

            cmode = shared_config.shared_mandelbrot_color.value
            cscale = shared_config.shared_mandelbrot_colorscale.value
            iters, MAX_ITER = draw_mandelbrot_frame(sign, xb, yb, frame, cmode, cscale)

            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.canvas.Clear()
            breakout = sign.wait_loop(0)
            if breakout:
                return

            frame += 1

            if time.perf_counter() - tstart > 1 or np.all(np.isclose(iters, iters[0], atol=2)) or np.sum(iters == MAX_ITER) > 3900:
                break
