from multiprocessing import Value

shared_mode = Value('i', 1)
shared_prev_mode = Value('i', 0)

shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)

shared_current_brightness = Value('i', 80)
shared_color_mode = Value('i', 0)
shared_forced_sign_update = Value('i', 0)

shared_satellite_mode = Value('i', 1)

shared_lighting_zoomind = Value('i', 6)
shared_lighting_mode = Value('i', 1)

shared_snow_mode = Value('i', 1)

local_timezone = None

log_filename = "logs/planesign.log"
icons_dir = "./icons"
font_dir = "../rpi-rgb-led-matrix/fonts"
sounds_dir = "sounds"

shared_shutdown_event = None
data_dict = None
arg_dict = None
CONF = None

code_to_airport = {}
