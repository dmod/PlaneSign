import os
from multiprocessing import Array, Event, Value

from modes import DisplayMode

shared_mode = Value("i", DisplayMode.WELCOME.value)
shared_prev_mode = Value("i", DisplayMode.PLANES_ALERT.value)

# Mode to fall back to once the transient IDENTIFY flash finishes.
shared_identify_return_mode = Value("i", DisplayMode.PLANES_ALERT.value)

shared_pong_player1 = Value("i", 0)
shared_pong_player2 = Value("i", 0)

shared_current_brightness = Value("i", 80)
shared_color_mode = Value("i", 0)
shared_forced_sign_update = Event()

shared_satellite_mode = Value("i", 1)

shared_lightning_zoomind = Value("i", 6)
shared_lightning_mode = Value("i", 1)

shared_mandelbrot_color = Value("i", 0)
shared_mandelbrot_colorscale = Value("d", 3)

shared_snow_mode = Value("i", 1)

free_sketch_pixels = Array("B", 128 * 32 * 3)

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

log_filename = "logs/planesign.log"
icons_dir = "./icons"

font_dir = "./fonts"

sounds_dir = "sounds"
datafiles_dir = "./datafiles"

shared_shutdown_event = None
data_dict = None
arg_dict = None
CONF = None

code_to_airport = {}
airport_codes_to_ignore = set()
country_name_to_code = {}


def shutdown_in_progress():
    return bool(shutdown_requested.value) or (shared_shutdown_event is not None and shared_shutdown_event.is_set())
