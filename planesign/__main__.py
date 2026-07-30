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


from multiprocessing import Process, Manager, Queue

import utilities
import fish
import finance
import satellite
import shared_config
import track_a_flight
import planes
import welcome
import pong
import custom_message
import countdown
import cca
import cgol
import identify
import lightning
import firework
import horse_race
import free_sketch
import weather
import moon
import snow
import snowfall
import santa
import mandelbrot
import planesign
import plants
import api
import signal
import sys
import os
import logging
from modes import DisplayMode

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
    logging.info("Shutdown signal received, exiting gracefully...")
    shared_config.shared_mode.value = DisplayMode.SIGN_OFF.value
    shared_config.shared_forced_sign_update.value = 1
    shared_config.shared_shutdown_event.set()


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

queue_handler = logging.handlers.QueueHandler(logging_queue)

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
utilities.detect_usb_audio_device()

api_server_process = Process(target=api.api_server, name="APIServer")
plane_data_process = Process(target=planes.get_plane_data_worker, name="PlaneData", args=(shared_config.data_dict,))
weather_data_process = Process(target=weather.get_weather_data_worker, name="WeatherData", args=(shared_config.data_dict,))

utilities.read_config()

api_server_process.start()
plane_data_process.start()
weather_data_process.start()

ps = planesign.PlaneSign(defined_mode_handlers)
defined_mode_handlers[DisplayMode.WELCOME](ps, duration=5)
shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value
ps.sign_loop()

logging.info("Sign loop exited, shutting down child processes...")
shared_config.shared_shutdown_event.set()

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

logging_queue.put(None)
listener.join(timeout=5)
if listener.is_alive():
    listener.terminate()
    listener.join(timeout=2)

print("Done.")
