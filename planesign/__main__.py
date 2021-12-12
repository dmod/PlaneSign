import planesign

ALL_MODE_HANDLERS = {}

def planesign_mode_handler(mode_int):

    """
    Decorator
    """
    def handler(func):
        print(f"Mode {mode_int} will be set to: '{func.__name__}' in module '{func.__module__}'")
        ALL_MODE_HANDLERS[mode_int] = func

    return handler

import weather
import firework
import lightning
import cgol
import cca
import custom_message
import pong
import welcome
import planes
import shared_config
import satellite
import finance
import fish
import utilities

utilities.configure_logging()
utilities.read_static_airport_data()

planesign.PlaneSign(ALL_MODE_HANDLERS).sign_loop()