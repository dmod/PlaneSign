import logging
import math
import re
import time
import unicodedata
from datetime import datetime

import requests
import shared_config
import utilities
from modes import DisplayMode
from rgbmatrix import graphics

import __main__

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard"
REQUEST_TIMEOUT = (5, 15)
LIVE_TTL = 10
IDLE_TTL = 60
MAX_RETRY = 15 * 60
STALE_AFTER = 5 * 60
FRAME_INTERVAL = 0.05

PANEL_RIGHT = 38
ROW_SPLIT = 16
ABBR_COLUMN = 1
ABBR_BASELINE = 7
MARKER_COLUMN = 17
MARKER_ROW = 4
HITS_COLUMN = 1
HITS_BASELINE = 15
SCORE_WIDTH = 9
SCORE_RIGHT = 38
SCORE_BASELINE = 13

# Everything between the score cards and the field: game state, count, rotating detail.
MIDDLE_LEFT = 40
MIDDLE_RIGHT = 94
MIDDLE_WIDTH = MIDDLE_RIGHT - MIDDLE_LEFT + 1
COUNT_COLUMN = 40
COUNT_BASELINE = 23
OUTS_RIGHT = 94
OUTS_BASELINE = 21
DECISION_BASELINES = (17, 24)
INFO_LEFT = 40
# The field narrows to a wedge down by home plate, so the detail line can run in under it.
INFO_RIGHT = 103
INFO_BASELINE = 31
DETAIL_SECONDS = 3.5

BALL_CAPACITY = 3
STRIKE_CAPACITY = 2
OUT_CAPACITY = 3

# The infield is drawn as a real ballpark seen from above: a dirt skin bounded by the foul
# lines and the outfield arc, with the grass diamond, mound and home plate circle cut into it.
FIELD_LEFT = 96
FIELD_RIGHT = 126
FIELD_TOP = 0
FIELD_BOTTOM = 30
FIELD_CX = 111
HOME_ROW = 29
BASE_R = 12
MOUND_ROW = HOME_ROW - BASE_R
ARC_R = 15
GRASS_R = 9
HOME_DIRT_R = 4
MOUND_DIRT_R = 2
BASE_HALF = 1

SHIMMER_PERIOD = 7.0
SHIMMER_SWEEP = 0.38
SHIMMER_GAIN = 0.45
SHIMMER_WIDTH = 7.0

GRASS_DARK = (10, 58, 26)
GRASS_LIGHT = (15, 80, 37)
OUTFIELD_DARK = (8, 48, 22)
OUTFIELD_LIGHT = (12, 66, 30)
DIRT_COLOR = (132, 84, 48)
DIRT_LIGHT = (156, 104, 62)
DIRT_DARK = (108, 66, 38)
BASE_EMPTY_COLOR = (120, 120, 120)
BASE_RUNNER_COLOR = (255, 215, 60)
HOME_PLATE_COLOR = (238, 238, 238)
BALL_COUNT_COLOR = (60, 205, 95)
STRIKE_COUNT_COLOR = (245, 195, 60)
OUT_COUNT_COLOR = (238, 72, 56)
COUNT_DASH_COLOR = (120, 130, 140)
HITS_COLOR_LEVEL = 0.78
TITLE_COLOR = (225, 80, 80)
STATE_COLOR = (215, 230, 245)
STALE_COLOR = (255, 190, 90)
INFO_COLOR = (150, 200, 235)
WARN_COLOR = (240, 180, 90)
MATCHUP_COLOR = (205, 215, 230)
BATTING_COLOR = (250, 246, 235)
BATTING_SEAM_COLOR = (215, 60, 50)
WINNER_COLOR = (120, 225, 150)
DUE_UP_COLOR = (170, 170, 175)

NEXT_HEADER_BASELINE = 5
NEXT_BLOCK_TOP = 8
NEXT_BLOCK_BOTTOM = 23
NEXT_BLOCK_WIDTH = 50
NEXT_ABBR_BASELINE = 20
NEXT_DETAIL_BASELINE = 31

