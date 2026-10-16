"""Outside lab: set Outside mode's time, weather, moon, hemisphere and hut by hand and see the result on the sign at once.
It can also pause Outside and summon its occasional visitors and sky events (outside_scene.SUMMONS).

Open /outside/lab on the API (http://<sign>/api/outside/lab through nginx), or use the "Outside lab"
button in the web UI's Outside controls. Every lab action switches the sign to Outside. The overrides only affect
Outside: the sign clock and every other mode keep real time and weather. They clear when the sign
leaves Outside, after outside.LAB_IDLE_SECONDS without a lab action, on "Back to live" (or the main
page's "Return to now"), or on restart.
"""

import logging
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import outside
import psclock
import shared_config
from flask import Blueprint, jsonify, render_template, request
from modes import DisplayMode
from outside_scene import HOLIDAY_NIGHTS, HOLIDAYS, HUT_STYLES, NIGHT_ALTITUDE, SUMMONS, WEATHER_DESCRIPTIONS, holiday_span_start

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
# Holidays that last the night also get a shortcut into the small hours of the next morning.
HOLIDAY_NIGHT_TIME = ("Before dawn", 3, 0)
# How long a sun event jump waits for the astronomy worker to cover a newly selected day.
SKY_WAIT_SECONDS = 20
# Moon positions the lab can place the moon at: name -> (label, altitude, azimuth). Each lands in open sky
# (east above the lamp, high in the middle, low between the mountain and the tree); None keeps the computed position.
MOON_POSITIONS = {
    "actual": ("Actual", None, None),
    "east": ("East", 34, 98),
    "high": ("High", 55, 180),
    "west": ("Low west", 12, 215),
}
# Named phase shortcuts in degrees (0 new, 90 first quarter, 180 full, 270 last quarter).
MOON_PHASES = (("New", 0), ("Waxing crescent", 45), ("First quarter", 90), ("Waxing gibbous", 135), ("Full", 180), ("Waning gibbous", 225), ("Last quarter", 270), ("Waning crescent", 315))
# Hemispheres the lab can show: their constellations and seasons. The sun and moon stay where they are at the sign's location.
HEMISPHERES = {"north": "Northern", "south": "Southern"}


@dataclass(frozen=True)
class WeatherField:
    field: str
    label: str
    unit: str
    # Accepted by /weather, in the query's units.
    low: float
    high: float
    # Query units to OutsideWeather units.
    scale: float
    # The page's slider (min, max, step): what the scene reacts to, finer than the accepted range.
    slider: tuple[float, float, float]
    # outside_status() key holding the shown reading, in OutsideWeather units.
    status_key: str


