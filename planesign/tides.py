import logging
import math
import time
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from modes import DisplayMode

import __main__


STATIONS_URL = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
PREDICTIONS_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
SAMPLE_SECONDS = 360
HALF_WINDOW = 12 * 60 * 60
GRAPH_WIDTH = 80
GRAPH_TOP = 9
GRAPH_BOTTOM = 23
CATALOG_TTL = 24 * 60 * 60
PREDICTIONS_TTL = 6 * 60 * 60
MAX_RETRY = 15 * 60
FRAME_INTERVAL = 0.05
SWELL_LENGTH = 29.0
SWELL_SPEED = 0.16
RIPPLE_LENGTH = 13.0
RIPPLE_SPEED = 0.27
WAVE_CONTRAST = 0.30
FOAM_MIX = 0.40
PAST_SHADE = 0.60
OCEAN_SURFACE = (26, 116, 168)
OCEAN_DEEP = (4, 24, 58)
OCEAN_FOAM = (150, 226, 240)
GUIDE_COLOR = (48, 40, 10)
NOW_COLOR = (255, 215, 40)
ARROW_COUNT = 3
ARROW_PERIOD = 3.6
SLACK_PERIOD = 3.0


class NOAAError(ValueError):
    def __init__(self, message, retry_after=0, unsupported=False):
        super().__init__(message)
        self.retry_after = retry_after
        self.unsupported = unsupported


def sensor_location(config):
    try:
        latitude = float(config["SENSOR_LAT"])
        longitude = float(config["SENSOR_LON"])
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return latitude, longitude


def nearest_station(stations, location, excluded=()):
    import utilities

    candidates = []
    for station in stations:
        if station.get("type") != "R" or station.get("id") in excluded:
            continue
        coordinates = sensor_location({"SENSOR_LAT": station.get("lat"), "SENSOR_LON": station.get("lng")})
        if coordinates is None or not station.get("id") or not station.get("name"):
            continue
        distance = utilities.get_distance(location, coordinates)
        candidates.append({"id": station["id"], "name": station["name"], "lat": coordinates[0], "lon": coordinates[1], "distance": distance})
    if not candidates:
        raise ValueError("No NOAA detailed-prediction stations available")
    return min(candidates, key=lambda station: (station["distance"], station["id"]))


