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
from PIL import Image, ImageDraw, ImageEnhance
from rgbmatrix import graphics
from utilities import fix_black

ROUND_SECONDS = 10
EXPERT_ROUND_SECONDS = 20
QUESTION_LIMIT = 25
SUDDEN_DEATH_NOTICE_SECONDS = 3
FIREWORK_SLOT_SECONDS = 0.82
WIDTH = 128
HEIGHT = 32
FLAG_GAME_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datafiles", "flag_game.csv")
FLAG_IMAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons", "flags")
DIFFICULTIES = {"easy": 3, "hard": 4, "expert": 0}
LOADING_FLAG_HEIGHT = 10


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


def _round_seconds(difficulty):
    return EXPERT_ROUND_SECONDS if difficulty == "expert" else ROUND_SECONDS


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
    victory_flag_codes = [country["code"] for country in load_countries()]
    random.shuffle(victory_flag_codes)

    state = {
        "difficulty": difficulty,
        "question_codes": question_codes,
        "regular_question_count": regular_question_count,
        "index": 0,
        "round_id": uuid.uuid4().hex,
        "deadline": now + _round_seconds(difficulty),
        "current": _make_question(question_codes[0], difficulty, pool),
        "answers": {},
        "scores": scores,
        "attempts": {player_id: 0 for player_id in scores},
        "last_result": None,
        "sudden_death": False,
        "sudden_death_notice_until": None,
        "winner_id": None,
        "tie": False,
        "victory_flag_codes": victory_flag_codes,
    }
    with shared_config.shared_games_lock:
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
    winner = _winner_summary(state, players, now)

    return {
        "ok": True,
        "difficulty": state["difficulty"],
        "question_number": state["index"] + 1 if current is not None else state["index"],
        "total": state["regular_question_count"],
        "round_id": state["round_id"],
        "seconds_left": seconds_left,
        "complete": current is None and notice_until is None,
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
        if state is None:
            return {"ok": True, "difficulty": None, "complete": False, "current": None, "players": [], "player": player}

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        state["scores"].setdefault(player["id"], 0)
        state["attempts"].setdefault(player["id"], 0)
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
            return {"difficulty": None, "question_number": 0, "total": 0, "current": None, "complete": False}

        state = dict(state)
        state["scores"] = dict(state["scores"])
        state["answers"] = dict(state["answers"])
        state["attempts"] = dict(state.get("attempts", {}))
        players = dict(shared_config.data_dict.get("game_players", {}))
        if _advance_if_ready(state, players, now):
            shared_config.data_dict["flagquiz_state"] = state
        notice_until = state.get("sudden_death_notice_until")
        return {
            "difficulty": state["difficulty"],
            "question_number": state["index"] + 1 if state["current"] is not None else state["index"],
            "total": state["regular_question_count"],
            "current": state["current"],
            "complete": state["current"] is None and notice_until is None,
            "sudden_death": state["sudden_death"],
            "sudden_death_notice": notice_until is not None,
            "tie": state["tie"],
            "winner": _winner_summary(state, players, now),
            "victory_flag_codes": state["victory_flag_codes"],
        }


@lru_cache(maxsize=1)
def _flag_image(code):
    with Image.open(os.path.join(FLAG_IMAGE_DIR, f"{code}.png")) as image:
        image = image.convert("RGB")
        if code != "NPL" and code != "OH":
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


def _draw_loading(sign, elapsed):
    _draw_scrolling_flags(sign, elapsed)
    text = "CHOOSE LEVEL"
    x = (WIDTH - len(text) * 6) // 2
    _draw_outlined_text(sign, sign.fontbig, text, x, 19, graphics.Color(46, 210, 255))


@lru_cache(maxsize=32)
def _firework_shell(slot):
    rng = random.Random(0xF17E + slot * 104729)
    palette = ((255, 75, 45), (255, 180, 50), (80, 170, 255), (230, 90, 255), (90, 255, 160), (255, 245, 190))
    color = rng.choice(palette)
    kind = rng.choice(("peony", "peony", "ring", "willow"))
    count = rng.randint(30, 38)
    radius = rng.uniform(8, 12)
    angle_offset = rng.uniform(0, math.tau)
    particles = []
    for index in range(count):
        angle = angle_offset + math.tau * index / count + rng.uniform(-0.08, 0.08)
        spread = rng.uniform(0.82, 1.05) if rng.random() < 0.7 else rng.uniform(0.35, 0.65)
        speed = radius * spread / 1.4
        particle_color = (255, 248, 220) if rng.random() < 0.2 else color
        particles.append((
            angle,
            speed,
            rng.uniform(1.7, 2.2) if kind == "willow" else rng.uniform(1.5, 2.0),
            particle_color,
            rng.random(),
            rng.uniform(4.0, 9.0),
            rng.uniform(0.25, 0.85),
        ))
    return (
        slot * FIREWORK_SLOT_SECONDS + rng.uniform(0.05, 0.35),
        rng.uniform(30, 112),
        rng.uniform(9, 17),
        rng.uniform(0.55, 0.85),
        3.5 if kind == "willow" else 2.0,
        tuple(particles),
    )


def _add_firework_pixel(pixels, x, y, color, brightness):
    x, y = round(x), round(y)
    if not 0 <= x < WIDTH or not 0 <= y < HEIGHT or brightness < 0.025:
        return
    old = pixels[x, y]
    pixels[x, y] = tuple(min(255, channel + round(value * brightness)) for channel, value in zip(old, color))


def _draw_fireworks(image, elapsed):
    pixels = image.load()
    last_slot = math.floor(elapsed / FIREWORK_SLOT_SECONDS)
    first_slot = math.floor((elapsed - 3.1) / FIREWORK_SLOT_SECONDS)
    for slot in range(first_slot, last_slot + 1):
        launch, burst_x, burst_y, rise, gravity, particles = _firework_shell(slot)
        age = elapsed - launch
        if age < 0 or age >= rise + 2.2:
            continue

        if age < rise:
            progress = age / rise
            eased = 1 - (1 - progress) ** 1.4
            rocket_x = 64 + (burst_x - 64) * eased
            rocket_y = HEIGHT - 1 + (burst_y - (HEIGHT - 1)) * eased
            for trail_step, brightness in ((0.0, 1.0), (0.09, 0.48), (0.18, 0.2)):
                trail_progress = max(0, age - trail_step) / rise
                trail_eased = 1 - (1 - trail_progress) ** 1.4
                trail_x = 64 + (burst_x - 64) * trail_eased
                trail_y = HEIGHT - 1 + (burst_y - (HEIGHT - 1)) * trail_eased
                _add_firework_pixel(pixels, trail_x, trail_y, (255, 214, 150), brightness)
            _add_firework_pixel(pixels, rocket_x, rocket_y, (255, 255, 235), 1.0)
            continue

        burst_age = age - rise
        if burst_age < 0.09:
            _add_firework_pixel(pixels, burst_x, burst_y, (255, 255, 235), 1.0 - burst_age / 0.09)

        for angle, speed, lifetime, color, phase, frequency, twinkle_depth in particles:
            for trail_step, trail_weight in ((0.0, 1.0), (0.13, 0.48), (0.26, 0.22)):
                particle_age = burst_age - trail_step
                if not 0 <= particle_age < lifetime:
                    continue
                fade = (1 - particle_age / lifetime) ** 1.45
                twinkle = 1 - twinkle_depth * (0.5 - 0.5 * math.sin(math.tau * (elapsed * frequency + phase)))
                distance = speed * particle_age
                x = burst_x + math.cos(angle) * distance
                y = burst_y + math.sin(angle) * distance * 0.72 + gravity * particle_age**2
                _add_firework_pixel(pixels, x, y, color, fade * twinkle * trail_weight)


@lru_cache(maxsize=256)
def _resized_winner_flag(code):
    source = _flag_image(code)
    width = max(1, round(source.width * 10 / source.height))
    return source.resize((width, 10), Image.Resampling.LANCZOS)


def _draw_raising_flag(draw, elapsed, flag_codes):
    pole_x = 3
    draw.line((pole_x, 0, pole_x, HEIGHT - 1), fill=(150, 150, 165))
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


def _draw_victory(sign, state, elapsed):
    image = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    _draw_fireworks(image, elapsed)
    draw = ImageDraw.Draw(image)
    _draw_raising_flag(draw, elapsed, state["victory_flag_codes"])
    sign.canvas.SetImage(image, 0, 0)

    winner = state.get("winner")
    title = "FLAG CHAMPION!" if winner else "QUIZ COMPLETE!"
    title_x = (WIDTH - len(title) * 5) // 2
    title_color = graphics.Color(46, 210, 255) if int(elapsed * 3) % 2 == 0 else graphics.Color(255, 220, 80)
    _draw_outlined_text(sign, sign.font57, title, title_x, 9, title_color)

    message = winner["name"] + " WINS!" if winner else "IT'S A TIE!"
    message_x = (WIDTH - len(message) * 4) // 2
    message_color = graphics.Color(255, 240, 150) if int(elapsed * 3) % 2 == 0 else graphics.Color(130, 255, 150)
    _draw_outlined_text(sign, sign.font46, message, message_x, 20, message_color)
    if winner:
        accuracy = f"ACCURACY {winner['accuracy']}%"
        accuracy_x = (WIDTH - len(accuracy) * 4) // 2
        _draw_outlined_text(sign, sign.font46, accuracy, accuracy_x, 30, graphics.Color(130, 255, 150))


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
    words = text.split()
    while words and len(" ".join(words)) + 3 > max_chars:
        words.pop()
    return " ".join(words) + "..." if words else text[:max_chars - 3] + "..."


def _draw_question(sign, state, elapsed=0.0):
    sign.canvas.Clear()
    if state["current"] is None:
        if state.get("sudden_death_notice"):
            _draw_sudden_death_notice(sign)
        elif state["complete"]:
            _draw_victory(sign, state, elapsed)
        else:
            _draw_loading(sign, elapsed)
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
