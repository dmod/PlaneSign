#!/usr/bin/python3
# -*- coding: utf-8 -*-

"""
OLED Adapter for PlaneSign - SSD1305 Support
This module provides a monkey-patching adapter to use Adafruit SSD1305 OLED displays
instead of the RGB LED matrix.
"""

import logging
import time
from PIL import Image, ImageDraw, ImageFont
import shared_config

try:
    import board
    import busio
    import digitalio
    from adafruit_ssd1305 import SSD1305_I2C
    OLED_AVAILABLE = True
except ImportError as e:
    OLED_AVAILABLE = False
    logging.warning(f"OLED libraries not available: {e}")


class OLEDColor:
    """Mock color class for OLED compatibility"""
    def __init__(self, r, g, b):
        # For monochrome OLED, convert RGB to grayscale brightness
        self.brightness = int((r * 0.299 + g * 0.587 + b * 0.114))
        self.r = r
        self.g = g
        self.b = b


class OLEDFont:
    """Mock font class for OLED compatibility"""
    def __init__(self):
        self.font_path = None
        self.pil_font = None
        
    def LoadFont(self, path):
        """Load a BDF font - convert to PIL font approximation"""
        self.font_path = path
        font_name = path.split('/')[-1] if path else "default"
        
        # Map BDF fonts to approximate PIL font sizes
        font_size_map = {
            "4x6.bdf": 8,
            "5x7.bdf": 10,
            "6x13.bdf": 12,
            "9x18B.bdf": 16,
            "helvR12.bdf": 14
        }
        
        size = font_size_map.get(font_name, 10)
        
        try:
            # Try to use a monospace font
            self.pil_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)
        except (OSError, IOError):
            try:
                # Try alternative monospace fonts
                alternatives = [
                    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                    "/usr/share/fonts/TTF/DejaVuSansMono.ttf"
                ]
                for alt_font in alternatives:
                    try:
                        self.pil_font = ImageFont.truetype(alt_font, size)
                        break
                    except (OSError, IOError):
                        continue
                else:
                    # Fallback to default font
                    self.pil_font = ImageFont.load_default()
            except:
                self.pil_font = ImageFont.load_default()
        
        logging.debug(f"Loaded OLED font approximation for {font_name} with size {size}")


class OLEDCanvas:
    """Mock canvas class for OLED compatibility"""
    def __init__(self, oled_display):
        self.oled_display = oled_display
        self.width = oled_display.width
        self.height = oled_display.height
        self.image = Image.new("1", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)
        self._brightness = 255  # OLED brightness value (0-255)
        
    @property
    def brightness(self):
        return self._brightness
        
    @brightness.setter 
    def brightness(self, value):
        """Set OLED brightness (0-100 scale from PlaneSign, convert to 0-255)"""
        self._brightness = int((value / 100.0) * 255)
        # Note: SSD1305 brightness control would be implemented here
        # self.oled_display.contrast(self._brightness)
        
    def Clear(self):
        """Clear the canvas"""
        self.draw.rectangle((0, 0, self.width, self.height), fill=0)
        
    def SetPixel(self, x, y, r, g, b):
        """Set a pixel - convert RGB to monochrome"""
        if 0 <= x < self.width and 0 <= y < self.height:
            # Convert RGB to grayscale and threshold for monochrome
            brightness = int((r * 0.299 + g * 0.587 + b * 0.114))
            color = 1 if brightness > 127 else 0
            self.draw.point((x, y), fill=color)
            
    def Fill(self, r, g, b):
        """Fill entire canvas with color"""
        brightness = int((r * 0.299 + g * 0.587 + b * 0.114))
        color = 1 if brightness > 127 else 0
        self.draw.rectangle((0, 0, self.width, self.height), fill=color)