# Weather query parameters, in the order the page shows them.
WEATHER_FIELDS = {
    "clouds": WeatherField("clouds", "Clouds", "%", 0, 100, 0.01, (0, 100, 1), "cloud_cover"),
    "wind": WeatherField("wind", "Wind", "mph", 0, 200, 1, (0, 60, 1), "wind_mph"),
    "temp": WeatherField("temperature", "Temp", "°F", -80, 140, 1, (-20, 110, 1), "temperature_f"),
    "dew_point": WeatherField("dew_point", "Dew point", "°F", -80, 100, 1, (-10, 85, 1), "dew_point_f"),
    "rain": WeatherField("rain", "Rain", "mm/h", 0, 300, 1, (0, 20, 0.1), "rain_mm_h"),
    "snow": WeatherField("snow", "Snow", "mm/h", 0, 300, 1, (0, 10, 0.1), "snow_mm_h"),
    # OpenWeather reports visibility up to 10 km.
    "visibility": WeatherField("visibility", "Visibility", "m", 0, 100000, 1, (0, 10000, 100), "visibility_m"),
}
# Weather presets: OpenWeather condition id plus readings in the query's units.
WEATHER_PRESETS = (
    ("Clear", {"code": 800, "clouds": 0, "wind": 5, "rain": 0, "snow": 0, "temp": 72, "dew_point": 50, "visibility": 10000}),
    ("Partly cloudy", {"code": 802, "clouds": 40, "wind": 8, "rain": 0, "snow": 0, "temp": 70, "dew_point": 52, "visibility": 10000}),
    ("Mostly cloudy", {"code": 803, "clouds": 75, "wind": 9, "rain": 0, "snow": 0, "temp": 66, "dew_point": 55, "visibility": 10000}),
    ("Overcast", {"code": 804, "clouds": 100, "wind": 10, "rain": 0, "snow": 0, "temp": 60, "dew_point": 52, "visibility": 10000}),
    ("Drizzle", {"code": 300, "clouds": 90, "wind": 6, "rain": 0.3, "snow": 0, "temp": 58, "dew_point": 56, "visibility": 8000}),
    ("Rain", {"code": 501, "clouds": 95, "wind": 12, "rain": 3, "snow": 0, "temp": 55, "dew_point": 53, "visibility": 6000}),
    ("Heavy rain", {"code": 502, "clouds": 100, "wind": 18, "rain": 10, "snow": 0, "temp": 55, "dew_point": 54, "visibility": 3000}),
    ("Light thunderstorm", {"code": 210, "clouds": 80, "wind": 14, "rain": 1, "snow": 0, "temp": 76, "dew_point": 68, "visibility": 8000}),
    ("Thunderstorm", {"code": 211, "clouds": 95, "wind": 20, "rain": 5, "snow": 0, "temp": 75, "dew_point": 70, "visibility": 5000}),
    ("Heavy thunderstorm", {"code": 212, "clouds": 100, "wind": 26, "rain": 12, "snow": 0, "temp": 74, "dew_point": 71, "visibility": 3000}),
    ("Light snow", {"code": 600, "clouds": 90, "wind": 5, "rain": 0, "snow": 0.5, "temp": 28, "dew_point": 25, "visibility": 5000}),
    ("Heavy snow", {"code": 602, "clouds": 100, "wind": 12, "rain": 0, "snow": 4, "temp": 24, "dew_point": 22, "visibility": 1000}),
    ("Sleet", {"code": 611, "clouds": 100, "wind": 10, "rain": 1, "snow": 0.5, "temp": 33, "dew_point": 31, "visibility": 4000}),
    ("Fog", {"code": 741, "clouds": 70, "wind": 2, "rain": 0, "snow": 0, "temp": 50, "dew_point": 50, "visibility": 300}),
    ("Windy", {"code": 801, "clouds": 15, "wind": 28, "rain": 0, "snow": 0, "temp": 65, "dew_point": 45, "visibility": 10000}),
    ("Freezing and clear", {"code": 800, "clouds": 0, "wind": 4, "rain": 0, "snow": 0, "temp": 20, "dew_point": 8, "visibility": 10000}),
    ("Warm, calm evening", {"code": 800, "clouds": 5, "wind": 3, "rain": 0, "snow": 0, "temp": 80, "dew_point": 62, "visibility": 10000}),
    ("Beach day", {"code": 800, "clouds": 10, "wind": 7, "rain": 0, "snow": 0, "temp": 84, "dew_point": 62, "visibility": 10000}),
    ("Hot and muggy", {"code": 801, "clouds": 20, "wind": 6, "rain": 0, "snow": 0, "temp": 90, "dew_point": 75, "visibility": 10000}),
)
LAB_SPEEDS = (("Pause", 0), ("×1", 1), ("×10", 10), ("×60", 60), ("×300", 300))
# How long /summon waits for the Outside loop to find the event and report back.
SUMMON_WAIT_SECONDS = 3


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
    for moment in sorted({holiday_span_start(span, year) for _, spans in HOLIDAYS.values() for span in spans}):
        environment = outside.OutsideEnvironment("", outside.OutsideWeather("LIVE"), "READY", local_date=moment)
        labels = [HOLIDAYS[feature][0] for feature in HOLIDAYS if feature in outside.holiday_features(environment)]
        times = [(label, moment, hour, minute) for label, hour, minute in HOLIDAY_TIMES]
        if (moment.month, moment.day) in HOLIDAY_NIGHTS:
            label, hour, minute = HOLIDAY_NIGHT_TIME
            times.append((label, moment + timedelta(days=1), hour, minute))
        shortcuts.append({
            "label": f"{moment:%b} {moment.day}: {', '.join(labels)}",
            "times": [{"label": label, "at": f"{day.isoformat()}T{hour:02d}:{minute:02d}"} for label, day, hour, minute in times],
        })
    return shortcuts


