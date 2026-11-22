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
VEXILLOLOGIST_ROUND_SECONDS = 60
QUESTION_LIMIT = 25
VEXILLOLOGIST_QUESTION_LIMIT = 5
SUDDEN_DEATH_NOTICE_SECONDS = 3
START_COUNTDOWN_SECONDS = 3
STUDY_FLAG_SECONDS = 3
VEXILLOLOGIST_TIME_UP_SECONDS = 1.5
VEXILLOLOGIST_COMPARISON_SECONDS = 3
VEXILLOLOGIST_QUESTION_PAUSE_SECONDS = 1.5
DRAWING_COLOR_WEIGHT = 0.1
DRAWING_SHAPE_WEIGHT = 0.2
DRAWING_COLOR_CLUSTER_DELTA_E = 12
DRAWING_COLOR_MATCH_DELTA_E = 36
DRAWING_SHAPE_EDGE_DELTA_E = 12
DRAWING_SHAPE_EDGE_TOLERANCE = 2
DRAWING_PIXEL_DELTA_E_SCALE = 80
WIDTH = 128
HEIGHT = 32
VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT = 20
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
DIFFICULTIES = {"easy": 3, "hard": 4, "expert": 0, "vexillologist": 0}
DIFFICULTY_LEVELS = {"easy": 0, "hard": 1, "expert": 2, "vexillologist": 0}
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
def load_flag_entries():
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
            if difficulty not in ("easy", "hard", "expert", "none"):
                raise ValueError(f"Invalid flag quiz difficulty on row {line}: expected Easy, Hard, Expert, or None")
            if not os.path.isfile(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")):
                raise FileNotFoundError(f"Flag image not found for {code} (CSV row {line})")
            seen_codes.add(code)
            countries.append({"code": code, "name": name, "difficulty": difficulty})
    if not any(country["difficulty"] != "none" for country in countries):
        raise ValueError("Flag quiz data contains no countries")
    return tuple(countries)


@lru_cache(maxsize=1)
def load_countries():
    return tuple(country for country in load_flag_entries() if country["difficulty"] != "none")


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
    for country in load_flag_entries():
        country_tokens = normalize_country_tokens(country["name"])
        if all(any(token.startswith(query_token) for token in country_tokens) for query_token in query_tokens):
            suggestions.append({"code": country["code"], "name": country["name"]})
            if len(suggestions) == limit:
                break
    return suggestions


def _country_pool(difficulty):
    if difficulty not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, hard, expert, or vexillologist")
    if difficulty == "vexillologist":
        return tuple(country for country in load_countries() if country["difficulty"] == "easy")
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
    if difficulty == "vexillologist":
        return VEXILLOLOGIST_ROUND_SECONDS
    return EXPERT_ROUND_SECONDS if difficulty == "expert" else ROUND_SECONDS


def select_difficulty(difficulty):
    if not isinstance(difficulty, str) or difficulty.casefold() not in DIFFICULTIES:
        raise ValueError("difficulty must be easy, hard, expert, or vexillologist")
    difficulty = difficulty.casefold()
    with shared_config.shared_games_lock:
        shared_config.data_dict["flagquiz_selected_difficulty"] = difficulty
    return {"ok": True, "difficulty": difficulty}


def select_study(code=None):
    countries = load_flag_entries()
    country_by_code = {country["code"]: country for country in countries}
    if code is not None:
        if not isinstance(code, str):
            raise ValueError("code must be a flag code")
        code = normalize_country_code(code)
        if code not in country_by_code:
            raise ValueError("Unknown flag")

    now = time.monotonic()
    with shared_config.shared_games_lock:
        study = shared_config.data_dict.get("flagquiz_study")
        if code is None:
            study = _new_study_state(now)
        elif study:
            study = dict(study)
            _advance_study(study, now)
            order = _study_order(study["seed"], study["cycle"], study["codes"])
            if code in order:
                study["index"] = order.index(code)
            study["code"] = code
            study["last_advance"] = now
        else:
            study = _new_study_state(now)
            study["code"] = code
        shared_config.data_dict["flagquiz_study"] = study
    return {"ok": True, "code": code}


def _new_study_state(now):
    return {
        "code": None,
        "compare_code": None,
        "codes": tuple(country["code"] for country in load_countries()),
        "seed": random.randrange(2**32),
        "cycle": 0,
        "index": 0,
        "last_advance": now,
        "paused": False,
    }


def select_study_comparison(code):
    if code is not None:
        if not isinstance(code, str):
            raise ValueError("code must be a flag code")
        code = normalize_country_code(code)
        if code not in {country["code"] for country in load_flag_entries()}:
            raise ValueError("Unknown flag")

    now = time.monotonic()
    with shared_config.shared_games_lock:
        study = shared_config.data_dict.get("flagquiz_study")
        if not study:
            study = _new_study_state(now)
        else:
            study = dict(study)
        shared_config.data_dict["flagquiz_study"] = {**study, "compare_code": code}
    return {"ok": True, "compare_code": code}


def study_action(action):
    if action not in ("next", "previous", "toggle_pause"):
        raise ValueError("Unknown study action")

    now = time.monotonic()
    with shared_config.shared_games_lock:
        study = shared_config.data_dict.get("flagquiz_study")
        if not study:
            raise ValueError("Study mode is not selected")
        _advance_study(study, now)
        if action == "toggle_pause":
            if study["code"] is not None:
                raise ValueError("Pause is only available while cycling flags")
            if study["paused"]:
                study["last_advance"] = now
                study["paused"] = False
            else:
                study["paused"] = True
        else:
            codes = study["codes"]
            if study["code"] is not None:
                current_index = next((index for index, code in enumerate(_study_order(study["seed"], study["cycle"], codes)) if code == study["code"]), study["index"])
                study["index"] = current_index
                study["code"] = None
            direction = 1 if action == "next" else -1
            study["index"] += direction
            if study["index"] >= len(codes):
                study["cycle"] += 1
                study["index"] = 0
            elif study["index"] < 0:
                study["cycle"] -= 1
                study["index"] = len(codes) - 1
            study["last_advance"] = now
        shared_config.data_dict["flagquiz_study"] = study
    return {"ok": True, "action": action}


@lru_cache(maxsize=32)
def _study_order(seed, cycle, codes):
    order = list(codes)
    random.Random(seed + cycle * 1103515245).shuffle(order)
    return tuple(order)


def _advance_study(study, now):
    if study["code"] is not None or study["paused"]:
        return False
    elapsed_steps = int(max(0.0, now - study["last_advance"]) / STUDY_FLAG_SECONDS)
    if elapsed_steps:
        cycle, study["index"] = divmod(study["index"] + elapsed_steps, len(study["codes"]))
        study["cycle"] += cycle
        study["last_advance"] += elapsed_steps * STUDY_FLAG_SECONDS
        return True
    return False


def _study_status(now):
    study = shared_config.data_dict.get("flagquiz_study")
    if not study:
        return {"active": False}

    codes = tuple(study["codes"])
    if _advance_study(study, now):
        shared_config.data_dict["flagquiz_study"] = study
    cycling = study["code"] is None
    if cycling:
        code = _study_order(study["seed"], study["cycle"], codes)[study["index"]]
        position = study["index"] + 1
    else:
        code = study["code"]
        position = None

    country = next(country for country in load_flag_entries() if country["code"] == code)
    compare_code = study.get("compare_code")
    comparison = None
    if compare_code is not None:
        compared_country = next(country for country in load_flag_entries() if country["code"] == compare_code)
        comparison = {"code": compared_country["code"], "name": compared_country["name"]}
    return {
        "active": True,
        "code": code,
        "name": country["name"],
        "comparison": comparison,
        "cycling": cycling,
        "paused": study["paused"],
        "position": position,
        "total": len(codes),
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
    question_limit = VEXILLOLOGIST_QUESTION_LIMIT if difficulty == "vexillologist" else QUESTION_LIMIT
    regular_question_count = min(question_limit, len(question_codes))
    now = time.monotonic()
    players = games.get_players()
    scores = {pid: 0 for pid, record in players.items() if now - record["last_seen"] < games.ACTIVE_PLAYER_SECONDS}
    scores[player["id"]] = 0
    countdown_until = now + START_COUNTDOWN_SECONDS
    firework_seed = random.randrange(2**32)
    if difficulty == "vexillologist":
        victory_flag_codes = question_codes[:regular_question_count]
    else:
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
        "vexillologist_phase": None,
        "vexillologist_phase_until": None,
        "vexillologist_submissions": {},
        "vexillologist_winner_submissions": {},
        "vexillologist_comparisons": [],
        "vexillologist_comparison_index": 0,
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
        shared_config.data_dict["flagquiz_study"] = None
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
    state["vexillologist_phase"] = None
    state["vexillologist_phase_until"] = None
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
    if state["difficulty"] == "vexillologist":
        _reset_vexillologist_question(state)


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
    if state["difficulty"] == "vexillologist":
        _reset_vexillologist_question(state)


def _reset_vexillologist_question(state):
    state["vexillologist_phase"] = "question"
    state["vexillologist_phase_until"] = None
    state["vexillologist_submissions"] = {}
    state["vexillologist_comparisons"] = []
    state["vexillologist_comparison_index"] = 0


def _finish_vexillologist_question(state, players, now):
    current = state["current"]
    width, height = _raw_flag_image(current["code"]).size
    black_pixels = [0] * (width * height * 3)
    comparisons = []
    answers = []
    winner_submissions = dict(state.get("vexillologist_winner_submissions", {}))
    for player_id in state["scores"]:
        player = players.get(player_id, {})
        submission = state["vexillologist_submissions"].get(player_id)
        if submission is not None:
            player_submissions = list(winner_submissions.get(player_id, ()))
            player_submissions.append((
                current["code"],
                submission["width"],
                submission["height"],
                bytes(submission["pixels"]),
            ))
            winner_submissions[player_id] = player_submissions
        pixels = submission["pixels"] if submission else black_pixels
        score = _score_drawing(current["code"], pixels, width, height)
        state["scores"][player_id] += score
        state["attempts"][player_id] = state["attempts"].get(player_id, 0) + 1
        name = player.get("name", "Player")
        answers.append({
            "id": player_id,
            "name": name,
            "correct": score == 20,
            "answered": submission is not None,
            "score": score,
        })
        comparisons.append({
            "id": player_id,
            "name": name,
            "score": score,
            "width": width,
            "height": height,
            "pixels": pixels,
        })

    comparisons.sort(key=lambda result: (result["name"].casefold(), result["id"]))
    answers.sort(key=lambda answer: (answer["name"].casefold(), answer["id"]))
    state["vexillologist_winner_submissions"] = winner_submissions
    state["last_result"] = {
        "question_number": state["index"] + 1,
        "round_id": state["round_id"],
        "code": current["code"],
        "correct_name": current["name"],
        "timed_out": True,
        "answers": answers,
    }
    state["vexillologist_comparisons"] = comparisons
    state["vexillologist_comparison_index"] = 0
    state["vexillologist_phase"] = "time_up"
    state["vexillologist_phase_until"] = now + VEXILLOLOGIST_TIME_UP_SECONDS
    state["deadline"] = None


def _advance_vexillologist(state, players, now):
    phase = state.get("vexillologist_phase")
    phase_until = state.get("vexillologist_phase_until")
    if phase == "question":
        if now >= state["deadline"]:
            _finish_vexillologist_question(state, players, now)
            return True
        return False
    if phase_until is None or now < phase_until:
        return False
    if phase == "time_up":
        if state["vexillologist_comparisons"]:
            state["vexillologist_phase"] = "comparison"
            state["vexillologist_phase_until"] = now + VEXILLOLOGIST_COMPARISON_SECONDS
        else:
            state["vexillologist_phase"] = "question_pause"
            state["vexillologist_phase_until"] = now + VEXILLOLOGIST_QUESTION_PAUSE_SECONDS
        return True
    if phase == "comparison":
        state["vexillologist_comparison_index"] += 1
        if state["vexillologist_comparison_index"] < len(state["vexillologist_comparisons"]):
            state["vexillologist_phase_until"] = now + VEXILLOLOGIST_COMPARISON_SECONDS
        else:
            state["vexillologist_phase"] = "question_pause"
            state["vexillologist_phase_until"] = now + VEXILLOLOGIST_QUESTION_PAUSE_SECONDS
        return True
    if phase == "question_pause":
        state["index"] += 1
        if state.get("end_requested"):
            _finish_game(state)
            return True
        if state["index"] >= state["regular_question_count"]:
            leader_id = _unique_leader_id(state["scores"])
            if leader_id is not None:
                _finish_game(state)
                return True
            if state["index"] >= len(state["question_codes"]):
                state["current"] = None
                state["tie"] = True
                state["vexillologist_phase"] = None
                return True
            state["sudden_death"] = True
            state["sudden_death_notice_until"] = now + SUDDEN_DEATH_NOTICE_SECONDS
            state["current"] = None
            state["round_id"] = None
            state["vexillologist_phase"] = None
            state["vexillologist_phase_until"] = None
            return True
        _start_next_question(state, now)
        return True
    return False


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

    if state["difficulty"] == "vexillologist":
        return _advance_vexillologist(state, players, now)

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
            "options": [{"key": option["key"], "name": option["name"]} for option in current["options"]],
        }
        if state["difficulty"] == "vexillologist":
            width, height = _raw_flag_image(current["code"]).size
            current_public.update({"name": current["name"], "width": width, "height": height})
        else:
            current_public["code"] = current["code"]
        if state["deadline"] is not None:
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
        "vexillologist_phase": state.get("vexillologist_phase"),
        "your_answer": answers.get(player_id),
        "your_vexillologist_score": (
            next(
                (answer["score"] for answer in state["last_result"]["answers"] if answer["id"] == player_id),
                None,
            )
            if state["last_result"] and state["difficulty"] == "vexillologist"
            else None
        ),
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
        "accuracy": round(score * 100 / (attempts * 20 if state["difficulty"] == "vexillologist" else attempts)) if attempts else 0,
    }


