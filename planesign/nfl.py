import logging
import math
import re
import time
from datetime import datetime

import requests
import shared_config
import utilities
from modes import DisplayMode
from rgbmatrix import graphics

import __main__

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
REQUEST_TIMEOUT = (5, 15)
LIVE_TTL = 8
IDLE_TTL = 60
MAX_RETRY = 15 * 60
STALE_AFTER = 5 * 60
FRAME_INTERVAL = 0.05

PANEL_RIGHT = 41
ROW_SPLIT = 16
ABBR_COLUMN = 2
ABBR_BASELINE = 7
RECORD_COLUMN = 2
RECORD_WIDTH = 4
RECORD_BASELINE = 14
RECORD_MAX_CHARS = 5
SCORE_WIDTH = 9
SCORE_RIGHT = 40
SCORE_BASELINE = 13

STATUS_LEFT = 43
STATUS_RIGHT = 55
STATUS_WIDTH = STATUS_RIGHT - STATUS_LEFT + 1
STATUS_LEVEL = 0.22
TIMEOUT_ROW = 5
TIMEOUT_PIP_WIDTH = 3
TIMEOUT_PIP_GAP = 2
TIMEOUTS_PER_TEAM = 3
MARKER_ROW = 11
MARKER_WIDTH = 5
WINNER_MARKER_WIDTH = 3

# The field is drawn to scale: two yards per pixel between the goal lines, one yard per pixel through the end zones.
AWAY_GOAL_COLUMN = 67
HOME_GOAL_COLUMN = AWAY_GOAL_COLUMN + 50
END_ZONE_DEPTH = 10
FIELD_LEFT = AWAY_GOAL_COLUMN - END_ZONE_DEPTH
FIELD_RIGHT = HOME_GOAL_COLUMN + END_ZONE_DEPTH
FIELD_TOP = 6
FIELD_BOTTOM = 25
TURF_TOP = FIELD_TOP + 1
TURF_BOTTOM = FIELD_BOTTOM - 1
TURF_HEIGHT = TURF_BOTTOM - TURF_TOP + 1
HASH_ROWS = (TURF_TOP + 7, TURF_BOTTOM - 7)
CENTER_ROWS = (TURF_TOP + 8, TURF_TOP + 9)
ARROW_ROW = TURF_TOP + 3
LETTER_HEIGHT = 6
LETTER_INK = 3
CLOCK_BASELINE = 5
# Capitals sit five rows above the baseline, so 32 bottom-aligns the line without clipping.
INFO_BASELINE = 32
ENDZONE_LEVEL = 0.85

NEXT_HEADER_BASELINE = 5
NEXT_BLOCK_TOP = 8
NEXT_BLOCK_BOTTOM = 23
NEXT_BLOCK_WIDTH = 50
NEXT_ABBR_BASELINE = 20
NEXT_DETAIL_BASELINE = 31
NEXT_DETAIL_SECONDS = 3.0

TURF_DARK = (10, 58, 26)
TURF_LIGHT = (14, 78, 36)
YARD_LINE_COLOR = (86, 140, 100)
HASH_COLOR = (64, 112, 78)
MIDFIELD_COLOR = (150, 205, 165)
GOAL_LINE_COLOR = (230, 236, 230)
SIDELINE_COLOR = (170, 180, 172)
GOAL_POST_COLOR = (238, 208, 60)
FIRST_DOWN_COLOR = (235, 205, 45)
SCRIMMAGE_COLOR = (60, 130, 245)
BALL_COLOR = (250, 246, 235)
TITLE_COLOR = (90, 170, 245)
CLOCK_COLOR = (200, 225, 250)
STALE_COLOR = (255, 190, 90)
INFO_COLOR = (150, 200, 235)
WARN_COLOR = (240, 180, 90)
MATCHUP_COLOR = (205, 215, 230)
TIMEOUT_COLOR = (245, 245, 245)
TIMEOUT_USED_COLOR = (72, 72, 72)
WINNER_COLOR = (120, 225, 150)
RED_ZONE_COLOR = (235, 60, 45)
RED_ZONE_PERIOD = 1.6

MIN_BLOCK_LUMINANCE = 0.09
MIN_TEAM_COLOR_DISTANCE = 60
MIN_TURF_CONTRAST = 55
PERIOD_NAMES = ("1ST", "2ND", "3RD", "4TH")
FIELD_SPOT = re.compile(r"^(?:([A-Z]{2,4})\s+)?(\d{1,2})$")


