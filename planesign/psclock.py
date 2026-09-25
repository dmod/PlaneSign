"""Wall clock for display and date logic that can be shifted or sped up for testing.

Use psclock.time() and psclock.now() for "what time is it on the sign": clocks, dates, countdowns, astronomy.
Keep time.time(), time.perf_counter() and time.monotonic() for scheduling, polling, timeouts, caches and the
age of live-streamed data, so a fake clock never changes how often the sign contacts remote services.

The state lives in shared memory created before the child processes fork, so setting it (with --fake-time,
--time-speed or the /debug/clock API) applies to every process at once.
"""

import time as _time
from datetime import UTC, datetime

import shared_config


def _state():
    with shared_config.clock_state.get_lock():
        return tuple(shared_config.clock_state[:])


def time():
    fake_base, real_base, speed = _state()
    return fake_base + (_time.time() - real_base) * speed


def now(tz=None):
    return datetime.fromtimestamp(time(), tz)


def set_clock(timestamp, speed=1.0):
    if not 0 < speed < float("inf"):
        raise ValueError("Clock speed must be a positive number")
    with shared_config.clock_state.get_lock():
        shared_config.clock_state[:] = [float(timestamp), _time.time(), float(speed)]


def reset_clock():
    with shared_config.clock_state.get_lock():
        shared_config.clock_state[:] = [0.0, 0.0, 1.0]


def is_fake():
    return _state() != (0.0, 0.0, 1.0)


def speed():
    return _state()[2]


def parse_time(text):
    """Parse an ISO 8601 time; one without an offset is taken to be in the sign's local timezone."""
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=shared_config.local_timezone or UTC)
    return moment.timestamp()


def describe():
    moment = now(shared_config.local_timezone or UTC)
    text = moment.strftime("%Y-%m-%d %H:%M:%S %Z")
    if is_fake():
        text += f" (fake, x{speed():g})"
    return text