def get_game_status(player_id, player_name=None):
    player = games.register_player(player_id, player_name)
    now = time.monotonic()
    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        state = shared_config.data_dict.get("flagquiz_state")
        selected_difficulty = shared_config.data_dict.get("flagquiz_selected_difficulty")
        study = _study_status(now)
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
                "study": study,
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
        status["study"] = study
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
            valid_answer = isinstance(answer, str) and any(country["code"] == answer for country in load_flag_entries())
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


def submit_drawing(player_id, round_id, width, height, pixels):
    player = games.register_player(player_id)
    if not isinstance(round_id, str):
        raise TypeError("round_id must be a string")
    if isinstance(width, bool) or not isinstance(width, int) or isinstance(height, bool) or not isinstance(height, int):
        raise TypeError("drawing dimensions must be integers")
    if not isinstance(pixels, list):
        raise TypeError("drawing pixels must be an array")
    if any(isinstance(channel, bool) or not isinstance(channel, int) for channel in pixels):
        raise TypeError("drawing pixels must contain integers")
    if any(not 0 <= channel <= 255 for channel in pixels):
        raise ValueError("drawing pixels must be RGB values from 0 to 255")

    now = time.monotonic()
    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None or state["current"] is None or state["difficulty"] != "vexillologist":
            raise FlagQuizConflict("There is no active Vexillologist question")

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        _advance_if_ready(state, players, now)
        if round_id != state["round_id"] or state.get("vexillologist_phase") != "question":
            shared_config.data_dict["flagquiz_state"] = state
            raise FlagQuizConflict("This question has ended; load the current question and try again")

        expected_width, expected_height = _raw_flag_image(state["current"]["code"]).size
        if (width, height) != (expected_width, expected_height):
            raise ValueError("drawing dimensions do not match the flag")
        if len(pixels) != width * height * 3:
            raise ValueError("drawing pixel count does not match its dimensions")

        state["scores"].setdefault(player["id"], 0)
        state["attempts"].setdefault(player["id"], 0)
        submissions = dict(state.get("vexillologist_submissions", {}))
        submissions[player["id"]] = {
            "width": width,
            "height": height,
            "pixels": pixels,
        }
        state["vexillologist_submissions"] = submissions
        shared_config.data_dict["flagquiz_state"] = state
        return {"ok": True}


