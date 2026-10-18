###
# Mandelbrot Set Zoom
# https://en.wikipedia.org/wiki/Mandelbrot_set
#
# Worker processes render one keyframe per octave of zoom, supersampled 2x relative to the panel.
# The sign composites the two keyframes around the current zoom level at a fixed frame rate, so an
# expensive view slows the zoom down instead of the frame rate.
###

import logging
import math
import multiprocessing
import os
import time
import traceback
from multiprocessing.sharedctypes import RawArray

import numpy as np
import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image

PANEL_WIDTH, PANEL_HEIGHT = 128, 32
KEY_WIDTH, KEY_HEIGHT = 2 * PANEL_WIDTH, 2 * PANEL_HEIGHT
VIEW_WIDTH = 21.0  # complex-plane width of the first view
MAX_LEVEL = 45  # doubles run out of precision soon after 45 octaves
FRAME_RATE = 60
ZOOM_SPEED = 1.0  # octaves per second while keyframes keep up
EASE_IN_SECONDS = 0.4
SLOWDOWN_OCTAVES = 1.5  # with fewer octaves rendered ahead, the zoom brakes so it stops at the last one
STALL_SPEED = 0.1  # octaves per second
STALL_SECONDS = 4.0  # a zoom that crawls slower than STALL_SPEED for this long ends at its last keyframe
URGENT_LOOKAHEAD = 2  # keyframes ahead of the view that come before preparing the next zoom
LOOKAHEAD = 8
NEXT_ZOOM_LEVELS = 4  # keyframes of the next zoom to render while the current one plays
BLACK_LIMIT = 3900 / 4096  # a view this black ends the zoom
UNIFORM_RANGE = 4.0  # so does a view without black whose escape counts span no more than this
MAX_WORKERS = 3
WORKER_NICE = 10

BLOCK = 8  # iterations between escape checks; from |z| <= 2, eight squarings cannot overflow a double
SCALAR_TAIL = 12  # below this many orbits, Python complex math beats NumPy's per-call overhead
TAIL_BLOCKS = 256  # scalar blocks between checks of the iteration limit and abort flag
SMOOTH_RADIUS2 = 1e6  # escaped orbits continue to |z| = 1000 so their smooth count does not depend on the block boundary
MIN_ITER = 1000
AUTO_STOP = 4  # stop once no orbit has escaped during the last 3/4 of the iterations
STRICT_EPS2 = 1e-32

BORDER_CHANCE = 0.1
BORDER_MAX_ITER = 100_000
BORDER_PRECISION = 1e-3
BORDER_BATCH = 256
BORDER_BATCHES = 40
BORDER_ATTEMPTS = 3

LUT_SIZE = 4096

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
_GREYSCALE = 9


def _palette_colors(indices, mode):
    colors, keypts = _PALETTES.get(mode, _PALETTES[_GREYSCALE])
    indices = indices % 1
    upper = np.searchsorted(keypts, indices, side="right")
    fraction = ((indices - keypts[upper - 1]) / (keypts[upper] - keypts[upper - 1]))[:, None]
    return (fraction * colors[upper] + (1 - fraction) * colors[upper - 1]).astype(np.uint8)


_luts = {}


def _palette_lut(mode):
    """Palette sampled at LUT_SIZE positions, plus a final black entry for points in the set, with each
    color packed as RGBX bytes in one uint32 because indexing whole words is several times faster."""
    mode = mode if mode in _PALETTES else _GREYSCALE
    if mode not in _luts:
        lut = np.zeros((LUT_SIZE + 1, 4), dtype=np.uint8)
        lut[:LUT_SIZE, :3] = _palette_colors(np.arange(LUT_SIZE) / LUT_SIZE, mode)
        _luts[mode] = lut.view(np.uint32).ravel()
    return _luts[mode]


