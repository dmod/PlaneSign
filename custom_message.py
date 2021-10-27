import random
from collections import namedtuple
import shared_config
from rgbmatrix import graphics

RGB = namedtuple('RGB', 'r g b')

COLORS = {}
COLORS[0] = [RGB(3, 194, 255)] #Plain
COLORS[1] = [RGB(0, 0, 0)] #RAINBOW
COLORS[2] = [RGB(12, 169, 12), RGB(206, 13, 13)] #CHRISTMAS
COLORS[3] = [RGB(173, 0, 30), RGB(178, 178, 178), RGB(37, 120, 178)] #FOURTH_OF_JULY
COLORS[4] = [RGB(20, 20, 20), RGB(247, 95, 28)] #HALLOWEEN


def show_custom_message(sign):
    starting_color_index = 0

    while shared_config.shared_mode.value == 8:
        sign.canvas.Clear()

        raw_message = ""

        if "custom_message" in shared_config.data_dict:
            raw_message = shared_config.data_dict["custom_message"]

        clean_message = raw_message.strip()

        line_1 = clean_message[0:14]
        line_2 = clean_message[14:]

        line_1 = line_1.strip()
        line_2 = line_2.strip()

        # Figure out odd/even # of chars spacing
        if len(line_1) % 2 == 0:
            starting_line_1_x_index = 64 - ((len(line_1) / 2) * 9)
        else:
            starting_line_1_x_index = 59 - (((len(line_1) - 1) / 2) * 9)

        if len(line_2) % 2 == 0:
            starting_line_2_x_index = 64 - ((len(line_2) / 2) * 9)
        else:
            starting_line_2_x_index = 59 - (((len(line_2) - 1) / 2) * 9)

        print_the_char_at_this_x_index = starting_line_1_x_index

        if len(line_2) == 0:
            print_at_y_index = 21
        else:
            print_at_y_index = 14

        if shared_config.shared_color_mode.value == 1:
            selected_color_list = [RGB(random.randrange(10, 255), random.randrange(10, 255), random.randrange(10, 255))]
        elif shared_config.shared_color_mode.value >= 5:
            selected_color_list = [RGB(((shared_config.shared_color_mode.value-5) >> 16) & 255, ((shared_config.shared_color_mode.value-5) >> 8) & 255, (shared_config.shared_color_mode.value-5) & 255)]
        else:
            selected_color_list = COLORS[shared_config.shared_color_mode.value]

        if starting_color_index >= len(selected_color_list):
            starting_color_index = 0

        color_index = starting_color_index

        for line_1_char in line_1:
            char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
            graphics.DrawText(sign.canvas, sign.fontreallybig, print_the_char_at_this_x_index, print_at_y_index, char_color, line_1_char)
            print_the_char_at_this_x_index += 9

            color_index = color_index + 1 if line_1_char is not  ' ' else color_index

            if color_index >= len(selected_color_list):
                color_index = 0

        print_the_char_at_this_x_index = starting_line_2_x_index

        for line_2_char in line_2:
            char_color = graphics.Color(selected_color_list[color_index].r, selected_color_list[color_index].g, selected_color_list[color_index].b)
            graphics.DrawText(sign.canvas, sign.fontreallybig, print_the_char_at_this_x_index, 28, char_color, line_2_char)
            print_the_char_at_this_x_index += 9

            color_index = color_index + 1 if line_2_char is not  ' ' else color_index

            if color_index >= len(selected_color_list):
                color_index = 0
        sign.matrix.SwapOnVSync(sign.canvas)
        
        starting_color_index += 1

        if shared_config.shared_color_mode.value == 1:
            sign.wait_loop(0.1)
        elif shared_config.shared_color_mode.value >= 5:
            sign.wait_loop(0.1)
        else:
            sign.wait_loop(1.1)
