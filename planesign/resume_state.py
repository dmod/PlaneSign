"""State the user set from the web UI, kept across a restart so the nightly update or a reboot leaves the
sign as they had it instead of lighting up with WELCOME and sign.conf's startup values in the middle of
the night.

A clean shutdown saves every field to datafiles/resume_state.json, and the next start applies the file
on top of sign.conf's values and deletes it. A crash or power loss leaves no file, so the sign starts
fresh. It is in datafiles/ because the container keeps only its bind mounts. The --web emulator never
uses it: it shares the workspace with the production sign.

To keep more state, add a field to FIELDS. Each one reads its live value, checks a saved value and puts
it back the same way, and an invalid saved value drops only that field."""

import json
import logging
import os
from collections.abc import Callable
from datetime import datetime
from typing import Any, NamedTuple

import shared_config
import utilities
from api import MAX_COLOR_MODE
from modes import DisplayMode, startup_mode_names

PATH = os.path.join(shared_config.datafiles_dir, "resume_state.json")


class Field(NamedTuple):
    read: Callable[[Any], Any]  # (sign) -> JSON value to save, or None to leave the field out
    parse: Callable[[Any], Any]  # saved JSON value -> live value; raises ValueError or TypeError if it is invalid
    apply: Callable[[Any], None] | None  # puts the live value back; None when __main__ uses it itself


def int_from(low, high):
    def parse(value):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"not a whole number from {low} to {high}")
        return value

    return parse


def text(value):
    if not isinstance(value, str):
        raise TypeError("not text")
    return value


def startup_mode(value):
    if value not in startup_mode_names():
        raise ValueError("not a mode the sign can start in")
    return value


def shared_value(shared, parse):
    """A multiprocessing Value that holds the field as it is saved."""

    def apply(value):
        shared.value = value

    return Field(lambda sign: shared.value, parse, apply)


def read_mode(sign):
    # shared_mode already reads SIGN_OFF during shutdown (wait_loop sets it), so use the mode the loop last ran.
    name = sign.current_mode.name if sign.current_mode else None
    return name if name in startup_mode_names() else None


def set_prev_mode(name):
    shared_config.shared_prev_mode.value = DisplayMode[name].value


def read_custom_message(sign):
    return shared_config.data_dict.get("custom_message")


def set_custom_message(message):
    shared_config.data_dict["custom_message"] = message


# The countdown mode reads the message whenever a date is set, so the two are saved and restored together.
def read_countdown(sign):
    if "countdown_datetime" not in shared_config.data_dict:
        return None
    return {"datetime": shared_config.data_dict["countdown_datetime"].isoformat(), "message": shared_config.data_dict.get("countdown_message", "")}


def parse_countdown(value):
    if not isinstance(value, dict):
        raise TypeError("not a countdown")
    return datetime.fromisoformat(text(value.get("datetime"))), text(value.get("message"))


def set_countdown(countdown):
    shared_config.data_dict["countdown_datetime"], shared_config.data_dict["countdown_message"] = countdown


FIELDS = {
    # Used by __main__ to choose the startup mode, and to skip WELCOME when it is resumed.
    "mode": Field(read_mode, startup_mode, None),
    # Where /turn_on returns to.
    "prev_mode": Field(lambda sign: DisplayMode(shared_config.shared_prev_mode.value).name, startup_mode, set_prev_mode),
    "brightness": shared_value(shared_config.shared_current_brightness, int_from(0, 100)),
    # None, and so not saved, without a USB speaker.
    "volume": Field(lambda sign: utilities.get_usb_audio_volume(), int_from(0, 100), utilities.set_usb_audio_volume),
    # Shared by the custom message and the countdown.
    "color_mode": shared_value(shared_config.shared_color_mode, int_from(0, MAX_COLOR_MODE)),
    "custom_message": Field(read_custom_message, text, set_custom_message),
    "countdown": Field(read_countdown, parse_countdown, set_countdown),
}


def save(sign):
    """Write every field that has a value. Called once the sign loop has stopped cleanly."""
    state = {}
    for name, field in FIELDS.items():
        try:
            value = field.read(sign)
        except (OSError, EOFError, ValueError) as error:  # the Manager behind data_dict can already be gone after Ctrl+C
            logging.warning(f"Not saving {name} for the next start: {error!r}")
            continue
        if value is not None:
            state[name] = value
    try:
        with open(PATH, "w") as f:
            json.dump(state, f)
        logging.info(f"Saved {state} for the next start")
    except OSError as error:
        logging.warning(f"Cannot save {PATH}: {error}")


def take():
    """The valid saved fields, parsed, or None without a file. Deletes the file so it is used only once."""
    try:
        with open(PATH) as f:
            saved = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logging.warning(f"Ignoring unreadable {PATH}: {error}")
        saved = {}
    try:
        os.remove(PATH)
    except OSError as error:
        logging.warning(f"Cannot remove {PATH}: {error}")
    if not isinstance(saved, dict):
        logging.warning(f"Ignoring {PATH}, which is not a JSON object")
        return None

    state = {}
    for name, field in FIELDS.items():
        if name in saved:
            try:
                state[name] = field.parse(saved[name])
            except (ValueError, TypeError) as error:
                logging.warning(f"Ignoring saved {name} {saved[name]!r}: {error}")
    return state or None


def apply(state):
    for name, value in state.items():
        if FIELDS[name].apply is not None:
            FIELDS[name].apply(value)
