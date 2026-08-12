"""
Drop-in replacement for the rgbmatrix package.

When injected into sys.modules as 'rgbmatrix', this package provides
a PIL Image-backed canvas and WebSocket frame streaming so that
PlaneSign can run without physical RGB LED matrix hardware.

Usage (handled automatically by __main__.py when --web is passed):
    import emulated_matrix
    sys.modules['rgbmatrix'] = emulated_matrix
"""

from emulated_matrix import graphics
from emulated_matrix.core import RGBMatrix, RGBMatrixOptions

__all__ = ["RGBMatrix", "RGBMatrixOptions", "graphics"]
