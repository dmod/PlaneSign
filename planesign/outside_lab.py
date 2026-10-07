"""Outside lab: set Outside mode's time and weather by hand and see the result on the sign at once.

Open /outside/lab on the API (http://<sign>/api/outside/lab through nginx). It is deliberately not
linked from the web UI. Every lab action switches the sign to Outside. The overrides only affect
Outside: the sign clock and every other mode keep real time and weather. They clear when the sign
leaves Outside, after outside.LAB_IDLE_SECONDS without a lab action, on "Back to live", or on restart.
"""

import logging
import math
import time
from datetime import date, datetime, timedelta

import outside
import psclock
import shared_config
from flask import Blueprint, jsonify, render_template, request
from modes import DisplayMode
from outside_scene import HOLIDAYS, NIGHT_ALTITUDE, WEATHER_DESCRIPTIONS

logger = logging.getLogger(__name__)
blueprint = Blueprint("outside_lab", __name__, url_prefix="/outside/lab")

# Season shortcuts land mid-season (months for the northern hemisphere; shifted six months south of the equator).
SEASON_MONTHS = {"winter": 1, "spring": 4, "summer": 7, "autumn": 10}
# Sun event shortcuts: (label, sun altitude crossed or None for the highest point, rising, minutes before the event to land).
SUN_EVENTS = {
    "sunrise": ("Sunrise", -0.833, True, 15),
    "noon": ("Solar noon", None, None, 0),
    "sunset": ("Sunset", -0.833, False, 20),
    "nightfall": ("Nightfall (lamp on)", NIGHT_ALTITUDE, False, 1),
}
HOLIDAY_TIMES = (("Day", 12, 0), ("Night", 21, 30))
# How long a sun event jump waits for the astronomy worker to cover a newly selected day.
SKY_WAIT_SECONDS = 20
# Weather query parameters: name -> (OutsideWeather field, minimum, maximum, scale).
WEATHER_FIELDS = {
    "clouds": ("clouds", 0, 100, 0.01),
    "wind": ("wind", 0, 200, 1),
    "rain": ("rain", 0, 300, 1),
    "snow": ("snow", 0, 300, 1),
    "temp": ("temperature", -80, 140, 1),
    "visibility": ("visibility", 0, 100000, 1),
}


class LabError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@blueprint.errorhandler(LabError)
def lab_error(error):
    return jsonify({"error": str(error)}), error.status


def location():
    latitude = float(shared_config.CONF["SENSOR_LAT"])
    longitude = float(shared_config.CONF["SENSOR_LON"])
    return latitude, longitude, outside.location_timezone(latitude, longitude)


def displayed_moment(tz) -> datetime:
    return outside.outside_moment(tz, shared_config.shared_outside_offset_minutes.value)


def touch():
    """Record lab activity and show Outside; called before any override is applied."""
    shared_config.shared_outside_lab_activity.value = time.monotonic()
    if shared_config.shared_mode.value != DisplayMode.OUTSIDE.value:
        shared_config.shared_mode.value = DisplayMode.OUTSIDE.value
        shared_config.shared_forced_sign_update.set()


def changed():
    outside.bump_lab_version()
    shared_config.shared_outside_time_update.set()


def set_lab_time(timestamp: float, speed: float | None = None):
    clock = shared_config.shared_outside_lab_clock
    with clock.get_lock():
        if speed is None:
            speed = clock[2] if clock[0] else 1.0
        clock[:] = [timestamp, time.time(), speed]
    # A jump lands the displayed moment itself on the chosen time, so drop any forecast offset.
    shared_config.shared_outside_offset_minutes.value = 0
    changed()


def local_timestamp(day: date, hour: int, minute: int, tz) -> float:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).timestamp()


def sky_for_day(day: date, latitude: float, longitude: float, tz):
    """The astronomy timeline covering the whole local day, moving the lab there first if needed."""
    start = local_timestamp(day, 0, 0, tz)
    end = local_timestamp(day + timedelta(days=1), 0, 0, tz)
    sky = shared_config.data_dict.get("outside_sky")
    if outside.sky_covers(sky, start, end, latitude, longitude):
        return sky, start, end
    set_lab_time(start)
    deadline = time.monotonic() + SKY_WAIT_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.25)
        sky = shared_config.data_dict.get("outside_sky")
        if outside.sky_covers(sky, start, end, latitude, longitude):
            return sky, start, end
    raise LabError("Astronomy is still loading for that day; try again in a moment", 503)


def find_sun_event(name: str, sky, start: float, end: float) -> float | None:
    _, threshold, rising, _ = SUN_EVENTS[name]
    altitudes = sky["sun_altitude"]
    first = max(0, math.ceil((start - sky["start"]) / outside.SKY_SAMPLE_SECONDS))
    last = min(len(altitudes) - 1, math.floor((end - sky["start"]) / outside.SKY_SAMPLE_SECONDS))
    if threshold is None:
        index = max(range(first, last + 1), key=altitudes.__getitem__)
        return sky["start"] + index * outside.SKY_SAMPLE_SECONDS
    for index in range(first, last):
        a, b = altitudes[index], altitudes[index + 1]
        if (a < threshold <= b) if rising else (a >= threshold > b):
            return sky["start"] + (index + (a - threshold) / (a - b)) * outside.SKY_SAMPLE_SECONDS
    return None


