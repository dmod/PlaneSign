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

import psclock
import requests
import shared_config
import utilities
from modes import DisplayMode, planesign_mode_handler
from outside_scene import draw_outside_frame
from skyfield import almanac
from skyfield.api import Loader, load_file, wgs84
from skyfield.errors import EphemerisRangeError

logger = logging.getLogger(__name__)
WEATHER_LIVE_SECONDS = 1800
WEATHER_CACHE_SECONDS = 7200
WEATHER_CODES = frozenset((200, 201, 202, 210, 211, 212, 221, 230, 231, 232, 300, 301, 302, 310, 311, 312, 313, 314, 321, 500, 501, 502, 503, 504, 511, 520, 521, 522, 531, 600, 601, 602, 611, 612, 613, 615, 616, 620, 621, 622, 701, 711, 721, 731, 741, 751, 761, 762, 771, 781, 800, 801, 802, 803, 804))


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


def outside_moment(tz, offset_minutes: int) -> datetime:
    # Add elapsed seconds before converting to local time, including across DST.
    return datetime.fromtimestamp(psclock.time() + offset_minutes * 60, tz)


def local_season(moment: datetime, latitude: float) -> str:
    quarter = ((moment.month % 12) // 3 + (2 if latitude < 0 else 0)) % 4
    return ("winter", "spring", "summer", "autumn")[quarter]


@lru_cache(maxsize=8)
def location_timezone(latitude: float, longitude: float):
    name = utilities.timezone_at(latitude, longitude)
    return ZoneInfo(name) if name is not None else UTC


def environment_snapshot(sky, weather, moment: datetime, latitude: float, longitude: float, *, offset_minutes: int = 0) -> OutsideEnvironment:
    observed = weather_snapshot(weather, time.time(), forecast_time=moment.timestamp() if offset_minutes else None)
    season = local_season(moment, latitude)
    if not isinstance(sky, dict):
        return OutsideEnvironment(season, observed, "LOADING", offset_minutes=offset_minutes)
    usable = sky.get("location") == [latitude, longitude] and sky.get("offset_minutes", 0) == offset_minutes and abs(moment.timestamp() - sky.get("at", 0)) <= 90 and sky.get("status") == "READY"
    if not usable:
        return OutsideEnvironment(season, observed, "UNAVAILABLE" if sky.get("status") == "UNAVAILABLE" else "LOADING", offset_minutes=offset_minutes)
    return OutsideEnvironment(season, observed, "READY", sky["sun_altitude"], sky["sun_azimuth"], sky["moon_altitude"], sky["moon_azimuth"], sky["moon_phase"], offset_minutes)


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


def calculate_sky(ephemeris, timescale, moment: datetime, latitude: float, longitude: float):
    observer = ephemeris["earth"] + wgs84.latlon(latitude, longitude)
    instant = timescale.from_datetime(moment)
    here = observer.at(instant)
    sun_altitude, sun_azimuth, _ = here.observe(ephemeris["sun"]).apparent().altaz()
    moon_altitude, moon_azimuth, _ = here.observe(ephemeris["moon"]).apparent().altaz()
    return {
        "status": "READY",
        "at": moment.timestamp(),
        "location": [latitude, longitude],
        "sun_altitude": float(sun_altitude.degrees),
        "sun_azimuth": float(sun_azimuth.degrees),
        "moon_altitude": float(moon_altitude.degrees),
        "moon_azimuth": float(moon_azimuth.degrees),
        "moon_phase": float(almanac.moon_phase(ephemeris, instant).degrees),
    }


def get_outside_data_worker(data_dict):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    ephemeris = None
    timescale = None
    retry_at = 0
    failures = 0
    try:
        while not shared_config.shutdown_in_progress():
            shared_config.shared_outside_time_update.clear()
            if shared_config.shared_mode.value != DisplayMode.OUTSIDE.value or time.monotonic() < retry_at:
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
                offset_minutes = shared_config.shared_outside_offset_minutes.value
                moment = outside_moment(UTC, offset_minutes)
                sky = calculate_sky(ephemeris, timescale, moment, latitude, longitude)
                sky["offset_minutes"] = offset_minutes
                data_dict["outside_sky"] = sky
                failures = 0
            except (OSError, ValueError, KeyError, requests.RequestException, EphemerisRangeError):
                logger.exception("Outside astronomy unavailable; retaining the landscape without invented sun/moon positions")
                data_dict["outside_sky"] = {"status": "UNAVAILABLE"}
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
    last_offset = None
    while shared_config.shared_mode.value == DisplayMode.OUTSIDE.value:
        elapsed = time.perf_counter() - started
        offset_minutes = shared_config.shared_outside_offset_minutes.value
        if int(elapsed) != last_snapshot or offset_minutes != last_offset or environment is None or environment.sky_status == "LOADING":
            latitude = float(shared_config.CONF["SENSOR_LAT"])
            longitude = float(shared_config.CONF["SENSOR_LON"])
            moment = outside_moment(location_timezone(latitude, longitude), offset_minutes)
            military_time = shared_config.CONF["MILITARY_TIME"].lower() == "true"
            environment = environment_snapshot(shared_config.data_dict.get("outside_sky"), shared_config.data_dict.get("weather"), moment, latitude, longitude, offset_minutes=offset_minutes)
            status = environment.weather.status, environment.sky_status
            if status != last_status:
                if status[0] in ("LIVE", "FORECAST") and status[1] == "READY":
                    logger.info("Outside: %s weather and local astronomy ready", status[0].lower())
                else:
                    logger.warning("Outside: weather %s, astronomy %s", *status)
                last_status = status
            last_snapshot = int(elapsed)
            last_offset = offset_minutes
        draw_outside_frame(sign, environment, elapsed, seed, moment=moment, military_time=military_time)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(max(0, started + elapsed + 0.05 - time.perf_counter())):
            return
