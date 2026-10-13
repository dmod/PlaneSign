import csv
import math
import os
import random
import re
import time
import uuid
from functools import lru_cache

import games
import shared_config
from modes import DisplayMode, planesign_mode_handler
from PIL import Image
from rgbmatrix import graphics

ROUND_SECONDS = 10
FLAG_GAME_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datafiles", "flag_game.csv")
FLAG_IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons", "flags")
DIFFICULTIES = {"easy": 3, "hard": 4, "expert": 0}


class FlagQuizConflict(ValueError):
    pass


@lru_cache(maxsize=1)
def load_countries():
    countries = []
    seen_codes = set()
    with open(FLAG_GAME_FILE, newline="", encoding="utf-8") as csv_file:
        for line, row in enumerate(csv.reader(csv_file), 1):
            if len(row) != 3:
                raise ValueError(f"Invalid flag quiz CSV row {line}: expected 3 columns")
            code, name, easy = (value.strip() for value in row)
            code = code.upper()
            if not code or not name or code in seen_codes:
                raise ValueError(f"Invalid or duplicate flag quiz entry on row {line}")
            if not os.path.isfile(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")):
                raise FileNotFoundError(f"Flag image not found for {code} (CSV row {line})")
            seen_codes.add(code)
            countries.append({"code": code, "name": name, "easy": easy.casefold() == "true"})
    if not countries:
        raise ValueError("Flag quiz data contains no countries")
    return tuple(countries)


def normalize_country_tokens(value):
    value = value.casefold()
    replacements = (
        (r"\bislands?\b|\bis\.?\b", "island"),
        (r"\bterritor(?:y|ies)\b|\bterr\.?\b", "territory"),
        (r"\bsouth\b|\bs\.?\b", "south"),
        (r"\bsaint\b|\bst\.?\b", "saint"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value)
    return re.findall(r"[^\W_]+", value, flags=re.UNICODE)


def get_country_suggestions(query, limit=12):
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
    countries = load_countries()
    if difficulty == "easy":
        countries = tuple(country for country in countries if country["easy"])
    return countries


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


def start_game(difficulty, player_id):
    difficulty = difficulty.casefold() if isinstance(difficulty, str) else difficulty
    pool = _country_pool(difficulty)
    option_count = DIFFICULTIES[difficulty]
    if option_count and len({country["name"].casefold() for country in pool}) < option_count:
        raise ValueError(f"Not enough unique countries for {difficulty} mode")

    player = games.register_player(player_id)
    question_codes = [country["code"] for country in pool]
    random.shuffle(question_codes)
    now = time.monotonic()
    players = games.get_players()
    scores = {pid: 0 for pid, record in players.items() if now - record["last_seen"] < games.ACTIVE_PLAYER_SECONDS}
    scores[player["id"]] = 0

    state = {
        "difficulty": difficulty,
        "question_codes": question_codes,
        "index": 0,
        "round_id": uuid.uuid4().hex,
        "deadline": now + ROUND_SECONDS,
        "current": _make_question(question_codes[0], difficulty, pool),
        "answers": {},
        "scores": scores,
        "last_result": None,
    }
    with shared_config.shared_games_lock:
        shared_config.data_dict["flagquiz_state"] = state
        shared_config.shared_mode.value = DisplayMode.FLAGQUIZ.value
        shared_config.shared_forced_sign_update.set()
    return {"ok": True, "difficulty": difficulty, "total": len(question_codes)}


def _advance(state, now):
    current = state["current"]
    state["last_result"] = {
        "question_number": state["index"] + 1,
        "code": current["code"],
        "correct_name": current["name"],
        "answers": [
            {"name": answer["name"], "correct": answer["correct"]}
            for answer in state["answers"].values()
        ],
    }
    state["index"] += 1
    state["answers"] = {}
    if state["index"] == len(state["question_codes"]):
        state["current"] = None
        state["deadline"] = None
        state["round_id"] = None
        return

    state["round_id"] = uuid.uuid4().hex
    state["deadline"] = now + ROUND_SECONDS
    state["current"] = _make_question(state["question_codes"][state["index"]], state["difficulty"], _country_pool(state["difficulty"]))


def _advance_if_ready(state, players, now):
    if state["current"] is None:
        return False
    active_ids = [
        player_id for player_id in state["scores"]
        if player_id in players and now - players[player_id]["last_seen"] < games.ACTIVE_PLAYER_SECONDS
    ]
    timed_out = now >= state["deadline"]
    all_active_answered = bool(active_ids) and all(player_id in state["answers"] for player_id in active_ids)
    if timed_out or all_active_answered:
        _advance(state, now)
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

    return {
        "ok": True,
        "difficulty": state["difficulty"],
        "question_number": min(state["index"] + 1, len(state["question_codes"])),
        "total": len(state["question_codes"]),
        "round_id": state["round_id"],
        "seconds_left": seconds_left,
        "complete": current is None,
        "current": current_public,
        "your_answer": answers.get(player_id),
        "last_result": state["last_result"],
        "players": _player_summary(players, scores, now),
    }


def get_game_status(player_id, player_name=None):
    player = games.register_player(player_id, player_name)
    now = time.monotonic()
    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None:
            return {"ok": True, "difficulty": None, "complete": False, "current": None, "players": [], "player": player}

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["scores"].setdefault(player["id"], 0)
        _advance_if_ready(state, players, now)
        shared_config.data_dict["flagquiz_state"] = state
        status = _public_status(state, player["id"], players, now)
        status["player"] = player
        return status


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

        state["answers"][player["id"]] = {"name": player["name"], "correct": correct}
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
            return {"difficulty": None, "question_number": 0, "total": 0, "current": None, "complete": False}

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        players = dict(shared_config.data_dict.get("game_players", {}))
        if _advance_if_ready(state, players, now):
            shared_config.data_dict["flagquiz_state"] = state
        return {
            "difficulty": state["difficulty"],
            "question_number": min(state["index"] + 1, len(state["question_codes"])),
            "total": len(state["question_codes"]),
            "current": state["current"],
            "complete": state["current"] is None,
        }


@lru_cache(maxsize=1)
def _flag_image(code):
    with Image.open(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")) as image:
        return image.convert("RGB")


def _fit_option(text, sign):
    if len(text) <= 15:
        return sign.font57, text
    if len(text) <= 19:
        return sign.font46, text

    words = text.split()
    while words and len(" ".join(words) + "...") > 19:
        words.pop()
    return sign.font46, (" ".join(words) + "...") if words else text[:16] + "..."


def _draw_question(sign, state):
    sign.canvas.Clear()
    if state["current"] is None:
        message = "QUIZ COMPLETE" if state["complete"] else "CHOOSE LEVEL"
        graphics.DrawText(sign.canvas, sign.font57, 34, 20, graphics.Color(255, 255, 255), message)
        if state["total"]:
            progress = f"{state['question_number']}/{state['total']}"
            graphics.DrawText(sign.canvas, sign.font46, 52, 30, graphics.Color(170, 220, 255), progress)
        return

    current = state["current"]
    difficulty_mark = {"easy": "E", "hard": "H", "expert": "X"}[state["difficulty"]]
    header = f"{difficulty_mark} {state['question_number']}/{state['total']}"
    graphics.DrawText(sign.canvas, sign.font46, 52, 5, graphics.Color(200, 220, 255), header)

    flag = _flag_image(current["code"]).copy()
    if state["difficulty"] == "expert":
        flag.thumbnail((46, 28), Image.Resampling.LANCZOS)
        sign.canvas.SetImage(flag, (128 - flag.width) // 2, 4 + (27 - flag.height) // 2)
        return

    flag.thumbnail((42, 24), Image.Resampling.LANCZOS)
    sign.canvas.SetImage(flag, (45 - flag.width) // 2, 8 + (24 - flag.height) // 2)
    options = current["options"]
    baselines = (12, 21, 30) if len(options) == 3 else (11, 18, 25, 32)
    for option, baseline in zip(options, baselines):
        label = f"{option['key']}. {option['name']}"
        font, label = _fit_option(label, sign)
        graphics.DrawText(sign.canvas, font, 52, baseline, graphics.Color(255, 255, 255), label)


@planesign_mode_handler(DisplayMode.FLAGQUIZ)
def flagquiz(sign):
    while shared_config.shared_mode.value == DisplayMode.FLAGQUIZ.value:
        _draw_question(sign, get_sign_state())
        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
        if sign.wait_loop(0.2):
            return