def colorize(counts, color_mode, color_scale):
    """RGB image of smooth escape counts; NaN counts are black."""
    visible = counts > 0  # False for NaN
    position = np.log2(counts, where=visible, out=np.zeros(counts.shape)) / max(color_scale, 0.01)
    index = ((position - np.floor(position)) * LUT_SIZE).astype(np.intp)
    np.minimum(index, LUT_SIZE - 1, out=index)
    index[~visible] = LUT_SIZE
    height, width = counts.shape
    return Image.frombytes("RGB", (width, height), _palette_lut(color_mode)[index].tobytes(), "raw", "RGBX")


class _Aborted(Exception):
    pass


def _abs2(z):
    parts = z.view(np.float64)
    squares = parts * parts
    return squares[0::2] + squares[1::2]


def _bulb_masks(x, y):
    """Points inside the main cardioid or the period-2 bulb, and points outside radius 2."""
    q = (x - 0.25) ** 2 + y * y
    inside = (q * (q + (x - 0.25)) < 0.25 * y * y) | ((x + 1) ** 2 + y * y < 0.0625)
    return inside, x * x + y * y > 4.0


def _smooth_counts(z, c, iteration):
    count = np.full(z.size, float(iteration))
    size2 = _abs2(z)
    small = np.flatnonzero(size2 < SMOOTH_RADIUS2)
    while small.size:
        zs = z[small]
        zs = zs * zs + c[small]
        z[small] = zs
        count[small] += 1
        size2[small] = _abs2(zs)
        small = small[size2[small] < SMOOTH_RADIUS2]
    return count - np.log2(0.5 * np.log(size2))


