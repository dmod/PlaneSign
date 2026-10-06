import json
import logging.handlers
import os
import random
import re
import time
from datetime import datetime, timedelta
from enum import Enum
from functools import cmp_to_key
from math import ceil, isfinite
from urllib.parse import urlparse

import network
import requests
import shared_config
from bs4 import BeautifulSoup
from modes import DisplayMode, planesign_mode_handler
from PIL import Image
from rgbmatrix import graphics
from utilities import CM_2_IN, acquire_lock, convert_c_to_f, draw_offline, getFavicon, release_lock, weather_icon_decode

resortinfo_filename = f"{shared_config.datafiles_dir}/resortdata.json"
userresorts_filename = f"{shared_config.datafiles_dir}/resortlist.txt"
SNOW_UPDATE_SECONDS = 20 * 60
SNOW_RETRY_SECONDS = 60
SNOW_MAX_RETRY_SECONDS = 5 * 60
SNOW_MAX_FEED_BYTES = 5 * 1024 * 1024


class SnowFeedError(ValueError):
    """An OnTheSnow response cannot supply a usable report."""


def _fetch_snow_feed(session, url, **kwargs):
    service = "OpenWeather" if "openweathermap.org" in url else "OnTheSnow"
    with network.get(service, url, session=session, timeout=(5, 10), stream=True, **kwargs) as response:
        response.raise_for_status()
        content = bytearray()
        deadline = time.monotonic() + 20
        for chunk in response.iter_content(65536):
            content.extend(chunk)
            if len(content) > SNOW_MAX_FEED_BYTES:
                raise SnowFeedError("feed exceeds 5 MiB")
            if time.monotonic() > deadline:
                raise SnowFeedError("feed download exceeded 20 seconds")
        return bytes(content)


def _snow_feed_error(error):
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"HTTP {error.response.status_code}"
    if isinstance(error, requests.RequestException):
        return type(error).__name__
    if isinstance(error, json.JSONDecodeError):
        return "invalid JSON"
    return str(error)[:160]


def _parse_snow_page(html, required_key="fullResort"):
    """Return feed props from legacy Next data or a concatenated Flight stream."""
    if len(html) > SNOW_MAX_FEED_BYTES:
        raise SnowFeedError("page exceeds 5 MiB")
    soup = BeautifulSoup(html, "html.parser")
    legacy = soup.find("script", {"id": "__NEXT_DATA__"})
    if legacy is not None:
        try:
            data = json.loads(legacy.get_text())
        except (json.JSONDecodeError, RecursionError) as error:
            raise SnowFeedError("invalid legacy Next data") from error
        props = data.get("props") if isinstance(data, dict) else None
        page = props.get("pageProps") if isinstance(props, dict) else None
        if not isinstance(page, dict) or required_key not in page:
            raise SnowFeedError(f"legacy page missing {required_key}")
        return page

    chunks = []
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        text = script.get_text()
        for match in re.finditer(r"self\.__next_f\.push\(\s*", text):
            try:
                push, _ = decoder.raw_decode(text, match.end())
            except (json.JSONDecodeError, RecursionError) as error:
                raise SnowFeedError("invalid Flight script") from error
            if not isinstance(push, list) or not push:
                raise SnowFeedError("invalid Flight chunk")
            if push[0] == 1:
                if len(push) != 2 or not isinstance(push[1], str):
                    raise SnowFeedError("invalid Flight text chunk")
                chunks.append(push[1])
    if not chunks:
        raise SnowFeedError("page has no Next data")

    flight = "".join(chunks).encode("utf-8")
    rows = {}
    offset = 0
    row_header = re.compile(rb"([0-9a-fA-F]+):")
    while offset < len(flight):
        match = row_header.match(flight, offset)
        if match is None:
            raise SnowFeedError("invalid Flight row framing")
        row_id = match[1].decode("ascii")
        offset = match.end()
        # Flight text records use a UTF-8 byte count, not a newline terminator.
        if flight[offset : offset + 1] == b"T":
            comma = flight.find(b",", offset, offset + 18)
            if comma < 0 or not re.fullmatch(rb"T[0-9a-fA-F]+", flight[offset:comma]):
                raise SnowFeedError("invalid Flight text length")
            end = comma + 1 + int(flight[offset + 1 : comma], 16)
            if end > len(flight):
                raise SnowFeedError("truncated Flight text")
            try:
                rows[row_id] = flight[comma + 1 : end].decode("utf-8")
            except UnicodeDecodeError as error:
                raise SnowFeedError("invalid Flight text encoding") from error
            offset = end
            continue
        end = flight.find(b"\n", offset)
        if end < 0:
            raise SnowFeedError("truncated Flight row")
        row = flight[offset:end]
        offset = end + 1
        if row.startswith((b"{", b"[", b'"', b"null", b"true", b"false")):
            try:
                rows[row_id] = json.loads(row)
            except (json.JSONDecodeError, RecursionError) as error:
                raise SnowFeedError("invalid Flight JSON row") from error

    remaining = 100000

    def resolve(value, active=(), depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise SnowFeedError("Flight references exceed size limit")
        if depth > 100:
            raise SnowFeedError("Flight references exceed depth limit")
        if isinstance(value, str) and re.fullmatch(r"\$[0-9a-fA-F]+", value):
            ref = value[1:]
            if ref not in rows or ref in active:
                raise SnowFeedError("missing or cyclic Flight reference")
            return resolve(rows[ref], (*active, ref), depth + 1)
        if isinstance(value, dict):
            return {key: resolve(item, active, depth + 1) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item, active, depth + 1) for item in value]
        return None if value == "$undefined" else value

    stack = list(reversed(list(rows.values())))
    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            if required_key in value:
                return {key: resolve(value[key]) for key in ("fullResort", "nearbyResorts", "weatherInfo", "weatherInfoDaily", "weatherInfoHourly") if key in value}
            stack.extend(reversed(list(value.values())))
        elif isinstance(value, list):
            stack.extend(reversed(value))
    raise SnowFeedError(f"Flight page missing {required_key}")