def holiday_shortcuts(year: int):
    shortcuts = []
    for month, day in sorted({(month, first) for _, spans in HOLIDAYS.values() for month, first, _ in spans}):
        moment = date(year, month, day)
        environment = outside.OutsideEnvironment("", outside.OutsideWeather("LIVE"), "READY", local_date=moment)
        labels = [HOLIDAYS[feature][0] for feature in HOLIDAYS if feature in outside.holiday_features(environment)]
        shortcuts.append({
            "label": f"{moment:%b} {moment.day}: {', '.join(labels)}",
            "times": [{"label": label, "at": f"{moment.isoformat()}T{hour:02d}:{minute:02d}"} for label, hour, minute in HOLIDAY_TIMES],
        })
    return shortcuts


def state():
    _, _, tz = location()
    return {
        **outside.outside_status(),
        "sign_clock": psclock.describe(),
        "options": {
            "weather_codes": [{"code": code, "description": description} for code, description in sorted(WEATHER_DESCRIPTIONS.items())],
            "seasons": list(SEASON_MONTHS),
            "sun_events": [{"name": name, "label": label, "lead_minutes": lead} for name, (label, _, _, lead) in SUN_EVENTS.items()],
            "holidays": holiday_shortcuts(displayed_moment(tz).year),
            "idle_minutes": outside.LAB_IDLE_SECONDS // 60,
            "emulated": shared_config.emulated_display,
            "ws_port": shared_config.ws_port,
        },
    }


def number(name: str, low: float, high: float) -> float | None:
    text = request.args.get(name, "").strip()
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise LabError(f"{name} must be a number") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise LabError(f"{name} must be between {low:g} and {high:g}")
    return value


@blueprint.route("")
@blueprint.route("/")
def page():
    return render_template("outside_lab.html")


@blueprint.route("/state")
def get_state():
    return jsonify(state())


@blueprint.route("/time")
def set_time():
    """?at=ISO (sensor-local without an offset), ?season=NAME, ?event=NAME, ?speed=FACTOR (alone or combined), or ?reset=1."""
    latitude, longitude, tz = location()
    speed = number("speed", 0.01, 3600)
    touch()
    if request.args.get("reset"):
        with shared_config.shared_outside_lab_clock.get_lock():
            shared_config.shared_outside_lab_clock[:] = [0.0, 0.0, 1.0]
        changed()
    elif "at" in request.args:
        try:
            moment = datetime.fromisoformat(request.args["at"])
        except ValueError:
            raise LabError("at must be an ISO 8601 time, e.g. 2026-12-24T21:30") from None
        set_lab_time((moment if moment.tzinfo else moment.replace(tzinfo=tz)).timestamp(), speed)
    elif "season" in request.args:
        season = request.args["season"]
        if season not in SEASON_MONTHS:
            raise LabError(f"season must be one of {', '.join(SEASON_MONTHS)}")
        moment = displayed_moment(tz)
        month = SEASON_MONTHS[season] if latitude >= 0 else (SEASON_MONTHS[season] + 5) % 12 + 1
        set_lab_time(local_timestamp(date(moment.year, month, 15), moment.hour, moment.minute, tz), speed)
    elif "event" in request.args:
        name = request.args["event"]
        if name not in SUN_EVENTS:
            raise LabError(f"event must be one of {', '.join(SUN_EVENTS)}")
        sky, start, end = sky_for_day(displayed_moment(tz).date(), latitude, longitude, tz)
        at = find_sun_event(name, sky, start, end)
        if at is None:
            raise LabError(f"The sun has no {SUN_EVENTS[name][0].lower()} on this date here", 404)
        set_lab_time(at - SUN_EVENTS[name][3] * 60, speed)
    elif speed is not None:
        set_lab_time(outside.outside_time(), speed)
    else:
        raise LabError("Pass at, season, event, speed or reset")
    logger.info("Outside lab: time %s", request.query_string.decode())
    return jsonify(state())


@blueprint.route("/weather")
def set_weather():
    """?code=OPENWEATHER_ID with optional clouds (%), wind (mph), rain/snow (mm/h), temp (°F), visibility (m); or ?reset=1."""
    if request.args.get("reset"):
        touch()
        shared_config.data_dict["outside_lab_weather"] = None
        changed()
        return jsonify(state())
    try:
        code = int(request.args.get("code", ""))
    except ValueError:
        raise LabError("code must be an OpenWeather condition id") from None
    if code not in WEATHER_DESCRIPTIONS:
        raise LabError(f"Unknown condition {code}")
    override = {"code": code}
    for name, (field, low, high, scale) in WEATHER_FIELDS.items():
        value = number(name, low, high)
        # A blank field stays unknown, exactly like a reading missing from the live feed.
        override[field] = None if value is None else value * scale
    touch()
    shared_config.data_dict["outside_lab_weather"] = override
    changed()
    logger.info("Outside lab: weather %s", request.query_string.decode())
    return jsonify(state())


@blueprint.route("/offset")
def set_offset():
    minutes = number("minutes", 0, 1440)
    if minutes is None or minutes != int(minutes):
        raise LabError("minutes must be an integer from 0 to 1440")
    touch()
    shared_config.shared_outside_offset_minutes.value = int(minutes)
    changed()
    return jsonify(state())


@blueprint.route("/reset")
def reset():
    """Back to the sign clock, live weather and no forecast offset."""
    shared_config.shared_outside_offset_minutes.value = 0
    outside.clear_lab(shared_config.data_dict, "reset from the lab")
    return jsonify(state())
