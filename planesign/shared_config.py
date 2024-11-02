from multiprocessing import Value
from modes import DisplayMode
import os

shared_mode = Value('i', DisplayMode.PLANES_ALERT.value)
shared_prev_mode = Value('i', DisplayMode.PLANES_ALERT.value)

shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)

shared_current_brightness = Value('i', 80)
shared_color_mode = Value('i', 0)
shared_forced_sign_update = Value('i', 0)

shared_satellite_mode = Value('i', 1)

shared_lighting_zoomind = Value('i', 6)
shared_lighting_mode = Value('i', 1)

shared_mandelbrot_color = Value('i', 0)
shared_mandelbrot_colorscale = Value('d', 3)

local_timezone = None

log_filename = "logs/planesign.log"
icons_dir = "./icons"

possible_font_dirs = [
    "../rpi-rgb-led-matrix/fonts",
    "../../rpi-rgb-led-matrix/fonts"
]
font_dir = None
for path in possible_font_dirs:
    if os.path.exists(path):
        print(f"Found font directory at {path}")
        font_dir = path
        break

sounds_dir = "sounds"
datafiles_dir = "./datafiles"

shared_shutdown_event = None
data_dict = None
arg_dict = None
CONF = None

code_to_airport = {}
airport_codes_to_ignore = set()
