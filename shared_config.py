from multiprocessing import Process, Manager, Value, Array, Queue

shared_flag = Value('i', 1)
shared_mode = Value('i', 1)

shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)

shared_current_brightness = Value('i', 80)
shared_color_mode = Value('i', 0)
shared_forced_sign_update = Value('i', 0)

data_dict = None
arg_dict = None
CONF = None