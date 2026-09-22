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

### Glyph Geometry (needed to budget a layout in pixels)
`DrawText`'s `y` is the baseline, and the bundled BDF glyphs sit **entirely above** it — the baseline row itself is blank. Ink rows for capitals and digits:

| Font | Ink rows | Advance | Notes |
|------|----------|---------|-------|
| 4x6  | `baseline-5` … `baseline-1` (5 rows) | 4px | |
| 5x7  | `baseline-6` … `baseline-1` (6 rows) | 5px | |
| 6x13 | `baseline-9` … `baseline-1` (9 rows) | 6px | |
| 9x18B | `baseline-10` … `baseline-1` (10 rows) | 9px | digits ink ~7px wide, ~1px side bearing |

- Text width is `len(text) * advance`. Right-align with `right - len(text) * advance + 1`; a 16-row band fits a 5x7 line at `baseline = top + 7` above a 4x6 line at `baseline = top + 15`.
- When two regions share rows, compare their **ink column ranges**, not their nominal boxes, and check the widest realistic content (the longest label, a two-digit value, the longest status string) — not the typical case.

## Drawing Conventions
- Origin is top-left. X: 0–127, Y: 0–31.
- Use `graphics.DrawText(canvas, font, x, y, color, text)` where `y` is the text baseline.
- Use `graphics.Color(r, g, b)` for colors.
- Call `self.matrix.SwapOnVSync(self.canvas)` to display a frame.
- Call `self.wait_loop(seconds)` to hold a display; returns `True` if a forced update interrupted the wait.
- Budget the layout in actual matrix pixels using the loaded font widths. Keep text and graphics within the 128x32 bounds, with clear gaps between regions; check the longest labels, not just typical values.
- Keep graphs proportionate to the key readings. Show units and the displayed time range, and mark the current time on time-series graphs.
- Display clock times in the timezone of the configured sensor location and honor `MILITARY_TIME`. Keep the layout stable across 12/24-hour formats and date changes.
- Separate "draw one frame" from "loop until the mode changes". A pure `draw_x_frame(sign, data, config, now, elapsed)` that takes a data snapshot and timestamps can be rendered offline and screenshotted without running the sign; a function that reads shared state and sleeps internally cannot.
- Prefer sizing text to the space rather than truncating: pick the largest font that fits (6x13 → 5x7 → 4x6) so uncommon long strings degrade instead of being clipped mid-word.
- For animated effects, precompute the static pixel geometry once into a module-level cache and apply only the per-frame modulation (brightness, phase) while drawing. Measure the result — a frame loop running at ~20 fps has a few milliseconds of budget, so time the draw call in a loop before shipping it.
- Derive texture and noise from a deterministic function of `(x, y)` rather than `random`, so speckle and grain stay put instead of flickering every frame. Reserve motion for the effect you actually intend.

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
- A `websockets ... InvalidMessage: did not receive a valid HTTP request` traceback right after the frame server starts comes from a port probe closing the connection; the preview still works, so do not treat it as a failure.

### Rendering Frames Offline For Fast Iteration
Restarting the app for every pixel tweak is slow, and some states (a rare data combination, a failure mode, expired data) cannot be waited for. For layout and artwork work, render frames directly with the real fonts into a PNG first, then confirm the result in the running app.

- Bootstrap: set `PLANESIGN_EMULATED_DISPLAY=1`, `import emulated_matrix` and assign it to `sys.modules["rgbmatrix"]`, then set `shared_config.local_timezone` and `shared_config.CONF` before importing the mode module. Mode modules `import __main__` for the `@planesign_mode_handler` decorator, so give the running script a `planesign_mode_handler` attribute that returns the function unchanged.
- Build a stub sign exposing `canvas` (an `emulated_matrix.core.Canvas(128, 32)`) plus the `font46`/`font57`/`fontbig`/`fontreallybig` attributes loaded from `fonts/`, then call the mode's frame-drawing function directly. Save `canvas._image` upscaled with `Image.NEAREST` to inspect it.
- Drive edge cases with synthetic data: parse a real cached payload once, then deep-copy and mutate the parsed snapshot to force states the live feed will not produce on demand.
- Print a 1:1 ASCII pixel map (128 columns, a column ruler every 5/10) that classifies each pixel by color into symbols. It is the fastest way to confirm exact columns, spot 1px overlaps, and prove nothing is clipped at x=0/x=127 — an upscaled screenshot hides all three.
- Keep these harness scripts and their PNG output in the session workspace, never in the repo; the repo must not accumulate test scaffolding.

### Comparing Layout Options In The Browser
When a layout is a judgement call, build two or three complete alternatives and let the user see them side by side instead of describing them.

- Render each candidate to a PNG with the offline harness, write a small `index.html` in the session workspace that lists them with headings, `image-rendering: pixelated`, and a one-line note on what each trades away.
- Serve that folder on a spare port (not 80/443/5055/5056), for example `python3 -m http.server 8899 --bind 127.0.0.1` from the session files directory, then open the page with the browser tools and hand the user the URL.
- Show every candidate rendering the *same* data state, and include the current shipped layout as the first entry so the comparison is honest.
- Pair the images with a short table of what actually changed in pixels (region widths, font sizes, area gained), and ask which direction to pursue before implementing one.
- For artwork, prototype variants the same way — render four versions of the graphic, look at them, then implement the winner. Animated effects should be rendered as a strip of frames across the cycle to confirm the motion reads correctly.

### Screenshotting The Preview
- `display.html` sizes `canvas#matrix` at a fixed 1024x256 CSS pixels, which is wider than the integrated browser viewport (~892x332), so a plain screenshot silently crops both edges of the matrix. Before capturing, shrink it so all 128 columns are in view:

	```js
	page.evaluate(() => {
		const c = document.getElementById('matrix');
		c.style.width = '768px';
		c.style.height = '192px';
	});
	```

- Capture with the screenshot tool scoped to the `canvas` selector. Confirm the capture shows x=0 through x=127 (both outer edges of the layout) before trusting it; a cropped frame looks like text that is missing its first or last characters.
- Re-apply the resize after any page reload, and reload the page after restarting the emulator.
- Playwright's `locator.screenshot({ path })` writes to the browser host, not into the devcontainer, so those files are not readable from the workspace. Use the screenshot tool for images you need to inspect.
- Rotating content advances on wall-clock time, so consecutive screenshot calls naturally land on different phases; repeat the call until every phase has been seen.
- A screenshot can come back stale after a data or mode change. Before concluding the sign is wrong, read the canvas directly — `getImageData` on `canvas#matrix` returns ground truth. The backing store is 8x the matrix (1024x256), so sample matrix pixel `(x, y)` at `(x * 8 + 4, y * 8 + 4)`.
- Verify animation the same way: sample one pixel repeatedly over a few seconds and check the values actually change through the expected range. A still frame cannot prove motion.

### Driving The Sign From The Terminal
- Hit the Flask API directly at `http://127.0.0.1:5055` (for example `/set_mode/<DISPLAYMODE_NAME>`, `/status`, and mode-specific endpoints in `planesign/api.py`). `curl` is in the image; in a container built before it was added, use `.venv/bin/python -c "import urllib.request; ..."` instead.
- Do not call `/write_config` to toggle settings for a test: it rewrites `sign.conf` from only the query parameters it receives and drops every key that is not passed. Verify config-dependent formatting (such as `MILITARY_TIME`) another way and report how it was checked.
- Do not expose API keys or other secrets from `sign.conf` or configuration dumps. Redact sensitive output when capturing logs or sharing diagnostics.
