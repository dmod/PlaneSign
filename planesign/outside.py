"""Local astronomy and existing OpenWeather observations/forecasts for Outside."""

import logging
import math
import os
import random
import signal
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import numpy as np
import psclock
import requests
import shared_config
import utilities
from modes import DisplayMode, planesign_mode_handler
from outside_scene import WEATHER_DESCRIPTIONS, draw_outside_frame
from skyfield import almanac
from skyfield.api import Loader, load_file, wgs84
from skyfield.errors import EphemerisRangeError

logger = logging.getLogger(__name__)
WEATHER_LIVE_SECONDS = 1800
WEATHER_CACHE_SECONDS = 7200
WEATHER_CODES = frozenset(WEATHER_DESCRIPTIONS)
SKY_SAMPLE_SECONDS = 60
SKY_PRELOAD_SECONDS = 26 * 3600
# Past samples let the scene know when the sun last set (the yard lamp burns for three hours after sunset).
SKY_HISTORY_SECONDS = 4 * 3600
SUNSET_ALTITUDE = -0.833
SKY_REFRESH_MARGIN_SECONDS = 1800
SKY_FIELDS = ("sun_altitude", "sun_azimuth", "moon_altitude", "moon_azimuth", "moon_phase")
OFFSET_TRANSITION_SECONDS = 0.15


@dataclass(frozen=True)
class OutsideWeather:
    status: str
    code: int | None = None
    clouds: float | None = None
    wind: float | None = None
    rain: float | None = None
    snow: float | None = None
    temperature: float | None = None
    visibility: float | None = None
    observed_at: float | None = None
    forecast_at: float | None = None


@dataclass(frozen=True)
class OutsideEnvironment:
    season: str
    weather: OutsideWeather
    sky_status: str
    sun_altitude: float | None = None
    sun_azimuth: float = 180
    moon_altitude: float | None = None
    moon_azimuth: float = 180
    moon_phase: float = 0
    offset_minutes: int = 0
    since_sunset: float | None = None