def get_sign_state():
    now = time.monotonic()
    with shared_config.shared_games_lock:
        state = shared_config.data_dict.get("flagquiz_state")
        if state is None:
            return {
                "difficulty": None,
                "selected_difficulty": shared_config.data_dict.get("flagquiz_selected_difficulty"),
                "study": _study_status(now),
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
            "study": _study_status(now),
            "question_number": state["index"] + 1 if state["current"] is not None else state["index"],
            "total": state["regular_question_count"],
            "current": state["current"],
            "vexillologist_phase": state.get("vexillologist_phase"),
            "vexillologist_comparison": (
                state.get("vexillologist_comparisons", [])[state.get("vexillologist_comparison_index", 0)]
                if state.get("vexillologist_phase") == "comparison"
                and state.get("vexillologist_comparison_index", 0) < len(state.get("vexillologist_comparisons", []))
                else None
            ),
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
            "victory_flag_submissions": (
                state.get("vexillologist_winner_submissions", {}).get(state.get("winner_id"), [])
                if state["difficulty"] == "vexillologist" and state.get("winner_id") is not None
                else []
            ),
        }


@lru_cache(maxsize=256)
def _raw_flag_image(code):
    with Image.open(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")) as source:
        rgba = source.convert("RGBA")
        image = Image.new("RGB", rgba.size, (0, 0, 0))
        image.paste(rgba, (0, 0), rgba.getchannel("A"))
        return image


def _srgb_to_lab(rgb):
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float32).T
    xyz /= np.array((0.95047, 1.0, 1.08883), dtype=np.float32)
    delta = 6 / 29
    transformed = np.where(
        xyz > delta**3,
        np.cbrt(xyz),
        xyz / (3 * delta**2) + 4 / 29,
    )
    return np.stack((
        116 * transformed[..., 1] - 16,
        500 * (transformed[..., 0] - transformed[..., 1]),
        200 * (transformed[..., 1] - transformed[..., 2]),
    ), axis=-1)