def escape_time(c, max_iter, eps2=STRICT_EPS2, min_iter=MIN_ITER, auto_stop=None, should_abort=None):
    """Smooth escape counts for the points c, and the iteration of the last escape.

    Points in the set, points outside radius 2 and points still unresolved at the iteration limit get NaN.
    An orbit that comes back within sqrt(eps2) of a checkpoint is periodic (Brent's method, checked per block).
    With auto_stop, iteration ends once no orbit has escaped during the last 1 - 1/auto_stop of the
    iterations, but not before min_iter or after max_iter.
    """
    nu = np.full(c.size, np.nan)
    inside, outside = _bulb_masks(c.real, c.imag)
    index = np.flatnonzero(~(inside | outside))
    cc = c[index]
    z = cc.copy()
    checkpoint_z = z.copy()
    iteration, blocks, checkpoint, last_escape = 1, 0, 1, 0
    parked = 0  # finished orbits stay in the arrays as NaN until enough accumulate to be worth compacting

    def iteration_limit():
        return max_iter if auto_stop is None else min(max_iter, max(min_iter, auto_stop * last_escape))

    limit = iteration_limit()
    with np.errstate(all="ignore"):
        while iteration < limit and index.size - parked > SCALAR_TAIL:
            if parked * 4 > index.size:
                keep = np.flatnonzero(~np.isnan(z))
                index, cc, z, checkpoint_z = index[keep], cc[keep], z[keep], checkpoint_z[keep]
                parked = 0
            for _ in range(BLOCK):
                np.multiply(z, z, out=z)
                np.add(z, cc, out=z)
            iteration += BLOCK
            blocks += 1
            # Once |z| > 2 the orbit grows without bound, so checking at block ends finds every escape.
            escaped = np.flatnonzero(_abs2(z) > 4.0)
            if escaped.size:
                nu[index[escaped]] = _smooth_counts(z[escaped], cc[escaped], iteration)
                z[escaped] = np.nan
                parked += escaped.size
                last_escape = iteration
                limit = iteration_limit()
            periodic = np.flatnonzero(_abs2(z - checkpoint_z) < eps2)
            if periodic.size:
                z[periodic] = np.nan
                parked += periodic.size
            if blocks == checkpoint:
                np.copyto(checkpoint_z, z)
                checkpoint *= 2
            if should_abort is not None and should_abort():
                raise _Aborted

        live = np.flatnonzero(~np.isnan(z)) if iteration < limit else ()
        orbits = [(int(index[k]), complex(cc[k]), complex(z[k]), complex(checkpoint_z[k])) for k in live]
        while orbits and iteration < limit:
            # Advance the remaining orbits in lockstep so they all see the same live iteration limit.
            steps = min(TAIL_BLOCKS, -(-(limit - iteration) // BLOCK))
            survivors = []
            for k, cv, zv, zc in orbits:
                b, cp = blocks, checkpoint
                for _ in range(steps):
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    zv = zv * zv + cv
                    b += 1
                    size2 = zv.real * zv.real + zv.imag * zv.imag
                    if size2 > 4.0:
                        escape = count = iteration + (b - blocks) * BLOCK
                        while size2 < SMOOTH_RADIUS2:
                            zv = zv * zv + cv
                            count += 1
                            size2 = zv.real * zv.real + zv.imag * zv.imag
                        nu[k] = count - math.log2(0.5 * math.log(size2))
                        last_escape = max(last_escape, escape)
                        break
                    d = zv - zc
                    if d.real * d.real + d.imag * d.imag < eps2:
                        break
                    if b == cp:
                        zc = zv
                        cp *= 2
                else:
                    survivors.append((k, cv, zv, zc))
            orbits = survivors
            for _ in range(steps):
                blocks += 1
                if blocks == checkpoint:
                    checkpoint *= 2
            iteration += steps * BLOCK
            limit = iteration_limit()
            if should_abort is not None and should_abort():
                raise _Aborted
    return nu, last_escape


def render_keyframe(x, y, level, hint=0, should_abort=None):
    """Smooth escape counts (float32, NaN for black) of the view `level` octaves in, the iteration of its
    last escape, and whether the zoom should end at this view.

    hint is the last escape of a shallower keyframe; iterating to at least that keeps a deep view of a
    minibrot from stopping before its first escapes.
    """
    spacing = VIEW_WIDTH * 2.0**-level / KEY_WIDTH
    xs = x + (np.arange(KEY_WIDTH) + 0.5 - KEY_WIDTH / 2) * spacing
    ys = y + (np.arange(KEY_HEIGHT) + 0.5 - KEY_HEIGHT / 2) * spacing
    c = (xs[None, :] + 1j * ys[:, None]).ravel()
    # A tolerance well below the pixel spacing finds cycles sooner than STRICT_EPS2 without misjudging pixels.
    eps = min(1e-12, max(1e-16, spacing * 1e-3))
    max_iter = int(1000 * 2 ** (level / 2))
    counts, last_escape = escape_time(c, max_iter, eps * eps, min_iter=max(MIN_ITER, hint), auto_stop=AUTO_STOP, should_abort=should_abort)
    black = np.isnan(counts)
    final = black.mean() > BLACK_LIMIT or (not black.any() and np.ptp(counts) <= UNIFORM_RANGE)
    return counts.astype(np.float32).reshape(KEY_HEIGHT, KEY_WIDTH), last_escape, bool(final)


def _is_inside_period_3_bulb(x, y):
    # Approximate
    return ((x + 0.12256) ** 2 + (y + 0.74486) ** 2 < 0.00925926) | ((x + 0.12256) ** 2 + (y - 0.74486) ** 2 < 0.00925926)


def find_border_point(rng, precision=BORDER_PRECISION, max_iter=BORDER_MAX_ITER, should_abort=None):
    """A random point near the boundary whose orbit escapes after max_iter/2 to max_iter iterations, or None."""

    def escapes(x, y):
        return x * x + y * y > 4.0 or not np.isnan(escape_time(np.array([complex(x, y)]), max_iter, should_abort=should_abort)[0][0])

    for _ in range(BORDER_ATTEMPTS):
        # A random point in the set, away from its largest components.
        start = None
        while start is None:
            x, y = rng.uniform(-2, 1, BORDER_BATCH), rng.uniform(-1.5, 1.5, BORDER_BATCH)
            inside, outside = _bulb_masks(x, y)
            c = (x + 1j * y)[~(inside | outside | _is_inside_period_3_bulb(x, y))]
            hits = np.flatnonzero(np.isnan(escape_time(c, max_iter, should_abort=should_abort)[0]))
            if hits.size:
                start = c[hits[0]]

        # Walk in a random direction, halving the step whenever it would leave the set.
        x, y = start.real, start.imag
        angle = 2 * math.pi * rng.random()
        dx, dy = 0.1 * math.cos(angle), 0.1 * math.sin(angle)
        while dx * dx + dy * dy >= precision * precision:
            if escapes(x + dx, y + dy):
                dx, dy = dx / 2, dy / 2
            else:
                x, y = x + dx, y + dy

        for _ in range(BORDER_BATCHES):
            tx = x - 2 * dx + 4 * dx * rng.random(BORDER_BATCH)
            ty = y - 2 * dy + 4 * dy * rng.random(BORDER_BATCH)
            counts = escape_time(tx + 1j * ty, max_iter, should_abort=should_abort)[0]
            hits = np.flatnonzero(counts > max_iter / 2)
            if hits.size:
                return float(tx[hits[0]]), float(ty[hits[0]])
    return None


def _worker_main(conn, inherited, cancel, index, parent):
    # A forked worker holds copies of the parent's pipe ends, which would hide the parent closing them.
    for other in inherited:
        other.close()
    try:
        os.nice(WORKER_NICE)
    except OSError:
        pass
    rng = np.random.default_rng()
    while not shared_config.shutdown_requested.value and os.getppid() == parent:
        try:
            if not conn.poll(0.5):
                continue
            task_id, kind, args = conn.recv()
        except (EOFError, OSError):
            return

        def should_abort(task_id=task_id):
            return cancel[index] >= task_id or shared_config.shutdown_requested.value

        try:
            if kind == "keyframe":
                reply = ("ok", render_keyframe(*args, should_abort=should_abort))
            else:
                reply = ("ok", find_border_point(rng, should_abort=should_abort))
        except _Aborted:
            reply = ("aborted", None)
        except Exception:  # noqa: BLE001 - the sign reports worker failures
            reply = ("error", traceback.format_exc())
        try:
            conn.send((task_id, *reply))
        except OSError:
            return


# The workers rely on fork: they inherit the parent's state and must close its pipe ends.
_FORK = multiprocessing.get_context("fork")


class _Slot:
    __slots__ = ("index", "process", "conn", "task")

    def __init__(self, index, process, conn):
        self.index, self.process, self.conn = index, process, conn
        self.task = None  # (task_id, zoom, kind, level) while the worker is busy


class _WorkerPool:
    """Forked worker processes that run one task each at a time."""

    def __init__(self, count):
        self._cancel = RawArray("q", count)  # a worker abandons any task whose id is at most its entry
        self._slots = []
        self._next_id = 1
        parent = os.getpid()
        try:
            for index in range(count):
                here, there = _FORK.Pipe()
                inherited = [slot.conn for slot in self._slots] + [here]
                process = _FORK.Process(target=_worker_main, args=(there, inherited, self._cancel, index, parent), name=f"Mandelbrot{index}", daemon=True)
                try:
                    process.start()
                finally:
                    there.close()
                self._slots.append(_Slot(index, process, here))
        except BaseException:
            self.close()
            raise

    def idle(self):
        return [slot for slot in self._slots if slot.task is None]

    def submit(self, slot, zoom, kind, level, args):
        task_id = self._next_id
        self._next_id += 1
        slot.conn.send((task_id, kind, args))
        slot.task = (task_id, zoom, kind, level)

    def results(self):
        """(zoom, kind, level, status, payload) for each task that has finished."""
        finished = []
        for slot in self._slots:
            if slot.task is None or not slot.conn.poll():
                continue
            try:
                _, status, payload = slot.conn.recv()
            except (EOFError, OSError) as error:
                raise RuntimeError(f"Mandelbrot worker {slot.index} exited unexpectedly") from error
            _, zoom, kind, level = slot.task
            slot.task = None
            finished.append((zoom, kind, level, status, payload))
        return finished

    def cancel(self, zoom, above=-2):
        for slot in self._slots:
            if slot.task is not None and slot.task[1] is zoom and slot.task[3] > above:
                self._cancel[slot.index] = slot.task[0]

    def close(self):
        for slot in self._slots:
            self._cancel[slot.index] = 1 << 62
            slot.conn.close()
        deadline = time.monotonic() + 2.0
        for slot in self._slots:
            slot.process.join(max(0.0, deadline - time.monotonic()))
            if slot.process.exitcode is None:
                slot.process.terminate()
                slot.process.join(1.0)
        self._slots = []


def _worker_count():
    # The installer isolates a core for the panel refresh thread, so the affinity mask shows what is left.
    cores = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    return max(1, min(MAX_WORKERS, cores - 1))


class _Keyframe:
    __slots__ = ("counts", "last_escape", "final", "_image", "_colors")

    def __init__(self, counts, last_escape, final):
        self.counts, self.last_escape, self.final = counts, last_escape, final
        self._image = self._colors = None

    def image(self, colors):
        if colors != self._colors:
            self._image = colorize(self.counts, *colors)
            self._colors = colors
        return self._image


class _Zoom:
    """One zoom into a target point: its keyframes and the displayed zoom level in octaves."""

    def __init__(self, target):
        self.target = target  # None until a border search picks one
        self.searching = False
        self.keyframes = {}
        self.pending = set()
        self.ready = -1  # keyframes 0..ready have all arrived
        self.final = MAX_LEVEL
        self.level = 0.0
        self.speed = 0.0
        self.stalled = 0.0

    @classmethod
    def random(cls, rng, pois):
        return cls(None if rng.random() < BORDER_CHANCE else pois[rng.integers(len(pois))])

    def next_task(self, depth):
        if self.target is None:
            return None if self.searching else ("border", -1)
        for level in range(self.ready + 1, min(self.final, depth) + 1):
            if level not in self.keyframes and level not in self.pending:
                return "keyframe", level
        return None

    def hint(self, level):
        shallower = [n for n in self.keyframes if n < level]
        return self.keyframes[max(shallower)].last_escape if shallower else 0

    def add(self, level, keyframe):
        self.keyframes[level] = keyframe
        if keyframe.final:
            self.final = min(self.final, level)
        while self.ready + 1 in self.keyframes:
            self.ready += 1

    def advance(self, dt):
        """Move the zoom on by dt seconds. Returns True once it has reached its final level."""
        if self.ready < 0:
            return False
        if self.ready >= self.final:
            end, safe = self.final, ZOOM_SPEED
        else:
            # The fastest speed that can still brake to a stop at the last keyframe.
            end = self.ready
            safe = ZOOM_SPEED * min(1.0, math.sqrt(max(0.0, end - self.level) / SLOWDOWN_OCTAVES))
        if safe < self.speed:
            self.speed = safe
        else:
            self.speed += (safe - self.speed) * (1 - math.exp(-dt / EASE_IN_SECONDS))
        self.level = min(self.level + self.speed * dt, end)
        self.stalled = self.stalled + dt if self.speed < STALL_SPEED and self.ready < self.final else 0.0
        return self.level >= self.final


def draw_zoom_frame(sign, outer, inner, fraction):
    """Draw the view `fraction` octaves (0 <= fraction < 1) into keyframe image `outer`, with the next
    keyframe image `inner`, if any, covering the middle where it has more detail."""
    scale = 2.0**-fraction
    half_width, half_height = KEY_WIDTH / 2, KEY_HEIGHT / 2
    frame = outer.resize((PANEL_WIDTH, PANEL_HEIGHT), Image.BOX, box=(half_width * (1 - scale), half_height * (1 - scale), half_width * (1 + scale), half_height * (1 + scale)))
    if inner is not None:
        grow = 2.0**fraction
        left, right = math.ceil(PANEL_WIDTH / 2 - PANEL_WIDTH / 4 * grow), math.floor(PANEL_WIDTH / 2 + PANEL_WIDTH / 4 * grow)
        top, bottom = math.ceil(PANEL_HEIGHT / 2 - PANEL_HEIGHT / 4 * grow), math.floor(PANEL_HEIGHT / 2 + PANEL_HEIGHT / 4 * grow)
        step = 4 * scale  # inner keyframe pixels per panel pixel
        box = (max(0.0, half_width + (left - PANEL_WIDTH / 2) * step), max(0.0, half_height + (top - PANEL_HEIGHT / 2) * step), min(KEY_WIDTH, half_width + (right - PANEL_WIDTH / 2) * step), min(KEY_HEIGHT, half_height + (bottom - PANEL_HEIGHT / 2) * step))
        frame.paste(inner.resize((right - left, bottom - top), Image.BOX, box=box), (left, top))
    sign.canvas.SetImage(frame, 0, 0)
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)


def draw_zoom(sign, zoom, colors):
    level = min(int(zoom.level), zoom.ready)
    inner = zoom.keyframes.get(level + 1)
    draw_zoom_frame(sign, zoom.keyframes[level].image(colors), inner.image(colors) if inner else None, zoom.level - level)


def _schedule(pool, current, upcoming):
    for slot in pool.idle():
        view = int(current.level)
        for zoom, depth in ((current, view + URGENT_LOOKAHEAD), (upcoming, NEXT_ZOOM_LEVELS - 1), (current, view + LOOKAHEAD)):
            task = zoom.next_task(depth)
            if task is not None:
                break
        else:
            return
        kind, level = task
        if kind == "border":
            zoom.searching = True
            pool.submit(slot, zoom, kind, level, ())
        else:
            zoom.pending.add(level)
            pool.submit(slot, zoom, kind, level, (*zoom.target, level, zoom.hint(level)))


_pois = []


def _load_pois():
    if not _pois:
        with open("datafiles/mandelbrot_poi.txt") as file:
            for line in file:
                parts = line.split("\t")
                _pois.append((float(parts[0]), float(parts[1])))
    return _pois


@planesign_mode_handler(DisplayMode.MANDELBROT)
def mandelbrot_zoom(sign):
    sign.canvas.Clear()
    sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
    pois = _load_pois()
    rng = np.random.default_rng()
    pool = None
    try:
        pool = _WorkerPool(_worker_count())
        current, upcoming = _Zoom.random(rng, pois), _Zoom.random(rng, pois)
        interval = 1.0 / FRAME_RATE
        last = next_frame = time.perf_counter()
        drawn = None

        while shared_config.shared_mode.value == DisplayMode.MANDELBROT.value:
            for zoom, kind, level, status, payload in pool.results():
                if kind == "border":
                    zoom.searching = False
                else:
                    zoom.pending.discard(level)
                if status == "error":
                    raise RuntimeError(f"Mandelbrot worker failed:\n{payload}")
                if status != "ok" or zoom not in (current, upcoming):
                    continue
                if kind == "border":
                    zoom.target = payload or pois[rng.integers(len(pois))]
                else:
                    zoom.add(level, _Keyframe(*payload))
                    pool.cancel(zoom, above=zoom.final)

            now = time.perf_counter()
            finished = current.advance(min(now - last, 0.1))
            last = now
            if current.stalled > STALL_SECONDS and current.final > current.ready:
                logging.debug(f"Mandelbrot zoom stalled at level {current.ready}")
                current.final = current.ready
                pool.cancel(current)
            if finished and upcoming.ready >= 0:
                logging.debug(f"Mandelbrot zoom ended at level {current.final}")
                pool.cancel(current)
                current, upcoming = upcoming, _Zoom.random(rng, pois)
            _schedule(pool, current, upcoming)

            if current.ready >= 0:
                colors = (shared_config.shared_mandelbrot_color.value, shared_config.shared_mandelbrot_colorscale.value)
                state = (current, current.level, current.ready, colors)
                if state != drawn:
                    draw_zoom(sign, current, colors)
                    drawn = state

            next_frame = max(next_frame + interval, time.perf_counter() - interval)
            if sign.wait_loop(max(0.0, next_frame - time.perf_counter())):
                return
    finally:
        if pool is not None:
            pool.close()
