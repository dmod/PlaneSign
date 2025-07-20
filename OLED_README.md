# OLED Display Support for PlaneSign

PlaneSign now supports Adafruit SSD1305 OLED displays as an alternative to RGB LED matrices. This feature uses monkey patching to redirect all RGB matrix calls to OLED-compatible operations without requiring code changes to the existing display modules.

## Hardware Requirements

- Raspberry Pi (any model with I2C support)
- Adafruit SSD1305 OLED Display (128x32 or 128x64 recommended)
- I2C connection between Pi and display

## Wiring

Connect the OLED display to your Raspberry Pi's I2C pins:

- VCC → 3.3V or 5V (depending on your display)
- GND → GND
- SCL → GPIO 3 (SCL)
- SDA → GPIO 2 (SDA)

## Software Setup

### 1. Install Required Libraries

```bash
pip install adafruit-circuitpython-ssd1305
```

Or install all dependencies:

```bash
pip install -r requirements.txt
```

### 2. Enable I2C

Enable I2C on your Raspberry Pi:

```bash
sudo raspi-config
```

- Navigate to: Interface Options → I2C → Enable

### 3. Configure PlaneSign

Edit your `sign.conf` file and set:

```
PINOUT_HARDWARE_MAPPING=adafruit-oled
```

Optional OLED size configuration (defaults to 128x32):

```
OLED_WIDTH=128
OLED_HEIGHT=32
```

For 128x64 displays:

```
OLED_WIDTH=128
OLED_HEIGHT=64
```

## How It Works

### Monkey Patching

When `PINOUT_HARDWARE_MAPPING=adafruit-oled` is detected:

1. The OLED adapter monkey patches the `rgbmatrix` module before any imports
2. All RGB matrix classes and functions are replaced with OLED-compatible versions
3. Existing PlaneSign modules work unchanged - they still call `graphics.DrawText()`, `canvas.SetPixel()`, etc.
4. These calls are automatically translated to OLED operations

### Color Conversion

Since OLED displays are monochrome:

- RGB colors are converted to grayscale using standard luminance formula: `0.299*R + 0.587*G + 0.114*B`
- Brightness values above 127 become white pixels, below become black pixels

### Font Handling

BDF fonts used by the RGB matrix are approximated using PIL TrueType fonts:

- `4x6.bdf` → 8pt font
- `5x7.bdf` → 10pt font  
- `6x13.bdf` → 12pt font
- `9x18B.bdf` → 16pt font
- `helvR12.bdf` → 14pt font

The system attempts to use DejaVu Sans Mono for consistent monospace rendering.

## Testing

Test your OLED setup:

```bash
cd /home/pi/PlaneSign
python test_oled.py
```

This will:
1. Check if OLED mode is configured
2. Initialize the display
3. Test basic graphics operations
4. Display "OLED Test" text

## Switching Between RGB and OLED

To switch back to RGB matrix mode, change your configuration:

```
PINOUT_HARDWARE_MAPPING=adafruit-hat
```

No other changes are needed - the same PlaneSign code works with both display types.

## Troubleshooting

### "OLED libraries not available"
Install the required library:
```bash
pip install adafruit-circuitpython-ssd1305
```

### "No I2C device found"
- Check wiring connections
- Verify I2C is enabled: `sudo i2cdetect -y 1`
- Your OLED should appear at address 0x3C or 0x3D

### Display not working
- Verify correct OLED_WIDTH and OLED_HEIGHT settings
- Check power supply (some displays need 5V, others 3.3V)
- Try different I2C addresses if your display uses a non-standard one

### Text appears garbled
- The font approximation may not be perfect for all text
- Try adjusting font size mappings in `oled_adapter.py`
- Consider using simpler display modes that work better on smaller screens

## Limitations

1. **Monochrome**: All colors are converted to black/white
2. **Resolution**: OLED displays are typically much smaller than RGB matrices
3. **Performance**: Slightly slower than direct RGB matrix operations
4. **Font accuracy**: BDF fonts are approximated, not perfectly matched

## Supported Display Modes

All PlaneSign display modes should work with OLED, though some may be more readable than others on the smaller screen:

- **Best**: Welcome, Weather, Custom Message, Countdown
- **Good**: Planes Alert, Track a Flight
- **Challenging**: Complex graphics modes (Mandelbrot, Conway's Game of Life)

Consider the smaller screen size when using complex display modes.