def parse_predictions(payload, events=False):
    if not isinstance(payload, dict) or payload.get("error") or not payload.get("predictions"):
        raise ValueError("NOAA returned no predictions")
    records = {}
    try:
        for record in payload["predictions"]:
            timestamp = datetime.strptime(record["t"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
            height = float(record["v"])
            if not math.isfinite(height):
                raise ValueError("Non-finite tide height")
            if events:
                kind = record["type"]
                if kind not in ("H", "L"):
                    raise ValueError("Invalid tide event")
                parsed = (timestamp, height, kind)
            else:
                parsed = (timestamp, height)
            if timestamp in records and records[timestamp] != parsed:
                raise ValueError("Conflicting tide predictions")
            records[timestamp] = parsed
    except (KeyError, TypeError, OverflowError) as error:
        raise ValueError("Malformed NOAA predictions") from error
    result = sorted(records.values())
    if len(result) < 2:
        raise ValueError("Insufficient NOAA predictions")
    return result


def sample_height(samples, timestamp):
    index = bisect_left(samples, (timestamp,))
    if index < len(samples) and samples[index][0] == timestamp:
        return samples[index][1]
    if index == 0 or index == len(samples):
        return None
    before, after = samples[index - 1], samples[index]
    if after[0] - before[0] > SAMPLE_SECONDS:
        return None
    fraction = (timestamp - before[0]) / (after[0] - before[0])
    return before[1] + fraction * (after[1] - before[1])


def next_event(events, now, kind):
    return next((event for event in events if event[0] >= now and event[2] == kind), None)


def covers_display(payload, now):
    if not payload or not payload.get("samples") or not payload.get("events"):
        return False
    samples = payload["samples"]
    start, end = now - HALF_WINDOW, now + HALF_WINDOW
    if sample_height(samples, start) is None or sample_height(samples, end) is None:
        return False
    first = max(0, bisect_left(samples, (start,)) - 1)
    last = bisect_left(samples, (end,))
    if any(samples[index + 1][0] - samples[index][0] > SAMPLE_SECONDS for index in range(first, last)):
        return False
    return all(next_event(payload["events"], now, kind) is not None for kind in ("H", "L"))


def noaa_json(session, url, params, now):
    response = session.get(url, params=params, timeout=(5, 20))
    retry_after = response.headers.get("Retry-After", "0")
    try:
        retry_after = max(0, float(retry_after))
    except (TypeError, ValueError):
        try:
            retry_after = max(0, parsedate_to_datetime(retry_after).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            retry_after = 0
    if not math.isfinite(retry_after):
        retry_after = 0
    if response.status_code != 200:
        raise NOAAError(f"NOAA HTTP {response.status_code}", retry_after=retry_after)
    payload = response.json()
    if not isinstance(payload, dict):
        raise NOAAError("Malformed NOAA response")
    if payload.get("error"):
        message = str(payload["error"])
        lower_message = message.lower()
        unsupported = params.get("interval") == "6" and ("subordinate" in lower_message or ("high/low" in lower_message and "only" in lower_message))
        raise NOAAError(message, retry_after=retry_after, unsupported=unsupported)
    return payload


def fetch_predictions(session, station_id, now):
    today = datetime.fromtimestamp(now, timezone.utc)
    params = {"product": "predictions", "application": "PlaneSign", "station": station_id, "datum": "MLLW", "time_zone": "gmt", "units": "english", "format": "json", "begin_date": (today - timedelta(days=1)).strftime("%Y%m%d"), "end_date": (today + timedelta(days=2)).strftime("%Y%m%d")}
    samples = parse_predictions(noaa_json(session, PREDICTIONS_URL, {**params, "interval": "6"}, now))
    events = parse_predictions(noaa_json(session, PREDICTIONS_URL, {**params, "interval": "hilo"}, now), events=True)
    return {"samples": samples, "events": events}


@lru_cache(maxsize=8)
def sensor_timezone(location):
    from timezonefinder import TimezoneFinder

    return TimezoneFinder().timezone_at(lat=location[0], lng=location[1]) or "UTC"


class TideCache:
    def __init__(self, session):
        self.session = session
        self.location = None
        self.station = None
        self.catalog = []
        self.catalog_at = 0
        self.excluded = set()
        self.snapshot = None
        self.next_attempt = 0
        self.failures = 0

    def poll(self, config, now, active=True):
        if not active:
            return None
        location = sensor_location(config)
        if location != self.location:
            self.location = location
            self.station = None
            self.snapshot = None
            self.next_attempt = 0
            self.failures = 0
        if location is None:
            return {"location": None, "status": "invalid"}
        if now < self.next_attempt:
            return None
        if self.snapshot and now - self.snapshot["fetched_at"] < PREDICTIONS_TTL and covers_display(self.snapshot, now):
            return None
        try:
            if not self.catalog or now - self.catalog_at >= CATALOG_TTL:
                catalog = noaa_json(self.session, STATIONS_URL, {"type": "tidepredictions"}, now).get("stations")
                if not isinstance(catalog, list) or not catalog or not all(isinstance(station, dict) for station in catalog):
                    raise NOAAError("Missing NOAA station catalog")
                self.catalog = catalog
                self.catalog_at = now
                self.excluded.clear()
                self.station = None
            if self.station is None:
                self.station = nearest_station(self.catalog, location, self.excluded)
            predictions = fetch_predictions(self.session, self.station["id"], now)
            if not covers_display(predictions, now):
                raise NOAAError("NOAA predictions do not cover the display interval")
            snapshot = {**predictions, "location": location, "station": self.station, "timezone": sensor_timezone(location), "units": "ft", "datum": "MLLW", "fetched_at": now, "status": "ready"}
            self.snapshot = snapshot
            self.failures = 0
            self.next_attempt = 0
            logging.info("NOAA tides: %s (%s), %.1f miles from sensor", self.station["name"], self.station["id"], self.station["distance"])
            return snapshot
        except Exception as error:
            self.failures += 1
            delay = min(MAX_RETRY, 30 * 2 ** min(self.failures - 1, 5))
            if isinstance(error, NOAAError):
                delay = max(delay, error.retry_after)
                if error.unsupported and self.station:
                    self.excluded.add(self.station["id"])
                    self.station = None
                    self.snapshot = None
                    delay = max(1, error.retry_after)
            self.next_attempt = now + delay
            logging.warning("NOAA tides unavailable; retry in %ss: %s", delay, error)
            if self.snapshot and covers_display(self.snapshot, now):
                return {**self.snapshot, "status": "cached"}
            return {"location": location, "status": "unavailable"}


def get_tides_data_worker(data_dict):
    import signal

    import requests
    import shared_config

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    with requests.Session() as session:
        cache = TideCache(session)
        while not shared_config.shared_shutdown_event.is_set():
            config = shared_config.CONF.copy()
            payload = cache.poll(config, time.time(), active=shared_config.shared_mode.value == DisplayMode.TIDES.value)
            if payload is not None and payload["location"] == sensor_location(shared_config.CONF.copy()):
                data_dict["tides"] = payload
            shared_config.shared_shutdown_event.wait(timeout=1)


def graph_points(samples, now):
    heights = [sample_height(samples, now - HALF_WINDOW + column * 2 * HALF_WINDOW / (GRAPH_WIDTH - 1)) for column in range(GRAPH_WIDTH)]
    current = sample_height(samples, now)
    visible = [height for height in heights + [current] if height is not None]
    if not visible:
        return [None] * GRAPH_WIDTH, None
    minimum, maximum = min(visible), max(visible)
    padding = max(0.1, (maximum - minimum) * 0.1)
    minimum -= padding
    maximum += padding

    def row(height):
        return round(GRAPH_BOTTOM - (height - minimum) / (maximum - minimum) * (GRAPH_BOTTOM - GRAPH_TOP))

    return [None if height is None else row(height) for height in heights], None if current is None else (GRAPH_WIDTH // 2, row(current))


def blend_color(base, target, amount):
    return [base[index] + (target[index] - base[index]) * amount for index in range(3)]


def wave_field(column, depth, elapsed):
    swell = math.sin(2 * math.pi * (column / SWELL_LENGTH - elapsed * SWELL_SPEED) - depth * 0.30)
    ripple = math.sin(2 * math.pi * (column / RIPPLE_LENGTH + elapsed * RIPPLE_SPEED) - depth * 0.55)
    return 0.62 * swell + 0.38 * ripple


def draw_ocean(canvas, points, elapsed):
    middle = GRAPH_WIDTH // 2
    for column in range(GRAPH_WIDTH):
        surface = points[column]
        if surface is None:
            continue
        side = PAST_SHADE if column < middle else 1.0
        for row in range(surface + 1, GRAPH_BOTTOM + 1):
            depth = row - surface
            wave = wave_field(column, depth, elapsed)
            color = blend_color(OCEAN_SURFACE, OCEAN_DEEP, min(1.0, (depth - 1) / 7.0))
            level = max(0.0, 1.0 + WAVE_CONTRAST * math.exp(-(depth - 1) / 4.5) * wave)
            color = [value * level for value in color]
            if depth == 1:
                color = blend_color(color, OCEAN_FOAM, FOAM_MIX * max(0.0, wave) ** 2)
            canvas.SetPixel(column, row, *(min(255, int(value * side)) for value in color))


def draw_now_line(canvas, direction, elapsed):
    middle = GRAPH_WIDTH // 2
    pulse = 0.5 + 0.5 * math.sin(2 * math.pi * elapsed / SLACK_PERIOD)
    guide = GUIDE_COLOR if direction else blend_color(GUIDE_COLOR, NOW_COLOR, 0.35 * pulse)
    for row in range(GRAPH_TOP, GRAPH_BOTTOM + 1):
        canvas.SetPixel(middle, row, *(int(value) for value in guide))


def draw_trend_arrows(canvas, direction, elapsed):
    if not direction:
        return
    middle = GRAPH_WIDTH // 2
    span = GRAPH_BOTTOM - GRAPH_TOP
    # Sub-pixel weights let the chevrons drift smoothly across only 15 rows.
    weights = {}
    for index in range(ARROW_COUNT):
        progress = (elapsed / ARROW_PERIOD + index / ARROW_COUNT) % 1.0
        tip = GRAPH_BOTTOM - progress * span if direction > 0 else GRAPH_TOP + progress * span
        fade = math.sin(math.pi * progress) ** 0.5
        for offset_x, offset_y in ((0, 0), (0, direction), (-1, direction), (1, direction)):
            exact = tip + offset_y
            lower = math.floor(exact)
            for row, share in ((lower, lower + 1 - exact), (lower + 1, exact - lower)):
                if GRAPH_TOP <= row <= GRAPH_BOTTOM:
                    key = (middle + offset_x, row)
                    weights[key] = max(weights.get(key, 0.0), fade * share)
    for (column, row), level in weights.items():
        if level >= 0.1:
            canvas.SetPixel(column, row, *(int(value) for value in blend_color(GUIDE_COLOR, NOW_COLOR, level)))


def tide_trend(payload, now):
    for timestamp, _, kind in payload["events"]:
        if abs(timestamp - now) <= 180:
            return "HIGH" if kind == "H" else "LOW"
    before = sample_height(payload["samples"], now - SAMPLE_SECONDS)
    after = sample_height(payload["samples"], now + SAMPLE_SECONDS)
    if before is None or after is None or abs(after - before) < 0.005:
        return "LEVEL"
    return "RISING" if after > before else "FALLING"


def event_label(event, now, timezone_name, military_time):
    timestamp, height, kind = event
    local_zone = ZoneInfo(timezone_name)
    local_event = datetime.fromtimestamp(timestamp, local_zone)
    if military_time:
        clock = local_event.strftime("%H:%M")
    else:
        clock = local_event.strftime("%-I:%M") + ("a" if local_event.hour < 12 else "p")
    return f"{'HIGH' if kind == 'H' else 'LOW'} {clock}"


def draw_tides_frame(sign, payload, config, now, elapsed):
    from rgbmatrix import graphics

    sign.canvas.Clear()

    def label(text, baseline, color, column=0):
        text = text.encode("ascii", "replace").decode("ascii")[: (128 - column) // 4]
        graphics.DrawText(sign.canvas, sign.font46, column, baseline, graphics.Color(*color), text)

    location = sensor_location(config)
    if location is None:
        message = "INVALID SENSOR LOCATION"
    elif not payload or payload.get("location") != location:
        message = "LOADING NOAA TIDES..."
    elif payload.get("status") == "unavailable":
        message = "NOAA TIDES UNAVAILABLE"
    elif not covers_display(payload, now):
        message = "TIDE DATA EXPIRED"
    else:
        message = None
    if message:
        label("TIDES", 10, (80, 210, 200))
        label(message, 23, (240, 180, 90))
        return

    points, marker = graph_points(payload["samples"], now)
    middle = GRAPH_WIDTH // 2
    trend = tide_trend(payload, now)
    direction = {"RISING": 1, "FALLING": -1}.get(trend, 0)
    draw_ocean(sign.canvas, points, elapsed)
    draw_now_line(sign.canvas, direction, elapsed)
    for column in range(1, GRAPH_WIDTH):
        if points[column - 1] is not None and points[column] is not None:
            color = graphics.Color(20, 90, 100) if column < middle else graphics.Color(40, 230, 170)
            graphics.DrawLine(sign.canvas, column - 1, points[column - 1], column, points[column], color)
    if marker is not None:
        sign.canvas.SetPixel(marker[0], marker[1], 255, 255, 255)
    draw_trend_arrows(sign.canvas, direction, elapsed)
    label("-12h", 31, (100, 145, 165))
    label("NOW", 31, (255, 215, 40), middle - 6)
    label("+12h", 31, (100, 145, 165), GRAPH_WIDTH - 16)

    phase = int(now // 5) % 2
    cached = payload["status"] == "cached" or now - payload["fetched_at"] >= PREDICTIONS_TTL
    if phase == 0:
        distance = f"{payload['station']['distance']:.0f}mi"
        prefix = "*" if cached else ""
        station_name = payload["station"]["name"].upper()
        top = prefix + station_name[: 31 - len(distance) - len(prefix)] + " " + distance
    else:
        height = sample_height(payload["samples"], now)
        top = f"{'CACHED' if cached else 'NOAA'} PRED 24H {height:.1f}ft {trend}"
    label(top, 5, (255, 190, 90) if cached else (160, 205, 230))
    military = str(config.get("MILITARY_TIME", "false")).lower() == "true"
    event_column = GRAPH_WIDTH + 4
    for kind, baseline, color in (("H", 12, (230, 200, 110)), ("L", 25, (130, 200, 245))):
        event = next_event(payload["events"], now, kind)
        label(event_label(event, now, payload["timezone"], military), baseline, color, event_column)
        label(f"{event[1]:.1f}ft", baseline + 6, color, event_column)


@__main__.planesign_mode_handler(DisplayMode.TIDES)
def show_tides(sign):
    import shared_config

    while shared_config.shared_mode.value == DisplayMode.TIDES.value:
        draw_tides_frame(sign, shared_config.data_dict.get("tides"), shared_config.CONF.copy(), time.time(), time.monotonic())
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(FRAME_INTERVAL):
            return
