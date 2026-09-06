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
- Budget the layout in actual matrix pixels using the loaded font widths. Keep text and graphics within the 128x32 bounds, with clear gaps between regions; check the longest labels, not just typical values.
- Keep graphs proportionate to the key readings. Show units and the displayed time range, and mark the current time on time-series graphs.
- Display clock times in the timezone of the configured sensor location and honor `MILITARY_TIME`. Keep the layout stable across 12/24-hour formats and date changes.

## New Display Modes
- Follow a neighboring mode's registration and lifecycle patterns. Append new `DisplayMode` members so existing numeric IDs remain stable, and expose the mode in both `web/index.html` and `web/layout-new.html`.
- Fetch remote data in a background worker, not in the frame-rendering loop. Use request timeouts, caching, and retry backoff; integrate workers with the existing shutdown handling.
- Render explicit loading, unavailable, and expired-data states. Identify cached data when it is still usable; do not show missing data as zero or stale data as current.

## Docker / Deployment
- Runs with `--network host` (container shares host network stack — no port mapping needed, host interfaces like `wlan0` are directly accessible).
- Production install script: `docker_install_and_update.sh`. Nginx config: `docker_nginx_planesign.conf`.
- Flask API listens on port 5055; nginx proxies `/api/` to it and serves `web/` static files on ports 80/443.

## Dev Environment
- Uses VS Code devcontainer (`.devcontainer/devcontainer.json`) built from the project `Dockerfile`.
- Devcontainer runs with `--privileged` and `--network=host`.
- Development uses the `uv`-managed `.venv`; use its Python interpreter rather than assuming system Python has the project dependencies. Run `uv sync` when dependency setup is needed. Native/system packages are installed via apt in the Dockerfile.
- The `PlaneSign Debug - Web Display` VS Code launch configuration runs with `--web` and has a pre-launch task for `uv sync` and nginx startup.

## Testing And Visual Verification
- Do not create unit-test or pytest files, automated test suites, or test-only scaffolding. Do not add testing frameworks or dependencies.
- Validate runtime and display changes by running the application with `--web` and visually inspecting the rendered matrix. Syntax/diagnostic checks may supplement this, but do not replace visual verification. Documentation-only edits do not require starting the application.

1. Check for an existing emulator or debugger before starting another. The Flask API uses port 5055 and the WebSocket frame server uses port 5056. Reuse a suitable running instance; restart it when needed to load Python changes. Do not launch competing instances or terminate unrelated/user-managed processes without approval.
2. From the repository root, run the following command, or use the Web Display launch configuration:

	```bash
	.venv/bin/python planesign/__main__.py --web
	```

3. With nginx running, open `http://localhost/` for the controls and `http://localhost/display.html` for the matrix preview. Select the affected mode and confirm the preview is connected and receiving frames. Reload the preview if its WebSocket does not reconnect after an emulator restart.
4. Inspect the actual matrix output, using browser screenshots when available. Check readability, clipping, overlap, spacing, colors, graph labels, and current-time markers. Observe all rotating header/content phases, not just one frame.
5. Exercise the relevant edge cases through the running application where practical: long names, 12/24-hour clocks, midnight transitions, negative/flat values, loading or failed data, and switching into and out of the mode. Report cases that could not be exercised rather than claiming they passed.
6. State what was visually checked and provide the preview URL. Emulator verification does not establish physical LED-panel readability; report hardware checks separately. Leave the preview available for user review unless asked to stop it.

- Normal continuous INFO logs and successful HTTP requests are not input prompts. Do not send terminal input or repeatedly poll just because a long-running server is producing output.
- Do not expose API keys or other secrets from `sign.conf` or configuration dumps. Redact sensitive output when capturing logs or sharing diagnostics.