MIN_BLOCK_LUMINANCE = 0.09
MIN_TEAM_COLOR_DISTANCE = 60
WINNER_MARKER_WIDTH = 3
INNING_SUFFIXES = ("TH", "ST", "ND", "RD")
HALF_INNING = re.compile(r"^(top|bot|bottom|mid|middle|end)\b", re.IGNORECASE)
PITCHER_ROLES = (("winningPitcher", "WP"), ("losingPitcher", "LP"), ("save", "SV"))
MIDDLE_DECISIONS = 2
NOT_PLAYED_STATUSES = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_CANCELLED")


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


def parse_first_pitch(value):
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return None


def count_value(value, capacity):
    if isinstance(value, (int, float)) and value >= 0:
        return min(int(value), capacity)
    return 0


def team_record(competitor):
    for record in competitor.get("records") or []:
        if not isinstance(record, dict):
            continue
        if str(record.get("type") or "").lower() in ("total", "overall"):
            return str(record.get("summary") or "").strip()
    return ""


def ascii_text(value):
    """Flatten accents so names like Pena and venues like Estadio Harp Helu stay readable in the sign's ASCII fonts."""
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").strip()


def athlete_name(athlete):
    """Short, sign sized player name such as J.SMITH."""
    if not isinstance(athlete, dict):
        return ""
    name = ascii_text(athlete.get("shortName") or athlete.get("displayName") or athlete.get("fullName"))
    return re.sub(r"\.\s+", ".", name).upper()


def surname(name):
    """Family name only, for the narrow decision lines beside the diamond."""
    return name.rpartition(".")[2].strip() or name


def probable_pitcher(competitor):
    for probable in competitor.get("probables") or []:
        if not isinstance(probable, dict):
            continue
        name = athlete_name(probable.get("athlete"))
        if name:
            return {"name": name, "record": str(probable.get("record") or "").strip()}
    return None


def team_snapshot(competitor):
    team = competitor.get("team") or {}
    hits, errors = competitor.get("hits"), competitor.get("errors")
    return {
        "id": str(team.get("id") or ""),
        "abbr": str(team.get("abbreviation") or "")[:3].upper(),
        "name": str(team.get("displayName") or team.get("name") or ""),
        "score": parse_score(competitor.get("score")),
        "color": str(team.get("color") or ""),
        "alt_color": str(team.get("alternateColor") or ""),
        "winner": bool(competitor.get("winner")),
        "record": team_record(competitor),
        "hits": hits if isinstance(hits, int) else None,
        "errors": errors if isinstance(errors, int) else None,
        "probable": probable_pitcher(competitor),
    }


def venue_snapshot(competition):
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}
    city = ascii_text(address.get("city"))
    region = ascii_text(address.get("state") or address.get("country"))
    return {"name": ascii_text(venue.get("fullName")), "location": ", ".join(part for part in (city, region) if part), "indoor": bool(venue.get("indoor"))}


def broadcast_label(competition):
    names = []
    for broadcast in competition.get("broadcasts") or []:
        if not isinstance(broadcast, dict):
            continue
        if str(broadcast.get("market") or "").lower() not in ("national", ""):
            continue
        for name in broadcast.get("names") or []:
            name = str(name).strip()
            if name and name not in names:
                names.append(name)
    if not names:
        single = str(competition.get("broadcast") or "").strip()
        if single:
            names.append(single)
    return "/".join(names[:2]).upper()


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
    condition = str(weather.get("conditionId") or "").strip().upper()
    temperature = weather.get("temperature")
    if not isinstance(temperature, (int, float)):
        temperature = weather.get("highTemperature")
    if isinstance(temperature, (int, float)):
        return f"{condition} {round(temperature)}F".strip()
    return condition


