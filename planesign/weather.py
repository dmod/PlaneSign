import logging
import time

import network
import psclock
import shared_config
import utilities
from modes import DisplayMode, planesign_mode_handler
from PIL import Image
from planes import PLANE_DATA_MODES
from rgbmatrix import graphics

WEATHER_POLL_SECONDS = 900
# Readings count as current for one poll interval plus a margin for a refresh in flight; after that the
# clock shows "--" and the forecast reloads until the next fetch lands.
WEATHER_STALE_SECONDS = WEATHER_POLL_SECONDS + 60

# The modes that show the shared OpenWeather data. The plane modes show the clock and its temperature
# whenever they have no plane. Santa, NFL and MLB fetch their own weather.
WEATHER_DATA_MODES = frozenset({DisplayMode.WEATHER, DisplayMode.OUTSIDE, DisplayMode.TIME_ONLY}) | PLANE_DATA_MODES
WEATHER_DATA_MODE_VALUES = frozenset(mode.value for mode in WEATHER_DATA_MODES)


@planesign_mode_handler(DisplayMode.WEATHER)
def show_weather(sign):
    polltime = None
    forecast = None

    while shared_config.shared_mode.value == DisplayMode.WEATHER.value:
        status = shared_config.data_dict.get("weather_status")
        if status == "offline":
            polltime = None
            if utilities.show_offline(sign, "WEATHER", 1):
                return
            continue

        if status == "no_key":
            polltime = None
            forecast = None
            if utilities.show_status(sign, "WEATHER", "NO API KEY", 1):
                return
            continue

        day_0_xoffset = 2
        day_1_xoffset = 45
        day_2_xoffset = 88

        # Default to the actual "today"
        start_index_day = 0

        # After 6PM today? Get the next days forecast
        if utilities.convert_unix_to_local_time(psclock.time()).hour >= 18:
            start_index_day = 1

        if polltime is None or time.perf_counter() - polltime > 30:
            forecast = load_forecast(utilities.fresh_weather(), start_index_day)
            if forecast:
                polltime = time.perf_counter()
            else:
                message = "UNAVAILABLE" if status == "error" else "LOADING"
                if utilities.show_status(sign, "WEATHER", message, 1):
                    return
                continue

        day0, day1, day2, sunrise_time, sunset_time = forecast

        sign.canvas.Clear()

        draw_daily_forcast(sign, day0, day_0_xoffset)
        draw_daily_forcast(sign, day1, day_1_xoffset)
        draw_daily_forcast(sign, day2, day_2_xoffset)

        graphics.DrawText(sign.canvas, sign.font46, 1, 5, graphics.Color(20, 20, 210), shared_config.CONF["WEATHER_CITY_NAME"])

        # Calculate and draw the horizontal boarder around the WEATHER_CITY_NAME
        num_horizontal_pixels = (len(shared_config.CONF["WEATHER_CITY_NAME"]) * 4) + 1
        for x in range(num_horizontal_pixels):
            sign.canvas.SetPixel(x, 6, 140, 140, 140)

        # Draw the vertical boarder around the WEATHER_CITY_NAME
        for y in range(7):
            sign.canvas.SetPixel(num_horizontal_pixels, y, 140, 140, 140)

        sunrise_sunset_start_x = min(num_horizontal_pixels + 20, 70)

        time_format = "%-I:%M"
        if shared_config.CONF["MILITARY_TIME"].lower() == "true":
            time_format = "%H:%M"

        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x, 6, graphics.Color(210, 190, 0), sunrise_time.strftime(time_format))
        graphics.DrawText(sign.canvas, sign.font57, sunrise_sunset_start_x + 30, 6, graphics.Color(255, 158, 31), sunset_time.strftime(time_format))

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

        breakout = sign.wait_loop(0.1)
        if breakout:
            return


def load_forecast(weather, start_index_day):
    """Return (day0, day1, day2, sunrise, sunset) from the OpenWeather payload, or None if it is missing or incomplete."""
    if not weather:
        return None

    current = weather.get("current")
    daily = weather.get("daily")
    if not current or not isinstance(daily, list) or len(daily) < start_index_day + 3:
        return None

    return (
        daily[start_index_day],
        daily[start_index_day + 1],
        daily[start_index_day + 2],
        utilities.convert_unix_to_local_time(current["sunrise"]),
        utilities.convert_unix_to_local_time(current["sunset"]),
    )


