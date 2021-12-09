###
# Conway's Game of Life
# https://en.wikipedia.org/wiki/Conway%27s_Game_of_Life
###

import time
import random
import shared_config
from utilities import *
from __main__ import planesign_mode_handler

@planesign_mode_handler(10)
def cgol(sign):
    sign.canvas.Clear()

    generation_time = 0.15

    if shared_config.arg_dict["style"] == "2":
        cgol_cellcolor = False
    else:
        cgol_cellcolor = True

    current_state = [[False for j in range(32)] for i in range(128)]
    next_state = [[False for j in range(32)] for i in range(128)]
    if cgol_cellcolor:
        hmatrix = [[0 for j in range(32)] for i in range(128)]
        next_hmatrix = [[0 for j in range(32)] for i in range(128)]

    for i in range(0, 128):
        for j in range(0, 32):
            if (random.random() < 0.3):
                current_state[i][j] = True
            else:
                current_state[i][j] = False
            if cgol_cellcolor:
                # hmatrix[i][j]=random_angle()
                hmatrix[i][j] = round(359*i/127+359*j/31) % 360

    firstgen = True

    gen_index = 0

    angle = random_angle()
    #r,g,b = random_rgb()

    tstart = time.perf_counter()
    while True:

        detect2cycle = True
        gen_index += 1

        if not cgol_cellcolor:
            #angle, r, g, b = next_color_rainbow_linear(angle)
            angle, r, g, b = next_color_rainbow_sine(angle)
            #r,g,b = next_color_random_walk_uniform_step(r,g,b,10)
            #r,g,b = next_color_random_walk_const_sum(r,g,b,10)

        next_state = [[False for j in range(32)] for i in range(128)]

        for col in range(0, 128):
            for row in range(0, 32):

                if cgol_cellcolor:
                    candidate, r, g, b = check_life_color(col, row, current_state, hmatrix, next_hmatrix)
                else:
                    candidate = check_life(col, row, current_state)

                next_state[col][row] = candidate

                if detect2cycle and not firstgen and candidate != prev_state[col][row]:
                    detect2cycle = False
                if candidate:
                    sign.canvas.SetPixel(col, row, r, g, b)
                else:
                    sign.canvas.SetPixel(col, row, 0, 0, 0)

        if firstgen:
            detect2cycle = False
            firstgen = False

        if detect2cycle:
            for i in range(0, 128):
                for j in range(0, 32):
                    if (random.random() < 0.3):
                        next_state[i][j] = True
                        if cgol_cellcolor:
                            hmatrix[i][j] = random_angle()
                    else:
                        next_state[i][j] = False

        prev_state = current_state
        current_state = next_state

        tend = time.perf_counter()
        if(tend < tstart + generation_time):
            breakout = sign.wait_loop(tstart + generation_time-tend)
        else:
            breakout = sign.wait_loop(0)

        sign.matrix.SwapOnVSync(sign.canvas)

        tstart = time.perf_counter()

        if breakout:
            return


def check_life(x, y, matrix):
    num_neighbors_alive = 0

    # Check neighbors above
    if check_matrix(x-1, y-1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x, y-1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y-1, matrix):
        num_neighbors_alive += 1

    # Check neighbors aside
    if check_matrix(x-1, y, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y, matrix):
        num_neighbors_alive += 1

    # Check neighbors below
    if check_matrix(x-1, y+1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x, y+1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y+1, matrix):
        num_neighbors_alive += 1

    # Any live cell with fewer than two live neighbours dies, as if by underpopulation.
    # Any live cell with two or three live neighbours lives on to the next generation.
    # Any live cell with more than three live neighbours dies, as if by overpopulation.
    # Any dead cell with exactly three live neighbours becomes a live cell, as if by reproduction.

    if matrix[x][y] and (num_neighbors_alive == 2 or num_neighbors_alive == 3):
        return True

    if not matrix[x][y] and num_neighbors_alive == 3:
        return True

    return False


def check_life_color(x, y, matrix, hm, nhm):

    num_neighbors_alive = 0

    cx = 0
    cy = 0

    # Check neighbors above
    if check_matrix(x-1, y-1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x, y-1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y-1, matrix):
        num_neighbors_alive += 1

    # Check neighbors aside
    if check_matrix(x-1, y, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y, matrix):
        num_neighbors_alive += 1

    # Check neighbors below
    if check_matrix(x-1, y+1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x, y+1, matrix):
        num_neighbors_alive += 1
    if check_matrix(x+1, y+1, matrix):
        num_neighbors_alive += 1

    # Any live cell with fewer than two live neighbours dies, as if by underpopulation.
    # Any live cell with two or three live neighbours lives on to the next generation.
    # Any live cell with more than three live neighbours dies, as if by overpopulation.
    # Any dead cell with exactly three live neighbours becomes a live cell, as if by reproduction.

    if matrix[x][y] and (num_neighbors_alive == 2 or num_neighbors_alive == 3):
        h = check_matrix(x, y, hm)
        set_matrix(x, y, nhm, h)
        r, g, b = hsv_2_rgb(h/360.0, 1, 1)
        return True, r, g, b

    if not matrix[x][y] and num_neighbors_alive == 3:

        # Find the mean color of the 3 neighbors

        # Check neighbors above
        if check_matrix(x-1, y-1, matrix):
            h = check_matrix(x-1, y-1, hm)
            cx += cos(h)
            cy += sin(h)
        if check_matrix(x, y-1, matrix):
            h = check_matrix(x, y-1, hm)
            cx += cos(h)
            cy += sin(h)
        if check_matrix(x+1, y-1, matrix):
            h = check_matrix(x+1, y-1, hm)
            cx += cos(h)
            cy += sin(h)

        # Check neighbors aside
        if check_matrix(x-1, y, matrix):
            h = check_matrix(x-1, y, hm)
            cx += cos(h)
            cy += sin(h)
        if check_matrix(x+1, y, matrix):
            h = check_matrix(x+1, y, hm)
            cx += cos(h)
            cy += sin(h)

        # Check neighbors below
        if check_matrix(x-1, y+1, matrix):
            h = check_matrix(x-1, y+1, hm)
            cx += cos(h)
            cy += sin(h)
        if check_matrix(x, y+1, matrix):
            h = check_matrix(x, y+1, hm)
            cx += cos(h)
            cy += sin(h)
        if check_matrix(x+1, y+1, matrix):
            h = check_matrix(x+1, y+1, hm)
            cx += cos(h)
            cy += sin(h)

        h = round(math.atan2(cy, cx)/DEG_2_RAD) % 360
        set_matrix(x, y, nhm, h)

        r, g, b = hsv_2_rgb(h/360.0, 1, 1)

        return True, r, g, b

    return False, 0, 0, 0