def series_label(competition):
    """Postseason billing such as WORLD SERIES - GAME 5."""
    for note in competition.get("notes") or []:
        if isinstance(note, dict) and ascii_text(note.get("headline")):
            return ascii_text(note["headline"]).upper()
    return ""


def series_status(competition):
    """Where a postseason series stands, such as TOR LEADS SERIES 3-2."""
    series = competition.get("series")
    if isinstance(series, dict) and ascii_text(series.get("summary")):
        return ascii_text(series["summary"]).upper()
    return ""


def ordinal_inning(period):
    if not isinstance(period, int) or period <= 0:
        return ""
    suffix = INNING_SUFFIXES[0] if 11 <= period % 100 <= 13 else INNING_SUFFIXES[min(period % 10, 3) if period % 10 <= 3 else 0]
    return f"{period}{suffix}"


def half_inning(status_detail):
    """Which half of the inning the game sits in: top, mid, bot, end, or None."""
    match = HALF_INNING.match(str(status_detail).strip())
    if not match:
        return None
    half = match.group(1).lower()
    return {"bottom": "bot", "middle": "mid"}.get(half, half)


def state_text(status_type, state, period, half):
    """Short ballpark status line such as TOP 7TH, MID 3RD, FINAL/10 or RAIN DELAY."""
    inning = ordinal_inning(period)
    if state == "in" and half and inning:
        return f"{half.upper()} {inning}"
    detail = str(status_type.get("detail") or "").strip().upper()
    if detail:
        return detail
    return "IN PROGRESS" if state == "in" else "SCHEDULED"


def batting_side(state, half):
    """Side at the plate right now; mid and end of inning have nobody batting."""
    if state != "in":
        return None
    if half == "top":
        return "away"
    if half == "bot":
        return "home"
    return None


def due_up_side(half):
    """Side that comes to the plate once the break between half innings ends."""
    if half == "mid":
        return "home"
    if half == "end":
        return "away"
    return None


def situation_snapshot(competition):
    situation = competition.get("situation")
    if not isinstance(situation, dict):
        return None
    due_up = []
    for entry in situation.get("dueUp") or []:
        if isinstance(entry, dict):
            name = athlete_name(entry.get("athlete"))
            if name:
                due_up.append(name)
    return {
        "balls": count_value(situation.get("balls"), BALL_CAPACITY),
        "strikes": count_value(situation.get("strikes"), STRIKE_CAPACITY),
        "outs": count_value(situation.get("outs"), OUT_CAPACITY),
        "on_first": bool(situation.get("onFirst")),
        "on_second": bool(situation.get("onSecond")),
        "on_third": bool(situation.get("onThird")),
        "batter": athlete_name((situation.get("batter") or {}).get("athlete")),
        "pitcher": athlete_name((situation.get("pitcher") or {}).get("athlete")),
        "due_up": due_up[:2],
    }