def weather_data_wanted():
    return shared_config.shared_mode.value in WEATHER_DATA_MODE_VALUES


def refresh_weather(data_dict):
    """Fetch the OpenWeather forecast once and return the seconds until the next attempt."""
    try:
        weather_data = network.get("OpenWeather", f"https://api.openweathermap.org/data/3.0/onecall?lat={shared_config.CONF['SENSOR_LAT']}&lon={shared_config.CONF['SENSOR_LON']}&appid={shared_config.CONF['OPENWEATHER_API_KEY']}&units=imperial", timeout=20)
        weather_json = weather_data.json()

        current = weather_json.get("current")
        daily = weather_json.get("daily")
        if current and isinstance(daily, list) and len(daily) >= 3:
            data_dict["weather"] = weather_json
            data_dict["weather_fresh_until"] = time.time() + WEATHER_STALE_SECONDS
            data_dict["weather_status"] = "ready"
            logging.info(f"At: {utilities.convert_unix_to_local_time(current['dt'])} Temp: {current['temp']}")
            return WEATHER_POLL_SECONDS
        cod = weather_json.get("cod", weather_data.status_code)
        message = weather_json.get("message", "missing expected weather fields")
        logging.error(f"OpenWeather response invalid (cod={cod}): {message}")
        data_dict["weather_status"] = "error"
        return 30
    except Exception as e:
        if network.is_offline_error(e):
            network.log_unreachable("OpenWeather", e)
            data_dict["weather_status"] = "offline"
            return 60
        logging.exception("Error getting weather data...", exc_info=e)
        data_dict["weather_status"] = "error"
        return 15


def get_weather_data_worker(data_dict):
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    toggle = network.OfflineToggle()
    next_attempt = 0.0
    logged_missing_key = False
    deferred = False

    while not shared_config.shutdown_in_progress():
        if toggle.changed():
            next_attempt = 0.0
        # A due refresh waits for a mode that shows weather; until then consumers treat the payload as stale.
        if time.monotonic() >= next_attempt:
            if not weather_data_wanted():
                if not deferred:
                    logging.info(f"Weather refresh due; deferring it while {DisplayMode(shared_config.shared_mode.value).name} is showing")
                    deferred = True
            else:
                deferred = False
                # Re-checked on every attempt so a key saved from the web UI is picked up without a restart
                if not shared_config.CONF.get("OPENWEATHER_API_KEY"):
                    if not logged_missing_key:
                        logging.error("OpenWeather API key is not configured. Weather data will not be available.")
                        logged_missing_key = True
                    data_dict.pop("weather", None)
                    data_dict.pop("weather_fresh_until", None)
                    data_dict["weather_status"] = "no_key"
                    next_attempt = time.monotonic() + 30
                else:
                    logged_missing_key = False
                    next_attempt = time.monotonic() + refresh_weather(data_dict)
        shared_config.shared_shutdown_event.wait(1)


def draw_daily_forcast(sign, day, xloc):
    code = day["weather"][0]["id"]
    status = day["weather"][0]["main"]
    local_time = utilities.convert_unix_to_local_time(day["dt"])

    icon, status = utilities.weather_icon_decode(code, status)

    image = Image.open(f"{shared_config.icons_dir}/weather/{icon}.png")
    iw, _ih = image.size
    sign.canvas.SetImage(image.convert("RGB"), xloc + 25 - round(iw / 2), 9)

    graphics.DrawText(sign.canvas, sign.font57, xloc, 14, graphics.Color(47, 158, 19), local_time.strftime("%a"))
    graphics.DrawText(sign.canvas, sign.font57, xloc, 22, graphics.Color(210, 20, 20), str(round(day["temp"]["max"])))
    graphics.DrawText(sign.canvas, sign.font57, xloc, 30, graphics.Color(20, 20, 210), str(round(day["temp"]["min"])))
    graphics.DrawText(sign.canvas, sign.font46, xloc + 26 - len(status) * 2, 30, graphics.Color(52, 235, 183), status[:7])
