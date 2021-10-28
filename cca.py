import time
import random
from utilities import *


def cca(sign):
    sign.canvas.Clear()

    generation_time = 0.15

    current_state = [[0 for j in range(32)] for i in range(128)]
    next_state = [[0 for j in range(32)] for i in range(128)]

    numstates = 12  # number of states/colors possible
    threshold = 1  # set from 1 to numstates to adjust behavior

    for i in range(128):
        for j in range(32):
            current_state[i][j] = random.randrange(0, numstates)

    tstart = time.perf_counter()
    while True:

        for col in range(0, 128):
            for row in range(0, 32):

                cs = check_matrix(col, row, current_state)
                ns = (cs+1) % numstates
                curr = 0

                if check_matrix(col, row-1, current_state) == ns:
                    curr += 1
                if check_matrix(col-1, row, current_state) == ns:
                    curr += 1
                if check_matrix(col+1, row, current_state) == ns:
                    curr += 1
                if check_matrix(col, row+1, current_state) == ns:
                    curr += 1

                if curr >= threshold:
                    set_matrix(col, row, next_state, ns)
                    r, g, b = hsv_2_rgb(ns/numstates, 1, 1)
                else:
                    set_matrix(col, row, next_state, cs)
                    r, g, b = hsv_2_rgb(cs/numstates, 1, 1)

                sign.canvas.SetPixel(col, row, r, g, b)

        for col in range(0, 128):
            for row in range(0, 32):
                current_state[col][row] = next_state[col][row]

        tend = time.perf_counter()
        if(tend < tstart + generation_time):
            breakout = sign.wait_loop(tstart + generation_time-tend)
        else:
            breakout = sign.wait_loop(0)

        sign.matrix.SwapOnVSync(sign.canvas)

        tstart = time.perf_counter()
        if breakout:
            return
