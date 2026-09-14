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

SCORE_RIGHT = 40
ROW_SPLIT = 16
ABBR_COLUMN = 2
ABBR_WIDTH = 5
SCORE_WIDTH = 6
ABBR_BASELINE = 11
SCORE_BASELINE = 12
MARKER_WIDTH = 5

PANEL_LEFT = 42
PANEL_RIGHT = 127
CLOCK_BASELINE = 5
INFO_BASELINE = 31
FIELD_TOP = 7
FIELD_BOTTOM = 24
ARROW_ROW = FIELD_TOP + 3
PLAY_LEFT = 49
PLAY_RIGHT = 120
YARD_PIXELS = (PLAY_RIGHT - PLAY_LEFT) / 100
ENDZONE_LEVEL = 0.85

TURF_DARK = (10, 58, 26)
TURF_LIGHT = (14, 78, 36)
YARD_LINE_COLOR = (78, 130, 92)
MIDFIELD_COLOR = (150, 205, 165)
FIRST_DOWN_COLOR = (235, 205, 45)
BALL_COLOR = (250, 246, 235)
TITLE_COLOR = (90, 170, 245)
CLOCK_COLOR = (200, 225, 250)
STALE_COLOR = (255, 190, 90)
INFO_COLOR = (150, 200, 235)
WARN_COLOR = (240, 180, 90)
RED_ZONE_COLOR = (235, 60, 45)
RED_ZONE_PERIOD = 1.6

MIN_BLOCK_LUMINANCE = 0.09
MIN_TEAM_COLOR_DISTANCE = 60
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


def emphasize(color, floor=0.45):
    # Team colors have to stay legible against turf, so lift dark ones without shifting hue.
    level = luminance(color)
    if level >= floor:
        return color
    if level <= 0.01:
        return (205, 205, 205)
    return scale(color, floor / level)


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
    }


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

    def interval(self):
        games = (self.snapshot or {}).get("games") or []
        return LIVE_TTL if any(game["state"] == "in" for game in games) else IDLE_TTL

    def poll(self, now, active):
        if not active or now < self.next_attempt:
            return None
        if self.snapshot and now - self.snapshot["fetched_at"] < self.interval():
            return None
        try:
            started = time.monotonic()
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


def fill_rect(canvas, x0, y0, x1, y1, color):
    pen = graphics.Color(*color)
    for row in range(y0, y1 + 1):
        graphics.DrawLine(canvas, x0, row, x1, row, pen)


def draw_centered(canvas, font, width, baseline, color, text, left=PANEL_LEFT, right=PANEL_RIGHT):
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


def draw_scoreboard(sign, game, colors, offense_id):
    for team, color, top in ((game["away"], colors[0], 0), (game["home"], colors[1], ROW_SPLIT)):
        ink = text_color_for(color)
        pen = graphics.Color(*ink)
        fill_rect(sign.canvas, 0, top, SCORE_RIGHT, top + ROW_SPLIT - 1, color)
        graphics.DrawText(sign.canvas, sign.font57, ABBR_COLUMN, top + ABBR_BASELINE, pen, team["abbr"])
        score = score_text(team)
        score_column = SCORE_RIGHT - len(score) * SCORE_WIDTH + 1
        graphics.DrawText(sign.canvas, sign.fontbig, score_column, top + SCORE_BASELINE, pen, score)

        gap = score_column - (ABBR_COLUMN + len(team["abbr"]) * ABBR_WIDTH)
        if gap < MARKER_WIDTH + 2:
            continue
        column = score_column - gap + (gap - MARKER_WIDTH) // 2
        row = top + ROW_SPLIT // 2 - 1
        if offense_id and team["id"] == offense_id:
            draw_possession_marker(sign.canvas, column, row, ink)
        elif game["state"] == "post" and team["winner"]:
            draw_winner_marker(sign.canvas, column, row, ink)


def yard_column(yards_from_away_goal):
    return round(PLAY_LEFT + yards_from_away_goal * YARD_PIXELS)


