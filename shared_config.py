from multiprocessing import Value
import logging

shared_flag = Value('i', 1)
shared_mode = Value('i', 1)

shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)

shared_current_brightness = Value('i', 80)
shared_color_mode = Value('i', 0)
shared_forced_sign_update = Value('i', 0)

shared_satellite_mode = Value('i', 1)

# These get set in the PlaneSign constructor
data_dict = None
arg_dict = None
CONF = None

code_to_airport = {}

def read_static_airport_data():
    with open("airports.csv") as f:
        lines = f.readlines()
        for line in lines:
            parts = line.strip().split(',')
            code = parts[0]
            name = parts[1]
            lat = float(parts[2])
            lon = float(parts[3])
            code_to_airport[code] = (name, lat, lon)

    logging.info(f"{len(code_to_airport)} static airport configs added")