def page_options():
    """Settings the lab page needs once, rendered into it rather than resent with every poll."""
    return {
        "weather_codes": [{"code": code, "description": description} for code, description in sorted(WEATHER_DESCRIPTIONS.items())],
        "weather_fields": [{"name": name, "field": f.field, "label": f.label, "unit": f.unit, "min": f.slider[0], "max": f.slider[1], "step": f.slider[2], "scale": f.scale} for name, f in WEATHER_FIELDS.items()],
        "weather_presets": [{"label": label, "values": values} for label, values in WEATHER_PRESETS],
        "speeds": [{"label": label, "speed": speed} for label, speed in LAB_SPEEDS],
        "seasons": list(SEASON_MONTHS),
        "sun_events": [{"name": name, "label": label, "lead_minutes": lead} for name, (label, _, _, lead) in SUN_EVENTS.items()],
        "moon_positions": [{"name": name, "label": label} for name, (label, _, _) in MOON_POSITIONS.items()],
        "moon_phases": [{"label": label, "phase": phase} for label, phase in MOON_PHASES],
        "hemispheres": [{"name": name, "label": label} for name, label in HEMISPHERES.items()],
        "huts": [{"name": name, "label": style.label} for name, style in HUT_STYLES.items()],
        "summons": [{"name": name, "label": summon.label, "requirement": summon.requirement} for name, summon in SUMMONS.items()],
        "idle_minutes": outside.LAB_IDLE_SECONDS // 60,
        # The emulator's frame server, for the live preview; None on the physical panel.
        "preview_port": shared_config.ws_port if shared_config.emulated_display else None,
    }