def draw_field(sign, colors, red_zone_side, elapsed):
    for band in range(10):
        start = yard_column(band * 10)
        end = PLAY_RIGHT if band == 9 else yard_column((band + 1) * 10) - 1
        fill_rect(sign.canvas, start, FIELD_TOP, end, FIELD_BOTTOM, TURF_LIGHT if band % 2 else TURF_DARK)
    for yards in range(10, 100, 10):
        column = yard_column(yards)
        graphics.DrawLine(sign.canvas, column, FIELD_TOP, column, FIELD_BOTTOM, graphics.Color(*(MIDFIELD_COLOR if yards == 50 else YARD_LINE_COLOR)))
    pulse = 0.55 + 0.45 * math.sin(2 * math.pi * elapsed / RED_ZONE_PERIOD)
    for side, color, x0, x1 in (("away", colors[0], PANEL_LEFT, PLAY_LEFT - 1), ("home", colors[1], PLAY_RIGHT + 1, PANEL_RIGHT)):
        zone = scale(color, ENDZONE_LEVEL)
        if side == red_zone_side:
            zone = scale(RED_ZONE_COLOR, 0.35 + 0.65 * pulse)
        fill_rect(sign.canvas, x0, FIELD_TOP, x1, FIELD_BOTTOM, zone)


def draw_direction_arrow(canvas, column, row, heading, color):
    pen = graphics.Color(*color)
    tail = column + heading * 2
    tip = column + heading * 6
    graphics.DrawLine(canvas, tail, row, tip, row, pen)
    graphics.DrawLine(canvas, tip - heading * 2, row - 2, tip, row, pen)
    graphics.DrawLine(canvas, tip - heading * 2, row + 2, tip, row, pen)


def draw_ball(sign, situation, offense, colors, heading):
    remaining = yards_to_goal(situation, offense["abbr"])
    if remaining is None:
        return
    yards_from_away_goal = remaining if heading < 0 else 100 - remaining
    column = min(PLAY_RIGHT, max(PLAY_LEFT, yard_column(yards_from_away_goal)))

    distance = situation.get("distance")
    if isinstance(distance, (int, float)) and 0 < distance <= remaining:
        marker = yard_column(yards_from_away_goal + heading * distance)
        if PLAY_LEFT < marker < PLAY_RIGHT:
            graphics.DrawLine(sign.canvas, marker, FIELD_TOP, marker, FIELD_BOTTOM, graphics.Color(*FIRST_DOWN_COLOR))

    scrimmage = emphasize(colors[0] if heading > 0 else colors[1])
    graphics.DrawLine(sign.canvas, column, FIELD_TOP, column, FIELD_BOTTOM, graphics.Color(*scrimmage))
    draw_direction_arrow(sign.canvas, column, ARROW_ROW, heading, scrimmage)
    middle = (FIELD_TOP + FIELD_BOTTOM) // 2
    fill_rect(sign.canvas, max(PLAY_LEFT, column - 1), middle - 1, min(PLAY_RIGHT, column + 1), middle, BALL_COLOR)


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
    draw_scoreboard(sign, game, colors, offense["id"] if offense else None)
    draw_field(sign, colors, red_zone_side, elapsed)
    if offense is not None:
        draw_ball(sign, situation, offense, colors, heading)

    stale = snapshot.get("status") == "cached" or now - snapshot.get("fetched_at", 0) >= STALE_AFTER
    clock, detail = info_lines(game, config, now)
    draw_centered(sign.canvas, sign.font46, 4, CLOCK_BASELINE, STALE_COLOR if stale else CLOCK_COLOR, clock)
    if detail:
        draw_centered(sign.canvas, sign.font46, 4, INFO_BASELINE, INFO_COLOR, detail)


def draw_nfl_frame(sign, snapshot, game_id, config, now, elapsed):
    if not snapshot:
        draw_message(sign, [("Loading...", INFO_COLOR)])
        return
    if snapshot.get("status") == "unavailable":
        draw_message(sign, [("No data", WARN_COLOR), ("Check network", INFO_COLOR)])
        return
    game = find_game(snapshot, game_id)
    if game is None:
        live = sum(1 for entry in snapshot.get("games") or [] if entry["state"] == "in")
        draw_message(sign, [("Pick a game", INFO_COLOR), (f"{live} live now" if live else "No games live", WARN_COLOR if not live else INFO_COLOR)])
        return
    draw_game(sign, game, snapshot, config, now, elapsed)


@__main__.planesign_mode_handler(DisplayMode.NFL)
def show_nfl(sign):
    while shared_config.shared_mode.value == DisplayMode.NFL.value:
        draw_nfl_frame(sign, shared_config.data_dict.get("nfl"), shared_config.data_dict.get("nfl_game_id"), shared_config.CONF.copy(), time.time(), time.monotonic())
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(FRAME_INTERVAL):
            return
