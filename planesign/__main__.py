import argparse
import multiprocessing
import os
import sys
from datetime import datetime

# Python 3.14 made forkserver the Linux default. Children must inherit the module-level setup below
# (shared_config state, Manager proxies, the selected rgbmatrix driver) instead of re-running this script.
multiprocessing.set_start_method("fork")


def parse_args():
    parser = argparse.ArgumentParser(prog="planesign", description="Drive the PlaneSign LED matrix or OLED display.")
    parser.add_argument("--web", action="store_true", help="emulate the matrix and stream frames to web/display.html instead of driving hardware")
    parser.add_argument("--mode", type=str.upper, metavar="MODE", help="mode to show after the welcome screen, e.g. MOON (default DEFAULT_MODE from the config)")
    parser.add_argument("--fake-time", metavar="ISO_TIME", help="start the clock at this time, e.g. 2026-12-24T18:00; without an offset it is local to the sign's location")
    parser.add_argument("--time-speed", type=float, default=1.0, metavar="FACTOR", help="run the clock this many times faster than real time (default 1)")
    parser.add_argument("--config", default="sign.conf", metavar="PATH", help="config file to read and to save settings to (default sign.conf)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE", help="override a config value for this run without changing the config file; repeatable")
    parser.add_argument("--api-port", type=int, metavar="PORT", help="port for the Flask API (default 5055)")
    parser.add_argument("--ws-port", type=int, metavar="PORT", help="port for the --web frame stream and frame capture (default 5056)")
    args = parser.parse_args()

    from modes import DisplayMode

    if args.mode and args.mode not in DisplayMode.__members__:
        parser.error(f"unknown mode {args.mode}; choose from {', '.join(DisplayMode.__members__)}")
    if not 0 < args.time_speed < float("inf"):
        parser.error("--time-speed must be a positive number")
    if args.fake_time:
        try:
            datetime.fromisoformat(args.fake_time)
        except ValueError:
            parser.error(f"--fake-time {args.fake_time!r} is not an ISO 8601 time")

    with open("sign.conf.sample") as f:
        known_keys = {line.split("=")[0] for line in f if "=" in line and not line.startswith("#")}
    args.overrides = {}
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep or key not in known_keys:
            parser.error(f"--set {item!r} must be KEY=VALUE with a key from sign.conf.sample")
        args.overrides[key] = value

    return args


cli_args = parse_args()

if cli_args.web:
    os.environ["PLANESIGN_EMULATED_DISPLAY"] = "1"
else:
    os.environ.pop("PLANESIGN_EMULATED_DISPLAY", None)

import shared_config

# Select the driver before importing modes, which all import rgbmatrix.
shared_config.config_path = cli_args.config
shared_config.config_overrides = cli_args.overrides
if cli_args.api_port:
    shared_config.api_port = cli_args.api_port
if cli_args.ws_port:
    shared_config.ws_port = cli_args.ws_port

startup_conf = shared_config.load_config_values(log_settings=False)
if startup_conf["PINOUT_HARDWARE_MAPPING"] == "adafruit-oled":
    import oled_matrix

    sys.modules["rgbmatrix"] = oled_matrix
elif cli_args.web:
    import emulated_matrix

    sys.modules["rgbmatrix"] = emulated_matrix

import atexit
import ctypes
import logging
import logging.handlers
import os
import signal
import sys
import threading
import traceback
from multiprocessing import Pipe, Process, Queue, current_process
from multiprocessing.managers import SyncManager
from queue import Empty as QueueEmpty

import api
import cca
import cgol
import countdown
import custom_message
import finance
import firework
import flagquiz
import fish
import free_sketch
import halloween
import horse_race
import identify
import lightning
import mandelbrot
import mlb
import moon
import nfl
import outside
import planes
import plants
import pong
import psclock
import santa
import satellite
import shared_config
import slime
import snow
import snowfall
import tides
import track_a_flight
import utilities
import weather
import welcome
from modes import DisplayMode, defined_mode_handlers, startup_mode_names

import planesign

main_pid = os.getpid()
_PR_SET_PDEATHSIG = 1
_libc = ctypes.CDLL(None, use_errno=True)


def die_with_parent():
    # A SIGKILL'd sign cannot stop its children, which would keep running and hold port 5055, so have
    # the kernel kill them with it. The signal fires when the *thread* that started the child exits, so
    # start every child from the main thread. Under Docker, PID 1 dying already ends the container.
    _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
    if os.getppid() != main_pid:  # the sign died before prctl took effect
        os._exit(1)


