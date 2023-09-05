###
# Mandelbrot Set Zoom
# https://en.wikipedia.org/wiki/Mandelbrot_set
###

import time
import numpy as np
from numba import njit, jit, prange
import shared_config
import __main__
import logging

# Function to calculate whether a point is in the Mandelbrot set
@njit
def mandelbrot(x0,y0, max_iter):
    power = lam = 1
    x = 0
    y = 0
    tortoise = hare = (x,y)
    iteration = 0
    condition = 1
    while x*x + y*y <= 4 and iteration < max_iter:
        
        if iteration > 0:
            condition = (tortoise[0] - hare[0])*(tortoise[0] - hare[0])+(tortoise[1] - hare[1])*(tortoise[1] - hare[1])
        
        if condition < 1e-32: # cycle detected - inside of set
            return max_iter, np.float32(0)
        else: # advance tortoise for cycle detection
            if power == lam:
                tortoise = hare
                power *= 2
                lam = 0
            
        xtemp = x*x - y*y + x0
        y = 2*x*y + y0
        x = xtemp
        
        hare = (x,y)
        lam += 1
            
        iteration += 1
        
    return iteration, np.sqrt(x*x+y*y)

# Main cardioid checking (exact)
@njit
def is_inside_main_cardioid(x,y):
    q = (x - 0.25) ** 2 + y ** 2
    return q * (q + (x - 0.25)) < 0.25 * y ** 2

#Period-2 bulb checking (exact)
@njit
def is_inside_period_2_bulb(x,y):
    return (x + 1) ** 2 + y ** 2 < 0.0625

#Period-3 bulb checking (approximate)
@njit
def is_inside_period_3_bulb(x,y):
    if (x + 0.12256) ** 2 + (y+0.74486) ** 2 < 0.00925926 or (x + 0.12256) ** 2 + (y-0.74486) ** 2 < 0.00925926:
        return 1
    else:
        return 0

# Calculate the adaptive MAX_ITER value based on zoom level
@njit
def calculate_max_iter(zoom_factor):
    return int(1000 / np.sqrt(zoom_factor))

def setcolor(index,mode):

    if mode == 0:

        #Saturated
        colors = [(255,0,0),(255,255,0),(0,255,0),(0,255,255),(0,0,255),(255,0,255),(255,0,0)]
        keypts = [0,0.2,0.33,0.45,0.6,0.83,1]

    elif mode == 1:

        #Sunset
        colors = [(0,0,0),(14,81,181),(18,218,222),(255,255,248),(242,210,82),(207,88,29),(0,0,0)]
        keypts = [0,0.16144,0.351671,0.501285,0.620051,0.8,1]

    elif mode == 2:

        #Nova
        colors = [(0,0,0),(15,50,190),(255,255,255),(255,200,30),(111,0,255),(0,0,0)]
        keypts = [0,0.2,0.4,0.6,0.8,1]

    elif mode == 3:

        #Vaporwave
        colors = [(48,3,80),(148,22,127),(246,46,151),(249,172,83),(5,195,221),(21,60,180),(48,3,80)]
        keypts = [0,0.15,0.3,0.44,0.73,0.9,1]

    elif mode == 4:

        #70s
        colors = [(0,18,25),(0,95,115),(10,147,150),(148,210,189),(233,216,166),(238,155,0),(202,103,2),(174,32,18),(0,18,25)]
        keypts = [0,0.1,0.2,0.35,0.5,0.6,0.7,0.8,1]

    elif mode == 5:

        #Rainbow
        colors = [(255,89,94),(255,202,58),(138,201,38),(25,130,196),(106,76,147),(255,89,94)]
        keypts = [0,0.2,0.4,0.6,0.8,1]

    else:

        #Greyscale
        colors = [(0,0,0),(200,200,200),(0,0,0)]
        keypts = [0,0.5,1]


    index = index % 1

    for i in range(len(keypts)):
        if keypts[i]>index:
            break
    
    frac = (index-keypts[i-1])/(keypts[i]-keypts[i-1])

    r = int(frac*colors[i][0]+(1-frac)*colors[i-1][0])
    g = int(frac*colors[i][1]+(1-frac)*colors[i-1][1])
    b = int(frac*colors[i][2]+(1-frac)*colors[i-1][2])

    return r,g,b