def _snow_object(value, field):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SnowFeedError(f"invalid {field} object")
    return value


def _snow_number(value, field):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SnowFeedError(f"invalid {field} reading")
    try:
        finite = isfinite(value)
    except OverflowError as error:
        raise SnowFeedError(f"invalid {field} reading") from error
    if not finite:
        raise SnowFeedError(f"invalid {field} reading")
    return value


def _parse_snow_report(page, res_id):
    full = _snow_object(page.get("fullResort"), "fullResort")
    if str(full.get("uuid")) != str(res_id) or not isinstance(full.get("snow"), dict):
        raise SnowFeedError("missing or mismatched resort report")
    nearby = page.get("nearbyResorts")
    if nearby is not None and not isinstance(nearby, list):
        raise SnowFeedError("invalid nearbyResorts list")
    for item in nearby or []:
        if isinstance(item, dict) and str(item.get("uuid")) == str(res_id):
            full = {**full, **item}
            break
    snow = _snow_object(full.get("snow"), "snow")
    runs = _snow_object(full.get("runs"), "runs")
    flag = _snow_object(full.get("status"), "status").get("openFlag")
    if isinstance(flag, bool):
        is_open = flag
    elif flag in (None, 0, 1, 2, 3, 4, 5, 6):
        # Weekends-only (4) and no-report (5) do not establish current operation.
        is_open = None if flag in (None, 0, 4, 5) else flag == 1
    else:
        raise SnowFeedError("invalid resort openFlag")
    forecast = full.get("weather")
    if forecast is None:
        future = full.get("forecast")
        if future is not None and not isinstance(future, list):
            raise SnowFeedError("invalid forecast list")
        forecast = [{"snowfall": None} for _ in range(7)]
        for item in future or []:
            item = _snow_object(item, "forecast day")
            forecast.append({"snowfall": item.get("snow")})
    if not isinstance(forecast, list):
        raise SnowFeedError("invalid resort weather list")
    normalized = []
    for item in forecast:
        item = _snow_object(item, "forecast day")
        normalized.append({**item, "snowfall": _snow_number(item.get("snowfall"), "forecast snowfall")})
    readings = {}
    for source, target in (("base", "snowBase"), ("middle", "snowMid"), ("summit", "snowPeak"), ("last24", "new")):
        number = _snow_number(snow.get(source), f"snow.{source}")
        readings[target] = None if number is None else number * CM_2_IN
    return {**readings, "isOpen": is_open, "runsOpen": _snow_number(runs.get("open"), "runs.open"), "runsTotal": _snow_number(runs.get("total"), "runs.total"), "forecast": normalized}, full


def _snow_weather_icon(icon):
    if icon is None:
        return None
    try:
        with Image.open(f"{shared_config.icons_dir}/weather/{icon}.png") as image:
            return image.convert("RGB")
    except OSError as error:
        logging.warning("Snow weather icon unavailable: %s", type(error).__name__)
        return None


def _parse_snow_weather(page):
    info = _snow_object(page.get("weatherInfoHourly"), "weatherInfoHourly")
    hourly = info.get("weatherItems")
    if not isinstance(hourly, list) or not hourly:
        raise SnowFeedError("missing hourly weather")
    weather = dict.fromkeys(("currTemp", "currWeatherIcon", "dayLow", "dayHigh", "nightLow", "nightHigh"))
    for index, item in enumerate(hourly):
        item = _snow_object(item, "hourly weather")
        stamp = item.get("datetime")
        if not isinstance(stamp, str):
            raise SnowFeedError("missing hourly weather datetime")
        try:
            hour = datetime.fromisoformat(stamp).hour
        except ValueError as error:
            raise SnowFeedError("invalid hourly weather datetime") from error
        mid = _snow_object(item.get("mid"), "mid weather")
        base = _snow_object(item.get("base"), "base weather")
        temp = _snow_object(mid.get("temp") if mid.get("temp") is not None else base.get("temp"), "weather temperature")
        low = _snow_number(temp.get("min"), "weather minimum")
        high = _snow_number(temp.get("max"), "weather maximum")
        is_night = hour <= 6 or hour >= 18
        if index == 0:
            if low is not None and high is not None:
                weather["currTemp"] = convert_c_to_f((low + high) / 2)
            symbol = mid.get("type") if mid.get("type") is not None else base.get("type")
            weather["currWeatherIcon"] = _snow_weather_icon(mapIcon(symbol, is_night))
        period = "night" if is_night else "day"
        if low is not None:
            key = period + "Low"
            value = convert_c_to_f(low)
            weather[key] = value if weather[key] is None else min(weather[key], value)
        if high is not None:
            key = period + "High"
            value = convert_c_to_f(high)
            weather[key] = value if weather[key] is None else max(weather[key], value)
    return weather