def parse_hex_color(value, fallback=(90, 90, 90)):
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return fallback


def luminance(color):
    return (0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]) / 255


def scale(color, level):
    return tuple(max(0, min(255, round(value * level))) for value in color)


def text_color_for(color):
    return (16, 16, 16) if luminance(color) > 0.45 else (245, 245, 245)


def end_zone_color(color):
    # A dark green team would otherwise vanish into the turf, so lift it until the end zone reads as its own block.
    zone = scale(color, ENDZONE_LEVEL)
    for step in range(1, 16):
        if min(math.dist(zone, TURF_DARK), math.dist(zone, TURF_LIGHT)) >= MIN_TURF_CONTRAST:
            break
        zone = scale(color, ENDZONE_LEVEL + 0.1 * step)
    return zone


def readable_team_color(team):
    primary = parse_hex_color(team.get("color"))
    alternate = parse_hex_color(team.get("alt_color"))
    if luminance(primary) < MIN_BLOCK_LUMINANCE <= luminance(alternate):
        return alternate
    return primary


def resolve_team_colors(away, home):
    away_color, home_color = readable_team_color(away), readable_team_color(home)
    if math.dist(away_color, home_color) >= MIN_TEAM_COLOR_DISTANCE:
        return away_color, home_color
    candidate = parse_hex_color(home.get("alt_color"))
    if luminance(candidate) >= MIN_BLOCK_LUMINANCE and math.dist(away_color, candidate) >= MIN_TEAM_COLOR_DISTANCE:
        return away_color, candidate
    candidate = parse_hex_color(away.get("alt_color"))
    if luminance(candidate) >= MIN_BLOCK_LUMINANCE and math.dist(candidate, home_color) >= MIN_TEAM_COLOR_DISTANCE:
        return candidate, home_color
    return away_color, scale(home_color, 0.45)


def parse_score(value):
    if isinstance(value, dict):
        value = value.get("displayValue", value.get("value"))
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_kickoff(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def timeout_count(value):
    if isinstance(value, (int, float)) and 0 <= value <= TIMEOUTS_PER_TEAM:
        return int(value)
    return None


def team_record(competitor):
    for record in competitor.get("records") or []:
        if not isinstance(record, dict):
            continue
        if str(record.get("type") or "").lower() in ("total", "overall"):
            return str(record.get("summary") or "").strip()
    return ""


def team_snapshot(competitor):
    team = competitor.get("team") or {}
    return {
        "id": str(team.get("id") or ""),
        "abbr": str(team.get("abbreviation") or "")[:3].upper(),
        "name": str(team.get("displayName") or team.get("name") or ""),
        "score": parse_score(competitor.get("score")),
        "color": str(team.get("color") or ""),
        "alt_color": str(team.get("alternateColor") or ""),
        "winner": bool(competitor.get("winner")),
        "record": team_record(competitor),
    }


def venue_snapshot(competition):
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}
    city = str(address.get("city") or "").strip()
    region = str(address.get("state") or address.get("country") or "").strip()
    return {"name": str(venue.get("fullName") or "").strip(), "location": ", ".join(part for part in (city, region) if part), "indoor": bool(venue.get("indoor"))}


def broadcast_label(competition):
    names = []
    for broadcast in competition.get("broadcasts") or []:
        if not isinstance(broadcast, dict):
            continue
        for name in broadcast.get("names") or []:
            name = str(name).strip()
            if name and name not in names:
                names.append(name)
    if not names:
        single = str(competition.get("broadcast") or "").strip()
        if single:
            names.append(single)
    return "/".join(names[:3]).upper()


def odds_label(competition):
    for odds in competition.get("odds") or []:
        if not isinstance(odds, dict):
            continue
        parts = []
        details = str(odds.get("details") or "").strip().upper()
        if details:
            parts.append(details)
        over_under = odds.get("overUnder")
        if isinstance(over_under, (int, float)):
            parts.append(f"O/U {over_under:g}")
        if parts:
            return "  ".join(parts)
    return ""


