###
# Mandelbrot Set Zoom
# https://en.wikipedia.org/wiki/Mandelbrot_set
###

import time
import numpy as np
from numba import njit, jit, prange
import utilities
import shared_config
import __main__
import logging

# Function to calculate whether a point is in the Mandelbrot set
@njit
def mandelbrot(x0,y0, max_iter):
    x = 0
    y = 0
    iteration = 0
    while x*x + y*y <= 4 and iteration < max_iter:
        xtemp = x*x - y*y + x0
        y = 2*x*y + y0
        x = xtemp
        iteration += 1
    return iteration, np.sqrt(x*x+y*y)

# Main cardioid and period-2 bulb checking
@njit
def is_inside_main_cardioid(x,y):
    q = (x - 0.25) ** 2 + y ** 2
    return q * (q + (x - 0.25)) < 0.25 * y ** 2

@njit
def is_inside_period_2_bulb(x,y):
    return (x + 1) ** 2 + y ** 2 < 0.0625

# Calculate the adaptive MAX_ITER value based on zoom level
@njit
def calculate_max_iter(zoom_factor):
    return int(1000 / np.sqrt(zoom_factor))

def setcolor(index):

    colors = [(0,0,0),(14,81,181),(18,218,222),(255,255,248),(242,210,82),(207,88,29),(0,0,0)]
    keypts = [0,0.16144,0.351671,0.501285,0.620051,0.8,1]

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
        if is_inside_main_cardioid(x,y) or is_inside_period_2_bulb(x,y):
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

    # Parameters for the Mandelbrot set and animation
    INIT_WIDTH, INIT_HEIGHT = 7*3, 7*3*32/128
    NUM_FRAMES = 950
    PRECISION = 1e-3

    #COLORS = [(0,0,0),(0,1,3),(0,2,6),(0,3,9),(0,4,13),(0,5,16),(0,6,19),(0,7,22),(0,8,25),(0,9,28),(0,10,32),(0,11,35),(0,11,38),(0,12,41),(0,13,44),(0,14,47),(0,15,51),(0,16,54),(0,17,57),(0,18,60),(0,19,63),(0,20,66),(0,21,70),(0,22,73),(0,23,76),(0,24,79),(0,25,82),(0,26,85),(0,27,89),(0,28,92),(0,29,95),(0,30,98),(0,31,101),(0,32,104),(0,33,108),(0,34,111),(0,34,114),(0,35,117),(0,36,120),(0,37,123),(0,38,127),(0,39,130),(0,40,133),(0,41,136),(0,42,139),(0,43,142),(0,44,146),(0,45,149),(0,46,152),(0,47,155),(0,48,158),(0,49,161),(0,50,165),(0,51,168),(0,52,171),(0,53,174),(0,54,177),(0,55,180),(0,56,183),(0,56,187),(0,57,190),(0,58,193),(0,59,196),(0,60,199),(1,62,202),(4,64,203),(8,67,204),(12,69,204),(15,72,205),(19,75,206),(22,77,207),(26,80,208),(29,82,209),(33,85,209),(36,88,210),(40,90,211),(44,93,212),(47,95,213),(51,98,214),(54,101,214),(58,103,215),(61,106,216),(65,108,217),(68,111,218),(72,114,219),(75,116,219),(79,119,220),(83,121,221),(86,124,222),(90,127,223),(93,129,224),(97,132,224),(100,134,225),(104,137,226),(107,140,227),(111,142,228),(115,145,229),(118,147,229),(122,150,230),(125,152,231),(129,155,232),(132,158,233),(136,160,234),(139,163,235),(143,165,235),(146,168,236),(150,171,237),(154,173,238),(157,176,239),(161,178,240),(164,181,240),(168,184,241),(171,186,242),(175,189,243),(178,191,244),(182,194,245),(186,197,245),(189,199,246),(193,202,247),(196,204,248),(200,207,249),(203,210,250),(207,212,250),(210,215,251),(214,217,252),(218,220,253),(221,223,254),(225,225,255),(226,226,253),(226,224,249),(226,223,245),(226,222,241),(225,221,237),(225,219,233),(225,218,229),(225,217,225),(224,215,221),(224,214,217),(224,213,213),(224,212,209),(223,210,205),(223,209,201),(223,208,197),(223,206,193),(222,205,189),(222,204,185),(222,203,181),(222,201,177),(221,200,173),(221,199,169),(221,198,165),(221,196,161),(220,195,157),(220,194,153),(220,192,149),(220,191,145),(220,190,141),(219,189,137),(219,187,133),(219,186,129),(219,185,125),(218,183,121),(218,182,117),(218,181,113),(218,180,109),(217,178,105),(217,177,101),(217,176,97),(217,174,93),(216,173,89),(216,172,85),(216,171,81),(216,169,77),(215,168,73),(215,167,69),(215,165,65),(215,164,61),(214,163,57),(214,162,53),(214,160,49),(214,159,45),(213,158,41),(213,156,37),(213,155,33),(213,154,29),(212,153,25),(212,151,21),(212,150,17),(212,149,13),(211,147,9),(211,146,5),(211,145,1),(208,143,0),(205,141,0),(202,138,0),(199,136,0),(195,134,0),(192,131,0),(189,129,0),(185,127,0),(182,125,0),(179,122,0),(175,120,0),(172,118,0),(169,116,0),(165,113,0),(162,111,0),(159,109,0),(156,107,0),(152,104,0),(149,102,0),(146,100,0),(142,97,0),(139,95,0),(136,93,0),(132,91,0),(129,88,0),(126,86,0),(122,84,0),(119,82,0),(116,79,0),(113,77,0),(109,75,0),(106,73,0),(103,70,0),(99,68,0),(96,66,0),(93,63,0),(89,61,0),(86,59,0),(83,57,0),(79,54,0),(76,52,0),(73,50,0),(69,48,0),(66,45,0),(63,43,0),(60,41,0),(56,39,0),(53,36,0),(50,34,0),(46,32,0),(43,29,0),(40,27,0),(36,25,0),(33,23,0),(30,20,0),(26,18,0),(23,16,0),(20,14,0),(17,11,0),(13,9,0),(10,7,0),(7,5,0),(3,2,0),(0,0,0)]

    frame = 0

    
    # for j in prange(128):
    #     r,g,b = setcolor(j/127)
    #     for i in prange(32):
    #         sign.canvas.SetPixel(j, i, r, g, b)
    
    # sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)

    # while True:
    #     pass

    
    while shared_config.shared_mode.value == 22:

        # Find a point on the border of the Mandelbrot set
        #border_point = (-0.743643887037158704752191506114774, 0.131825904205311970493132056385139)
        #border_point = (0.001643721971153, -0.822467633298876)
        border_point = find_border_point(PRECISION)

        xb,yb = border_point
        

        while frame<900:
            tstart = time.perf_counter()
            print(frame)
                
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

            for i in prange(32):
                for j in prange(128):
                    
                    if is_inside_main_cardioid(x[j],y[i]) or is_inside_period_2_bulb(x[j],y[i]):
                        sign.canvas.SetPixel(j, i, 0,0,0)
                    else:
                        mandelbrot_iters, mandelbrot_modulus = mandelbrot(x[j], y[i], MAX_ITER)

                        if mandelbrot_iters == MAX_ITER or mandelbrot_iters <= 1:
                            #can maybe just do nothing because clear alreay sets to 0?
                            sign.canvas.SetPixel(j, i, 0,0,0)
                        else:
                            #index = int(np.log2(mandelbrot_iters - np.log(np.log(mandelbrot_modulus))/np.log(2))/np.log2(MAX_ITER)*255)
                            #sign.canvas.SetPixel(j, i, COLORS[index][0], COLORS[index][1], COLORS[index][2])

                            index = np.log2(mandelbrot_iters - np.log(np.log(mandelbrot_modulus))/np.log(2))/np.log2(10)
                            r,g,b = setcolor(index)
                            sign.canvas.SetPixel(j, i, r, g, b)
            
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            
            breakout = sign.wait_loop(0)
            if breakout:
                return

            frame += 1

            if time.perf_counter() - tstart > 1:
                breakout = 1
                break

        if breakout:
            return
