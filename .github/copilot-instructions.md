# PlaneSign - Copilot Instructions

## Project Overview
PlaneSign is a Raspberry Pi 4-powered RGB LED matrix display that shows real-time information across multiple display modes (planes, weather, satellites, finance, moon phases, etc.). It runs as a Docker container with `--network host` and `--privileged` flags.

## Hardware
- **Display:** Two chained 64x32 RGB LED matrix panels = **128 pixels wide × 32 pixels tall**
- **Platform:** Raspberry Pi 4, uses the [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library (`rgbmatrix` Python bindings)

## Architecture
- **`planesign/`** — Main application. Each display mode is a separate module (e.g., `planes.py`, `weather.py`, `moon.py`) registered via the `@planesign_mode_handler(DisplayMode.X)` decorator in `__main__.py`.
- **`planesign/planesign.py`** — `PlaneSign` class: initializes the matrix, loads fonts, runs the main sign loop dispatching to mode handlers.
- **`planesign/utilities.py`** — Shared drawing/math helpers. Use `get_centered_text_x_offset_value(font_width, text)` to horizontally center text (center point is x=64).
- **`planesign/modes.py`** — `DisplayMode` enum defining all available modes.
- **`planesign/shared_config.py`** — Shared state (multiprocessing values) and configuration from `sign.conf`.
- **`web/`** — Frontend served by nginx; communicates with a Flask API (`/api/`).
- **`ble/`** — Bluetooth Low Energy setup interface.
- **`fonts/`** — BDF bitmap fonts: `4x6`, `5x7`, `6x13`, `9x18B`, `helvR12`.
- **`sign.conf`** — Runtime config (key=value, `#` comments). Defaults in `sign.conf.sample`.

## Fonts (loaded in PlaneSign.__init__)
| Attribute         | Font File | Char Width | Typical Use          |
|-------------------|-----------|------------|----------------------|
| `self.font46`     | 4x6       | 4px        | Small labels         |
| `self.font57`     | 5x7       | 5px        | Standard text        |
| `self.fontbig`    | 6x13      | 6px        | Larger text          |
| `self.fontreallybig` | 9x18B | 9px        | Large numbers/titles |
| `self.fontplanesign` | helvR12 | variable  | Title/branding       |

## Drawing Conventions
- Origin is top-left. X: 0–127, Y: 0–31.
- Use `graphics.DrawText(canvas, font, x, y, color, text)` where `y` is the text baseline.
- Use `graphics.Color(r, g, b)` for colors.
- Call `self.matrix.SwapOnVSync(self.canvas)` to display a frame.
- Call `self.wait_loop(seconds)` to hold a display; returns `True` if a forced update interrupted the wait.

## Docker / Deployment
- Runs with `--network host` (container shares host network stack — no port mapping needed, host interfaces like `wlan0` are directly accessible).
- Production install script: `docker_install_and_update.sh`. Nginx config: `docker_nginx_planesign.conf`.
- Flask API listens on port 5000; nginx proxies `/api/` to it and serves `web/` static files on ports 80/443.

## Dev Environment
- Uses VS Code devcontainer (`.devcontainer/devcontainer.json`) built from the project `Dockerfile`.
- Devcontainer runs with `--privileged` and `--network=host`.
- Python 3, no virtualenv — system packages installed via apt in the Dockerfile.