def weather_label(event):
    weather = event.get("weather")
    if not isinstance(weather, dict):
        return ""
    condition = str(weather.get("displayValue") or "").strip().upper()
    temperature = weather.get("temperature")
    if not isinstance(temperature, (int, float)):
        temperature = weather.get("highTemperature")
    if isinstance(temperature, (int, float)):
        return f"{condition} {round(temperature)}F".strip()
    return condition


def series_label(event, competition):
    for note in competition.get("notes") or []:
        if isinstance(note, dict) and str(note.get("headline") or "").strip():
            return str(note["headline"]).strip().upper()
    week = (event.get("week") or {}).get("number")
    if not isinstance(week, (int, float)):
        return ""
    season_type = (event.get("season") or {}).get("type")
    if season_type == 1:
        return f"PRESEASON WK {int(week)}"
    if season_type == 3:
        return f"PLAYOFFS WK {int(week)}"
    return f"WEEK {int(week)}"


def period_text(period, status_name):
    if status_name == "STATUS_HALFTIME":
        return "HALF"
    if status_name.startswith("STATUS_FINAL"):
        return "FINAL/OT" if period and period > 4 else "FINAL"
    if not period:
        return ""
    if period > 4:
        return "OT" if period == 5 else f"{period - 4}OT"
    return PERIOD_NAMES[period - 1]


def situation_snapshot(competition):
    situation = competition.get("situation")
    if not isinstance(situation, dict):
        return None
    possession = situation.get("possession")
    if isinstance(possession, dict):
        possession = possession.get("id")
    return {
        "possession_id": str(possession or ""),
        "down": situation.get("down"),
        "distance": situation.get("distance"),
        "yard_line": situation.get("yardLine"),
        "possession_text": str(situation.get("possessionText") or ""),
        "down_distance_text": str(situation.get("downDistanceText") or ""),
        "short_down_distance_text": str(situation.get("shortDownDistanceText") or ""),
        "is_red_zone": bool(situation.get("isRedZone")),
        "away_timeouts": timeout_count(situation.get("awayTimeouts")),
        "home_timeouts": timeout_count(situation.get("homeTimeouts")),
    }


def parse_game(event):
    competition = (event.get("competitions") or [{}])[0]
    teams = {}
    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        if side in ("home", "away"):
            teams[side] = team_snapshot(competitor)
    if "home" not in teams or "away" not in teams:
        raise ValueError("Competition is missing a home or away team")
    status = competition.get("status") or event.get("status") or {}
    status_type = status.get("type") or {}
    status_name = str(status_type.get("name") or "")
    period = status.get("period") or 0
    return {
        "id": str(event.get("id") or competition.get("id") or ""),
        "short_name": str(event.get("shortName") or ""),
        "state": str(status_type.get("state") or "pre"),
        "status_name": status_name,
        "status_detail": str(status_type.get("detail") or ""),
        "display_clock": str(status.get("displayClock") or ""),
        "period": period,
        "period_text": period_text(period, status_name),
        "kickoff": parse_kickoff(event.get("date")),
        "home": teams["home"],
        "away": teams["away"],
        "situation": situation_snapshot(competition),
        "venue": venue_snapshot(competition),
        "broadcast": broadcast_label(competition),
        "odds": odds_label(competition),
        "weather": weather_label(event),
        "series": series_label(event, competition),
        "neutral_site": bool(competition.get("neutralSite")),
    }