def _parse_snow_openweather(data):
    data = _snow_object(data, "OpenWeather")
    current = _snow_object(data.get("current"), "OpenWeather current")
    if not current:
        raise SnowFeedError("missing OpenWeather current weather")
    weather = dict.fromkeys(("currTemp", "currWeatherIcon", "dayLow", "dayHigh", "nightLow", "nightHigh"))
    weather["currTemp"] = _snow_number(current.get("temp"), "OpenWeather temperature")
    conditions = current.get("weather")
    if isinstance(conditions, list) and conditions and isinstance(conditions[0], dict):
        dt, sunrise, sunset = (_snow_number(current.get(key), f"OpenWeather {key}") for key in ("dt", "sunrise", "sunset"))
        if all(value is not None for value in (dt, sunrise, sunset)):
            is_night = dt < sunrise or dt > sunset
            condition = conditions[0]
            if isinstance(condition.get("id"), int) and isinstance(condition.get("main"), str):
                icon, _ = weather_icon_decode(condition["id"], condition["main"], is_night)
                weather["currWeatherIcon"] = _snow_weather_icon(icon)
    daily = data.get("daily")
    if daily is not None and not isinstance(daily, list):
        raise SnowFeedError("invalid OpenWeather daily list")
    for day in daily or []:
        temp = _snow_object(_snow_object(day, "OpenWeather day").get("temp"), "OpenWeather daily temperature")
        for period, fields in (("day", ("day", "morn")), ("night", ("night", "eve"))):
            for field in fields:
                value = _snow_number(temp.get(field), f"OpenWeather {field}")
                if value is not None:
                    low, high = period + "Low", period + "High"
                    weather[low] = value if weather[low] is None else min(weather[low], value)
                    weather[high] = value if weather[high] is None else max(weather[high], value)
    return weather


def _snow_forecast_inches(resort):
    forecast = resort.get("forecast") or []
    return [None if index >= len(forecast) or forecast[index].get("snowfall") is None else forecast[index]["snowfall"] * CM_2_IN for index in range(7, 15)]


def _snow_forecast_total(values):
    return None if any(value is None for value in values) else sum(values)


class SnowMode(Enum):
    STATIC = 0
    ROTATE = 1
    OVERVIEW = 2


def load_user_list():
    # Load the user's saved resorts
    resort_list = []
    if os.path.isfile(userresorts_filename):
        acquire_lock(userresorts_filename)
        try:
            with open(userresorts_filename, "r") as file:
                resort_list = [line.rstrip() for line in file]
        except Exception as e:
            logging.error(f"Error reading {userresorts_filename}: {e}")
        finally:
            release_lock(userresorts_filename)

    shared_config.data_dict["user_resorts"] = resort_list
    return


def save_current_resort():
    if shared_config.shared_snow_mode.value != SnowMode.STATIC.value:
        return

    # Save the currently displayed resort
    uuid = shared_config.data_dict["displayed_resort"]
    if uuid == "" or uuid is None:
        return

    acquire_lock(userresorts_filename)
    try:
        with open(userresorts_filename, "a+") as file:
            resort_list = [line.rstrip() for line in file]
            if uuid not in resort_list:
                file.write(uuid + "\n")
                logging.debug(f"Saving resort uuid: {uuid}")
    except Exception as e:
        logging.error(f"Error saving uuid {uuid} to {userresorts_filename}: {e}")
    finally:
        release_lock(userresorts_filename)
    return


def delete_user_resort(uuid):
    acquire_lock(userresorts_filename)
    try:
        with open(userresorts_filename, "r+") as file:
            resort_list = [line.rstrip() for line in file]
            if uuid in resort_list:
                logging.debug(f"Deleting resort uuid: {uuid}")
                resort_list.remove(uuid)
                file.seek(0)
                for res in resort_list:
                    file.write(res + "\n")
                file.truncate()
    except Exception as e:
        logging.error(f"Error deleting uuid {uuid} from {userresorts_filename}: {e}")
    finally:
        release_lock(userresorts_filename)
    return


