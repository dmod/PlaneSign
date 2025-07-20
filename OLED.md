# OLED Display Support

PlaneSign now supports Adafruit SSD1305 OLED displays as an alternative to RGB LED matrices.

## Hardware Requirements

- Adafruit SSD1305 OLED Display (128x32 pixels)
- I2C connection to Raspberry Pi

## Software Requirements

Install the required OLED libraries:

```bash
pip install adafruit-circuitpython-ssd1305
```

## Configuration

To use the OLED display instead of the RGB LED matrix:

1. Edit your `sign.conf` file
2. Change `PINOUT_HARDWARE_MAPPING` from `adafruit-hat` to `adafruit-oled`

Example:
```
PINOUT_HARDWARE_MAPPING=adafruit-oled
```

## Wiring

Connect the SSD1305 OLED to your Raspberry Pi:

- VCC → 3.3V or 5V
- GND → Ground
- SCL → GPIO 3 (I2C Clock)
- SDA → GPIO 2 (I2C Data)

## Features

- All PlaneSign modes are supported on the OLED
- Automatic color conversion from RGB to monochrome
- Font approximation using PIL fonts
- Same brightness control as RGB matrix
- Seamless integration - no code changes needed in existing modes

## Testing

Run the test script to verify OLED functionality:

```bash
python3 test_oled.py
```

## Limitations

- Monochrome display (no color)
- Smaller display area (128x32 vs 128x64 RGB matrix)
- Some visual effects may appear different due to monochrome nature

## Troubleshooting

### Import Errors
If you see import errors for OLED libraries, install them:
```bash
pip install adafruit-circuitpython-ssd1305
```

### I2C Issues
Ensure I2C is enabled on your Raspberry Pi:
```bash
sudo raspi-config
# Go to Interface Options → I2C → Enable
```

### Permission Issues
Make sure your user is in the i2c group:
```bash
sudo usermod -a -G i2c $USER
```

### Display Not Working
Check I2C connectivity:
```bash
sudo i2cdetect -y 1
```

You should see your OLED device (typically at address 0x3C or 0x3D).