def decisions(status):
    """Winning, losing and saving pitchers once a game is final."""
    featured = {}
    for entry in status.get("featuredAthletes") or []:
        if isinstance(entry, dict):
            featured[str(entry.get("name") or "")] = athlete_name(entry.get("athlete"))
    return [(label, featured[key]) for key, label in PITCHER_ROLES if featured.get(key)]


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
    state = str(status_type.get("state") or "pre")
    half = half_inning(status_type.get("detail")) if state == "in" else None
    if status_name in NOT_PLAYED_STATUSES:
        # A called off game was never played, so ESPN's zeroes are not a real score.
        for team in teams.values():
            team.update(score=None, hits=None, errors=None, winner=False)
    return {
        "id": str(event.get("id") or competition.get("id") or ""),
        "state": state,
        "status_detail": str(status_type.get("detail") or ""),
        "half": half,
        "state_text": state_text(status_type, state, period, half),
        "first_pitch": parse_first_pitch(event.get("date")),
        "home": teams["home"],
        "away": teams["away"],
        "situation": situation_snapshot(competition) if state == "in" else None,
        "decisions": decisions(status) if state == "post" else [],
        "venue": venue_snapshot(competition),
        "broadcast": broadcast_label(competition),
        "odds": odds_label(competition),
        "weather": weather_label(event),
        "series": series_label(competition),
        "series_status": series_status(competition),
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
    if payload["events"] and not games:
        raise ValueError("ESPN scoreboard contained no usable games")
    return games


class MLBCache:
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
            logging.info("ESPN MLB scoreboard: %s games (%s live) in %.2fs", len(games), sum(1 for game in games if game["state"] == "in"), time.monotonic() - started)
            return self.snapshot
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            self.failures += 1
            delay = min(MAX_RETRY, 15 * 2 ** min(self.failures - 1, 5))
            self.next_attempt = now + delay
            logging.warning("ESPN MLB scoreboard unavailable; retry in %ss: %s", delay, error)
            if self.snapshot:
                return {**self.snapshot, "status": "cached"}
            return {"games": [], "fetched_at": now, "status": "unavailable"}


def get_mlb_data_worker(data_dict):
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)
    with requests.Session() as session:
        cache = MLBCache(session)
        while not shared_config.shared_shutdown_event.is_set():
            payload = cache.poll(time.time(), active=shared_config.shared_mode.value == DisplayMode.MLB.value)
            if payload is not None:
                data_dict["mlb"] = payload
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


def first_pitch_label(timestamp, military, compact=False):
    if not timestamp:
        return "TBD"
    day = utilities.convert_unix_to_local_time(timestamp).strftime("%a")
    return f"{day.upper() if compact else day} {clock_label(timestamp, military, compact)}"


def is_today(timestamp, now):
    if not timestamp:
        return False
    return utilities.convert_unix_to_local_time(timestamp).date() == utilities.convert_unix_to_local_time(now).date()


def sort_key(game, now):
    first_pitch = game["first_pitch"] or 0
    if game["state"] == "in":
        return (0, first_pitch)
    if game["state"] == "pre" and is_today(game["first_pitch"], now):
        return (1, first_pitch)
    if game["state"] == "post":
        return (2, -first_pitch)
    return (3, first_pitch)


def score_text(team):
    return "-" if team["score"] is None else str(team["score"])


def game_label(game, military):
    away, home = game["away"], game["home"]
    if game["state"] == "pre":
        return f"{away['abbr']} @ {home['abbr']} - {first_pitch_label(game['first_pitch'], military)}"
    matchup = f"{away['abbr']} {score_text(away)} @ {home['abbr']} {score_text(home)}"
    return f"{matchup} - {game['status_detail'] or game['state_text']}"


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
    future = [game for game in scheduled if game["first_pitch"] and game["first_pitch"] >= now]
    return min(future or scheduled, key=lambda game: game["first_pitch"] or float("inf"))


def followed_game(snapshot, now):
    """Game to show when none is pinned: the live one, then the next matchup, then the last final."""
    games = (snapshot or {}).get("games") or []
    live = [game for game in games if game["state"] == "in"]
    if live:
        return min(live, key=lambda game: game["first_pitch"] or 0)
    upcoming = next_upcoming_game(snapshot, now)
    if upcoming:
        return upcoming
    finished = [game for game in games if game["state"] == "post"]
    if finished:
        return max(finished, key=lambda game: game["first_pitch"] or 0)
    return games[0] if games else None


