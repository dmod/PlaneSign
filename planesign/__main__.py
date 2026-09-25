import os
import sys

if "--web" in sys.argv:
    sys.argv.remove("--web")
    os.environ["PLANESIGN_EMULATED_DISPLAY"] = "1"
    import emulated_matrix

    sys.modules["rgbmatrix"] = emulated_matrix

from functools import wraps

from modes import DisplayMode

defined_mode_handlers = {}


def planesign_mode_handler(mode: DisplayMode):
    """Decorator to register mode handlers"""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        defined_mode_handlers[mode] = wrapper
        return wrapper

    return decorator


import logging
import os
import signal
import sys
from multiprocessing import Manager, Process, Queue

import api
import cca
import cgol
import countdown
import custom_message
import finance
import firework
import fish
import free_sketch
import horse_race
import identify
import lightning
import mandelbrot
import mlb
import moon
import nfl
import planes
import plants
import pong
import santa
import satellite
import shared_config
import snow
import snowfall
import tides
import track_a_flight
import utilities
import weather
import welcome
from modes import DisplayMode

import planesign

manager = Manager()
shared_config.data_dict = manager.dict()
shared_config.arg_dict = manager.dict()
shared_config.CONF = manager.dict()
shared_config.shared_shutdown_event = manager.Event()

shared_config.data_dict["closest"] = None
shared_config.data_dict["highest"] = None
shared_config.data_dict["fastest"] = None
shared_config.data_dict["slowest"] = None


def exit_gracefully(*args):
    # Only lock-free shared memory is safe here; see shared_config.shutdown_requested.
    shared_config.shutdown_requested.value = 1


signal.signal(signal.SIGINT, exit_gracefully)
signal.signal(signal.SIGTERM, exit_gracefully)


def log_file_rotation_namer(default_name):
    base_filename, ext, date = default_name.split(".")
    return f"{base_filename}.{date}.{ext}"


def log_listener_process(queue):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    root = logging.getLogger()

    os.makedirs(os.path.dirname(shared_config.log_filename), exist_ok=True)
    log_handler = logging.handlers.TimedRotatingFileHandler(shared_config.log_filename, when="midnight", backupCount=90)
    log_handler.namer = log_file_rotation_namer
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(processName)-10s %(name)s %(levelname)-8s %(message)s"))

    root.addHandler(log_handler)

    while True:
        try:
            record = queue.get(timeout=1)
        except Exception:
            if shared_config.shared_shutdown_event.is_set():
                break
            continue
        if record is None:
            break
        root.handle(record)


logging_queue = Queue(-1)
listener = Process(target=log_listener_process, args=(logging_queue,))
listener.start()

_STANDARD_LOG_RECORD_KEYS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message", "asctime"}


class SanitizingQueueHandler(logging.handlers.QueueHandler):
    # Libraries attach live objects to records via `extra` (websockets adds the connection), which
    # the queue feeder thread cannot pickle, so the record is silently dropped from the log file.
    def prepare(self, record):
        record = super().prepare(record)
        for key, value in list(record.__dict__.items()):
            if key in _STANDARD_LOG_RECORD_KEYS or value is None or isinstance(value, (str, int, float, bool)):
                continue
            try:
                record.__dict__[key] = repr(value)
            except Exception:  # noqa: BLE001 - a broken __repr__ must never break logging
                record.__dict__[key] = object.__repr__(value)
        return record


queue_handler = SanitizingQueueHandler(logging_queue)

console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
console_handler.setFormatter(console_formatter)

root = logging.getLogger()
root.addHandler(queue_handler)
root.addHandler(console_handler)
root.setLevel(logging.DEBUG)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("fiona.ogrext").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)

utilities.read_static_airport_data()
utilities.read_static_country_data()
utilities.detect_usb_audio_device()

api_server_process = Process(target=api.api_server, name="APIServer")
plane_data_process = Process(target=planes.get_plane_data_worker, name="PlaneData", args=(shared_config.data_dict,))
weather_data_process = Process(target=weather.get_weather_data_worker, name="WeatherData", args=(shared_config.data_dict,))
tides_data_process = Process(target=tides.get_tides_data_worker, name="TidesData", args=(shared_config.data_dict,))
nfl_data_process = Process(target=nfl.get_nfl_data_worker, name="NFLData", args=(shared_config.data_dict,))
mlb_data_process = Process(target=mlb.get_mlb_data_worker, name="MLBData", args=(shared_config.data_dict,))

utilities.read_config()

api_server_process.start()
plane_data_process.start()
weather_data_process.start()
tides_data_process.start()
nfl_data_process.start()
mlb_data_process.start()

ps = planesign.PlaneSign(defined_mode_handlers)
defined_mode_handlers[DisplayMode.WELCOME](ps, duration=5)
shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value
ps.sign_loop()

logging.info("Sign loop exited, shutting down child processes...")
shared_config.shared_mode.value = DisplayMode.SIGN_OFF.value
shared_config.shared_shutdown_event.set()
shared_config.shared_forced_sign_update.set()

api_server_process.join(timeout=5)
if api_server_process.is_alive():
    logging.warning("API server did not exit in time, terminating...")
    api_server_process.terminate()
    api_server_process.join(timeout=2)

plane_data_process.join(timeout=10)
if plane_data_process.is_alive():
    logging.warning("Plane data process did not exit in time, terminating...")
    plane_data_process.terminate()
    plane_data_process.join(timeout=2)

weather_data_process.join(timeout=10)
if weather_data_process.is_alive():
    logging.warning("Weather data process did not exit in time, terminating...")
    weather_data_process.terminate()
    weather_data_process.join(timeout=2)

tides_data_process.join(timeout=10)
if tides_data_process.is_alive():
    logging.warning("Tides data process did not exit in time, terminating...")
    tides_data_process.terminate()
    tides_data_process.join(timeout=2)

nfl_data_process.join(timeout=10)
if nfl_data_process.is_alive():
    logging.warning("NFL data process did not exit in time, terminating...")
    nfl_data_process.terminate()
    nfl_data_process.join(timeout=2)

mlb_data_process.join(timeout=10)
if mlb_data_process.is_alive():
    logging.warning("MLB data process did not exit in time, terminating...")
    mlb_data_process.terminate()
    mlb_data_process.join(timeout=2)

logging_queue.put(None)
listener.join(timeout=5)
if listener.is_alive():
    listener.terminate()
    listener.join(timeout=2)

print("Done.")