def _pixel_score(target_lab, drawing_lab):
    """Score average Lab pixel error: 1 for exact, linearly falling to 0 at mean ΔE 110; always [0, 1]."""
    delta_e = np.linalg.norm(target_lab - drawing_lab, axis=-1)
    return float(np.clip(1.0 - float(delta_e.mean()) / DRAWING_PIXEL_DELTA_E_SCALE, 0.0, 1.0))


def _color_coverage_score(target_lab, drawing_lab):
    """Compare the flag's main colors and their proportions with the drawing."""
    target_colors, target_counts = np.unique(target_lab.reshape((-1, 3)), axis=0, return_counts=True)
    centers = []
    for index in np.argsort(target_counts)[::-1]:
        if not centers or np.min(np.linalg.norm(target_colors[index] - centers, axis=1)) > DRAWING_COLOR_CLUSTER_DELTA_E:
            centers.append(target_colors[index])

    centers = np.asarray(centers)
    target_distances = np.linalg.norm(target_colors[:, None, :] - centers[None, :, :], axis=2)
    target_labels = np.argmin(target_distances, axis=1)
    target_histogram = np.bincount(target_labels, weights=target_counts, minlength=len(centers))

    drawing_pixels = drawing_lab.reshape((-1, 3))
    drawing_distances = np.linalg.norm(drawing_pixels[:, None, :] - centers[None, :, :], axis=2)
    drawing_labels = np.argmin(drawing_distances, axis=1)
    drawing_labels[drawing_distances[np.arange(len(drawing_pixels)), drawing_labels] > DRAWING_COLOR_MATCH_DELTA_E] = len(centers)
    drawing_histogram = np.bincount(drawing_labels, minlength=len(centers) + 1)

    pixel_count = target_lab.shape[0] * target_lab.shape[1]
    target_histogram = target_histogram / pixel_count
    drawing_histogram = drawing_histogram / pixel_count
    return float(np.clip(np.minimum(target_histogram, drawing_histogram[:-1]).sum(), 0.0, 1.0))