def countdown_label(first_pitch, now):
    if not first_pitch:
        return "1ST PITCH TBD"
    remaining = int(first_pitch - now)
    if remaining <= 0:
        return "1ST PITCH ANY MIN"
    days, remainder = divmod(remaining, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"1ST PITCH {days}D {hours}H"
    if hours:
        return f"1ST PITCH {hours}H {minutes}M"
    if minutes:
        return f"1ST PITCH {minutes}M {seconds}S"
    return f"1ST PITCH {seconds}S"


def upcoming_first_pitch_label(game, now, military):
    if not game["first_pitch"]:
        return "TIME TBD"
    if is_today(game["first_pitch"], now):
        return f"TODAY {clock_label(game['first_pitch'], military)}"
    return first_pitch_label(game["first_pitch"], military).upper()


def upcoming_details(game, now):
    away, home, venue = game["away"], game["home"], game["venue"]
    details = [countdown_label(game["first_pitch"], now)]
    for team in (away, home):
        if team["probable"]:
            record = team["probable"]["record"]
            details.append(f"{team['abbr']} SP {team['probable']['name']} {record}".strip())
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


def error_label(game):
    away, home = game["away"]["errors"], game["home"]["errors"]
    if away is None or home is None or not (away or home):
        return ""
    return f"ERRORS {away}-{home}"


def live_details(game):
    situation = game["situation"] or {}
    details = []
    if situation.get("batter"):
        details.append(f"AB {situation['batter']}")
    if situation.get("pitcher"):
        details.append(f"P {situation['pitcher']}")
    for name in situation.get("due_up") or []:
        details.append(f"DUE {name}")
    if error_label(game):
        details.append(error_label(game))
    for team in (game["away"], game["home"]):
        if team["record"]:
            details.append(f"{team['abbr']} {team['record']}")
    if game["series_status"]:
        details.append(game["series_status"])
    return details


def decision_lines(game):
    """Winning and losing pitchers in box score shorthand, trimmed to the column beside the field."""
    room = MIDDLE_WIDTH // 4
    return [f"{label[0]} {surname(name)}"[:room] for label, name in game["decisions"][:MIDDLE_DECISIONS]]


def final_details(game, config):
    details = []
    if game["first_pitch"]:
        played = utilities.convert_unix_to_local_time(game["first_pitch"])
        details.append(f"{played.strftime('%a %-m/%-d').upper()} {clock_label(game['first_pitch'], military_time(config), compact=True)}")
    # The first decisions already have their own lines beside the field.
    for label, name in game["decisions"][MIDDLE_DECISIONS:]:
        details.append(f"{label} {name}")
    if error_label(game):
        details.append(error_label(game))
    if game["series_status"]:
        details.append(game["series_status"])
    if game["venue"]["name"]:
        details.append(game["venue"]["name"].upper())
    return details


def fill_rect(canvas, x0, y0, x1, y1, color):
    pen = graphics.Color(*color)
    for row in range(y0, y1 + 1):
        graphics.DrawLine(canvas, x0, row, x1, row, pen)


def draw_centered(canvas, font, width, baseline, color, text, left=MIDDLE_LEFT, right=MIDDLE_RIGHT):
    text = text.encode("ascii", "replace").decode("ascii")[: (right - left + 1) // width]
    column = left + (right - left + 1 - len(text) * width) // 2
    graphics.DrawText(canvas, font, column, baseline, graphics.Color(*color), text)


def draw_message(sign, lines):
    sign.canvas.Clear()
    draw_centered(sign.canvas, sign.fontbig, 6, 12, TITLE_COLOR, "MLB", 0, 127)
    for index, (text, color) in enumerate(lines):
        draw_centered(sign.canvas, sign.font57, 5, 22 + index * 9, color, text, 0, 127)


def draw_batting_marker(canvas, column, row, color, seam_color):
    """A baseball: a lit three pixel ball with a dimmer seam down its middle."""
    pen = graphics.Color(*color)
    graphics.DrawLine(canvas, column, row - 1, column + 2, row - 1, pen)
    graphics.DrawLine(canvas, column, row + 1, column + 2, row + 1, pen)
    canvas.SetPixel(column, row, *color)
    canvas.SetPixel(column + 2, row, *color)
    canvas.SetPixel(column + 1, row, *seam_color)


def draw_winner_marker(canvas, column, row, color):
    pen = graphics.Color(*color)
    for offset in range(WINNER_MARKER_WIDTH):
        graphics.DrawLine(canvas, column + offset, row - 2 + offset, column + offset, row + 2 - offset, pen)


def draw_team_panel(sign, team, color, top, marker):
    pen = graphics.Color(*text_color_for(color))
    fill_rect(sign.canvas, 0, top, PANEL_RIGHT, top + ROW_SPLIT - 1, color)
    graphics.DrawText(sign.canvas, sign.font57, ABBR_COLUMN, top + ABBR_BASELINE, pen, team["abbr"])
    if team["hits"] is not None:
        hits_pen = graphics.Color(*scale(text_color_for(color), HITS_COLOR_LEVEL))
        graphics.DrawText(sign.canvas, sign.font46, HITS_COLUMN, top + HITS_BASELINE, hits_pen, f"{team['hits']}H")
    score = score_text(team)
    graphics.DrawText(sign.canvas, sign.fontreallybig, SCORE_RIGHT - len(score) * SCORE_WIDTH + 1, top + SCORE_BASELINE, pen, score)
    if marker == "batting":
        draw_batting_marker(sign.canvas, MARKER_COLUMN, top + MARKER_ROW, BATTING_COLOR, BATTING_SEAM_COLOR)
    elif marker == "due":
        draw_batting_marker(sign.canvas, MARKER_COLUMN, top + MARKER_ROW, DUE_UP_COLOR, scale(DUE_UP_COLOR, 0.45))
    elif marker == "winner":
        draw_winner_marker(sign.canvas, MARKER_COLUMN, top + MARKER_ROW, WINNER_COLOR)


def draw_scoreboard(sign, game, colors, markers):
    for team, color, top, marker in ((game["away"], colors[0], 0, markers[0]), (game["home"], colors[1], ROW_SPLIT, markers[1])):
        draw_team_panel(sign, team, color, top, marker)


def draw_state(sign, text, color):
    """Game state in the largest font that fits, so RAIN DELAY never has to be clipped."""
    for font, width, baseline in ((sign.fontbig, 6, 10), (sign.font57, 5, 9), (sign.font46, 4, 8)):
        if len(text) * width <= MIDDLE_WIDTH:
            draw_centered(sign.canvas, font, width, baseline, color, text)
            return
    draw_centered(sign.canvas, sign.font46, 4, 8, color, text)


def draw_count(sign, situation):
    """Balls and strikes as a large count, with the outs called out beside it."""
    column = COUNT_COLUMN
    for text, color in ((str(situation["balls"]), BALL_COUNT_COLOR), ("-", COUNT_DASH_COLOR), (str(situation["strikes"]), STRIKE_COUNT_COLOR)):
        graphics.DrawText(sign.canvas, sign.fontreallybig, column, COUNT_BASELINE, graphics.Color(*color), text)
        column += SCORE_WIDTH
    outs = f"{situation['outs']} OUT"
    graphics.DrawText(sign.canvas, sign.font57, OUTS_RIGHT + 1 - len(outs) * 5, OUTS_BASELINE, graphics.Color(*OUT_COUNT_COLOR), outs)


def draw_decisions(sign, lines):
    for baseline, text in zip(DECISION_BASELINES, lines):
        draw_centered(sign.canvas, sign.font46, 4, baseline, INFO_COLOR, text)


def draw_base(canvas, cx, cy, color):
    fill_rect(canvas, cx - BASE_HALF, cy - BASE_HALF, cx + BASE_HALF, cy + BASE_HALF, color)


def grit(x, y):
    """Deterministic speckle so the skin reads as raked dirt instead of flat paint."""
    return (x * 7 + y * 13 + (x * y) % 5) % 7


def build_field():
    """Static ballpark pixels: (x, y, color, sheen axis), built once and reused every frame."""
    pixels = []
    for y in range(FIELD_TOP, FIELD_BOTTOM + 1):
        for x in range(FIELD_LEFT, FIELD_RIGHT + 1):
            offset, height = x - FIELD_CX, HOME_ROW - y
            fair = abs(offset) <= height
            from_mound = math.hypot(offset, y - MOUND_ROW)
            from_home = math.hypot(offset, y - HOME_ROW)
            if fair and from_mound <= ARC_R:
                # Inside the infield skin: the grass diamond is cut back out of the dirt.
                on_grass = abs(offset) + abs(y - MOUND_ROW) <= GRASS_R and from_mound > MOUND_DIRT_R and from_home > HOME_DIRT_R
                if on_grass:
                    color = GRASS_LIGHT if (y // 3) % 2 else GRASS_DARK
                else:
                    speckle = grit(x, y)
                    color = DIRT_LIGHT if speckle == 0 else DIRT_DARK if speckle == 1 else DIRT_COLOR
            elif from_home <= HOME_DIRT_R:
                color = DIRT_LIGHT if grit(x, y) == 0 else DIRT_COLOR
            elif fair:
                color = OUTFIELD_LIGHT if (y // 3) % 2 else OUTFIELD_DARK
            else:
                continue
            pixels.append((x, y, color, (x - FIELD_LEFT) + (FIELD_BOTTOM - y)))
    return tuple(pixels)


FIELD_PIXELS = None
FIELD_SPAN = (FIELD_RIGHT - FIELD_LEFT) + (FIELD_BOTTOM - FIELD_TOP)


def sheen(color, gain):
    return tuple(min(255, round(channel * (1 + gain))) for channel in color)


def shimmer_position(elapsed):
    """Where the light sweep sits, or None while it rests between passes."""
    phase = (elapsed % SHIMMER_PERIOD) / SHIMMER_PERIOD
    if phase > SHIMMER_SWEEP:
        return None
    return -SHIMMER_WIDTH + (phase / SHIMMER_SWEEP) * (FIELD_SPAN + 2 * SHIMMER_WIDTH)


def draw_field(sign, situation, elapsed):
    global FIELD_PIXELS
    if FIELD_PIXELS is None:
        FIELD_PIXELS = build_field()
    canvas = sign.canvas
    position = shimmer_position(elapsed)
    for x, y, color, axis in FIELD_PIXELS:
        if position is not None:
            distance = abs(axis - position)
            if distance < SHIMMER_WIDTH:
                canvas.SetPixel(x, y, *sheen(color, SHIMMER_GAIN * (1 - (distance / SHIMMER_WIDTH) ** 2)))
                continue
        canvas.SetPixel(x, y, *color)

    bases = ((FIELD_CX + BASE_R, MOUND_ROW, "on_first"), (FIELD_CX, MOUND_ROW - BASE_R, "on_second"), (FIELD_CX - BASE_R, MOUND_ROW, "on_third"))
    for cx, cy, key in bases:
        occupied = bool((situation or {}).get(key))
        draw_base(canvas, cx, cy, BASE_RUNNER_COLOR if occupied else BASE_EMPTY_COLOR)

    plate_pen = graphics.Color(*HOME_PLATE_COLOR)
    graphics.DrawLine(canvas, FIELD_CX - 1, HOME_ROW - 1, FIELD_CX + 1, HOME_ROW - 1, plate_pen)
    graphics.DrawLine(canvas, FIELD_CX - 1, HOME_ROW, FIELD_CX + 1, HOME_ROW, plate_pen)
    canvas.SetPixel(FIELD_CX, HOME_ROW + 1, *HOME_PLATE_COLOR)


def is_stale(snapshot, now):
    return snapshot.get("status") == "cached" or now - snapshot.get("fetched_at", 0) >= STALE_AFTER


def draw_game(sign, game, snapshot, config, now, elapsed):
    colors = resolve_team_colors(game["away"], game["home"])
    batting, due = batting_side(game["state"], game["half"]), due_up_side(game["half"])
    markers = []
    for side, team in (("away", game["away"]), ("home", game["home"])):
        if side == batting:
            markers.append("batting")
        elif side == due:
            markers.append("due")
        elif game["state"] == "post" and team["winner"]:
            markers.append("winner")
        else:
            markers.append(None)

    sign.canvas.Clear()
    draw_scoreboard(sign, game, colors, markers)
    draw_field(sign, game["situation"], elapsed)
    if game["state"] == "in" and game["situation"]:
        draw_count(sign, game["situation"])
    elif game["state"] == "post":
        draw_decisions(sign, decision_lines(game))

    draw_state(sign, game["state_text"], STALE_COLOR if is_stale(snapshot, now) else STATE_COLOR)
    details = final_details(game, config) if game["state"] == "post" else live_details(game)
    if details:
        draw_centered(sign.canvas, sign.font46, 4, INFO_BASELINE, INFO_COLOR, details[int(elapsed / DETAIL_SECONDS) % len(details)], INFO_LEFT, INFO_RIGHT)


def draw_upcoming(sign, game, snapshot, config, now, elapsed):
    colors = resolve_team_colors(game["away"], game["home"])
    sign.canvas.Clear()
    graphics.DrawText(sign.canvas, sign.font46, 1, NEXT_HEADER_BASELINE, graphics.Color(*TITLE_COLOR), "NEXT UP")
    first_pitch = upcoming_first_pitch_label(game, now, military_time(config))[:16]
    first_pitch_color = STALE_COLOR if is_stale(snapshot, now) else STATE_COLOR
    graphics.DrawText(sign.canvas, sign.font46, 128 - len(first_pitch) * 4, NEXT_HEADER_BASELINE, graphics.Color(*first_pitch_color), first_pitch)

    for team, color, left in ((game["away"], colors[0], 0), (game["home"], colors[1], 128 - NEXT_BLOCK_WIDTH)):
        right = left + NEXT_BLOCK_WIDTH - 1
        fill_rect(sign.canvas, left, NEXT_BLOCK_TOP, right, NEXT_BLOCK_BOTTOM, color)
        draw_centered(sign.canvas, sign.fontbig, 6, NEXT_ABBR_BASELINE, text_color_for(color), team["abbr"], left, right)
    draw_centered(sign.canvas, sign.fontbig, 6, NEXT_ABBR_BASELINE, MATCHUP_COLOR, "@", NEXT_BLOCK_WIDTH, 127 - NEXT_BLOCK_WIDTH)

    details = upcoming_details(game, now)
    detail = details[int(elapsed / DETAIL_SECONDS) % len(details)]
    draw_centered(sign.canvas, sign.font46, 4, NEXT_DETAIL_BASELINE, INFO_COLOR, detail, 0, 127)


def draw_mlb_frame(sign, snapshot, game_id, config, now, elapsed):
    if not snapshot:
        draw_message(sign, [("Loading...", INFO_COLOR)])
        return
    if snapshot.get("status") == "unavailable":
        draw_message(sign, [("No data", WARN_COLOR), ("Check network", INFO_COLOR)])
        return
    game = find_game(snapshot, game_id) or followed_game(snapshot, now)
    if game is None:
        draw_message(sign, [("No games today", INFO_COLOR)])
        return
    if game["state"] == "pre":
        # An empty diamond says less than the matchup that is coming.
        draw_upcoming(sign, game, snapshot, config, now, elapsed)
        return
    draw_game(sign, game, snapshot, config, now, elapsed)


@__main__.planesign_mode_handler(DisplayMode.MLB)
def show_mlb(sign):
    while shared_config.shared_mode.value == DisplayMode.MLB.value:
        draw_mlb_frame(sign, shared_config.data_dict.get("mlb"), shared_config.data_dict.get("mlb_game_id"), shared_config.CONF.copy(), time.time(), time.monotonic())
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(FRAME_INTERVAL):
            return