class OLEDMatrix:
    """Mock matrix class for OLED compatibility"""
    def __init__(self, options=None):
        if not OLED_AVAILABLE:
            raise ImportError("OLED libraries not available")
            
        # Initialize I2C and OLED display
        self.i2c = busio.I2C(board.SCL, board.SDA)
        
        # Fixed OLED size: 128x32 for SSD1305
        self.oled = SSD1305_I2C(128, 32, self.i2c)
        
        # Set up display properties
        self.width = self.oled.width
        self.height = self.oled.height
        
        # Create canvas
        self.current_canvas = OLEDCanvas(self.oled)
        
        # Clear display
        self.oled.fill(0)
        self.oled.show()
        
        self._brightness = 255
        
        logging.info(f"Initialized OLED display: {self.width}x{self.height}")
        
    @property
    def brightness(self):
        return self._brightness
        
    @brightness.setter
    def brightness(self, value):
        """Set matrix brightness (0-100 scale)"""
        self._brightness = int((value / 100.0) * 255)
        # Set OLED contrast
        try:
            self.oled.contrast(self._brightness)
        except:
            # Some OLED libraries may not support contrast control
            pass
            
    def CreateFrameCanvas(self):
        """Create a frame canvas"""
        return OLEDCanvas(self.oled)
        
    def SwapOnVSync(self, canvas):
        """Display the canvas and return it"""
        # Convert PIL image to OLED format and display
        self.oled.image(canvas.image)
        self.oled.show()
        
        # Return the same canvas (OLED doesn't use double buffering like RGB matrix)
        return canvas


class OLEDGraphics:
    """Mock graphics module for OLED compatibility"""
    
    @staticmethod
    def Color(r, g, b):
        """Create a color object"""
        return OLEDColor(r, g, b)
        
    @staticmethod
    def DrawText(canvas, font, x, y, color, text):
        """Draw text on canvas"""
        if hasattr(canvas, 'draw') and hasattr(font, 'pil_font'):
            # Convert color to monochrome
            brightness = color.brightness if hasattr(color, 'brightness') else 255
            fill_color = 1 if brightness > 127 else 0
            
            try:
                canvas.draw.text((x, y), text, font=font.pil_font, fill=fill_color)
            except Exception as e:
                logging.error(f"Error drawing text: {e}")
                # Fallback to default font
                canvas.draw.text((x, y), text, fill=fill_color)
                
    @staticmethod
    def Font():
        """Create a font object"""
        return OLEDFont()


def monkey_patch_for_oled():
    """Apply monkey patches to use OLED instead of RGB matrix"""
    import sys
    
    # Create mock modules
    class MockRGBMatrix:
        def __init__(self, **kwargs):
            pass
            
        def __new__(cls, options=None, **kwargs):
            return OLEDMatrix(options)
    
    class MockRGBMatrixOptions:
        def __init__(self):
            self.cols = 128  # OLED width
            self.rows = 32   # OLED height
            self.gpio_slowdown = 0
            self.chain_length = 1
            self.limit_refresh_rate_hz = 60
            self.hardware_mapping = "adafruit-oled"
            self.drop_privileges = False
    
    # Create mock rgbmatrix module
    class MockRGBMatrixModule:
        RGBMatrix = MockRGBMatrix
        RGBMatrixOptions = MockRGBMatrixOptions
        graphics = OLEDGraphics()
    
    # Install the mock module
    sys.modules['rgbmatrix'] = MockRGBMatrixModule()
    
    logging.info("Applied OLED monkey patches - RGB matrix functionality redirected to SSD1305 OLED")


def should_use_oled():
    """Check if OLED should be used based on configuration"""
    if not OLED_AVAILABLE:
        return False
    
    # Handle case where CONF might not be initialized yet
    if not hasattr(shared_config, 'CONF') or shared_config.CONF is None:
        return False
        
    return (shared_config.CONF.get("PINOUT_HARDWARE_MAPPING", "").lower() == "adafruit-oled")


def initialize_oled_if_needed():
    """Initialize OLED display if configured to use it"""
    if should_use_oled():

        try:
            # Apply monkey patches before any RGB matrix imports
            monkey_patch_for_oled()
            logging.info("OLED mode enabled - using SSD1305 display")
            return True
        except Exception as e:
            logging.error(f"Failed to initialize OLED: {e}")
            return False
    else:
        logging.info("RGB matrix mode enabled")
        return False