def _color_edges(lab, threshold=DRAWING_SHAPE_EDGE_DELTA_E):
    height, width = lab.shape[:2]
    edges = np.zeros((height, width), dtype=bool)
    horizontal = np.linalg.norm(lab[:, 1:] - lab[:, :-1], axis=2) >= threshold
    vertical = np.linalg.norm(lab[1:, :] - lab[:-1, :], axis=2) >= threshold
    edges[:, 1:] |= horizontal
    edges[:, :-1] |= horizontal
    edges[1:, :] |= vertical
    edges[:-1, :] |= vertical
    return edges


def _dilate_mask(mask, radius=DRAWING_SHAPE_EDGE_TOLERANCE):
    height, width = mask.shape
    padded = np.pad(mask, radius, mode="constant")
    dilated = np.zeros_like(mask)
    for y in range(radius * 2 + 1):
        for x in range(radius * 2 + 1):
            dilated |= padded[y : y + height, x : x + width]
    return dilated


def _shape_score(target_lab, drawing_lab):
    """Compare the placement of color boundaries in the flag and drawing."""
    target_edges = _color_edges(target_lab)
    drawing_edges = _color_edges(drawing_lab)
    target_count = np.count_nonzero(target_edges)
    drawing_count = np.count_nonzero(drawing_edges)
    if not target_count or not drawing_count:
        return float(target_count == drawing_count)

    target_matches = np.count_nonzero(target_edges & _dilate_mask(drawing_edges))
    drawing_matches = np.count_nonzero(drawing_edges & _dilate_mask(target_edges))
    precision = drawing_matches / drawing_count
    recall = target_matches / target_count
    if precision + recall == 0:
        return 0.0
    return float(np.clip(2 * precision * recall / (precision + recall), 0.0, 1.0))


