#!/usr/bin/env python3
"""
Simple test script for OLED functionality
"""

import sys
import os

# Add the planesign directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'planesign'))

# Initialize shared_config properly like in __main__.py
from multiprocessing import Manager

# Import and set up shared_config
import shared_config

# Set up the manager and dictionaries
manager = Manager()
shared_config.data_dict = manager.dict()
shared_config.arg_dict = manager.dict()
shared_config.CONF = manager.dict()

# Set test configuration
shared_config.CONF["PINOUT_HARDWARE_MAPPING"] = "adafruit-oled"
shared_config.CONF["DEFAULT_BRIGHTNESS"] = "80"
shared_config.CONF["GPIO_SLOWDOWN"] = "5"

print("✓ Shared config initialized")

# Initialize OLED
try:
    import oled_adapter
    if oled_adapter.initialize_oled_if_needed():
        print("✓ OLED adapter initialized successfully")
        
        # Test basic functionality
        from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
        
        print("✓ Successfully imported rgbmatrix modules (monkey-patched)")
        
        # Create matrix instance
        options = RGBMatrixOptions()
        matrix = RGBMatrix(options=options)
        
        print(f"✓ Created OLED matrix: {matrix.width}x{matrix.height}")
        
        # Create canvas
        canvas = matrix.CreateFrameCanvas()
        print("✓ Created canvas")
        
        # Test drawing
        canvas.Clear()
        font = graphics.Font()
        graphics.DrawText(canvas, font, 10, 10, graphics.Color(255, 255, 255), "Test")
        matrix.SwapOnVSync(canvas)
        
        print("✓ Successfully drew text to OLED")
        print("✓ All OLED tests passed!")
        
    else:
        print("✗ OLED adapter not initialized (likely using RGB matrix mode)")
        
except ImportError as e:
    print(f"✗ Import error: {e}")
    print("Note: This is expected if OLED libraries are not installed")
except Exception as e:
    print(f"✗ Error: {e}")
    import traceback
    traceback.print_exc()
import time
import logging

# Add the planesign directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'planesign'))

# Set up basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] - %(message)s')

# Mock shared_config for testing
class MockSharedConfig:
    CONF = {"PINOUT_HARDWARE_MAPPING": "adafruit-oled", "OLED_WIDTH": "128", "OLED_HEIGHT": "32"}
    font_dir = "./fonts"

import shared_config
shared_config.CONF = MockSharedConfig.CONF
shared_config.font_dir = MockSharedConfig.font_dir

# Test OLED initialization
try:
    print("=== PlaneSign OLED Adapter Test ===")
    import planesign.oled_adapter as oled_adapter
    
    print("Testing OLED adapter...")
    
    # Check if OLED should be used
    should_use = oled_adapter.should_use_oled()
    print(f"Should use OLED: {should_use}")
    
    if should_use:
        # Initialize OLED
        success = oled_adapter.initialize_oled_if_needed()
        print(f"OLED initialization success: {success}")
        
        # Test basic rgbmatrix functionality regardless of hardware availability
        print("Testing monkey-patched rgbmatrix...")
        
        from rgbmatrix import graphics, RGBMatrix, RGBMatrixOptions
        
        # Create matrix
        options = RGBMatrixOptions()
        print(f"Matrix options: {options.cols}x{options.rows}, hardware: {options.hardware_mapping}")
        
        matrix = RGBMatrix(options=options)
        canvas = matrix.CreateFrameCanvas()
        
        print(f"Canvas size: {canvas.width}x{canvas.height}")
        
        # Test graphics operations
        print("Testing graphics operations...")
        
        # Clear canvas
        canvas.Clear()
        
        # Test color creation
        red = graphics.Color(255, 0, 0)
        green = graphics.Color(0, 255, 0)
        blue = graphics.Color(0, 0, 255)
        white = graphics.Color(255, 255, 255)
        
        print(f"Created colors - Red: {red}, White: {white}")
        
        # Test pixel setting
        canvas.SetPixel(10, 10, 255, 0, 0)
        canvas.SetPixel(20, 10, 0, 255, 0)
        canvas.SetPixel(30, 10, 0, 0, 255)
        
        # Test font and text
        font = graphics.Font()
        if hasattr(shared_config, 'font_dir') and shared_config.font_dir:
            font_path = os.path.join(shared_config.font_dir, "5x7.bdf")
            if os.path.exists(font_path):
                font.LoadFont(font_path)
                print(f"Loaded font from {font_path}")
            else:
                print(f"Font file not found: {font_path}, using default")
        else:
            print("Using default font (no font directory configured)")
            
        graphics.DrawText(canvas, font, 5, 20, white, "OLED Test")
        
        # Test brightness
        print("Testing brightness control...")
        canvas.brightness = 80
        matrix.brightness = 80
        
        # Display
        canvas = matrix.SwapOnVSync(canvas)
        
        if success:
            print("✓ Test completed! Check your OLED display for 'OLED Test' text.")
            print("  Display should show colored pixels and text.")
            time.sleep(5)
            
            # Clear display
            print("Clearing display...")
            canvas.Clear()
            canvas = matrix.SwapOnVSync(canvas)
        else:
            print("✓ Console mode test completed! Check logs for display operations.")
            
    else:
        print("RGB matrix mode - OLED not configured")
        print("To test OLED mode, set PINOUT_HARDWARE_MAPPING=adafruit-oled in sign.conf")
        
    print("=== Test Complete ===")
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("OLED libraries may not be installed. Run: pip install adafruit-circuitpython-ssd1305")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
