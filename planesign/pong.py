import shared_config
import random
from rgbmatrix import graphics
import __main__

@__main__.planesign_mode_handler(11)
def pong(sign):

    xball = 64
    yball = 16

    xvel = random.randint(0,1)*2-1
    yvel = random.randint(0,1)*2-1

    framecount = 0

    player1_score = 0
    player2_score = 0

    starting_y_value = shared_config.shared_pong_player1.value
    starting_y_value_2 = shared_config.shared_pong_player2.value

    #player 1 paddle
    for width in range(0, 3):
        for height in range(starting_y_value, starting_y_value + 6):
            sign.canvas.SetPixel(width, height, 255, 20, 20)

    #player 2 paddle
    for width in range(125, 128):
        for height in range(starting_y_value_2, starting_y_value_2 + 6):
            sign.canvas.SetPixel(width, height, 20, 20, 255)

    while shared_config.shared_mode.value == 11:
        framecount += 1
        sign.canvas.Clear()

        setyval = shared_config.shared_pong_player1.value
        setyval2 = shared_config.shared_pong_player2.value

        if framecount % 20 == 0 and sign.wait_loop(0):
            return

        #starting_y_value = shared_pong_player1.value
        #starting_y_value_2 = shared_pong_player2.value

        #limit paddle move speed to 1 per frame - continuous motion, no teleporting
        if framecount == 1:
            starting_y_value = setyval
            starting_y_value_2 = setyval2
        else:
            if framecount % 3 == 0: #limit paddle update (move speed)
                if starting_y_value < setyval:
                    starting_y_value += 1
                if starting_y_value > setyval:
                    starting_y_value -= 1
                if starting_y_value_2 < setyval2:
                    starting_y_value_2 += 1
                if starting_y_value_2 > setyval2:
                    starting_y_value_2 -= 1

        ##paddle face reflection
        #if (starting_y_value <= yball and starting_y_value+6 >= yball and xball <= 4 and xvel < 0) or (starting_y_value_2 <= yball and starting_y_value_2+6 >= yball and xball >= 123 and xvel > 0):
        #    xvel *= -1
        #    yvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '1' for default gameplay

        ##paddle top and bottom reflection
        #if (yball >= starting_y_value and yball <= starting_y_value+6+2 and yvel < 0 and xball <= 3) or (yball >= starting_y_value-2 and yball <= starting_y_value+6 and yvel > 0 and xball <= 3) or (yball >= starting_y_value_2 and yball <= starting_y_value_2+6+2 and yvel < 0 and xball >= 124) or (yball >= starting_y_value_2-2 and yball <= starting_y_value_2+6 and yvel > 0 and xball >= 124):
        #    xvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '-1' for default gameplay
        #    yvel *= -1

        #left paddle face reflection
        if (starting_y_value-1 <= yball and starting_y_value+6 >= yball and xball <= 4 and xvel < 0):
            xvel = 1
            if (starting_y_value-1 <= yball and starting_y_value+1 >= yball):
                yvel = -1
            elif (starting_y_value+2 <= yball and starting_y_value+3 >= yball):
                yvel = 0
                #xvel = 2
            else:
                yvel = 1

        #right paddle face reflection
        if (starting_y_value_2-1 <= yball and starting_y_value_2+6 >= yball and xball >= 123 and xvel > 0):
            xvel = -1
            if (starting_y_value_2-1 <= yball and starting_y_value_2+1 >= yball):
                yvel = -1
            elif (starting_y_value_2+2 <= yball and starting_y_value_2+3 >= yball):
                yvel = 0
                #xvel = 2
            else:
                yvel = 1        

        #paddle top and bottom reflection
        if (yball >= starting_y_value and yball <= starting_y_value+5+2 and yvel < 0 and xball <= 3) or (yball >= starting_y_value-2 and yball <= starting_y_value+5 and yvel > 0 and xball <= 3) or (yball >= starting_y_value_2 and yball <= starting_y_value_2+5+2 and yvel < 0 and xball >= 124) or (yball >= starting_y_value_2-2 and yball <= starting_y_value_2+5 and yvel > 0 and xball >= 124):
            xvel *= random.randint(0,1)*2-1 #try and make it a little more unpredictable to prevent steadystate during real gameplay - set to '-1' for default gameplay
            yvel *= -1

        #top and bottom bounce
        if (yball <= 0 and yvel <0) or (yball >= 31 and yvel >0):
            yvel *= -1

        if xball <= 0:
            graphics.DrawText(sign.canvas, sign.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
            graphics.DrawText(sign.canvas, sign.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.wait_loop(0.5)
            sign.canvas.Clear()
            player2_score += 1
            graphics.DrawText(sign.canvas, sign.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
            graphics.DrawText(sign.canvas, sign.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.wait_loop(3)
            sign.canvas.Clear()
            xball = 64
            yball = random.randint(2,30)
            xvel = random.randint(0,1)*2-1
            yvel = random.randint(0,1)*2-1

        if xball >= 127:
            graphics.DrawText(sign.canvas, sign.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
            graphics.DrawText(sign.canvas, sign.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.wait_loop(0.5)
            sign.canvas.Clear()
            player1_score += 1
            graphics.DrawText(sign.canvas, sign.fontreallybig, 55 - (len(str(player1_score)) * 9), 12, graphics.Color(255, 20, 20), str(player1_score))
            graphics.DrawText(sign.canvas, sign.fontreallybig, 65 + (len(str(player2_score)) * 9), 12, graphics.Color(20, 20, 255), str(player2_score))
            sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
            sign.wait_loop(3)
            sign.canvas.Clear()
            xball = 64
            yball = random.randint(2,30)
            xvel = random.randint(0,1)*2-1
            yvel = random.randint(0,1)*2-1

        if framecount % 5 == 0:
            xball += xvel
            yball += yvel

        #player 1 paddle
        for width in range(0, 3):
            for height in range(starting_y_value, starting_y_value + 6):
                sign.canvas.SetPixel(width, height, 255, 20, 20)

        #player 2 paddle
        for width in range(125, 128):
            for height in range(starting_y_value_2, starting_y_value_2 + 6):
                sign.canvas.SetPixel(width, height, 20, 20, 255)

        for width in range(xball-1, xball+2):
            for height in range(yball-1, yball+2):
                sign.canvas.SetPixel(width, height, 255, 255, 255)

        sign.canvas = sign.matrix.SwapOnVSync(sign.canvas)
