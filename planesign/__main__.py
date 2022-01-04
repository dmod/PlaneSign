ALL_MODE_HANDLERS = {}

def planesign_mode_handler(mode_int):

    def handler(func):
        print(f"Mode {mode_int} will be set to: '{func.__name__}' in module '{func.__module__}'")
        ALL_MODE_HANDLERS[mode_int] = func

    return handler


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
import cca
import cgol
import lightning
import firework
import weather
import planesign
import signal
import sys
import os
import logging


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
    logging.debug("Exiting...")
    shared_config.shared_mode.value = 0
    shared_config.shared_forced_sign_update.value = 1
    shared_config.shared_shutdown_event.set()


#signal.signal(signal.SIGINT, exit_gracefully)
#signal.signal(signal.SIGTERM, exit_gracefully)

def log_listener_process(queue):
    root = logging.getLogger()

    os.makedirs(os.path.dirname(shared_config.log_filename), exist_ok=True)
    log_handler = logging.handlers.TimedRotatingFileHandler(shared_config.log_filename, when="midnight", backupCount=90)
    log_handler.setFormatter(logging.Formatter('%(asctime)s %(processName)-10s %(name)s %(levelname)-8s %(message)s'))

    root.addHandler(log_handler)

    while True:
        record = queue.get()
        if record is None:
            break
        root.handle(record)


logging_queue = Queue(-1)
listener = Process(target=log_listener_process, args=(logging_queue, ))
listener.start()

queue_handler = logging.handlers.QueueHandler(logging_queue)

console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s')
console_handler.setFormatter(console_formatter)

root = logging.getLogger() 
root.addHandler(queue_handler)
root.addHandler(console_handler)
root.setLevel(logging.DEBUG)
logging.getLogger('PIL').setLevel(logging.WARNING)

utilities.read_static_airport_data()

api_server_process = Process(target=planesign.api_server, name="APIServer")
plane_data_process = Process(target=planes.get_plane_data_worker, name="PlaneData", args=(shared_config.data_dict,))
weather_data_process = Process(target=weather.get_weather_data_worker, name="WeatherData", args=(shared_config.data_dict,))

api_server_process.start()
plane_data_process.start()
weather_data_process.start()

planesign.PlaneSign(ALL_MODE_HANDLERS).sign_loop()

api_server_process.join()
plane_data_process.join()
weather_data_process.join()

listener.join()

print("Done.")