@njit
def find_border_point(precision, max_iterations=100000):

    while True:
        x = np.random.uniform(-2, 1)
        y = np.random.uniform(-1.5, 1.5)
        if is_inside_main_cardioid(x,y) or is_inside_period_2_bulb(x,y) or is_inside_period_3_bulb(x,y):
            continue
        else:
            m,_ = mandelbrot(x,y, max_iterations)
        if m==max_iterations:
            break
    
    angle = 2*np.pi*np.random.rand()
    
    delta = 0.1
    dx = delta*np.cos(angle)
    dy = delta*np.sin(angle)
    
    while True:
        
        m,_ = mandelbrot(x+dx,y+dy,max_iterations)
        if m<max_iterations:
            dx /= 2
            dy /= 2
        else:
            x += dx
            y += dy
        
        if dx*dx+dy*dy<precision*precision:
            break
        
    while True:
        tx = x-2*dx+4*dx*np.random.rand()
        ty = y-2*dy+4*dy*np.random.rand()
        m,_ = mandelbrot(tx,ty,max_iterations)
        if m>max_iterations/2 and m<max_iterations:
            break
    #print(m)
    return tx,ty

@__main__.planesign_mode_handler(22)
def mandelbrot_zoom(sign):
    sign.canvas.Clear()
    
    numba_logger = logging.getLogger('numba')
    numba_logger.setLevel(logging.WARNING)

    # Initialize an empty list to store tuples
    pois = []

    # Open the file for reading
    with open("mandelbrot_poi.txt", 'r') as file:
        # Iterate through each line in the file
        for line in file:
            # Split the line into two floats using tab as the delimiter
            parts = line.strip().split('\t')
            pois.append((float(parts[0]), float(parts[1])))


    lp = len(pois)

    # Parameters for the Mandelbrot set and animation
    INIT_WIDTH, INIT_HEIGHT = 7*3, 7*3*32/128

    while shared_config.shared_mode.value == 22:

        xb,yb = pois[np.random.randint(0, high=lp)]#find_border_point(1e-3)
        frame = 0

        while frame<900:
            tstart = time.perf_counter()
                
            # Calculate the bounds of the visible area based on the zoomed frame
            zoom_factor = 2 ** (-0.05 * frame)
            half_width = INIT_WIDTH / 2
            half_height = INIT_HEIGHT / 2
            real_min = xb - half_width * zoom_factor
            real_max = xb + half_width * zoom_factor
            imag_min = yb - half_height * zoom_factor
            imag_max = yb + half_height * zoom_factor
            
            MAX_ITER = calculate_max_iter(zoom_factor)
            
            # Generate the Mandelbrot image for the visible area
            x, y = np.linspace(real_min, real_max, 128), np.linspace(imag_min, imag_max, 32)
            mandelbrot_iters = np.zeros((32, 128), dtype=int)
            mandelbrot_modulus = np.zeros((32, 128), dtype=int)

            cmode = shared_config.shared_mandelbrot_color.value
            cscale = shared_config.shared_mandelbrot_colorscale.value

            iters = np.empty((32,128))
                        
            for i in prange(32):
                for j in prange(128):
                    
                    if is_inside_main_cardioid(x[j],y[i]) or is_inside_period_2_bulb(x[j],y[i]):
                        iters[i][j] = MAX_ITER
                    else:
                        mandelbrot_iters, mandelbrot_modulus = mandelbrot(x[j], y[i], MAX_ITER)

                        if mandelbrot_iters == MAX_ITER or mandelbrot_iters <= 1:
                            iters[i][j] = MAX_ITER
                        else:
                            index = np.log2(mandelbrot_iters - np.log(np.log(mandelbrot_modulus))/np.log(2))/cscale
                            r,g,b = setcolor(index,cmode)
                            sign.canvas.SetPixel(j, i, r, g, b)
                            iters[i][j] = mandelbrot_iters
            
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.canvas.Clear()
            breakout = sign.wait_loop(0)
            if breakout:
                return

            frame += 1

            if time.perf_counter() - tstart > 1 or np.all(np.isclose(iters, iters[0], atol=2)):
                break
