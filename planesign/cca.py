###
# Cyclic cellular automaton
# https://en.wikipedia.org/wiki/Cyclic_cellular_automaton
###

import time
import random
import utilities
import __main__

@__main__.planesign_mode_handler(12)
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

                cs = utilities.check_matrix(col, row, current_state)
                ns = (cs+1) % numstates
                curr = 0

                if utilities.check_matrix(col, row-1, current_state) == ns:
                    curr += 1
                if utilities.check_matrix(col-1, row, current_state) == ns:
                    curr += 1
                if utilities.check_matrix(col+1, row, current_state) == ns:
                    curr += 1
                if utilities.check_matrix(col, row+1, current_state) == ns:
                    curr += 1

                if curr >= threshold:
                    utilities.set_matrix(col, row, next_state, ns)
                    r, g, b = utilities.hsv_2_rgb(ns/numstates, 1, 1)
                else:
                    utilities.set_matrix(col, row, next_state, cs)
                    r, g, b = utilities.hsv_2_rgb(cs/numstates, 1, 1)

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