def parse_scoreboard(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise TypeError("Malformed ESPN scoreboard response")
    games = []
    for event in payload["events"]:
        try:
            game = parse_game(event)
        except (AttributeError, IndexError, TypeError, ValueError) as error:
            logging.warning("Skipping malformed ESPN event: %s", error)
            continue
        if game["id"]:
            games.append(game)
    if not games:
        raise ValueError("ESPN scoreboard contained no usable games")
    return games


def parse_field_spot(text):
    if not text:
        return None
    spot = str(text).upper().strip()
    _, _, tail = spot.rpartition(" AT ")
    match = FIELD_SPOT.fullmatch(tail.strip() or spot)
    if not match:
        return None
    return match.group(1), int(match.group(2))


def yards_to_goal(situation, offense_abbr):
    """Yards from the ball to the end zone the offense is attacking, or None when unknown."""
    red_zone = situation.get("is_red_zone")
    for text in (situation.get("possession_text"), situation.get("down_distance_text")):
        spot = parse_field_spot(text)
        if spot is None:
            continue
        abbr, yard = spot
        if abbr is None:
            yards = 50
        elif abbr == offense_abbr:
            yards = 100 - yard
        else:
            yards = yard
        if red_zone and yards > 20:
            logging.warning("Ignoring field spot %r: red zone flag disagrees with %s yards to goal", text, yards)
            continue
        return yards
    yard_line = situation.get("yard_line")
    if not isinstance(yard_line, (int, float)) or not 0 <= yard_line <= 100:
        return None
    # ESPN measures yardLine from the offense's own goal line, but the red zone flag breaks ties.
    for yards in (100 - int(yard_line), int(yard_line)):
        if not red_zone or yards <= 20:
            return yards
    return None


class NFLCache:
    def __init__(self, session):
        self.session = session
        self.snapshot = None
        self.next_attempt = 0
        self.failures = 0
        self.pooled = False

    def interval(self):
        games = (self.snapshot or {}).get("games") or []
        return LIVE_TTL if any(game["state"] == "in" for game in games) else IDLE_TTL

    def poll(self, now, active):
        if not active:
            # Keep-alive would otherwise hold a socket open to ESPN for as long as the sign runs.
            if self.pooled:
                self.session.close()
                self.pooled = False
            return None
        if now < self.next_attempt:
            return None
        if self.snapshot and now - self.snapshot["fetched_at"] < self.interval():
            return None
        try:
            started = time.monotonic()
            self.pooled = True
            response = self.session.get(SCOREBOARD_URL, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                raise ValueError(f"ESPN HTTP {response.status_code}")
            games = parse_scoreboard(response.json())
            self.snapshot = {"games": games, "fetched_at": now, "status": "ready"}
            self.failures = 0
            logging.info("ESPN NFL scoreboard: %s games (%s live) in %.2fs", len(games), sum(1 for game in games if game["state"] == "in"), time.monotonic() - started)
            return self.snapshot
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            self.failures += 1
            delay = min(MAX_RETRY, 15 * 2 ** min(self.failures - 1, 5))
            self.next_attempt = now + delay
            logging.warning("ESPN NFL scoreboard unavailable; retry in %ss: %s", delay, error)
            if self.snapshot:
                return {**self.snapshot, "status": "cached"}
            return {"games": [], "fetched_at": now, "status": "unavailable"}


def get_nfl_data_worker(data_dict):
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    with requests.Session() as session:
        cache = NFLCache(session)
        while not shared_config.shared_shutdown_event.is_set():
            payload = cache.poll(time.time(), active=shared_config.shared_mode.value == DisplayMode.NFL.value)
            if payload is not None:
                data_dict["nfl"] = payload
            shared_config.shared_shutdown_event.wait(timeout=1)


def military_time(config):
    return str(config.get("MILITARY_TIME", "false")).lower() == "true"


def clock_label(timestamp, military, compact=False):
    moment = utilities.convert_unix_to_local_time(timestamp)
    if military:
        return moment.strftime("%H:%M")
    if compact:
        return moment.strftime("%-I:%M") + ("A" if moment.hour < 12 else "P")
    return moment.strftime("%-I:%M %p")


def kickoff_label(timestamp, military, compact=False):
    if not timestamp:
        return "TBD"
    day = utilities.convert_unix_to_local_time(timestamp).strftime("%a")
    return f"{day.upper() if compact else day} {clock_label(timestamp, military, compact)}"


def is_today(timestamp, now):
    if not timestamp:
        return False
    return utilities.convert_unix_to_local_time(timestamp).date() == utilities.convert_unix_to_local_time(now).date()


def sort_key(game, now):
    kickoff = game["kickoff"] or 0
    if game["state"] == "in":
        return (0, kickoff)
    if game["state"] == "pre" and is_today(game["kickoff"], now):
        return (1, kickoff)
    if game["state"] == "post":
        return (2, -kickoff)
    return (3, kickoff)


def score_text(team):
    return "-" if team["score"] is None else str(team["score"])


def game_label(game, military):
    away, home = game["away"], game["home"]
    if game["state"] == "pre":
        return f"{away['abbr']} @ {home['abbr']} - {kickoff_label(game['kickoff'], military)}"
    matchup = f"{away['abbr']} {score_text(away)} @ {home['abbr']} {score_text(home)}"
    if game["state"] == "post":
        return f"{matchup} - {game['period_text'] or 'Final'}"
    return f"{matchup} - {' '.join(part for part in (game['display_clock'], game['period_text']) if part)}"


def game_options(snapshot, now, military):
    games = (snapshot or {}).get("games") or []
    ordered = sorted(games, key=lambda game: sort_key(game, now))
    return [{"id": game["id"], "label": game_label(game, military), "state": game["state"]} for game in ordered]


def find_game(snapshot, game_id):
    if not game_id:
        return None
    for game in (snapshot or {}).get("games") or []:
        if game["id"] == game_id:
            return game
    return None


def next_upcoming_game(snapshot, now):
    scheduled = [game for game in (snapshot or {}).get("games") or [] if game["state"] == "pre"]
    if not scheduled:
        return None
    future = [game for game in scheduled if game["kickoff"] and game["kickoff"] >= now]
    return min(future or scheduled, key=lambda game: game["kickoff"] or float("inf"))


def countdown_label(kickoff, now):
    if not kickoff:
        return "KICKOFF TBD"
    remaining = int(kickoff - now)
    if remaining <= 0:
        return "KICKOFF ANY MINUTE"
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"KICKOFF IN {days}D {hours}H"
    if hours:
        return f"KICKOFF IN {hours}H {minutes}M"
    if minutes:
        return f"KICKOFF IN {minutes}M {seconds}S"
    return f"KICKOFF IN {seconds}S"


def upcoming_kickoff_label(game, now, military):
    if not game["kickoff"]:
        return "TIME TBD"
    if is_today(game["kickoff"], now):
        return f"TODAY {clock_label(game['kickoff'], military)}"
    return kickoff_label(game["kickoff"], military).upper()


def upcoming_details(game, now):
    away, home, venue = game["away"], game["home"], game["venue"]
    details = [countdown_label(game["kickoff"], now)]
    if venue["name"]:
        details.append(venue["name"].upper())
    place = venue["location"].upper()
    if place:
        details.append(f"{place} (DOME)" if venue["indoor"] else place)
    if game["neutral_site"]:
        details.append("NEUTRAL SITE")
    billing = " ON ".join(part for part in (game["series"], game["broadcast"]) if part)
    if billing:
        details.append(billing)
    if away["record"] and home["record"]:
        details.append(f"{away['abbr']} {away['record']}  {home['abbr']} {home['record']}")
    if game["odds"]:
        details.append(game["odds"])
    if game["weather"]:
        details.append(game["weather"])
    return details


def fill_rect(canvas, x0, y0, x1, y1, color):
    pen = graphics.Color(*color)
    for row in range(y0, y1 + 1):
        graphics.DrawLine(canvas, x0, row, x1, row, pen)


def draw_centered(canvas, font, width, baseline, color, text, left=FIELD_LEFT, right=FIELD_RIGHT):
    text = text.encode("ascii", "replace").decode("ascii")[: (right - left + 1) // width]
    column = left + (right - left + 1 - len(text) * width) // 2
    graphics.DrawText(canvas, font, column, baseline, graphics.Color(*color), text)


def draw_message(sign, lines):
    sign.canvas.Clear()
    draw_centered(sign.canvas, sign.fontbig, 6, 12, TITLE_COLOR, "NFL", 0, 127)
    for index, (text, color) in enumerate(lines):
        draw_centered(sign.canvas, sign.font57, 5, 22 + index * 9, color, text, 0, 127)


def draw_possession_marker(canvas, column, row, color):
    pen = graphics.Color(*color)
    graphics.DrawLine(canvas, column + 1, row - 1, column + 3, row - 1, pen)
    graphics.DrawLine(canvas, column, row, column + 4, row, pen)
    graphics.DrawLine(canvas, column + 1, row + 1, column + 3, row + 1, pen)


def draw_winner_marker(canvas, column, row, color):
    pen = graphics.Color(*color)
    for offset in range(3):
        graphics.DrawLine(canvas, column + offset, row - 2 + offset, column + offset, row + 2 - offset, pen)


def draw_timeouts(canvas, row, remaining):
    span = TIMEOUTS_PER_TEAM * TIMEOUT_PIP_WIDTH + (TIMEOUTS_PER_TEAM - 1) * TIMEOUT_PIP_GAP
    left = STATUS_LEFT + (STATUS_WIDTH - span) // 2
    for index in range(TIMEOUTS_PER_TEAM):
        start = left + index * (TIMEOUT_PIP_WIDTH + TIMEOUT_PIP_GAP)
        fill_rect(canvas, start, row, start + TIMEOUT_PIP_WIDTH - 1, row + 1, TIMEOUT_COLOR if index < remaining else TIMEOUT_USED_COLOR)


def draw_team_status(sign, game, team, color, top, timeouts, offense_id):
    fill_rect(sign.canvas, STATUS_LEFT, top, STATUS_RIGHT, top + ROW_SPLIT - 1, scale(color, STATUS_LEVEL))
    if timeouts is not None:
        draw_timeouts(sign.canvas, top + TIMEOUT_ROW, timeouts)
    if offense_id and team["id"] == offense_id:
        draw_possession_marker(sign.canvas, STATUS_LEFT + (STATUS_WIDTH - MARKER_WIDTH) // 2, top + MARKER_ROW, BALL_COLOR)
    elif game["state"] == "post" and team["winner"]:
        draw_winner_marker(sign.canvas, STATUS_LEFT + (STATUS_WIDTH - WINNER_MARKER_WIDTH) // 2, top + MARKER_ROW, WINNER_COLOR)


def draw_scoreboard(sign, game, colors, situation, offense_id):
    timeouts = situation or {}
    for team, color, top, remaining in ((game["away"], colors[0], 0, timeouts.get("away_timeouts")), (game["home"], colors[1], ROW_SPLIT, timeouts.get("home_timeouts"))):
        pen = graphics.Color(*text_color_for(color))
        fill_rect(sign.canvas, 0, top, PANEL_RIGHT, top + ROW_SPLIT - 1, color)
        graphics.DrawText(sign.canvas, sign.font57, ABBR_COLUMN, top + ABBR_BASELINE, pen, team["abbr"])
        if team["record"] and len(team["record"]) <= RECORD_MAX_CHARS:
            graphics.DrawText(sign.canvas, sign.font46, RECORD_COLUMN, top + RECORD_BASELINE, pen, team["record"])
        score = score_text(team)
        graphics.DrawText(sign.canvas, sign.fontreallybig, SCORE_RIGHT - len(score) * SCORE_WIDTH + 1, top + SCORE_BASELINE, pen, score)
        draw_team_status(sign, game, team, color, top, remaining, offense_id)


def yard_column(yards_from_away_goal):
    """Column for a spot measured in yards from the away team's goal line."""
    yards = min(100, max(0, yards_from_away_goal))
    return AWAY_GOAL_COLUMN + int(yards / 2 + 0.5)


def draw_end_zone_label(canvas, font, left, abbr, color):
    letters = abbr[:3]
    if not letters:
        return
    pen = graphics.Color(*color)
    baseline = TURF_TOP + 5 + (TURF_HEIGHT - len(letters) * LETTER_HEIGHT) // 2
    column = left + (END_ZONE_DEPTH - 1 - LETTER_INK) // 2
    for index, letter in enumerate(letters):
        graphics.DrawText(canvas, font, column, baseline + index * LETTER_HEIGHT, pen, letter)


def draw_field(sign, game, colors, red_zone_side, elapsed):
    canvas = sign.canvas
    fill_rect(canvas, AWAY_GOAL_COLUMN, TURF_TOP, HOME_GOAL_COLUMN, TURF_BOTTOM, TURF_DARK)
    for band in range(1, 10, 2):
        # Mow bands run ten yards, so every other one is five pixels of lighter turf.
        fill_rect(canvas, yard_column(band * 10) + 1, TURF_TOP, yard_column((band + 1) * 10), TURF_BOTTOM, TURF_LIGHT)
    for yards in range(5, 100, 10):
        # Real hash marks sit at every yard; at this scale they read as a dotted inbound line.
        for row in HASH_ROWS:
            canvas.SetPixel(yard_column(yards), row, *HASH_COLOR)

    pulse = 0.55 + 0.45 * math.sin(2 * math.pi * elapsed / RED_ZONE_PERIOD)
    for side, team, color, left in (("away", game["away"], colors[0], FIELD_LEFT + 1), ("home", game["home"], colors[1], HOME_GOAL_COLUMN + 1)):
        zone = scale(RED_ZONE_COLOR, 0.35 + 0.65 * pulse) if side == red_zone_side else end_zone_color(color)
        fill_rect(canvas, left, TURF_TOP, left + END_ZONE_DEPTH - 2, TURF_BOTTOM, zone)
        draw_end_zone_label(canvas, sign.font46, left, team["abbr"], text_color_for(zone))

    for yards in range(10, 100, 10):
        column = yard_column(yards)
        graphics.DrawLine(canvas, column, TURF_TOP, column, TURF_BOTTOM, graphics.Color(*(MIDFIELD_COLOR if yards == 50 else YARD_LINE_COLOR)))
    goal_pen = graphics.Color(*GOAL_LINE_COLOR)
    for column in (AWAY_GOAL_COLUMN, HOME_GOAL_COLUMN):
        graphics.DrawLine(canvas, column, TURF_TOP, column, TURF_BOTTOM, goal_pen)

    side_pen = graphics.Color(*SIDELINE_COLOR)
    graphics.DrawLine(canvas, FIELD_LEFT, FIELD_TOP, FIELD_RIGHT, FIELD_TOP, side_pen)
    graphics.DrawLine(canvas, FIELD_LEFT, FIELD_BOTTOM, FIELD_RIGHT, FIELD_BOTTOM, side_pen)
    post_pen = graphics.Color(*GOAL_POST_COLOR)
    for column in (FIELD_LEFT, FIELD_RIGHT):
        graphics.DrawLine(canvas, column, FIELD_TOP, column, FIELD_BOTTOM, side_pen)
        graphics.DrawLine(canvas, column, CENTER_ROWS[0], column, CENTER_ROWS[1], post_pen)


def draw_direction_arrow(canvas, column, row, heading, color):
    pen = graphics.Color(*color)
    tail = column + heading * 2
    tip = column + heading * 5
    graphics.DrawLine(canvas, tail, row, tip, row, pen)
    graphics.DrawLine(canvas, tip - heading * 2, row - 2, tip, row, pen)
    graphics.DrawLine(canvas, tip - heading * 2, row + 2, tip, row, pen)


def draw_ball(sign, situation, offense, heading):
    remaining = yards_to_goal(situation, offense["abbr"])
    if remaining is None:
        return
    spot = remaining if heading < 0 else 100 - remaining
    column = yard_column(spot)

    distance = situation.get("distance")
    if isinstance(distance, (int, float)) and 0 < distance <= remaining:
        # Short yardage rounds onto the line of scrimmage at two yards per pixel, so nudge it clear.
        marker = max(column + 1, yard_column(spot + distance)) if heading > 0 else min(column - 1, yard_column(spot - distance))
        if AWAY_GOAL_COLUMN < marker < HOME_GOAL_COLUMN:
            graphics.DrawLine(sign.canvas, marker, TURF_TOP, marker, TURF_BOTTOM, graphics.Color(*FIRST_DOWN_COLOR))

    graphics.DrawLine(sign.canvas, column, TURF_TOP, column, TURF_BOTTOM, graphics.Color(*SCRIMMAGE_COLOR))
    draw_direction_arrow(sign.canvas, column, ARROW_ROW, heading, SCRIMMAGE_COLOR)
    fill_rect(sign.canvas, max(AWAY_GOAL_COLUMN, column - 1), CENTER_ROWS[0], min(HOME_GOAL_COLUMN, column + 1), CENTER_ROWS[1], BALL_COLOR)


def info_lines(game, config, now):
    military = military_time(config)
    state, situation = game["state"], game["situation"]
    if state == "pre":
        return kickoff_label(game["kickoff"], military, compact=True), "PREGAME"
    if state == "post":
        date = utilities.convert_unix_to_local_time(game["kickoff"]).strftime("%a %-m/%-d").upper() if game["kickoff"] else ""
        return game["period_text"] or "FINAL", date
    if game["status_name"] == "STATUS_HALFTIME":
        return "HALF", clock_label(now, military, compact=True)
    clock = " ".join(part for part in (game["display_clock"], game["period_text"]) if part)
    if not situation:
        return clock or "IN PROGRESS", ""
    spot = " ".join(part for part in (situation["short_down_distance_text"], situation["possession_text"]) if part)
    return clock or "IN PROGRESS", spot.upper()


def is_stale(snapshot, now):
    return snapshot.get("status") == "cached" or now - snapshot.get("fetched_at", 0) >= STALE_AFTER


def draw_game(sign, game, snapshot, config, now, elapsed):
    situation = game["situation"] if game["state"] == "in" else None
    offense = None
    if situation and situation["possession_id"]:
        offense = next((team for team in (game["away"], game["home"]) if team["id"] == situation["possession_id"]), None)
    colors = resolve_team_colors(game["away"], game["home"])
    # The offense always attacks the opponent's end zone, and away owns the left one.
    heading = 1 if offense is not None and offense["id"] == game["away"]["id"] else -1
    red_zone_side = None
    if offense is not None and situation["is_red_zone"]:
        red_zone_side = "home" if heading > 0 else "away"

    sign.canvas.Clear()
    draw_scoreboard(sign, game, colors, situation, offense["id"] if offense else None)
    draw_field(sign, game, colors, red_zone_side, elapsed)
    if offense is not None:
        draw_ball(sign, situation, offense, heading)

    stale = is_stale(snapshot, now)
    clock, detail = info_lines(game, config, now)
    draw_centered(sign.canvas, sign.font46, 4, CLOCK_BASELINE, STALE_COLOR if stale else CLOCK_COLOR, clock)
    if detail:
        draw_centered(sign.canvas, sign.font46, 4, INFO_BASELINE, INFO_COLOR, detail)


def draw_upcoming(sign, game, snapshot, config, now, elapsed):
    colors = resolve_team_colors(game["away"], game["home"])
    sign.canvas.Clear()
    graphics.DrawText(sign.canvas, sign.font46, 1, NEXT_HEADER_BASELINE, graphics.Color(*TITLE_COLOR), "NEXT UP")
    kickoff = upcoming_kickoff_label(game, now, military_time(config))[:16]
    kickoff_color = STALE_COLOR if is_stale(snapshot, now) else CLOCK_COLOR
    graphics.DrawText(sign.canvas, sign.font46, 128 - len(kickoff) * 4, NEXT_HEADER_BASELINE, graphics.Color(*kickoff_color), kickoff)

    for team, color, left in ((game["away"], colors[0], 0), (game["home"], colors[1], 128 - NEXT_BLOCK_WIDTH)):
        right = left + NEXT_BLOCK_WIDTH - 1
        fill_rect(sign.canvas, left, NEXT_BLOCK_TOP, right, NEXT_BLOCK_BOTTOM, color)
        draw_centered(sign.canvas, sign.fontbig, 6, NEXT_ABBR_BASELINE, text_color_for(color), team["abbr"], left, right)
    draw_centered(sign.canvas, sign.fontbig, 6, NEXT_ABBR_BASELINE, MATCHUP_COLOR, "@", NEXT_BLOCK_WIDTH, 127 - NEXT_BLOCK_WIDTH)

    details = upcoming_details(game, now)
    detail = details[int(elapsed / NEXT_DETAIL_SECONDS) % len(details)]
    draw_centered(sign.canvas, sign.font46, 4, NEXT_DETAIL_BASELINE, INFO_COLOR, detail, 0, 127)


def draw_nfl_frame(sign, snapshot, game_id, config, now, elapsed):
    if not snapshot:
        draw_message(sign, [("Loading...", INFO_COLOR)])
        return
    if snapshot.get("status") == "unavailable":
        draw_message(sign, [("No data", WARN_COLOR), ("Check network", INFO_COLOR)])
        return
    game = find_game(snapshot, game_id)
    live = sum(1 for entry in snapshot.get("games") or [] if entry["state"] == "in")
    if not live and (game is None or game["state"] == "pre"):
        # With nothing being played, an empty field says less than the matchup that is coming.
        preview = game or next_upcoming_game(snapshot, now)
        if preview is not None:
            draw_upcoming(sign, preview, snapshot, config, now, elapsed)
            return
    if game is None:
        draw_message(sign, [("Pick a game", INFO_COLOR), (f"{live} live now" if live else "No games live", INFO_COLOR if live else WARN_COLOR)])
        return
    draw_game(sign, game, snapshot, config, now, elapsed)


@__main__.planesign_mode_handler(DisplayMode.NFL)
def show_nfl(sign):
    while shared_config.shared_mode.value == DisplayMode.NFL.value:
        draw_nfl_frame(sign, shared_config.data_dict.get("nfl"), shared_config.data_dict.get("nfl_game_id"), shared_config.CONF.copy(), time.time(), time.monotonic())
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(FRAME_INTERVAL):
            return