def _score_drawing(code, pixels, width, height):
    drawing_pixels = np.asarray(pixels, dtype=np.uint8).reshape((height, width, 3))
    if not np.any(drawing_pixels):
        return 0
    target_pixels = np.asarray(_raw_flag_image(code), dtype=np.uint8)
    drawing = drawing_pixels.astype(np.float32) / 255
    target = target_pixels.astype(np.float32) / 255
    target_lab = _srgb_to_lab(target)
    drawing_lab = _srgb_to_lab(drawing)
    pixel_score = _pixel_score(target_lab, drawing_lab)
    score = 20 * pixel_score
    if pixel_score < 1.0:
        color_score = _color_coverage_score(target_lab, drawing_lab)
        shape_score = _shape_score(target_lab, drawing_lab)
        score += 20 * (DRAWING_COLOR_WEIGHT * color_score + DRAWING_SHAPE_WEIGHT * shape_score)
    return math.floor(min(20.0, score) + 0.5)


@lru_cache(maxsize=1)
def _flag_image(code):
    with Image.open(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")) as image:
        image = image.convert("RGBA")
        if code == "NPL" or code == "states/OH":
            bg = Image.new("RGB", image.size, (0, 0, 0))
            bg.paste(image, (0, 0), image)
            image = bg.convert("RGB")
        else:
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


def _study_name_lines(name, max_chars=19):
    lines = []
    line = ""
    for word in name.split():
        while len(word) > max_chars:
            if line:
                lines.append(line)
                line = ""
            lines.append(word[:max_chars])
            word = word[max_chars:]
        if line and len(line) + len(word) + 1 > max_chars:
            lines.append(line)
            line = ""
        line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines


def _draw_study(sign, study):
    comparison = study.get("comparison")
    font_width = sign.font46.CharacterWidth(ord("A"))
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    if comparison:
        left_flag = _flag_image(study["code"]).convert("RGB")
        right_flag = _flag_image(comparison["code"]).convert("RGB")
        right_x = WIDTH - right_flag.width
        image.paste(left_flag, (0, (HEIGHT - left_flag.height) // 2))
        image.paste(right_flag, (right_x, (HEIGHT - right_flag.height) // 2))
    else:
        flag = _flag_image(study["code"]).convert("RGB")
        image.paste(flag, (0, (HEIGHT - flag.height) // 2))
    sign.canvas.SetImage(image, 0, 0)

    if comparison:
        name_area_width = max(0, right_x - left_flag.width)
        max_chars = name_area_width // font_width
        left_lines = _study_comparison_lines(study["name"], left=True, max_chars=max_chars)
        right_lines = _study_comparison_lines(comparison["name"], left=False, max_chars=max_chars)
        for line, baseline in zip(left_lines, (11, 17)):
            x = left_flag.width + (name_area_width - len(line) * font_width) // 2
            graphics.DrawText(sign.canvas, sign.font46, x, baseline, graphics.Color(255, 255, 255), line)
        for line, baseline in zip(right_lines, (24, 30)):
            x = left_flag.width + (name_area_width - len(line) * font_width) // 2
            graphics.DrawText(sign.canvas, sign.font46, x, baseline, graphics.Color(255, 255, 255), line)
        return

    name_area_width = WIDTH - flag.width
    max_chars = name_area_width // font_width
    header = f"STUDY {study['position']}/{study['total']}" if study["cycling"] else "STUDY"
    header_x = flag.width + (name_area_width - len(header) * font_width) // 2
    graphics.DrawText(sign.canvas, sign.font46, header_x, 6, graphics.Color(46, 210, 255), header)
    lines = _study_name_lines(study["name"], max_chars)
    if len(lines) > 4:
        lines = lines[:4]
        lines[-1] = lines[-1][:max(0, max_chars - 3)] + "..."
    for index, line in enumerate(lines):
        x = flag.width + (name_area_width - len(line) * font_width) // 2
        graphics.DrawText(sign.canvas, sign.font46, x, 12 + index * 6, graphics.Color(255, 255, 255), line)


def _study_comparison_lines(name, left, max_chars):
    if max_chars < 3:
        return ("<" if left else ">",)

    capacities = (max_chars - 2, max_chars) if left else (max_chars, max_chars - 2)
    words = name.split()
    lines = []
    for capacity in capacities:
        line = ""
        while words:
            word = words[0]
            separator = 1 if line else 0
            available = capacity - len(line) - separator
            if len(word) <= available:
                line = f"{line} {word}".strip()
                words.pop(0)
            elif line:
                break
            else:
                line = word[:capacity]
                words[0] = word[capacity:]
                if not words[0]:
                    words.pop(0)
                break
        if line != "":
            lines.append(line)

    if words:
        content_limit = capacities[-1]
        lines[-1] = lines[-1][:max(0, content_limit - 3)] + "..."
    if left:
        lines[0] = "< " + lines[0]
    else:
        lines[-1] += " >"
    return tuple(lines)


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


@lru_cache(maxsize=32)
def _resized_winner_submission(width, height, pixels):
    source = Image.frombytes("RGB", (width, height), pixels)
    resized_width = max(1, round(width * 10 / height))
    return source.resize((resized_width, 10), Image.Resampling.LANCZOS)


def _draw_raising_flag(draw, elapsed, flag_codes, ornate=False, pole_x=3, flag_code=None, submissions=None):
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

    if flag_code is None:
        flag_index = int(elapsed / 2.5) % len(flag_codes)
        flag_code = flag_codes[flag_index]
    if submissions is None:
        flag = _resized_winner_flag(flag_code)
    else:
        submission = submissions.get(flag_code)
        flag = _resized_winner_submission(*submission) if submission else None
    if flag is not None:
        rise = int(min(1.0, elapsed / 1.5) * (HEIGHT - flag.height - 4))
        top = HEIGHT - flag.height - rise
        for x in range(flag.width):
            wave = math.sin(elapsed * 6.5 - x * 0.42) * (x / flag.width) ** 1.3 * 2.0
            for y in range(flag.height):
                draw.point((pole_x + 2 + x, round(top + y + wave)), fill=flag.getpixel((x, y)))
    return flag_code


def _draw_perfect_crown(draw, x, y, elapsed):
    period = elapsed % 2.0
    pulse = max(0.0, 1.0 - period / 0.34)
    bright = elapsed < 1.5 or pulse > 0
    crown = (
        "Y...Y...Y",
        "YY..Y..YY",
        "YYYYYYYYY",
        ".YJYJYJY.",
        ".YYYYYYY.",
        "..YYYYY..",
    )
    gold = (255, 205, 55) if not bright else (255, 229, 115)
    for row, pattern in enumerate(crown):
        for column, pixel in enumerate(pattern):
            if pixel == "Y":
                draw.point((x + column, y + row), fill=(255, 250, 190) if bright and row == 0 else gold)
            elif pixel == "J":
                draw.point((x + column, y + row), fill=(255, 70, 55))
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
    perfect_vexillologist = bool(
        winner
        and state["difficulty"] == "vexillologist"
        and winner_attempts >= VEXILLOLOGIST_QUESTION_LIMIT
        and winner["score"] == winner_attempts * 20
    )
    perfect = bool(
        winner
        and (
            (
                state["difficulty"] == "expert"
                and winner_attempts
                and winner["score"] == winner_attempts
                and winner["score"] >= QUESTION_LIMIT
            )
            or perfect_vexillologist
        )
    )
    _draw_fireworks(image, elapsed, state.get("firework_seed", 0), perfect)
    draw = ImageDraw.Draw(image)
    active_flag_code = _draw_raising_flag(
        draw,
        elapsed,
        state["victory_flag_codes"],
        perfect,
    )
    if state["difficulty"] == "vexillologist":
        victory_submissions = state.get("victory_flag_submissions", ())
        if winner and victory_submissions:
            submission_by_code = {
                code: (width, height, pixels)
                for code, width, height, pixels in victory_submissions
            }
            _draw_raising_flag(
                draw,
                elapsed,
                state["victory_flag_codes"],
                ornate=perfect,
                pole_x=105,
                flag_code=active_flag_code,
                submissions=submission_by_code,
            )
    message = winner["name"] + " WINS!" if winner and winner["accuracy"] > 0 else "NO WINNER!" if winner else "IT'S A TIE!"
    message_x = (WIDTH - len(message) * 4) // 2 + 3
    if perfect:
        _draw_perfect_crown(draw, message_x - 11, 15, elapsed)
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
    if state.get("difficulty") == "vexillologist" and state["current"] is not None:
        _draw_vexillologist_question(sign, state)
        return
    if state["current"] is None:
        if state.get("sudden_death_notice"):
            _draw_sudden_death_notice(sign)
        elif state.get("countdown") is not None:
            _draw_countdown(sign, state["countdown"])
        elif state.get("study", {}).get("active"):
            _draw_study(sign, state["study"])
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
        flag.thumbnail((42, 20), Image.Resampling.LANCZOS)
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


def _draw_vexillologist_question(sign, state):
    phase = state.get("vexillologist_phase")
    current = state.get("current")
    if phase == "time_up":
        text = "TIME'S UP!"
        x = (WIDTH - len(text) * 6) // 2
        _draw_outlined_text(sign, sign.fontbig, text, x, 20, graphics.Color(255, 225, 90))
        return
    if phase == "question_pause":
        text = f"QUESTION {state['question_number']}/{state['total']}"
        x = (WIDTH - len(text) * 4) // 2
        _draw_outlined_text(sign, sign.font46, text, x, 18, graphics.Color(46, 210, 255))
        return
    if phase == "comparison":
        result = state.get("vexillologist_comparison")
        if result:
            _draw_vexillologist_comparison(sign, current, result)
        return
    if not current:
        return

    question_number = state["question_number"]
    header = f"SUDDEN DEATH Q{question_number}" if state.get("sudden_death") else f"Q {question_number}/{state['total']}"
    header_x = (WIDTH - len(header) * 4) // 2
    graphics.DrawText(sign.canvas, sign.font46, header_x, 8, graphics.Color(220, 230, 255), header)
    name_lines = _study_name_lines(current["name"], WIDTH // 4)
    if len(name_lines) == 1:
        baselines = (21,)
    else:
        name_lines = name_lines[:2]
        baselines = (17, 24)
    for line, baseline in zip(name_lines, baselines):
        x = (WIDTH - len(line) * 4) // 2
        graphics.DrawText(sign.canvas, sign.font46, x, baseline, graphics.Color(46, 210, 255), line)
    _draw_question_timer(sign, state["time_remaining_fraction"])


def _draw_vexillologist_comparison(sign, current, result):
    submission = Image.frombytes("RGB", (result["width"], result["height"]), bytes(result["pixels"]))
    solution = _raw_flag_image(current["code"]).copy()
    if submission.height != VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT:
        width = round(submission.width * VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT / submission.height)
        submission = submission.resize((width, VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT), Image.Resampling.NEAREST)
    if solution.height != VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT:
        width = round(solution.width * VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT / solution.height)
        solution = solution.resize((width, VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT), Image.Resampling.NEAREST)

    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    image.paste(submission, (0, 0))
    image.paste(solution, (WIDTH - solution.width, 0))
    sign.canvas.SetImage(image, 0, 0)

    font_width = sign.font46.CharacterWidth(ord("A"))
    name_width = (WIDTH - submission.width - solution.width) // font_width
    name = _fit_option(current["name"], name_width * 4)
    name_lines = _study_name_lines(name, name_width)[:4]
    first_baseline = 5 + (VEXILLOLOGIST_COMPARISON_FLAG_HEIGHT - len(name_lines) * 5) // 2
    for index, line in enumerate(name_lines):
        x = (WIDTH - len(line) * 4) // 2
        graphics.DrawText(sign.canvas, sign.font46, x, first_baseline + index * 5, graphics.Color(255, 255, 255), line)

    score_text = f"+{result['score']}/20"
    score_x = (WIDTH - len(score_text) * 4) // 2
    score_color = (
        graphics.Color(255, 70, 70) if result["score"] < 6
        else graphics.Color(255, 160, 50) if result["score"] < 11
        else graphics.Color(255, 225, 70) if result["score"] < 16
        else graphics.Color(100, 255, 130)
    )
    _draw_outlined_text(sign, sign.font46, score_text, score_x, 26, score_color)
    player_name = _fit_option(result["name"], WIDTH // 4)
    player_x = (WIDTH - len(player_name) * 4) // 2
    graphics.DrawText(sign.canvas, sign.font46, player_x, 31, graphics.Color(255, 255, 255), player_name)


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