def populate_resort_lists():

    if "resort_info" in shared_config.data_dict and "resorts" in shared_config.data_dict["resort_info"] and len(shared_config.data_dict["resort_info"]["resorts"]) > 0 and datetime.now() < datetime.fromtimestamp(shared_config.data_dict["resort_info"]["last_update"]) + timedelta(days=30):
        # No need to update
        return

    # First check for locally saved data:
    if os.path.isfile(resortinfo_filename):
        success = False
        try:
            with open(resortinfo_filename, "r") as file:
                info = json.load(file)
                if "last_update" in info and datetime.now() <= datetime.fromtimestamp(info["last_update"]) + timedelta(days=30):
                    # Data is still valid
                    if "resorts" in info and len(info["resorts"]) > 0:
                        shared_config.data_dict["resort_info"] = info
                        success = True
                    else:
                        logging.error(f"Error in {resortinfo_filename} saved data.")
                else:
                    logging.debug(f"Data in {resortinfo_filename} no longer valid.")
        except Exception as e:
            logging.error(f"Error reading {resortinfo_filename}: {e}")

        if success:
            return

    # Need to get data from web. Start from scratch
    resort_info = {}

    logging.debug("Getting available ski resort list jsons from internet.")

    headers = {
        "Host": "www.onthesnow.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Sec-GPC": "1",
        "Connection": "keep-alive",
        "Referer": "https://www.onthesnow.com/",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }

    session = requests.Session()
    session.headers.update(headers)

    allresorts_url = "https://www.onthesnow.com/index/resorts-en-US.json"
    allresorts_response = network.get("OnTheSnow", allresorts_url, session=session, timeout=10)
    if allresorts_response.status_code == requests.codes.ok:
        resort_info["resorts"] = json.loads(allresorts_response.text)
    else:
        resort_info["resorts"] = None
        logging.error(f"Error getting resort list from url: {allresorts_url}")

    altnames_url = "https://www.onthesnow.com/index/resorts-alt-en-US.json"
    altnames_response = network.get("OnTheSnow", altnames_url, session=session, timeout=10)
    if altnames_response.status_code == requests.codes.ok:
        resort_info["alt_names"] = json.loads(altnames_response.text)
    else:
        resort_info["alt_names"] = None
        logging.error(f"Error getting alternate names list from url: {altnames_url}")

    misspellings_url = "https://www.onthesnow.com/index/resorts-misspellings-en-US.json"
    misspellings_response = network.get("OnTheSnow", misspellings_url, session=session, timeout=10)
    if misspellings_response.status_code == requests.codes.ok:
        resort_info["misspellings"] = json.loads(misspellings_response.text)
    else:
        resort_info["misspellings"] = None
        logging.error(f"Error getting misspellings list from url: {misspellings_url}")

    if resort_info["resorts"] is not None and len(resort_info["resorts"]) > 0:
        # Data is good enough

        resort_info["last_update"] = datetime.now().timestamp()
        shared_config.data_dict["resort_info"] = resort_info
        try:
            with open(resortinfo_filename, "w", encoding="utf-8") as f:
                json.dump(resort_info, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logging.error(f"Error saving data to file {resortinfo_filename}: {e}")

    else:
        shared_config.data_dict["resort_info"] = {}
        logging.error("Problem getting ski resort list jsons from the internet.")


def draw_loading(sign):

    gif = Image.open(f"{shared_config.icons_dir}/snow/snow.gif")

    nf = gif.n_frames
    frame = 0
    attempted = False
    sign.canvas.Clear()
    # Potentially also pre-load user resort list data in a separate thread and check for that here also
    while not ("resort_info" in shared_config.data_dict and "resorts" in shared_config.data_dict["resort_info"] and len(shared_config.data_dict["resort_info"]["resorts"]) > 0 and datetime.now() < datetime.fromtimestamp(shared_config.data_dict["resort_info"]["last_update"]) + timedelta(days=30)):
        gif.seek(frame)

        image = Image.new("RGB", gif.size, (255, 255, 255))
        image.paste(gif, (0, 0))

        sign.canvas.SetImage(image.resize((128, 64), Image.BICUBIC).convert("RGB"), 1, -15)
        for i in range(-1, 2):
            for j in range(-1, 2):
                graphics.DrawText(sign.canvas, sign.fontbig, 7 + i, 12 + j, graphics.Color(0, 0, 0), "Loading...")
        graphics.DrawText(sign.canvas, sign.fontbig, 7, 12, graphics.Color(255, 255, 255), "Loading...")

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        frame = (frame + 1) % nf

        if not attempted:
            attempted = True
            # Unreachable OnTheSnow shows OFFLINE instead of loading forever; other failures still wait for the web UI.
            try:
                populate_resort_lists()
            except Exception as error:
                if network.is_offline_error(error):
                    raise
                logging.warning("Ski resort list unavailable: %s", error)

        breakout = sign.wait_loop(1.0)

        if breakout:
            return breakout

    return False


def mapIcon(i, isNight):
    if (i == "MOSTLY_SUNNY") or (i == "PARTLY_CLOUDY") or (i == "SLIGHTLY_CLOUDY") or (i == "FAIR"):
        if isNight:
            return "cloudpart_night"
        else:
            return "cloudpart"
    elif i == "CLOUDY":
        return "cloud"
    elif i == "OVERCAS":
        return "cloudheavy"
    elif i == "LIGHT_RAI":
        if isNight:
            return "rainlight_night"
        else:
            return "rainlight"
    elif i == "RAIN":
        return "rain"
    elif i == "RAIN_SHOWERS":
        return "rainheavy"
    elif (i == "SNOW") or (i == "SNOW_SHOWERS") or (i == "SLEET") or (i == "SLEET_SHOWERS"):
        return "snow"
    elif i == "FOG":
        return "haze"
    elif (i == "SUN") or (i == "SUNNY") or (i == "LUNE"):
        if isNight:
            return "clear_night"
        else:
            return "clear"
    elif i == "THUNDERSTORM":
        return "thunder"
    else:
        return None


def compute_display_name(resdata, desired_length):

    nameopts = set()

    nameopts.add(resdata["title"])

    # Check short name from valid resorts info
    info = next((res for res in shared_config.data_dict.get("resort_info", {}).get("resorts") or [] if res["uuid"] == resdata["uuid"]), None)

    if info is not None and "title_short" in info and info["title_short"]:
        nameopts.add(info["title_short"])

    if info is not None and "title_original" in info and info["title_original"]:
        nameopts.add(info["title_original"])

    # Check various subsitution combos
    optlist = list(nameopts)
    nopts = len(optlist)
    lastnopts = None

    def fixWhitespace(string):
        return string.replace("  ", " ").strip()

    while lastnopts is None or nopts != lastnopts:
        for name in optlist:
            nameopts.add(fixWhitespace(name.replace("Mountain", "Mtn.")))
            nameopts.add(fixWhitespace(name.replace("Mountain", "Mt.")))
            nameopts.add(fixWhitespace(name.replace("Mountain", "")))
            nameopts.add(fixWhitespace(name.replace("Resort", "Res.")))
            nameopts.add(fixWhitespace(name.replace("Resort", "")))
            nameopts.add(fixWhitespace(name.replace("Ski & Snowboard Area", "")))

        lastnopts = nopts
        optlist = list(nameopts)
        nopts = len(optlist)

    def compare(item1, item2):
        l1 = len(item1)
        l2 = len(item2)
        d1 = l1 - desired_length
        d2 = l2 - desired_length
        if d1 <= 0 and d2 > 0:
            # Prefer fitting over too long
            return -1
        elif d1 > 0 and d2 <= 0:
            # Prefer fitting over too long
            return 1
        elif d1 > 0 and d2 > 0:
            # Both too long, prefer less abbreviations
            c1 = item1[:desired_length].count(".")
            c2 = item2[:desired_length].count(".")
            return c1 - c2
        else:
            # Both are shorter than desired, prefer longer
            return l2 - l1

    optlist = list(nameopts)
    names_sorted = sorted(optlist, key=cmp_to_key(compare))

    return names_sorted[0]


def snowcolor(inches):

    if inches == "-" or inches == "--" or inches == "?":
        return graphics.Color(50, 50, 50)

    inches = float(inches)

    if inches < 1.0:
        color = graphics.Color(150, 150, 150)
    elif inches >= 6.0:
        color = graphics.Color(229, 119, 0)
    else:
        color = graphics.Color(66, 151, 213)

    return color


class SnowReport:
    def __init__(self, sign):
        self.sign = sign
        self.resorts = []
        self.gif = Image.open(f"{shared_config.icons_dir}/snow/snow.gif")
        self.nf = self.gif.n_frames
        self.frame = 0

    def draw_snow_frame(self):
        self.gif.seek(self.frame)
        self.frame = (self.frame + 1) % self.nf

        image = Image.new("RGB", self.gif.size, (255, 255, 255))
        image.paste(self.gif, (0, 0))
        self.sign.canvas.SetImage(image.resize((128, 64), Image.BICUBIC).convert("RGB"), 1, -15)

    def drawresort(self, res_id):

        resort = self.update(res_id)

        if resort is not None and resort.get("status") == "offline":
            draw_offline(self.sign, "SNOW")
            return

        if resort is None or resort.get("status") == "unavailable":
            name = resort["displayName"][:20] if resort else "Snow report"
            graphics.DrawText(self.sign.canvas, self.sign.font57, 64 - len(name) * 5 // 2, 10, graphics.Color(100, 100, 100), name)
            graphics.DrawText(self.sign.canvas, self.sign.font57, 36, 23, graphics.Color(180, 80, 30), "UNAVAILABLE")
            return

        if resort is not None:
            if resort.get("isOpen") is not None:
                if resort["isOpen"]:
                    color = graphics.Color(10, 150, 10)
                else:
                    color = graphics.Color(100, 10, 10)
            else:
                color = graphics.Color(75, 75, 75)

            if "displayName" in resort:
                graphics.DrawText(self.sign.canvas, self.sign.fontbig, 46 - round(len(resort["displayName"][:15]) * 3), 10, color, resort["displayName"][:15])

            if resort.get("status") == "cached":
                graphics.DrawText(self.sign.canvas, self.sign.font46, 0, 25, graphics.Color(180, 100, 30), "CACHED")
            elif "logo" in resort and resort["logo"] is not None:
                sizex, sizey = resort["logo"].size
                x = 12 - round(sizex / 2)
                y = 22 - round(sizey / 2)
                self.sign.canvas.SetImage(resort["logo"], x, y)

            graphics.DrawText(self.sign.canvas, self.sign.font57, 24, 20, graphics.Color(100, 10, 10), "New:")

            snownew = None
            if "new" in resort:
                snownew = resort["new"]

            if snownew is None:
                snownew = "?"
            else:
                snownew = str(round(snownew))
            graphics.DrawText(self.sign.canvas, self.sign.font57, 45, 20, snowcolor(snownew), snownew + '"')

            weather = None
            if "weather" in resort:
                weather = resort["weather"]

            currtemp = "?°F"
            if weather and "currTemp" in weather and weather["currTemp"] is not None:
                currtemp = f"{round(weather['currTemp'])}°F"

            graphics.DrawText(self.sign.canvas, self.sign.font57, 40 - round(len(currtemp) * 5 / 2), 30, graphics.Color(60, 60, 200), currtemp)

            if weather and "currWeatherIcon" in weather and weather["currWeatherIcon"]:
                image = weather["currWeatherIcon"]

                width, height = image.size
                if width > height:
                    image = image.resize((10, int(10 * height / width)), Image.BICUBIC)
                elif height > width:
                    image = image.resize((int(10 * width / height), 10), Image.BICUBIC)
                else:
                    image = image.resize((10, 10), Image.BICUBIC)

                sizex, sizey = image.size
                x = 40 + round(len(currtemp) * 5 / 2) + 1
                y = 26 - round(sizey / 2)
                self.sign.canvas.SetImage(image, x, y)

            snowfall_days = _snow_forecast_inches(resort)
            snow4d = _snow_forecast_total(snowfall_days[:4])
            snow8d = _snow_forecast_total(snowfall_days[4:])

            graphx = 66
            graphy = 30
            graphw = 6
            num_bars = 8
            offset = 0

            graphend = graphx + num_bars * (graphw + 1)
            graphics.DrawLine(self.sign.canvas, graphx - 1, graphy + 1, graphend + 1, graphy + 1, graphics.Color(13, 13, 25))
            for i in range(num_bars):
                # Daily forecast
                snowfall = snowfall_days[i]

                if i == 4:
                    offset = 2

                if snowfall and snowfall > 0.0:
                    barheight = ceil(snowfall / 2)
                    for j in range(barheight):
                        if j >= 10:
                            break
                        startx = offset + graphx + i * (graphw + 1)
                        graphics.DrawLine(self.sign.canvas, startx, graphy - j, startx + graphw - 1, graphy - j, snowcolor(snowfall))

            if snow4d is not None:
                snow4d = str(round(snow4d))
            else:
                snow4d = "?"

            if snow8d is not None:
                snow8d = str(round(snow8d))
            else:
                snow8d = "?"

            liney = 17
            x4d = graphx - 1 + round((num_bars / 4) * (graphw + 1) + 0.5 - (len(snow4d) + 1) * 5 / 2)
            x8d = graphx - 1 + round((3 * num_bars / 4) * (graphw + 1) + 2 + 0.5 - (len(snow8d) + 1) * 5 / 2)
            middlex = round(graphx - 1 + num_bars / 2 * (graphw + 1) + 1)
            graphics.DrawLine(self.sign.canvas, graphx - 2, liney, x4d - 2, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x4d + 1 + (len(snow4d) + 1) * 5, liney, x8d - 2, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, x8d + 1 + (len(snow8d) + 1) * 5, liney, graphend + 1, liney, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, graphx - 2, liney - 3, graphx - 2, liney + 3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, middlex, liney - 3, middlex, liney + 3, graphics.Color(13, 13, 25))
            graphics.DrawLine(self.sign.canvas, graphend + 2, liney - 3, graphend + 2, liney + 3, graphics.Color(13, 13, 25))
            graphics.DrawText(self.sign.canvas, self.sign.font57, x4d, liney + 3, snowcolor(snow4d), snow4d + '"')
            graphics.DrawText(self.sign.canvas, self.sign.font57, x8d, liney + 3, snowcolor(snow8d), snow8d + '"')

            # Draw small Sun icon
            sunx = 93
            suny = 1

            self.sign.canvas.SetPixel(sunx + 1, suny + 1, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx + 2, suny + 1, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx + 3, suny + 1, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx + 1, suny + 2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx + 2, suny + 2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx + 3, suny + 2, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx + 1, suny + 3, 185, 120, 0)
            self.sign.canvas.SetPixel(sunx + 2, suny + 3, 220, 130, 0)
            self.sign.canvas.SetPixel(sunx + 3, suny + 3, 185, 120, 0)

            self.sign.canvas.SetPixel(sunx, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx + 2, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx + 4, suny, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx, suny + 2, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx + 4, suny + 2, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx, suny + 4, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx + 2, suny + 4, 180, 65, 0)
            self.sign.canvas.SetPixel(sunx + 4, suny + 4, 180, 65, 0)

            minTemp = "?"
            maxTemp = "?"
            if weather and "dayLow" in weather and weather["dayLow"] is not None:
                minTemp = round(weather["dayLow"])
            if weather and "dayHigh" in weather and weather["dayHigh"] is not None:
                maxTemp = round(weather["dayHigh"])

            graphics.DrawText(self.sign.canvas, self.sign.font46, sunx + 7, suny + 5, graphics.Color(95, 95, 105), f"{minTemp}-{maxTemp}°F")

            # Draw small Moon icon
            moonx = 93
            moony = 7

            self.sign.canvas.SetPixel(moonx + 1, moony, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx + 2, moony, 103, 111, 116)
            self.sign.canvas.SetPixel(moonx + 3, moony, 31, 33, 34)
            self.sign.canvas.SetPixel(moonx, moony + 1, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx + 1, moony + 1, 113, 122, 116)
            self.sign.canvas.SetPixel(moonx + 2, moony + 1, 31, 33, 35)
            self.sign.canvas.SetPixel(moonx, moony + 2, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx + 1, moony + 2, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx + 2, moony + 2, 18, 19, 20)
            self.sign.canvas.SetPixel(moonx, moony + 3, 92, 99, 103)
            self.sign.canvas.SetPixel(moonx + 1, moony + 3, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx + 2, moony + 3, 81, 87, 91)
            self.sign.canvas.SetPixel(moonx + 1, moony + 4, 92, 100, 104)
            self.sign.canvas.SetPixel(moonx + 2, moony + 4, 113, 122, 127)
            self.sign.canvas.SetPixel(moonx + 3, moony + 4, 92, 100, 104)

            minTemp = "?"
            maxTemp = "?"
            if weather and "nightLow" in weather and weather["nightLow"] is not None:
                minTemp = round(weather["nightLow"])
            if weather and "nightHigh" in weather and weather["nightHigh"] is not None:
                maxTemp = round(weather["nightHigh"])

            graphics.DrawText(self.sign.canvas, self.sign.font46, moonx + 7, moony + 5, graphics.Color(95, 95, 105), f"{minTemp}-{maxTemp}°F")

    def drawoverview(self, res_id, user_list):

        n = len(user_list)
        currently_displayed = res_id

        start_index = -1
        found = False
        for uuid in user_list:
            start_index += 1
            if currently_displayed == uuid:
                found = True
                break

        if not found:
            if n > 0:
                start_index = random.randint(0, n - 1)
            else:
                # Do not want to be in this mode if we have no saved user resorts
                shared_config.shared_snow_mode.value = SnowMode.STATIC.value
                self.drawresort(currently_displayed)
                return

        numdisplay = min(4, n)
        display_ids = []
        index = start_index
        for i in range(numdisplay):
            display_ids.append(user_list[index])
            index = (index + 1) % n

        resorts = [self.update(res_id) for res_id in display_ids]
        if any(resort is not None and resort.get("status") == "offline" for resort in resorts):
            draw_offline(self.sign, "SNOW")
            return

        offset = 0
        for resort in resorts:
            if resort is not None:
                state = resort.get("status", "ready")
                if state == "unavailable" or resort.get("isOpen") is None:
                    color = graphics.Color(100, 100, 100)
                elif resort["isOpen"]:
                    color = graphics.Color(40, 167, 69)
                else:
                    color = graphics.Color(115, 18, 15)

                if state == "ready":
                    graphics.DrawText(self.sign.canvas, self.sign.font57, 1, 7 + offset, color, resort["displayName"][:15])
                else:
                    label = "CACHED" if state == "cached" else "N/A"
                    graphics.DrawText(self.sign.canvas, self.sign.font46, 1, 7 + offset, graphics.Color(180, 100, 30), f"{label} {resort['displayName']}"[:19])

                graphics.DrawLine(self.sign.canvas, 94, 0, 94, 31, graphics.Color(13, 13, 25))

                snownew = resort.get("new")
                if snownew is None:
                    snownew = "?"
                else:
                    snownew = str(round(snownew))

                snowfall_days = _snow_forecast_inches(resort)
                snow4d = _snow_forecast_total(snowfall_days[:4])
                snow8d = _snow_forecast_total(snowfall_days[4:])
                if snow4d is not None:
                    snow4d = str(round(snow4d))
                else:
                    snow4d = "?"

                if snow8d is not None:
                    snow8d = str(round(snow8d))
                else:
                    snow8d = "?"

                graphics.DrawText(self.sign.canvas, self.sign.font57, 86 - round((len(snownew) + 1) * 5 / 2), 7 + offset, snowcolor(snownew), snownew + '"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 104 - round((len(snow4d) + 1) * 5 / 2), 7 + offset, snowcolor(snow4d), snow4d + '"')
                graphics.DrawText(self.sign.canvas, self.sign.font57, 121 - round((len(snow8d) + 1) * 5 / 2), 7 + offset, snowcolor(snow8d), snow8d + '"')

                offset += 8

    def _failed_update(self, resort, error):
        failures = resort.get("failures", 0) + 1
        delay = network.retry_delay(failures, SNOW_RETRY_SECONDS, SNOW_MAX_RETRY_SECONDS, max_doublings=3)
        if network.is_offline_error(error):
            status = "offline"
        else:
            status = "cached" if "last_update" in resort else "unavailable"
        resort.update(status=status, failures=failures, next_attempt=time.monotonic() + delay)
        logging.warning("Snow feed %s for uuid=%s; retry in %ss: %s", resort["status"], resort["uuid"], delay, _snow_feed_error(error))
        return resort

    def _get_weather(self, session, reporturl, resortdata):
        weather_url = reporturl.rsplit("/", 1)[0] + "/weather"
        try:
            page = _parse_snow_page(_fetch_snow_feed(session, weather_url), "weatherInfoHourly")
            return _parse_snow_weather(page)
        except (requests.RequestException, SnowFeedError) as error:
            key = shared_config.CONF.get("OPENWEATHER_API_KEY")
            if not key:
                raise
            logging.warning("Snow hourly weather unavailable; attempting OpenWeather: %s", _snow_feed_error(error))
        lat = _snow_number(resortdata.get("latitude"), "resort latitude")
        lon = _snow_number(resortdata.get("longitude"), "resort longitude")
        if lat is None or lon is None:
            raise SnowFeedError("missing coordinates for OpenWeather fallback")
        params = {"lat": lat, "lon": lon, "appid": key, "exclude": "minutely,hourly", "units": "imperial"}
        data = json.loads(_fetch_snow_feed(session, "https://api.openweathermap.org/data/3.0/onecall", params=params))
        return _parse_snow_openweather(data)

    def update(self, res_id):
        """Return a ready, cached, or unavailable resort; retry failures separately."""
        if not res_id:
            return None
        resort = next((res for res in self.resorts if res["uuid"] == res_id), None)
        if resort is None:
            resort = {"uuid": res_id, "displayName": "Snow report", "status": "unavailable"}
            self.resorts.append(resort)
        if time.monotonic() < resort.get("next_attempt", 0):
            return resort
        if resort.get("status") == "ready" and time.time() < resort["last_update"] + SNOW_UPDATE_SECONDS:
            return resort
        if "url" not in resort:
            try:
                populate_resort_lists()
            except (requests.RequestException, json.JSONDecodeError) as error:
                return self._failed_update(resort, error)
            catalog_info = shared_config.data_dict.get("resort_info", {})
            if not isinstance(catalog_info, dict):
                return self._failed_update(resort, SnowFeedError("invalid resort catalog"))
            catalog = catalog_info.get("resorts") or []
            if not isinstance(catalog, list) or not all(isinstance(res, dict) for res in catalog):
                return self._failed_update(resort, SnowFeedError("invalid resort catalog list"))
            info = next((res for res in catalog if res.get("uuid") == res_id), None)
            if info is None:
                return self._failed_update(resort, SnowFeedError("resort not found in catalog"))
            if not all(isinstance(info.get(key), str) and info[key] for key in ("region", "slug", "title")):
                return self._failed_update(resort, SnowFeedError("invalid resort catalog entry"))
            domain = info.get("domain") or "www.onthesnow.com"
            resort.update(url=f"https://{domain}/{info['region']}/{info['slug']}/skireport", name=info["title"], slug=info["slug"], displayName=compute_display_name(info, 15))
        reporturl = resort["url"]
        logging.debug("Updating snow data for uuid=%s using %s", res_id, reporturl)

        report_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:147.0) Gecko/20100101 Firefox/147.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "cross-site",
            "Sec-GPC": "1",
        }

        with requests.Session() as s:
            s.headers.update(report_headers)
            try:
                page = _parse_snow_page(_fetch_snow_feed(s, reporturl))
                snapshot, resortdata = _parse_snow_report(page, res_id)
                snapshot["weather"] = self._get_weather(s, reporturl, resortdata)
            except (requests.RequestException, SnowFeedError, json.JSONDecodeError, UnicodeDecodeError) as error:
                return self._failed_update(resort, error)

            resort.update(snapshot, last_update=time.time(), status="ready", failures=0, next_attempt=0)
            logging.info("Snow report refreshed for uuid=%s: %s forecast days", res_id, len(snapshot["forecast"]))
            if "logo" not in resort or resort["logo"] is None:
                logo = None

                # First try to get saved logo
                try:
                    with Image.open(f"{shared_config.icons_dir}/snow/logos/{resort['slug']}.png") as image:
                        logo = image.convert("RGB")
                except FileNotFoundError:
                    logo = None
                except OSError as error:
                    logging.warning("Snow resort logo unavailable for uuid=%s: %s", res_id, type(error).__name__)

                if logo is None:
                    # List of websites to try getting favicon from (in preference order)
                    website_list = [resortdata.get(key) for key in ("website", "liftsUrl", "rentalUrl", "lessonsUrl", "mobileWebsite")]

                    if not any(website_list):
                        logging.debug(f"No websites listed for {resort['name']}.")

                    checked = []

                    for website in website_list:
                        if not isinstance(website, str) or not website:
                            continue
                        if website in checked:
                            continue

                        logging.debug(f"Attempting to get favicon for {resort['name']} from: {website}.")

                        logo = getFavicon(website)
                        if logo is not None:
                            logging.debug(f"Successfully got logo for resort {resort['name']} from: {website}.")
                            break

                        if len(checked) == 0:
                            # First website, also try url version without "www."
                            p = urlparse(website)
                            baseurl = p.netloc
                            scheme = p.scheme
                            if baseurl.startswith("www."):
                                website = scheme + "://" + baseurl[4:]

                                logging.debug(f"Attempting to get favicon for {resort['name']} from: {website}.")

                                logo = getFavicon(website)
                                if logo is not None:
                                    logging.debug(f"Successfully got logo for resort {resort['name']} from: {website}.")
                                    break

                        checked.append(website)

                if logo is None:
                    # Give up and use the default image
                    try:
                        with Image.open(f"{shared_config.icons_dir}/snow/logos/DEFAULT.png") as image:
                            logo = image.convert("RGB")
                    except OSError as error:
                        logging.warning("Snow default logo unavailable: %s", type(error).__name__)
                    logging.debug(f"Could not get logo for resort {resort['name']}.")
                else:
                    # Save logo to disk so we don't need to get it from the web again
                    try:
                        logo.convert("RGB").save(f"{shared_config.icons_dir}/snow/logos/{resort['slug']}.png")
                    except OSError as error:
                        logging.warning("Could not save Snow logo for uuid=%s: %s", res_id, type(error).__name__)

                resort["logo"] = logo

        return resort


@planesign_mode_handler(DisplayMode.SNOW)
def snow_forecast(sign):
    release_lock(userresorts_filename)
    sign.canvas.Clear()

    breakout = draw_loading(sign)
    if breakout:
        return

    sr = SnowReport(sign)

    load_user_list()
    user_list = shared_config.data_dict["user_resorts"]
    n = len(user_list)
    if n > 0:
        shared_config.data_dict["displayed_resort"] = user_list[random.randint(0, n - 1)]

    last_rotate = time.perf_counter()
    while shared_config.shared_mode.value == DisplayMode.SNOW.value:
        if "displayed_resort" in shared_config.data_dict and shared_config.data_dict["displayed_resort"]:
            current_resort = shared_config.data_dict["displayed_resort"]
        else:
            current_resort = None

        if current_resort is None:
            # Nothing to display - draw the background gif
            sr.draw_snow_frame()

        elif shared_config.shared_snow_mode.value == SnowMode.STATIC.value:
            sr.drawresort(current_resort)

        elif shared_config.shared_snow_mode.value == SnowMode.ROTATE.value:
            if time.perf_counter() - last_rotate > 30:
                load_user_list()
                user_list = shared_config.data_dict["user_resorts"]
                n = len(user_list)
                index = -1
                found = False
                for uuid in user_list:
                    index += 1
                    if current_resort == uuid:
                        found = True
                        break

                if found:
                    index = (index + 1) % n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                elif n > 0:
                    index = random.randint(0, n - 1)
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                else:
                    current_resort = None
                    shared_config.data_dict["displayed_resort"] = None

            if current_resort:
                sr.drawresort(current_resort)
            else:
                sr.draw_snow_frame()

        elif shared_config.shared_snow_mode.value == SnowMode.OVERVIEW.value:
            if time.perf_counter() - last_rotate > 15:
                load_user_list()
                user_list = shared_config.data_dict["user_resorts"]
                n = len(user_list)
                index = -1
                found = False
                for uuid in user_list:
                    index += 1
                    if current_resort == uuid:
                        found = True
                        break

                if found and n >= 8:
                    index = (index + 4) % n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                elif found and n >= 4:
                    index = (index + 1) % n
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                elif found and n > 0:
                    index = 0
                    current_resort = user_list[index]
                    shared_config.data_dict["displayed_resort"] = current_resort
                    last_rotate = time.perf_counter()
                else:
                    current_resort = None
                    shared_config.data_dict["displayed_resort"] = None

            if current_resort:
                sr.drawoverview(current_resort, user_list)
            else:
                sr.draw_snow_frame()

        else:
            logging.error(f"Invalid snow mode: {shared_config.shared_snow_mode.value}.")
            shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value
            return

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        sign.canvas.Clear()

        breakout = sign.wait_loop(1.0)

        if breakout:
            return
