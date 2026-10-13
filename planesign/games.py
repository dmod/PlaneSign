import random
import time
import uuid

import shared_config

ACTIVE_PLAYER_SECONDS = 30
MAX_PLAYER_NAME_LENGTH = 24

_NAME_ADJECTIVES = ("Amber", "Bright", "Calm", "Clever", "Cosmic", "Curious", "Jolly", "Lucky", "Misty", "Swift")
_NAME_NOUNS = ("Badger", "Comet", "Crane", "Fox", "Heron", "Kite", "Otter", "Panda", "Robin", "Tiger")


def normalize_player_id(player_id):
    try:
        return str(uuid.UUID(player_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("player_id must be a valid UUID") from error


def normalize_player_name(name):
    if not isinstance(name, str):
        raise ValueError("name must be a string")
    name = " ".join(name.split())
    if not name or len(name) > MAX_PLAYER_NAME_LENGTH:
        raise ValueError(f"name must be 1 to {MAX_PLAYER_NAME_LENGTH} characters")
    return name


def register_player(player_id, name=None):
    player_id = normalize_player_id(player_id)
    if name is not None:
        name = normalize_player_name(name)

    with shared_config.shared_games_lock:
        players = dict(shared_config.data_dict.get("game_players", {}))
        player = players.get(player_id)
        if player is None:
            player = {
                "name": name or f"{random.choice(_NAME_ADJECTIVES)} {random.choice(_NAME_NOUNS)}",
                "last_seen": time.monotonic(),
            }
        else:
            player = dict(player)
            if name is not None:
                player["name"] = name
            player["last_seen"] = time.monotonic()
        players[player_id] = player
        shared_config.data_dict["game_players"] = players

    return {"id": player_id, "name": player["name"]}


def get_players():
    with shared_config.shared_games_lock:
        return dict(shared_config.data_dict.get("game_players", {}))