def state():
    _, _, tz = location()
    status, environment = outside.outside_status_and_environment()
    return {
        **status,
        "sign_clock": psclock.describe(),
        # The readings the sign is showing, in the weather form's units; None is an unknown reading.
        "weather_form": {"code": status["condition_code"], **{name: None if status[f.status_key] is None else status[f.status_key] / f.scale for name, f in WEATHER_FIELDS.items()}},
        "summons_allowed": {name: summon.allowed(environment) for name, summon in SUMMONS.items()},
        # Follows the shown year, so it is sent with every state.
        "holiday_shortcuts": holiday_shortcuts(displayed_moment(tz).year),
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
    return render_template("outside_lab.html", options=page_options())


@blueprint.route("/state")
def get_state():
    return jsonify(state())


@blueprint.route("/time")
def set_time():
    """?at=ISO (sensor-local without an offset), ?season=NAME, ?event=NAME, ?speed=FACTOR (alone or combined; 0 pauses), or ?reset=1."""
    latitude, longitude, tz = location()
    speed = number("speed", 0, 3600)
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
        hemisphere = outside.hemisphere_at(latitude, shared_config.data_dict.get("outside_lab_hemisphere"))
        month = SEASON_MONTHS[season] if hemisphere == "north" else (SEASON_MONTHS[season] + 5) % 12 + 1
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
    """?code=OPENWEATHER_ID with optional clouds (%), wind (mph), rain/snow (mm/h), temp and dew_point (°F), visibility (m); or ?reset=1."""
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
    for name, field in WEATHER_FIELDS.items():
        value = number(name, field.low, field.high)
        # A blank field stays unknown, exactly like a reading missing from the live feed.
        override[field.field] = None if value is None else value * field.scale
    touch()
    shared_config.data_dict["outside_lab_weather"] = override
    changed()
    logger.info("Outside lab: weather %s", request.query_string.decode())
    return jsonify(state())


@blueprint.route("/moon")
def set_moon():
    """?phase=DEGREES (0 new, 180 full) and/or ?position=NAME; whichever is omitted keeps its current setting. Or ?reset=1."""
    if request.args.get("reset"):
        touch()
        shared_config.data_dict["outside_lab_moon"] = None
        changed()
        return jsonify(state())
    phase = number("phase", 0, 360)
    position = request.args.get("position")
    if position is not None and position not in MOON_POSITIONS:
        raise LabError(f"position must be one of {', '.join(MOON_POSITIONS)}")
    if phase is None and position is None:
        raise LabError("Pass phase, position or reset")
    override = dict(shared_config.data_dict.get("outside_lab_moon") or {"phase": None, "position": "actual", "altitude": None, "azimuth": None})
    if phase is not None:
        override["phase"] = phase % 360
    if position is not None:
        _, altitude, azimuth = MOON_POSITIONS[position]
        override.update(position=position, altitude=altitude, azimuth=azimuth)
    touch()
    shared_config.data_dict["outside_lab_moon"] = override
    changed()
    logger.info("Outside lab: moon %s", request.query_string.decode())
    return jsonify(state())


@blueprint.route("/hemisphere")
def set_hemisphere():
    """?name=north|south shows that hemisphere's constellations and seasons; or ?reset=1 for the sign's own."""
    if request.args.get("reset"):
        hemisphere = None
    else:
        hemisphere = request.args.get("name", "")
        if hemisphere not in HEMISPHERES:
            raise LabError(f"name must be one of {', '.join(HEMISPHERES)}")
    touch()
    shared_config.data_dict["outside_lab_hemisphere"] = hemisphere
    changed()
    logger.info("Outside lab: hemisphere %s", request.query_string.decode())
    return jsonify(state())


@blueprint.route("/hut")
def set_hut():
    """?name=STYLE (an outside_scene.HUT_STYLES key) shows the hut in that style; or ?reset=1 for the default hut."""
    if request.args.get("reset"):
        hut = None
    else:
        hut = request.args.get("name", "")
        if hut not in HUT_STYLES:
            raise LabError(f"name must be one of {', '.join(HUT_STYLES)}")
    touch()
    shared_config.data_dict["outside_lab_hut"] = hut
    changed()
    logger.info("Outside lab: hut %s", request.query_string.decode())
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


@blueprint.route("/summon")
def summon():
    """?event=NAME: skip Outside's animation ahead to just before that event's next natural appearance."""
    name = request.args.get("event", "")
    if name not in SUMMONS:
        raise LabError(f"event must be one of {', '.join(SUMMONS)}")
    touch()
    request_id = time.time()
    shared_config.data_dict["outside_lab_summon"] = {"id": request_id, "event": name}
    changed()
    deadline = time.monotonic() + SUMMON_WAIT_SECONDS
    while time.monotonic() < deadline:
        result = shared_config.data_dict.get("outside_lab_summon_result")
        if result is not None and result["id"] == request_id:
            if result["error"]:
                raise LabError(result["error"], 409)
            return jsonify(state())
        time.sleep(0.05)
    raise LabError("Outside did not pick up the request; try again once it is showing", 504)


@blueprint.route("/reset")
def reset():
    """Back to the sign clock, live weather and no forecast offset."""
    shared_config.shared_outside_offset_minutes.value = 0
    outside.clear_lab(shared_config.data_dict, "reset from the lab")
    return jsonify(state())
