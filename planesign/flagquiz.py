import csv
import math
import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import games
import numpy as np
import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image, ImageDraw, ImageEnhance
from rgbmatrix import graphics
from utilities import fix_black, rainbow_pen_color

ROUND_SECONDS = 10
EXPERT_ROUND_SECONDS = 20
QUESTION_LIMIT = 5
SUDDEN_DEATH_NOTICE_SECONDS = 3
START_COUNTDOWN_SECONDS = 3
WIDTH = 128
HEIGHT = 32
FIREWORK_SLOT_SECONDS = 0.7
FIREWORK_CHANCE = 0.9
FIREWORK_FINALE_PERIOD = 75
FIREWORK_FINALE_SECONDS = 7
FIREWORK_MAX_SECONDS = 4.2
FIREWORK_HORIZON = HEIGHT - 1
FIREWORK_COLORS = ((255, 40, 40), (255, 190, 40), (40, 255, 90), (60, 130, 255), (200, 80, 255), (255, 255, 255), (255, 110, 200), (40, 230, 255))
PERFECT_FIREWORK_COLORS = ((255, 188, 50), (255, 218, 90), (255, 244, 180), (255, 255, 255))
FIREWORK_WILLOW = (255, 176, 70)
FIREWORK_GLITTER = (255, 244, 210)
FIREWORK_ROCKET = (255, 214, 150)
FLAG_GAME_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datafiles", "flag_game.csv")
FLAG_IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons", "flags")
DIFFICULTIES = {"easy": 3, "hard": 4, "expert": 0}
DIFFICULTY_LEVELS = {"easy": 0, "hard": 1, "expert": 2}
LOADING_FLAG_HEIGHT = 10
FIREWORK_X, FIREWORK_Y = np.meshgrid(np.arange(WIDTH, dtype=np.float32), np.arange(HEIGHT, dtype=np.float32))


@dataclass(frozen=True, eq=False)
class QuizFireworkShell:
    launch: float
    rise: float
    origin: float
    burst: tuple[float, float]
    kind: str
    life: float
    gravity: float
    radius: float
    salt: int
    angles: np.ndarray
    speeds: np.ndarray
    colors: np.ndarray


class FlagQuizConflict(ValueError):
    pass


