import logging
import os
from multiprocessing import Array, Event, Value

from modes import DisplayMode

shared_mode = Value("i", DisplayMode.WELCOME.value)
shared_prev_mode = Value("i", DisplayMode.PLANES_ALERT.value)
shared_games_lock = None

# Mode to fall back to once the transient IDENTIFY flash finishes.
shared_identify_return_mode = Value("i", DisplayMode.PLANES_ALERT.value)

shared_pong_player1 = Value("i", 0)
shared_pong_player2 = Value("i", 0)

shared_current_brightness = Value("i", 80)
shared_color_mode = Value("i", 0)
shared_forced_sign_update = Event()
# Set when a plane mode starts, so the paused FR24 worker (planes.get_plane_data_worker) fetches right away.
shared_plane_data_wake = Event()

shared_satellite_mode = Value("i", 1)

shared_lightning_zoomind = Value("i", 6)
shared_lightning_mode = Value("i", 1)

shared_halloween_lightning = Value("i", 1)

shared_mandelbrot_color = Value("i", 0)
shared_mandelbrot_colorscale = Value("d", 3)

shared_snow_mode = Value("i", 1)

shared_outside_offset_minutes = Value("i", 0)
shared_outside_time_update = Event()
# Outside lab overrides (outside_lab.py). Lab time is [base, real_anchor, speed], read like clock_state;
# a zero base means Outside follows the sign clock. The lab's weather override lives in data_dict.
shared_outside_lab_clock = Array("d", [0.0, 0.0, 1.0])
# time.monotonic() of the last lab action; the overrides expire after outside.LAB_IDLE_SECONDS.
shared_outside_lab_activity = Value("d", 0.0)
# Bumped on every lab change so the Outside loop picks it up on the next frame.
shared_outside_lab_version = Value("i", 0)

free_sketch_pixels = Array("B", 128 * 32 * 3)

# Wall clock as [fake_base, real_base, speed]: now = fake_base + (time.time() - real_base) * speed.
# The default [0, 0, 1] is the real clock. Read and set it through psclock.py.
clock_state = Array("d", [0.0, 0.0, 1.0])

# Signal handlers run on the main thread between bytecodes, so they may only touch lock-free
# shared memory. Anything holding a lock (logging, Event.set(), manager proxies) deadlocks when
# the handler interrupts the same lock, which is why shutdown is requested through this flag and
# acted on by the main loop instead.
shutdown_requested = Value("b", 0, lock=False)

local_timezone = None

# True when running with --web (emulated matrix streamed to a browser). In that case there is
# no audio hardware attached to the sign, so sound playback is delegated to the browser.
emulated_display = os.environ.get("PLANESIGN_EMULATED_DISPLAY") == "1"

# Set once by utilities.detect_usb_audio_device() in the parent process, before the API server
# process is forked, so the API process inherits them.
audio_device = None
audio_card = None
audio_mixer_control = None

log_filename = os.environ.get("PLANESIGN_LOG_FILE", "logs/planesign.log")
icons_dir = "./icons"

font_dir = "./fonts"

sounds_dir = "sounds"
datafiles_dir = "./datafiles"

# Overridable from the command line (see __main__.parse_args) so a second instance can run alongside the first.
# Avoid 5000/5001/7000: macOS AirPlay Receiver listens on those and Docker Desktop's host
# networking leaks them into the container's loopback, which silently hijacks the ports.
api_port = 5055
ws_port = 5056
config_path = "sign.conf"
config_overrides = {}

shared_shutdown_event = None
data_dict = None
arg_dict = None
CONF = None

code_to_airport = {}
country_name_to_code = {}


def load_config_schema():
    """Read defaults and '#type [secret] [min/max/step value] - description' metadata."""
    defaults = {}
    datatypes = []
    metadata = None
    with open("sign.conf.sample") as f:
        for number, raw_line in enumerate(f, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                annotation, separator, description = line[1:].partition(" - ")
                tokens = annotation.split()
                if not separator or not description.strip() or not tokens or tokens[0] not in {"text", "checkbox", "select", "number", "range"}:
                    raise ValueError(f"Invalid config metadata on line {number} of sign.conf.sample")
                metadata = {"type": tokens[0], "secret": False, "description": description.strip()}
                index = 1
                while index < len(tokens):
                    token = tokens[index]
                    if token == "secret":
                        metadata["secret"] = True
                        index += 1
                    elif token in {"min", "max", "step"} and index + 1 < len(tokens):
                        metadata[token] = tokens[index + 1]
                        index += 2
                    else:
                        raise ValueError(f"Invalid config metadata on line {number} of sign.conf.sample")
                continue
            key, separator, value = line.partition("=")
            if not separator or not key or metadata is None or key in defaults:
                raise ValueError(f"Invalid config setting on line {number} of sign.conf.sample")
            defaults[key] = value
            datatypes.append({"id": key, **metadata})
            metadata = None
    if metadata is not None:
        raise ValueError("Config metadata has no setting in sign.conf.sample")
    return defaults, datatypes


def config_for_logging(conf):
    """Copy config, exposing only presence markers for secret or unrecognized settings."""
    _, datatypes = load_config_schema()
    public_keys = {item["id"] for item in datatypes if not item["secret"]}
    return {key: value if key in public_keys else "<set>" if value else "<unset>" for key, value in conf.items()}


def load_config_values(*, log_settings=True):
    """Read configuration without importing a display driver or changing shared state."""
    conf = {}
    if not os.path.exists(config_path):
        if log_settings:
            logging.warning(f"WARNING! No {config_path} found... using default values from sign.conf.sample")
    else:
        with open(config_path) as f:
            for line in f:
                if line.isspace() or line.startswith("#"):
                    continue
                key, val = line.split("=", 1)
                conf[key] = val.rstrip()

    defaults, _ = load_config_schema()
    for key, value in defaults.items():
        if key not in conf:
            if log_settings:
                logging.warning(f"WARNING! No setting for '{key}' found in {config_path}, using the default from sign.conf.sample")
            conf[key] = value

    if config_overrides:
        if log_settings:
            logging.info(f"Overriding config from the command line: {', '.join(config_overrides)}")
        conf.update(config_overrides)
    return conf


def shutdown_in_progress():
    return bool(shutdown_requested.value) or (shared_shutdown_event is not None and shared_shutdown_event.is_set())