def reading(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def weather_readings(current, status: str, observed: float, forecast_at: float | None = None) -> OutsideWeather:
    conditions = current.get("weather")
    code = conditions[0].get("id") if isinstance(conditions, list) and conditions and isinstance(conditions[0], dict) else None
    if not isinstance(code, int) or isinstance(code, bool) or code not in WEATHER_CODES:
        return OutsideWeather("UNAVAILABLE", observed_at=observed, forecast_at=forecast_at)
    clouds = reading(current.get("clouds"))
    wind = reading(current.get("wind_speed"))
    rain = reading(current.get("rain", {}).get("1h")) if isinstance(current.get("rain", {}), dict) else None
    snow = reading(current.get("snow", {}).get("1h")) if isinstance(current.get("snow", {}), dict) else None
    visibility = reading(current.get("visibility"))
    return OutsideWeather(
        status,
        code=code,
        clouds=clouds / 100 if clouds is not None and 0 <= clouds <= 100 else None,
        wind=wind if wind is not None and wind >= 0 else None,
        rain=rain if rain is not None and rain >= 0 else None,
        snow=snow if snow is not None and snow >= 0 else None,
        temperature=reading(current.get("temp")),
        visibility=visibility if visibility is not None and visibility >= 0 else None,
        observed_at=observed,
        forecast_at=forecast_at,
    )


def weather_snapshot(payload, real_now: float, *, forecast_time: float | None = None) -> OutsideWeather:
    current = payload.get("current") if isinstance(payload, dict) else None
    if not isinstance(current, dict):
        return OutsideWeather("UNAVAILABLE")
    observed = reading(current.get("dt"))
    if observed is None or not -300 <= real_now - observed <= WEATHER_CACHE_SECONDS:
        return OutsideWeather("UNAVAILABLE", observed_at=observed)
    live = real_now - observed <= WEATHER_LIVE_SECONDS
    if forecast_time is None:
        return weather_readings(current, "LIVE" if live else "CACHED", observed)
    hourly = payload.get("hourly")
    if not isinstance(hourly, list):
        return OutsideWeather("UNAVAILABLE", observed_at=observed)
    for hour in hourly:
        if not isinstance(hour, dict):
            continue
        at = reading(hour.get("dt"))
        if at is not None and at <= forecast_time < at + 3600:
            return weather_readings(hour, "FORECAST" if live else "FORECAST_CACHED", observed, at)
    return OutsideWeather("UNAVAILABLE", observed_at=observed)


def outside_moment(tz, offset_minutes: float) -> datetime:
    # Add elapsed seconds before converting to local time, including across DST.
    return datetime.fromtimestamp(psclock.time() + offset_minutes * 60, tz)


def local_season(moment: datetime, latitude: float) -> str:
    quarter = ((moment.month % 12) // 3 + (2 if latitude < 0 else 0)) % 4
    return ("winter", "spring", "summer", "autumn")[quarter]


@lru_cache(maxsize=8)
def location_timezone(latitude: float, longitude: float):
    name = utilities.timezone_at(latitude, longitude)
    return ZoneInfo(name) if name is not None else UTC


def sky_covers(sky, start: float, end: float, latitude: float, longitude: float) -> bool:
    if not isinstance(sky, dict) or sky.get("status") != "READY" or sky.get("location") != [latitude, longitude]:
        return False
    first = reading(sky.get("start"))
    last = reading(sky.get("end"))
    return first is not None and last is not None and first <= start <= end <= last


def sky_snapshot(sky, timestamp: float, latitude: float, longitude: float):
    if not sky_covers(sky, timestamp, timestamp, latitude, longitude):
        return None
    position = (timestamp - sky["start"]) / SKY_SAMPLE_SECONDS
    index = min(int(position), len(sky["sun_altitude"]) - 2)
    fraction = position - index
    values = {}
    for field in SKY_FIELDS:
        first, second = sky[field][index : index + 2]
        delta = second - first
        circular = field.endswith("azimuth") or field == "moon_phase"
        if circular:
            delta = (delta + 180) % 360 - 180
        value = first + delta * fraction
        values[field] = value % 360 if circular else value
    return values


def environment_snapshot(sky, weather, moment: datetime, latitude: float, longitude: float, *, offset_minutes: int = 0) -> OutsideEnvironment:
    observed = weather_snapshot(weather, time.time(), forecast_time=moment.timestamp() if offset_minutes else None)
    season = local_season(moment, latitude)
    if not isinstance(sky, dict):
        return OutsideEnvironment(season, observed, "LOADING", offset_minutes=offset_minutes)
    positions = sky_snapshot(sky, moment.timestamp(), latitude, longitude)
    if positions is None:
        return OutsideEnvironment(season, observed, "UNAVAILABLE" if sky.get("status") == "UNAVAILABLE" else "LOADING", offset_minutes=offset_minutes)
    passed = [sunset for sunset in sky.get("sunsets", ()) if sunset <= moment.timestamp()]
    since_sunset = moment.timestamp() - passed[-1] if passed else None
    return OutsideEnvironment(season, observed, "READY", positions["sun_altitude"], positions["sun_azimuth"], positions["moon_altitude"], positions["moon_azimuth"], positions["moon_phase"], offset_minutes, since_sunset)


def load_ephemeris():
    path = os.path.join(shared_config.datafiles_dir, "de421.bsp")
    if os.path.isfile(path):
        return load_file(path)
    os.makedirs(shared_config.datafiles_dir, exist_ok=True)
    temporary = None
    try:
        logger.info("Outside: downloading the Moon mode's shared DE421 ephemeris")
        with requests.get("https://ssd.jpl.nasa.gov/ftp/eph/planets/bsp/de421.bsp", stream=True, timeout=(5, 20)) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(dir=shared_config.datafiles_dir, suffix=".bsp", delete=False) as destination:
                temporary = destination.name
                for chunk in response.iter_content(65536):
                    if shared_config.shutdown_in_progress():
                        raise InterruptedError("Outside ephemeris download interrupted by shutdown")
                    destination.write(chunk)
        ephemeris = load_file(temporary)
        os.replace(temporary, path)
        return ephemeris
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def sky_angles(ephemeris, instant, latitude: float, longitude: float):
    observer = ephemeris["earth"] + wgs84.latlon(latitude, longitude)
    here = observer.at(instant)
    sun_altitude, sun_azimuth, _ = here.observe(ephemeris["sun"]).apparent().altaz()
    moon_altitude, moon_azimuth, _ = here.observe(ephemeris["moon"]).apparent().altaz()
    return {
        "sun_altitude": sun_altitude.degrees,
        "sun_azimuth": sun_azimuth.degrees,
        "moon_altitude": moon_altitude.degrees,
        "moon_azimuth": moon_azimuth.degrees,
        "moon_phase": almanac.moon_phase(ephemeris, instant).degrees,
    }


def calculate_sky(ephemeris, timescale, moment: datetime, latitude: float, longitude: float):
    angles = sky_angles(ephemeris, timescale.from_datetime(moment), latitude, longitude)
    return {
        "status": "READY",
        "at": moment.timestamp(),
        "location": [latitude, longitude],
        **{field: float(value) for field, value in angles.items()},
    }


def calculate_sky_timeline(ephemeris, timescale, timestamp: float, latitude: float, longitude: float):
    start = math.floor(timestamp / SKY_SAMPLE_SECONDS) * SKY_SAMPLE_SECONDS - SKY_SAMPLE_SECONDS - SKY_HISTORY_SECONDS
    count = (SKY_PRELOAD_SECONDS + SKY_HISTORY_SECONDS) // SKY_SAMPLE_SECONDS + 3
    moments = [datetime.fromtimestamp(start + index * SKY_SAMPLE_SECONDS, UTC) for index in range(count)]
    angles = sky_angles(ephemeris, timescale.from_datetimes(moments), latitude, longitude)
    altitude = np.asarray(angles["sun_altitude"])
    setting = np.nonzero((altitude[:-1] >= SUNSET_ALTITUDE) & (altitude[1:] < SUNSET_ALTITUDE))[0]
    sunsets = [float(start + (index + (altitude[index] - SUNSET_ALTITUDE) / (altitude[index] - altitude[index + 1])) * SKY_SAMPLE_SECONDS) for index in setting]
    return {
        "status": "READY",
        "start": start,
        "end": start + (count - 1) * SKY_SAMPLE_SECONDS,
        "location": [latitude, longitude],
        "sunsets": sunsets,
        **{field: value.tolist() for field, value in angles.items()},
    }


def get_outside_data_worker(data_dict):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    ephemeris = None
    timescale = None
    retry_at = 0
    failures = 0
    sky = None
    try:
        while not shared_config.shutdown_in_progress():
            shared_config.shared_outside_time_update.clear()
            if time.monotonic() < retry_at:
                shared_config.shared_shutdown_event.wait(1)
                continue
            try:
                latitude = float(shared_config.CONF["SENSOR_LAT"])
                longitude = float(shared_config.CONF["SENSOR_LON"])
                if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                    raise ValueError("Outside requires valid SENSOR_LAT and SENSOR_LON")
                if ephemeris is None:
                    data_dict["outside_sky"] = {"status": "LOADING"}
                    ephemeris = load_ephemeris()
                if timescale is None:
                    timescale = Loader(shared_config.datafiles_dir).timescale(builtin=True)
                now = psclock.time()
                if not sky_covers(sky, now, now + 24 * 3600 + SKY_REFRESH_MARGIN_SECONDS, latitude, longitude):
                    sky = calculate_sky_timeline(ephemeris, timescale, now, latitude, longitude)
                    data_dict["outside_sky"] = sky
                failures = 0
            except (OSError, ValueError, KeyError, requests.RequestException, EphemerisRangeError):
                logger.exception("Outside astronomy unavailable; retaining the landscape without invented sun/moon positions")
                data_dict["outside_sky"] = {"status": "UNAVAILABLE"}
                sky = None
                failures += 1
                retry_at = time.monotonic() + min(300, 15 * 2 ** min(failures - 1, 5))
            shared_config.shared_outside_time_update.wait(1)
    finally:
        if ephemeris is not None:
            ephemeris.close()


def outside_status():
    latitude = float(shared_config.CONF["SENSOR_LAT"])
    longitude = float(shared_config.CONF["SENSOR_LON"])
    tz = location_timezone(latitude, longitude)
    offset_minutes = shared_config.shared_outside_offset_minutes.value
    moment = outside_moment(tz, offset_minutes)
    environment = environment_snapshot(shared_config.data_dict.get("outside_sky"), shared_config.data_dict.get("weather"), moment, latitude, longitude, offset_minutes=offset_minutes)
    return {
        "offset_minutes": offset_minutes,
        "now": datetime.fromtimestamp(moment.timestamp() - offset_minutes * 60, tz).isoformat(),
        "selected_time": moment.isoformat(),
        "timezone": getattr(tz, "key", "UTC"),
        "military_time": shared_config.CONF["MILITARY_TIME"].lower() == "true",
        "season": environment.season,
        "weather": environment.weather.status,
        "astronomy": environment.sky_status,
        "observed_at": environment.weather.observed_at,
        "forecast_at": environment.weather.forecast_at,
        "temperature_f": environment.weather.temperature,
        "wind_mph": environment.weather.wind,
        "condition_code": environment.weather.code,
        "condition": WEATHER_DESCRIPTIONS.get(environment.weather.code),
        "cloud_cover": environment.weather.clouds,
        "rain_mm_h": environment.weather.rain,
        "snow_mm_h": environment.weather.snow,
        "sun_altitude": environment.sun_altitude,
        "moon_altitude": environment.moon_altitude,
        "moon_phase": environment.moon_phase if environment.sky_status == "READY" else None,
    }


@planesign_mode_handler(DisplayMode.OUTSIDE)
def outside(sign):
    started = time.perf_counter()
    seed = random.SystemRandom().randrange(2**31)
    last_snapshot = -1
    last_status = None
    environment = None
    rendered_offset = float(shared_config.shared_outside_offset_minutes.value)
    target_offset = rendered_offset
    transition_from = rendered_offset
    transition_started = started
    text_styles: tuple[bool | None, bool | None, bool | None] = (None, None, None)
    while shared_config.shared_mode.value == DisplayMode.OUTSIDE.value:
        frame_time = time.perf_counter()
        elapsed = frame_time - started
        offset_minutes = shared_config.shared_outside_offset_minutes.value
        fraction = min(1, (frame_time - transition_started) / OFFSET_TRANSITION_SECONDS)
        rendered_offset = transition_from + (target_offset - transition_from) * fraction
        if offset_minutes != target_offset:
            transition_from = rendered_offset
            target_offset = offset_minutes
            transition_started = frame_time
        if int(elapsed) != last_snapshot or environment is None or environment.sky_status == "LOADING":
            latitude = float(shared_config.CONF["SENSOR_LAT"])
            longitude = float(shared_config.CONF["SENSOR_LON"])
            tz = location_timezone(latitude, longitude)
            military_time = shared_config.CONF["MILITARY_TIME"].lower() == "true"
            sky = shared_config.data_dict.get("outside_sky")
            weather = shared_config.data_dict.get("weather")
            last_snapshot = int(elapsed)
        moment = outside_moment(tz, rendered_offset)
        environment = environment_snapshot(sky, weather, moment, latitude, longitude, offset_minutes=math.ceil(rendered_offset))
        status = environment.weather.status, environment.sky_status
        if status != last_status:
            if status[0] in ("LIVE", "FORECAST") and status[1] == "READY":
                logger.info("Outside: %s weather and local astronomy ready", status[0].lower())
            else:
                logger.warning("Outside: weather %s, astronomy %s", *status)
            last_status = status
        text_styles = draw_outside_frame(sign, environment, elapsed, seed, moment=moment, military_time=military_time, previous_text_styles=text_styles)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(max(0, started + elapsed + 0.05 - time.perf_counter())):
            return