@lru_cache(maxsize=1)
def load_countries():
    countries = []
    seen_codes = set()
    with open(FLAG_GAME_FILE, newline="", encoding="utf-8") as csv_file:
        for line, row in enumerate(csv.reader(csv_file), 1):
            if not row or not row[0].strip() or row[0].lstrip().startswith("#"):
                continue
            if len(row) != 3:
                raise ValueError(f"Invalid flag quiz CSV row {line}: expected 3 columns")
            code, name, difficulty = (value.strip() for value in row)
            code = normalize_country_code(code)
            difficulty = difficulty.casefold()
            if not code or not name or code in seen_codes:
                raise ValueError(f"Invalid or duplicate flag quiz entry on row {line}")
            if difficulty not in DIFFICULTY_LEVELS:
                raise ValueError(f"Invalid flag quiz difficulty on row {line}: expected Easy, Hard, or Expert")
            if not os.path.isfile(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")):
                raise FileNotFoundError(f"Flag image not found for {code} (CSV row {line})")
            seen_codes.add(code)
            countries.append({"code": code, "name": name, "difficulty": difficulty})
    if not countries:
        raise ValueError("Flag quiz data contains no countries")
    return tuple(countries)


def normalize_country_code(code):
    if code.casefold().startswith("states/"):
        return "states/" + code.split("/", 1)[1].upper()
    return code.upper()


def normalize_country_tokens(value):
    value = value.casefold()
    replacements = (
        (r"\bislands?\b|\bis\.(?!\w)", "island"),
        (r"\bterritor(?:y|ies)\b|\bterr\.(?!\w)", "territory"),
        (r"\bsouth\b|\bs\.(?!\w)", "south"),
        (r"\bsa?int\b|\bst\.(?!\w)", "saint"),
        (r"\brep\.(?!\w)", "republic"),
        (r"\bprin\.(?!\w)", "principality"),
        (r"\bcabo\b", "cape"),
        (r"\bcote\b", "coast"),
        (r"\b(?:d')?ivoire\b", "ivory"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return re.findall(r"[^\W_]+", value, flags=re.UNICODE)


def get_country_suggestions(query, limit=20):
    query_tokens = normalize_country_tokens(query)
    if not query_tokens:
        return []

    suggestions = []
    for country in load_countries():
        country_tokens = normalize_country_tokens(country["name"])
        if all(any(token.startswith(query_token) for token in country_tokens) for query_token in query_tokens):
            suggestions.append({"code": country["code"], "name": country["name"]})
            if len(suggestions) == limit:
                break
    return suggestions


def _country_pool(difficulty):
    if difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, hard, or expert")
    max_level = DIFFICULTY_LEVELS[difficulty]
    return tuple(country for country in load_countries() if DIFFICULTY_LEVELS[country["difficulty"]] <= max_level)


def _make_question(code, difficulty, pool):
    country_by_code = {country["code"]: country for country in pool}
    correct = country_by_code[code]
    option_count = DIFFICULTIES[difficulty]
    if not option_count:
        return {"code": correct["code"], "name": correct["name"], "options": []}

    correct_name = correct["name"].casefold()
    distractors = []
    distractor_names = {correct_name}
    for country in pool:
        name = country["name"].casefold()
        if country["code"] != code and name not in distractor_names:
            distractors.append(country)
            distractor_names.add(name)
    if len(distractors) < option_count - 1:
        raise ValueError(f"Not enough distinct country names for {difficulty} mode")

    options = [correct, *random.sample(distractors, option_count - 1)]
    random.shuffle(options)
    return {
        "code": correct["code"],
        "name": correct["name"],
        "options": [{"key": chr(ord("A") + index), "code": country["code"], "name": country["name"]} for index, country in enumerate(options)],
    }


def _round_seconds(difficulty):
    return EXPERT_ROUND_SECONDS if difficulty == "expert" else ROUND_SECONDS


def select_difficulty(difficulty):
    if not isinstance(difficulty, str) or difficulty.casefold() not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, hard, or expert")
    difficulty = difficulty.casefold()
    with shared_config.shared_games_lock:
        shared_config.data_dict["flagquiz_selected_difficulty"] = difficulty
    return {"ok": True, "difficulty": difficulty}


def start_game(difficulty, player_id):
    difficulty = difficulty.casefold() if isinstance(difficulty, str) else difficulty
    pool = _country_pool(difficulty)
    option_count = DIFFICULTIES[difficulty]
    if option_count and len({country["name"].casefold() for country in pool}) < option_count:
        raise ValueError(f"Not enough unique countries for {difficulty} mode")

    player = games.register_player(player_id)
    question_codes = [country["code"] for country in pool]
    random.shuffle(question_codes)
    regular_question_count = min(QUESTION_LIMIT, len(question_codes))
    now = time.monotonic()
    players = games.get_players()
    scores = {pid: 0 for pid, record in players.items() if now - record["last_seen"] < games.ACTIVE_PLAYER_SECONDS}
    scores[player["id"]] = 0
    countdown_until = now + START_COUNTDOWN_SECONDS
    firework_seed = random.randrange(2**32)
    victory_flag_codes = [country["code"] for country in load_countries()]
    random.shuffle(victory_flag_codes)

    state = {
        "difficulty": difficulty,
        "question_codes": question_codes,
        "regular_question_count": regular_question_count,
        "index": 0,
        "round_id": None,
        "deadline": None,
        "current": None,
        "countdown_until": countdown_until,
        "answers": {},
        "scores": scores,
        "attempts": {player_id: 0 for player_id in scores},
        "last_result": None,
        "sudden_death": False,
        "sudden_death_notice_until": None,
        "winner_id": None,
        "tie": False,
        "end_requested": False,
        "firework_seed": firework_seed,
        "victory_flag_codes": victory_flag_codes,
    }
    with shared_config.shared_games_lock:
        shared_config.data_dict["flagquiz_selected_difficulty"] = difficulty
        shared_config.data_dict["flagquiz_state"] = state
        shared_config.shared_mode.value = DisplayMode.FLAGQUIZ.value
        shared_config.shared_forced_sign_update.set()
    return {"ok": True, "difficulty": difficulty, "total": regular_question_count}


def _unique_leader_id(scores):
    if not scores:
        return None
    highest_score = max(scores.values())
    leaders = [player_id for player_id, score in scores.items() if score == highest_score]
    return leaders[0] if len(leaders) == 1 else None


def _finish_game(state):
    state["current"] = None
    state["countdown_until"] = None
    state["deadline"] = None
    state["round_id"] = None
    state["sudden_death_notice_until"] = None
    state["winner_id"] = _unique_leader_id(state["scores"])
    state["tie"] = state["winner_id"] is None


def _start_first_question(state, now):
    state["countdown_until"] = None
    state["round_id"] = uuid.uuid4().hex
    state["deadline"] = now + _round_seconds(state["difficulty"])
    state["current"] = _make_question(
        state["question_codes"][state["index"]],
        state["difficulty"],
        _country_pool(state["difficulty"]),
    )


def _start_next_question(state, now):
    if state["index"] >= len(state["question_codes"]):
        state["current"] = None
        state["deadline"] = None
        state["round_id"] = None
        state["sudden_death_notice_until"] = None
        state["tie"] = True
        return

    state["round_id"] = uuid.uuid4().hex
    state["deadline"] = now + _round_seconds(state["difficulty"])
    state["current"] = _make_question(
        state["question_codes"][state["index"]],
        state["difficulty"],
        _country_pool(state["difficulty"]),
    )
    state["sudden_death_notice_until"] = None


def _advance(state, now, players, active_ids, timed_out):
    current = state["current"]
    result_player_ids = state["scores"] if timed_out else active_ids
    result_answers = []
    for player_id in result_player_ids:
        answer = state["answers"].get(player_id)
        player = players.get(player_id, {})
        result_answers.append({
            "id": player_id,
            "name": player.get("name", "Player"),
            "correct": bool(answer and answer["correct"]),
            "answered": answer is not None,
        })
    result_answers.sort(key=lambda answer: (answer["name"].casefold(), answer["id"]))
    state["last_result"] = {
        "question_number": state["index"] + 1,
        "round_id": state["round_id"],
        "code": current["code"],
        "correct_name": current["name"],
        "timed_out": timed_out,
        "answers": result_answers,
    }
    state["index"] += 1
    attempts = state.setdefault("attempts", {})
    for player_id in state["scores"]:
        attempts[player_id] = attempts.get(player_id, 0) + 1
    state["answers"] = {}
    state["round_id"] = None
    state["deadline"] = None

    if state.get("end_requested"):
        _finish_game(state)
        return

    if state["index"] >= state["regular_question_count"]:
        leader_id = _unique_leader_id(state["scores"])
        if leader_id is not None:
            state["current"] = None
            state["winner_id"] = leader_id
            state["tie"] = False
            return
        if state["index"] == state["regular_question_count"]:
            if state["index"] < len(state["question_codes"]):
                state["sudden_death"] = True
                state["sudden_death_notice_until"] = now + SUDDEN_DEATH_NOTICE_SECONDS
                state["current"] = None
                return
            state["current"] = None
            state["tie"] = True
            return
        if state["index"] >= len(state["question_codes"]):
            state["current"] = None
            state["tie"] = True
            return

    _start_next_question(state, now)


def _advance_if_ready(state, players, now):
    if state["current"] is None:
        countdown_until = state.get("countdown_until")
        if countdown_until is not None:
            if now >= countdown_until:
                _start_first_question(state, now)
                return True
            return False
        notice_until = state.get("sudden_death_notice_until")
        if notice_until is not None and now >= notice_until:
            _start_next_question(state, now)
            return True
        return False

    active_ids = [
        player_id for player_id in state["scores"]
        if player_id in players and now - players[player_id]["last_seen"] < games.ACTIVE_PLAYER_SECONDS
    ]
    timed_out = now >= state["deadline"]
    all_active_answered = bool(active_ids) and all(player_id in state["answers"] for player_id in active_ids)
    if timed_out or all_active_answered:
        _advance(state, now, players, active_ids, timed_out)
        return True
    return False


def _player_summary(players, scores, now):
    active_ids = {
        player_id for player_id, player in players.items()
        if now - player["last_seen"] < games.ACTIVE_PLAYER_SECONDS
    }
    scoreboard = [
        {"id": player_id, "name": players.get(player_id, {}).get("name", "Player"), "score": score, "active": player_id in active_ids}
        for player_id, score in scores.items()
    ]
    scoreboard.sort(key=lambda player: (-player["score"], player["name"].casefold()))
    return scoreboard


def _public_status(state, player_id, players, now):
    current = state["current"]
    scores = dict(state["scores"])
    answers = dict(state["answers"])
    current_public = None
    seconds_left = 0
    if current is not None:
        current_public = {
            "code": current["code"],
            "options": [{"key": option["key"], "name": option["name"]} for option in current["options"]],
        }
        seconds_left = max(0, math.ceil(state["deadline"] - now))
    notice_until = state.get("sudden_death_notice_until")
    notice_seconds = max(0, math.ceil(notice_until - now)) if notice_until is not None else 0
    countdown_until = state.get("countdown_until")
    countdown = max(1, math.ceil(countdown_until - now)) if countdown_until is not None else None
    winner = _winner_summary(state, players, now)
    complete = current is None and notice_until is None and countdown_until is None

    return {
        "ok": True,
        "difficulty": state["difficulty"],
        "question_number": state["index"] + 1 if current is not None else state["index"],
        "total": state["regular_question_count"],
        "round_id": state["round_id"],
        "seconds_left": seconds_left,
        "complete": complete,
        "in_progress": not complete,
        "countdown": countdown,
        "end_requested": state.get("end_requested", False),
        "sudden_death": state["sudden_death"],
        "sudden_death_notice": notice_until is not None,
        "notice_seconds": notice_seconds,
        "tie": state["tie"],
        "winner": winner,
        "current": current_public,
        "your_answer": answers.get(player_id),
        "round_answers": [
            {"id": answer_id, "correct": answer["correct"]}
            for answer_id, answer in answers.items()
        ],
        "last_result": state["last_result"],
        "players": _player_summary(players, scores, now),
    }


def _winner_summary(state, players, now):
    winner_id = state.get("winner_id")
    if winner_id is None:
        return None
    player = players.get(winner_id, {})
    attempts = state.get("attempts", {}).get(winner_id, 0)
    score = state["scores"].get(winner_id, 0)
    return {
        "id": winner_id,
        "name": player.get("name", "Player"),
        "score": score,
        "active": winner_id in players and now - players[winner_id]["last_seen"] < games.ACTIVE_PLAYER_SECONDS,
        "accuracy": round(score * 100 / attempts) if attempts else 0,
    }


def get_game_status(player_id, player_name=None):
    player = games.register_player(player_id, player_name)
    now = time.monotonic()
    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        state = shared_config.data_dict.get("flagquiz_state")
        selected_difficulty = shared_config.data_dict.get("flagquiz_selected_difficulty")
        if state is None:
            active_players = {
                player_id: 0
                for player_id, record in players.items()
                if now - record["last_seen"] < games.ACTIVE_PLAYER_SECONDS
            }
            return {
                "ok": True,
                "difficulty": None,
                "selected_difficulty": selected_difficulty,
                "complete": False,
                "in_progress": False,
                "current": None,
                "players": _player_summary(players, active_players, now),
                "player": player,
            }

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        state["scores"].setdefault(player["id"], 0)
        state["attempts"].setdefault(player["id"], 0)
        _advance_if_ready(state, players, now)
        shared_config.data_dict["flagquiz_state"] = state
        status = _public_status(state, player["id"], players, now)
        status["selected_difficulty"] = selected_difficulty
        status["player"] = player
        return status


def end_game():
    now = time.monotonic()
    with shared_config.shared_games_lock:
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None:
            raise FlagQuizConflict("There is no flag quiz to end")

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        players = dict(shared_config.data_dict.get("game_players", {}))
        if state["current"] is None:
            if state.get("winner_id") is None and not state.get("tie"):
                _finish_game(state)
        else:
            state["end_requested"] = True
            _advance_if_ready(state, players, now)
        shared_config.data_dict["flagquiz_state"] = state
        shared_config.shared_forced_sign_update.set()
        return {"ok": True, "end_requested": state.get("end_requested", False)}


def submit_answer(player_id, round_id, answer):
    player = games.register_player(player_id)
    now = time.monotonic()
    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None or state["current"] is None:
            raise FlagQuizConflict("There is no active flag quiz question")

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        state["scores"].setdefault(player["id"], 0)
        state["attempts"].setdefault(player["id"], 0)
        _advance_if_ready(state, players, now)
        if round_id != state["round_id"]:
            shared_config.data_dict["flagquiz_state"] = state
            raise FlagQuizConflict("This question has ended; load the current question and try again")
        if player["id"] in state["answers"]:
            raise FlagQuizConflict("You have already answered this question")

        current = state["current"]
        if state["difficulty"] == "expert":
            valid_answer = isinstance(answer, str) and any(country["code"] == answer for country in _country_pool("expert"))
            if not valid_answer:
                raise ValueError("Select a country from the suggestions")
            correct = answer == current["code"]
        else:
            option = next((option for option in current["options"] if option["key"] == answer), None)
            if option is None:
                raise ValueError("Select one of the displayed answers")
            correct = option["code"] == current["code"]

        state["answers"][player["id"]] = {
            "name": player["name"],
            "correct": correct,
            "answer": answer,
        }
        if correct:
            state["scores"][player["id"]] += 1
        _advance_if_ready(state, players, now)
        shared_config.data_dict["flagquiz_state"] = state
        return {"ok": True, "correct": correct, "question_number": state["index"] + (1 if state["current"] else 0)}


def get_sign_state():
    now = time.monotonic()
    with shared_config.shared_games_lock:
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None:
            return {
                "difficulty": None,
                "selected_difficulty": shared_config.data_dict.get("flagquiz_selected_difficulty"),
                "question_number": 0,
                "total": 0,
                "current": None,
                "countdown": None,
                "complete": False,
            }

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        players = dict(shared_config.data_dict.get("game_players", {}))
        if _advance_if_ready(state, players, now):
            shared_config.data_dict["flagquiz_state"] = state
        notice_until = state.get("sudden_death_notice_until")
        countdown_until = state.get("countdown_until")
        return {
            "difficulty": state["difficulty"],
            "selected_difficulty": shared_config.data_dict.get("flagquiz_selected_difficulty"),
            "question_number": state["index"] + 1 if state["current"] is not None else state["index"],
            "total": state["regular_question_count"],
            "current": state["current"],
            "time_remaining_fraction": (
                max(0.0, min(1.0, (state["deadline"] - now) / _round_seconds(state["difficulty"])))
                if state["current"] is not None and state["deadline"] is not None
                else 0.0
            ),
            "countdown": max(1, math.ceil(countdown_until - now)) if countdown_until is not None else None,
            "complete": state["current"] is None and notice_until is None and countdown_until is None,
            "sudden_death": state["sudden_death"],
            "sudden_death_notice": notice_until is not None,
            "tie": state["tie"],
            "end_requested": state.get("end_requested", False),
            "winner": _winner_summary(state, players, now),
            "attempts": state["attempts"],
            "firework_seed": state.get("firework_seed", 0),
            "victory_flag_codes": state["victory_flag_codes"],
        }


@lru_cache(maxsize=1)
def _flag_image(code):
    with Image.open(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")) as image:
        image = image.convert("RGB")
        if code != "NPL" and code != "states/OH":
            image = fix_black(image)
        return image


@lru_cache(maxsize=1)
def _loading_flag_rows():
    countries = load_countries()
    rows = []
    for row_index in range(3):
        flags = []
        width = 0
        phase = 0
        while width < WIDTH * 2:
            country = random.choice(countries)
            source = _flag_image(country["code"])
            flag_width = round(source.width * LOADING_FLAG_HEIGHT / source.height)
            flag = source.resize((flag_width, LOADING_FLAG_HEIGHT), Image.Resampling.LANCZOS)
            flags.append(flag)
            if row_index == 1 and not phase:
                phase = flag.width // 2
            width += flag.width
        row = Image.new("RGB", (width, LOADING_FLAG_HEIGHT), (0, 0, 0))
        x = 0
        for flag in flags:
            row.paste(flag, (x, 0))
            x += flag.width
        rows.append((ImageEnhance.Brightness(row).enhance(0.28), phase))
    return tuple(rows)


def _draw_scrolling_flags(sign, elapsed):
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    offset = int(elapsed * 2.0)
    for row_index, (row, phase) in enumerate(_loading_flag_rows()):
        row_offset = (offset + phase) % row.width
        y = 1 + row_index * LOADING_FLAG_HEIGHT
        first_width = min(WIDTH, row.width - row_offset)
        image.paste(row.crop((row_offset, 0, row_offset + first_width, row.height)), (0, y))
        if first_width < WIDTH:
            image.paste(row.crop((0, 0, WIDTH - first_width, row.height)), (first_width, y))
    sign.canvas.SetImage(image, 0, 0)


def _draw_outlined_text(sign, font, text, x, baseline, color):
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx or dy:
                graphics.DrawText(sign.canvas, font, x + dx, baseline + dy, graphics.Color(0, 0, 0), text)
    graphics.DrawText(sign.canvas, font, x, baseline, color, text)


def _draw_loading(sign, elapsed, selected_difficulty=None):
    _draw_scrolling_flags(sign, elapsed)
    text = f"{selected_difficulty.upper()} MODE" if selected_difficulty else "CHOOSE LEVEL"
    x = (WIDTH - len(text) * 6) // 2
    _draw_outlined_text(sign, sign.fontbig, text, x, 19, graphics.Color(46, 210, 255))


def _draw_countdown(sign, countdown):
    text = f"{countdown}..."
    x = (WIDTH - len(text) * 9) // 2
    _draw_outlined_text(sign, sign.fontreallybig, text, x, 24, graphics.Color(255, 225, 90))


@lru_cache(maxsize=32)
def _firework_shells(slot, seed, perfect=False):
    rng = random.Random(seed * 2741 + slot * 48611 + 31)
    start = slot * FIREWORK_SLOT_SECONDS
    finale = start % FIREWORK_FINALE_PERIOD >= FIREWORK_FINALE_PERIOD - FIREWORK_FINALE_SECONDS
    if perfect:
        count = rng.choice((2, 3, 3, 4)) if finale else rng.choice((1, 2, 2, 3))
    else:
        count = rng.choice((1, 2, 2, 3)) if finale else int(rng.random() < FIREWORK_CHANCE)
    colors_available = PERFECT_FIREWORK_COLORS if perfect else FIREWORK_COLORS
    shells = []
    for _ in range(count):
        kind = rng.choice(("peony", "peony", "ring", "willow", "crackle"))
        radius = rng.uniform(5.5, 8.5) if perfect and kind != "ring" else rng.uniform(4.5, 7.5) if kind != "ring" else rng.uniform(5, 7)
        burst = (rng.uniform(10, 118), rng.uniform(radius + 5, 15))
        stars = round(radius * (3.6 if kind != "ring" else 2.8))
        angles = np.array([math.tau * (index + rng.uniform(-0.25, 0.25)) / stars for index in range(stars)], dtype=np.float32)
        if kind == "ring":
            speeds = np.full(stars, radius, dtype=np.float32)
        else:
            speeds = np.array([radius * (rng.uniform(0.85, 1.05) if rng.random() < 0.7 else rng.uniform(0.35, 0.65)) for _ in range(stars)], dtype=np.float32)
        outer, inner = rng.sample(colors_available, 2)
        if kind == "willow":
            willow = (255, 214, 110) if perfect else FIREWORK_WILLOW
            colors = np.tile(np.array(willow, dtype=np.float32) / 255, (stars, 1))
        else:
            colors = np.where((speeds < radius * 0.7)[:, None], np.array(inner, dtype=np.float32) / 255, np.array(outer, dtype=np.float32) / 255)
        life = rng.uniform(2.4, 2.9) if kind == "willow" else rng.uniform(1.5, 2.1)
        shells.append(QuizFireworkShell(
            launch=start + rng.uniform(0, FIREWORK_SLOT_SECONDS),
            rise=rng.uniform(0.7, 1.1),
            origin=burst[0] + rng.uniform(-4, 4),
            burst=burst,
            kind=kind,
            life=life,
            gravity=3.2 if kind == "willow" else 1.4,
            radius=radius,
            salt=rng.randrange(2**30),
            angles=angles,
            speeds=speeds,
            colors=colors,
        ))
    return tuple(shells)


def _firework_hash(*values):
    value = 2166136261
    for item in values:
        value = ((value ^ (item & 0xFFFFFFFF)) * 16777619) & 0xFFFFFFFF
    value ^= value >> 15
    value = (value * 2246822519) & 0xFFFFFFFF
    value ^= value >> 13
    return value / 2**32


def _splat_firework(light, xs, ys, colors, weights):
    columns, rows = np.rint(xs).astype(int), np.rint(ys).astype(int)
    keep = (columns >= 0) & (columns < WIDTH) & (rows >= 0) & (rows < HEIGHT) & (weights > 0.004)
    np.add.at(light, (rows[keep], columns[keep]), colors[keep] * weights[keep, None])


def _firework_light(elapsed, seed, perfect=False):
    light = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float32)
    for slot in range(math.floor((elapsed - FIREWORK_MAX_SECONDS) / FIREWORK_SLOT_SECONDS), math.floor(elapsed / FIREWORK_SLOT_SECONDS) + 1):
        for shell in _firework_shells(slot, seed, perfect):
            age = elapsed - shell.launch
            if not 0 <= age < shell.rise + shell.life:
                continue
            burst_x, burst_y = shell.burst
            if age < shell.rise:
                for back, weight in ((0, 0.9), (0.05, 0.45), (0.1, 0.22), (0.15, 0.1)):
                    progress = max(0, age - back) / shell.rise
                    climb = 1 - (1 - progress) ** 2
                    x = shell.origin + (burst_x - shell.origin) * climb + math.sin(age * 23 + shell.salt) * 0.4
                    y = FIREWORK_HORIZON + (burst_y - FIREWORK_HORIZON) * climb
                    _splat_firework(
                        light,
                        np.array([x]),
                        np.array([y]),
                        np.array([FIREWORK_ROCKET], dtype=np.float32) / 255,
                        np.array([weight]),
                    )
                continue

            age -= shell.rise
            fade = 1.0 if age < 0.15 else max(0.0, 1 - (age - 0.15) / (shell.life - 0.15)) ** 1.3
            heat = max(0.0, 1 - age / 0.2)
            colors = shell.colors + (1 - shell.colors) * heat * 0.8
            glow = 0.42 * math.exp(-age / 0.3)
            if glow > 0.01:
                distance = (FIREWORK_X - burst_x) ** 2 + (FIREWORK_Y - burst_y) ** 2
                tint = shell.colors.mean(axis=0) * 0.6 + 0.4
                light += np.exp(-distance / (2 * (shell.radius * 1.3) ** 2))[..., None] * tint * glow

            trail = 6 if shell.kind == "willow" else 3
            for step in range(trail + 1):
                particle_age = age - step * 0.05
                if particle_age < 0:
                    break
                reach = shell.speeds * (1 - math.exp(-particle_age / 0.28))
                xs = burst_x + reach * np.cos(shell.angles)
                ys = burst_y + reach * np.sin(shell.angles) * 0.9 + shell.gravity * particle_age * particle_age
                weights = np.full(len(xs), fade * (0.72 if shell.kind == "willow" else 0.5) ** step, dtype=np.float32)
                if shell.kind == "crackle" and age > shell.life * 0.45:
                    flicker = np.array([
                        _firework_hash(shell.salt, index, math.floor(elapsed * 16))
                        for index in range(len(xs))
                    ], dtype=np.float32)
                    glitter = np.array(FIREWORK_GLITTER, dtype=np.float32) / 255
                    _splat_firework(light, xs, ys, np.tile(glitter, (len(xs), 1)), weights * (flicker > 0.45) * 1.3)
                    continue
                _splat_firework(light, xs, ys, colors, weights)
            if age < 0.08:
                _splat_firework(
                    light,
                    np.array([burst_x]),
                    np.array([burst_y]),
                    np.ones((1, 3), dtype=np.float32),
                    np.array([1.0]),
                )
    return light


def _draw_fireworks(image, elapsed, seed, perfect=False):
    light = np.clip(_firework_light(elapsed, seed, perfect), 0, 1)
    base = np.asarray(image, dtype=np.float32) / 255
    composited = base * (1 - light.max(axis=-1, keepdims=True)) + light
    image.paste(Image.fromarray(np.round(composited * 255).astype(np.uint8), "RGB"))


@lru_cache(maxsize=256)
def _resized_winner_flag(code):
    source = _flag_image(code)
    width = max(1, round(source.width * 10 / source.height))
    return source.resize((width, 10), Image.Resampling.LANCZOS)


def _draw_raising_flag(draw, elapsed, flag_codes, ornate=False):
    pole_x = 3
    pole_color = (212, 164, 52) if ornate else (150, 150, 165)
    draw.line((pole_x, 0, pole_x, HEIGHT - 1), fill=pole_color)
    if ornate:
        draw.line((pole_x - 1, 4, pole_x - 1, HEIGHT - 1), fill=(255, 220, 100))
        draw.line((pole_x + 1, 4, pole_x + 1, HEIGHT - 1), fill=(112, 78, 28))
        for band_y in (8, 16, 24):
            draw.point((pole_x - 1, band_y), fill=(255, 236, 150))
            draw.point((pole_x, band_y), fill=(255, 196, 55))
            draw.point((pole_x + 1, band_y), fill=(150, 102, 30))
        draw.polygon(((pole_x, 0), (pole_x - 2, 2), (pole_x - 1, 4), (pole_x, 3), (pole_x + 1, 4), (pole_x + 2, 2)), fill=(255, 202, 55))
        draw.point((pole_x, 1), fill=(255, 255, 220))
    else:
        draw.point((pole_x - 1, 0), fill=(245, 205, 75))
        draw.point((pole_x + 1, 0), fill=(245, 205, 75))

    flag_index = int(elapsed / 2.5) % len(flag_codes)
    flag = _resized_winner_flag(flag_codes[flag_index])
    rise = int(min(1.0, elapsed / 1.5) * (HEIGHT - flag.height - 4))
    top = HEIGHT - flag.height - rise
    for x in range(flag.width):
        wave = math.sin(elapsed * 6.5 - x * 0.42) * (x / flag.width) ** 1.3 * 2.0
        for y in range(flag.height):
            draw.point((pole_x + 2 + x, round(top + y + wave)), fill=flag.getpixel((x, y)))


def _draw_perfect_crown(draw, x, y, elapsed):
    period = elapsed % 2.0
    pulse = max(0.0, 1.0 - period / 0.34)
    bright = elapsed < 1.5 or pulse > 0
    crown = (
        "Y.....Y",
        "YY...YY",
        "YYYYYYY",
        ".YYYYY.",
        "..YYY..",
    )
    gold = (255, 205, 55) if not bright else (255, 229, 115)
    for row, pattern in enumerate(crown):
        for column, pixel in enumerate(pattern):
            if pixel == "Y":
                draw.point((x + column, y + row), fill=(255, 250, 190) if bright and row == 0 else gold)
    if elapsed < 1.5:
        sparkle = (255, 255, 235) if int(elapsed * 12) % 2 == 0 else (255, 220, 100)
        for sx, sy in ((x - 2, y + 1), (x + 3, y - 2), (x + 9, y + 1)):
            draw.point((sx, sy), fill=sparkle)
            if int(elapsed * 8) % 2 == 0:
                draw.point((sx, sy + 1), fill=(255, 204, 70))
    elif pulse > 0.55:
        draw.point((x - 1, y + 2), fill=(255, 231, 130))
        draw.point((x + 7, y + 2), fill=(255, 231, 130))


def _draw_victory(sign, state, elapsed):
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    winner = state.get("winner")
    winner_attempts = state.get("attempts", {}).get(winner["id"], 0) if winner else 0
    perfect = bool(
        winner
        and state["difficulty"] == "expert"
        and winner_attempts
        and winner["score"] == winner_attempts
    )
    _draw_fireworks(image, elapsed, state.get("firework_seed", 0), perfect)
    draw = ImageDraw.Draw(image)
    _draw_raising_flag(draw, elapsed, state["victory_flag_codes"], perfect)
    message = winner["name"] + " WINS!" if winner and winner["accuracy"] > 0 else "NO WINNER!" if winner else "IT'S A TIE!"
    message_x = (WIDTH - len(message) * 4) // 2 + 3
    if perfect:
        _draw_perfect_crown(draw, message_x - 9, 15, elapsed)
    sign.canvas.SetImage(image, 0, 0)

    title = "PERFECT GAME!" if perfect else "FLAG CHAMPION!" if winner and winner['accuracy'] > 0 else "QUIZ COMPLETE!"
    title_x = (WIDTH - len(title) * 5) // 2 + 3
    title_color = graphics.Color(46, 210, 255) if int(elapsed * 3) % 2 == 0 else graphics.Color(255, 220, 80)
    _draw_outlined_text(sign, sign.font57, title, title_x, 9, title_color)

    message_color = graphics.Color(255, 240, 150) if int(elapsed * 3) % 2 == 0 else graphics.Color(130, 255, 150)
    _draw_outlined_text(sign, sign.font46, message, message_x, 20, message_color)
    if winner and winner['accuracy'] > 0:
        accuracy = f"ACCURACY {winner['accuracy']}%"
        accuracy_x = (WIDTH - len(accuracy) * 4) // 2 + 3
        accuracy_color = (
            graphics.Color(*rainbow_pen_color(round(elapsed * 60)))
            if perfect
            else graphics.Color(130, 255, 150)
        )
        _draw_outlined_text(sign, sign.font46, accuracy, accuracy_x, 30, accuracy_color)


def _draw_sudden_death_notice(sign):
    first_line = "SUDDEN DEATH"
    second_line = "ROUNDS"
    first_x = (WIDTH - len(first_line) * 6) // 2
    second_x = (WIDTH - len(second_line) * 6) // 2
    red = graphics.Color(255, 40, 40)
    _draw_outlined_text(sign, sign.fontbig, first_line, first_x, 12, red)
    _draw_outlined_text(sign, sign.fontbig, second_line, second_x, 27, red)


def _fit_option(text, max_chars=20):
    if len(text) <= max_chars:
        return text
    text = text.replace("and", "&")
    if len(text) <= max_chars:
        return text
    text = text.replace("Islands", "Is.").replace("Island", "Is.")
    if len(text) <= max_chars:
        return text
    text = text.replace("Saint", "St.")
    if len(text) <= max_chars:
        return text
    text = text.replace("Southern", "S.").replace("Northern", "N.")
    if len(text) <= max_chars:
        return text
    words = text.split()
    while words and len(" ".join(words)) + 3 > max_chars:
        words.pop()
    return " ".join(words) + "..." if words else text[:max_chars - 3] + "..."


def _draw_question_timer(sign, time_remaining_fraction):
    remaining_pixels = math.ceil(max(0.0, min(1.0, time_remaining_fraction)) * WIDTH)
    if remaining_pixels:
        graphics.DrawLine(
            sign.canvas,
            0,
            HEIGHT - 1,
            remaining_pixels - 1,
            HEIGHT - 1,
            graphics.Color(255, 0, 0),
        )


def _draw_question(sign, state, elapsed=0.0):
    sign.canvas.Clear()
    if state["current"] is None:
        if state.get("sudden_death_notice"):
            _draw_sudden_death_notice(sign)
        elif state.get("countdown") is not None:
            _draw_countdown(sign, state["countdown"])
        elif state["complete"]:
            _draw_victory(sign, state, elapsed)
        else:
            _draw_loading(sign, elapsed, state.get("selected_difficulty"))
        return

    current = state["current"]
    difficulty_mark = {"easy": "E", "hard": "H", "expert": "X"}[state["difficulty"]]
    question_number = f"{state['question_number']}/{state['total']}"
    header = f"{difficulty_mark} {question_number}"
    header_label_color = graphics.Color(200, 220, 255)
    question_number_color = graphics.Color(255, 40, 40) if state.get("sudden_death") else header_label_color

    flag = _flag_image(current["code"]).copy()
    if state["difficulty"] == "expert":
        flag.thumbnail((46, 28), Image.Resampling.LANCZOS)
        sign.canvas.SetImage(flag, (WIDTH - flag.width) // 2, (HEIGHT - flag.height) // 2)
        header_x = (40 - len(header) * 4) // 2
        graphics.DrawText(sign.canvas, sign.font46, header_x, 18, header_label_color, difficulty_mark)
        graphics.DrawText(sign.canvas, sign.font46, header_x + 8, 18, question_number_color, question_number)
        _draw_question_timer(sign, state["time_remaining_fraction"])
        return

    flag.thumbnail((42, 20), Image.Resampling.LANCZOS)
    sign.canvas.SetImage(flag, (44 - flag.width) // 2, 1)
    header_x = (44 - len(header) * 4) // 2
    graphics.DrawText(sign.canvas, sign.font46, header_x, 29, header_label_color, difficulty_mark)
    graphics.DrawText(sign.canvas, sign.font46, header_x + 8, 29, question_number_color, question_number)

    options = current["options"]
    spacing = 8 if len(options) == 3 else 7
    block_height = 5 + (len(options) - 1) * spacing
    first_baseline = (HEIGHT - block_height) // 2 + 5
    baselines = tuple(first_baseline + index * spacing for index in range(len(options)))
    for option, baseline in zip(options, baselines):
        label = _fit_option(f"{option['key']}. {option['name']}")
        graphics.DrawText(sign.canvas, sign.font46, 48, baseline, graphics.Color(255, 255, 255), label)
    _draw_question_timer(sign, state["time_remaining_fraction"])


@planesign_mode_handler(DisplayMode.FLAGQUIZ)
def flagquiz(sign):
    start_time = time.perf_counter()
    celebration_start = None
    while shared_config.shared_mode.value == DisplayMode.FLAGQUIZ.value:
        now = time.perf_counter()
        state = get_sign_state()
        if state["complete"] and state["difficulty"] is not None:
            if celebration_start is None:
                celebration_start = now
            elapsed = now - celebration_start
        else:
            celebration_start = None
            elapsed = now - start_time
        _draw_question(sign, state, elapsed)
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(0.08):
            return
