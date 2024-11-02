import shared_config
from rgbmatrix import graphics
import __main__

from modes import DisplayMode

@__main__.planesign_mode_handler(DisplayMode.WELCOME)
def welcome(self):

    self.canvas.Clear()
    graphics.DrawText(self.canvas, self.fontplanesign, 34, 20, graphics.Color(46, 210, 255), "Plane Sign")
    self.canvas = self.matrix.SwapOnVSync(self.canvas)
    self.wait_loop(2)
    self.canvas.Clear()
    shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value  # Go back to the default mode after this welcome