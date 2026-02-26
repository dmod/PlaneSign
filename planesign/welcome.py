import subprocess
import shared_config
from rgbmatrix import graphics
from utilities import get_centered_text_x_offset_value
import __main__

from modes import DisplayMode


def get_mac_suffix(interface='wlan0'):
    try:
        cmd = f"cat /sys/class/net/{interface}/address"
        mac_address = subprocess.check_output(cmd, shell=True, timeout=5).decode().strip()
        return mac_address.replace(":", "")[-4:].upper()
    except Exception:
        return "????"


@__main__.planesign_mode_handler(DisplayMode.WELCOME)
def welcome(self):

    device_name = f"PlaneSign-BLE-{get_mac_suffix()}"
    device_name_x = int(get_centered_text_x_offset_value(4, device_name))

    self.canvas.Clear()
    graphics.DrawText(self.canvas, self.fontplanesign, 34, 14, graphics.Color(46, 210, 255), "Plane Sign")
    graphics.DrawText(self.canvas, self.font46, device_name_x, 26, graphics.Color(180, 180, 180), device_name)
    self.canvas = self.matrix.SwapOnVSync(self.canvas)
    self.wait_loop(2)
    self.canvas.Clear()
    shared_config.shared_mode.value = DisplayMode.PLANES_ALERT.value  # Go back to the default mode after this welcome