manager = SyncManager()
manager.start(initializer=die_with_parent)
shared_config.shared_games_lock = manager.RLock()
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
    # planesign.log.2026-10-19 -> planesign.2026-10-19.log, whatever dots the folders' names contain
    base, date = default_name.rsplit(".", 1)
    stem, ext = os.path.splitext(base)
    return f"{stem}.{date}{ext}"


def open_log_file():
    os.makedirs(os.path.dirname(os.path.abspath(shared_config.log_filename)), exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(shared_config.log_filename, when="midnight", backupCount=30)
    handler.namer = log_file_rotation_namer
    handler.setFormatter(logging.Formatter("%(asctime)s %(processName)-10s %(name)s %(levelname)-8s %(message)s"))
    return handler


def drop_root_to_log_folder_owner():
    # The sign runs as root for the panel driver, but logs/ belongs to pi. Writing as its owner keeps
    # every log file, including each new one after a midnight rollover, editable over SSH and from
    # the devcontainer. The folder may not exist yet; then its nearest existing parent decides.
    folder = os.path.dirname(os.path.abspath(shared_config.log_filename))
    while not os.path.isdir(folder):
        folder = os.path.dirname(folder)
    owner = os.stat(folder)
    log_path = os.path.abspath(shared_config.log_filename)
    # A log an earlier root run left behind could no longer be appended to.
    if os.path.isfile(log_path) and os.stat(log_path).st_uid != owner.st_uid:
        os.chown(log_path, owner.st_uid, owner.st_gid)
    os.setgroups([])
    os.setgid(owner.st_gid)
    os.setuid(owner.st_uid)


def run_log_writer(records, status):
    # Ctrl+C reaches the whole process group; the writer must outlive the shutdown it is logging.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:
        if os.geteuid() == 0:
            drop_root_to_log_folder_owner()
        file_handler = open_log_file()
    except Exception as error:  # noqa: BLE001 - reported to the sign, which falls back to the console
        status.send(f"{type(error).__name__}: {error}")
        return
    status.send(None)
    status.close()

    # Only the None from stop_log_writer ends this loop, so records logged late in shutdown still
    # reach the file. A record that cannot be unpickled must not end logging for the whole sign.
    while True:
        try:
            record = records.get(timeout=1)
        except QueueEmpty:
            # Not die_with_parent: a SIGKILL would drop the records still in the pipe, and dropping
            # root clears the parent-death signal anyway.
            if os.getppid() != main_pid:
                return  # the sign died without stopping the writer
            continue
        except (EOFError, OSError):
            return
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        if record is None:
            return
        file_handler.handle(record)


# Every process logs into this queue, and the LogWriter process writes the file without root.
# If it cannot start, nothing may log into the queue: with no reader, the pipe fills up and blocks
# every process's logging and its exit.
logging_queue = Queue(-1)
log_writer_status, log_writer_status_sender = Pipe(duplex=False)
log_writer = Process(target=run_log_writer, args=(logging_queue, log_writer_status_sender), name="LogWriter", daemon=True)
log_writer.start()
log_writer_status_sender.close()
if log_writer_status.poll(10):
    try:
        log_file_error = log_writer_status.recv()
    except EOFError:
        log_file_error = "the log writer exited while starting"
else:
    log_file_error = "the log writer did not start within 10 s"
log_writer_status.close()
if log_file_error is not None:
    if log_writer.is_alive():
        log_writer.kill()
    log_writer.join(timeout=2)
    log_writer = None


def stop_log_writer():
    if log_writer is None or os.getpid() != main_pid:
        return
    if log_writer.is_alive():
        logging_queue.put(None)
        log_writer.join(timeout=5)
        if log_writer.is_alive():
            log_writer.kill()
            log_writer.join(timeout=2)
    # Nothing reads the queue any more, so don't let records logged after this block interpreter exit.
    logging_queue.cancel_join_thread()


# Also covers a crash before the main try block below; atexit runs after sys.excepthook has logged it.
atexit.register(stop_log_writer)

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


class SuccessfulRequestFilter(logging.Filter):
    # werkzeug logs every request at INFO with (request line, status, size) as args. The web UI's
    # polling made those over half of all log lines, so only keep requests that failed.
    def filter(self, record):
        args = record.args
        return not (isinstance(args, tuple) and len(args) == 3 and str(args[1])[:1] in ("1", "2", "3"))


# The file keeps DEBUG; stdout (docker logs, the terminal) only needs INFO and up.
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_formatter = logging.Formatter("%(asctime)s [%(levelname)s] - %(message)s")
console_handler.setFormatter(console_formatter)

root = logging.getLogger()
if log_writer is not None:
    root.addHandler(queue_handler)
root.addHandler(console_handler)
root.setLevel(logging.DEBUG)
logging.getLogger("PIL").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("fiona.ogrext").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("werkzeug").addFilter(SuccessfulRequestFilter())
if log_file_error is not None:
    logging.error(f"Cannot open {shared_config.log_filename} ({log_file_error}); logging to the console only")


# Uncaught exceptions would otherwise go only to stderr, which the classic install discards.
# Child processes inherit both hooks.
def log_uncaught_exception(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logging.critical(f"Uncaught exception in {current_process().name}", exc_info=(exc_type, exc_value, exc_tb))


def log_uncaught_thread_exception(args):
    if issubclass(args.exc_type, SystemExit):
        return
    thread_name = args.thread.name if args.thread is not None else "an unknown thread"
    logging.critical(f"Uncaught exception in {current_process().name} thread {thread_name}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


sys.excepthook = log_uncaught_exception
threading.excepthook = log_uncaught_thread_exception


def run_worker(target, *args):
    die_with_parent()
    # multiprocessing prints a worker's uncaught exception to stderr only, so log it here instead.
    try:
        target(*args)
    except Exception:
        logging.exception(f"{current_process().name} crashed; its data stops updating until the sign restarts")
        sys.exit(1)


utilities.read_static_airport_data()
utilities.read_static_country_data()
utilities.detect_usb_audio_device()

api_server_process = Process(target=run_worker, name="APIServer", args=(api.api_server,))
plane_data_process = Process(target=run_worker, name="PlaneData", args=(planes.get_plane_data_worker, shared_config.data_dict))
weather_data_process = Process(target=run_worker, name="WeatherData", args=(weather.get_weather_data_worker, shared_config.data_dict))
tides_data_process = Process(target=run_worker, name="TidesData", args=(tides.get_tides_data_worker, shared_config.data_dict))
nfl_data_process = Process(target=run_worker, name="NFLData", args=(nfl.get_nfl_data_worker, shared_config.data_dict))
mlb_data_process = Process(target=run_worker, name="MLBData", args=(mlb.get_mlb_data_worker, shared_config.data_dict))
outside_data_process = Process(target=run_worker, name="OutsideData", args=(outside.get_outside_data_worker, shared_config.data_dict))

utilities.read_config()

# After read_config, which sets the local timezone that --fake-time values without an offset are read in
if cli_args.fake_time or cli_args.time_speed != 1:
    psclock.set_clock(psclock.parse_time(cli_args.fake_time) if cli_args.fake_time else psclock.time(), cli_args.time_speed)
    logging.info(f"Clock set to {psclock.describe()}")

startup_mode = cli_args.mode
if not startup_mode:
    startup_mode = shared_config.CONF["DEFAULT_MODE"].strip().upper()
    if startup_mode not in startup_mode_names():
        logging.warning(f"DEFAULT_MODE {startup_mode!r} is not a mode the sign can start in, using PLANES_ALERT")
        startup_mode = "PLANES_ALERT"

workers = [(api_server_process, 5), (plane_data_process, 10), (weather_data_process, 10), (tides_data_process, 10), (nfl_data_process, 10), (mlb_data_process, 10), (outside_data_process, 5)]
ps = None
exit_code = 0
try:
    for process, _ in workers:
        process.start()
    utilities.preload_geojsons()
    ps = planesign.PlaneSign(defined_mode_handlers)
    defined_mode_handlers[DisplayMode.WELCOME](ps, duration=5)
    shared_config.shared_mode.value = DisplayMode[startup_mode].value
    ps.sign_loop()
except Exception:
    # Logged here because the finally block stops the log writer before sys.excepthook would run.
    logging.exception("The sign loop crashed")
    exit_code = 1
finally:
    logging.info("Shutting down sign and child processes...")
    shared_config.shared_mode.value = DisplayMode.SIGN_OFF.value
    shared_config.shared_shutdown_event.set()
    shared_config.shared_forced_sign_update.set()

    for process, timeout in workers:
        if process.pid is None:
            continue
        process.join(timeout=timeout)
        if process.is_alive():
            logging.warning("%s did not exit in time, terminating...", process.name)
            process.terminate()
            process.join(timeout=2)

    try:
        if ps is not None:
            close_display = getattr(ps.matrix, "close", None)
            if close_display is not None:
                close_display()
    finally:
        stop_log_writer()

print("Done.")
sys.exit(exit_code)
