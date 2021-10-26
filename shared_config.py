from multiprocessing import Process, Manager, Value, Array, Queue

shared_pong_player1 = Value('i', 0)
shared_pong_player2 = Value('i', 0)

data_dict = None
arg_dict = None
CONF = None