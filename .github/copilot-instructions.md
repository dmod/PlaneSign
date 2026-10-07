# PlaneSign - Copilot Instructions

## Project Overview
PlaneSign is a Raspberry Pi 4-powered RGB LED matrix display that shows real-time information across multiple display modes (planes, weather, satellites, finance, moon phases, etc.). It runs as a Docker container with `--network host` and `--privileged` flags.

## Documentation Policy
- Update `README.md` ONLY when the project's installation instructions change. Do not update it for general operation, configuration, usage, display features, routine bug fixes, or as a changelog.
- Agent guidance lives here and in `.github/instructions/`. Those scoped files load only for matching work: `outside.instructions.md` (Outside mode), `free-sketch.instructions.md` (the Free Sketch modal), `docker.instructions.md` (the image, installer and nginx) and `visual-verification.instructions.md` (screenshots, offline renders, layout comparisons). Put guidance for a single mode or area in a scoped file, not here.
- Record rules, constraints and their reasons: things an agent would get wrong that it cannot quickly find in the code. Do not record values or behavior the code already states, such as coordinates, sizes, timings, percentages or feature descriptions. Put a comment next to a non-obvious constant instead.
- Never record session-specific process IDs, temporary paths, credentials, or speculative explanations.

## Hardware
- **Display:** Two chained 64x32 RGB LED matrix panels = **128 pixels wide × 32 pixels tall**
- **Platform:** Raspberry Pi 4, uses the [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) library (`rgbmatrix` Python bindings)
- **Alternative display:** Adafruit 2.23" 128x32 monochrome OLED bonnet (SSD1305), selected by `PINOUT_HARDWARE_MAPPING=adafruit-oled`. Any other mapping value selects the native RGB driver. Changing the mapping needs a restart.

## Architecture
- **`planesign/`** — Main application. Each display mode is its own module (e.g. `planes.py`, `weather.py`, `moon.py`), registered with the `@planesign_mode_handler(DisplayMode.X)` decorator from `modes.py`. The entry point imports the mode modules to populate the registry.
- **`planesign/planesign.py`** — `PlaneSign` class: initializes the matrix, loads fonts, and runs the sign loop that dispatches to mode handlers.
- **`planesign/shared_config.py`** — Shared multiprocessing state and the configuration loaded from `sign.conf`.
- **`planesign/api.py`** — Flask API on port 5055. nginx proxies `/api/` to it.
- **`planesign/utilities.py`** — Shared drawing and math helpers. Center text with `get_centered_text_x_offset_value(font_width, text)` (the center is x=64).
- **`planesign/psclock.py`** — The sign's wall clock: real time unless `--fake-time`, `--time-speed` or `/debug/clock` shifts it for testing.
- **`planesign/network.py`** — Offline mode and guarded third-party requests; see "Network And Offline Mode".
- **`planesign/datasources.py`** — Registry (`SOURCES`) of reference files in `datafiles/` that are downloaded on first use. Add new on-demand files there instead of writing per-mode download code. Do not use Skyfield's `Loader` to download: its `urlopen` has no timeout.
- **`planesign/emulated_matrix/`** — The `--web` emulator: an RGBMatrix-compatible PIL canvas plus the WebSocket and frame-capture server.
- **`planesign/oled_matrix.py`** — OLED backend sharing the emulator's canvas. The entry point loads configuration before importing modes so it can select the `rgbmatrix` alias. Non-black pixels become white, except in modes that set fixed luminance thresholds. With `--web`, the preview shows the same conversion.
- **`planesign/outside.py`, `outside_scene.py`, `outside_lab.py`** — Outside mode and its lab (`/outside/lab`); see `.github/instructions/outside.instructions.md`.
- **`planesign/snow.py`** — Parses both legacy `__NEXT_DATA__` pages and current Next.js Flight streams. Hourly weather comes from the resort's weather page, not the daily summary on its snow-report page.
- **`web/`** — Frontend served by nginx; talks to the Flask API through `/api/`.
- **`ble/`** — Bluetooth Low Energy setup interface.
- **`fonts/`** — BDF bitmap fonts: `4x6`, `5x7`, `6x13`, `9x18B`, `helvR12`.
- **`sign.conf`** — Runtime config (key=value, `#` comments). Defaults are in `sign.conf.sample`.

## Network And Offline Mode
- Send every third-party request through `network.get(service, url, session=..., **kwargs)`, which applies a default `(5, 20)` timeout. For libraries that make their own requests (Finnhub's client and WebSocket, Blitzortung's WebSocket, `favicon`), call `network.require_online(service)` first. Save files with `network.download` (atomic replace), and fetch images with `utilities.download_image`.
- `OFFLINE_MODE` is read live from `CONF`, so saving it applies without a restart. `OfflineModeError` subclasses `requests.ConnectionError`, so offline mode and a real outage take the same code path and look identical on the sign. The Flask API, frame server and local files keep working offline.
- Retry policy stays with each service, because providers impose different limits. Use `retry_delay` for capped backoff, and `OfflineToggle().changed()` to retry immediately when the setting flips. `is_offline_error` treats DNS failures, refused connections and connect timeouts as offline; read timeouts and HTTP errors are not.
- Log failures with `log_unreachable`, which never logs the request URL; URLs can carry API keys.
- On the sign, internet-dependent modes show `utilities.draw_offline` / `show_offline` (the mode title plus `OFFLINE`). The main clock stays plain with `--°F` and never shows a stale plane. Workers publish an `offline` status and wake when the setting changes. `sign_loop` catches connectivity errors that escape a handler, shows that mode's OFFLINE screen and retries; it does not fall back to PLANES_ALERT.

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

- Text width is `len(text) * advance`. Right-align with `right - len(text) * advance + 1`. A 16-row band fits a 5x7 line at `baseline = top + 7` above a 4x6 line at `baseline = top + 15`.
- When two regions share rows, compare their **ink column ranges**, not their nominal boxes, and check the widest realistic content (the longest label, a two-digit value, the longest status string), not the typical case.

## Drawing Conventions
- Origin is top-left. X: 0–127, Y: 0–31.
- Use `graphics.DrawText(canvas, font, x, y, color, text)` where `y` is the text baseline, and `graphics.Color(r, g, b)` for colors.
- Call `self.matrix.SwapOnVSync(self.canvas)` to display a frame, and `self.wait_loop(seconds)` to hold it; `wait_loop` returns `True` if a forced update interrupted the wait.
- Budget layouts in real matrix pixels with the loaded font widths. Keep everything inside 128x32, with clear gaps between regions, and check the longest labels, not just typical values.
- Keep graphs proportionate to the key readings. Show units and the displayed time range, and mark the current time on time-series graphs.
- Display clock times in the timezone of the configured sensor location and honor `MILITARY_TIME`. Keep the layout stable across 12/24-hour formats and date changes.
- Read "what time is it on the sign" from `psclock.now(tz)` / `psclock.time()`, never `datetime.now()` or `time.time()`, so the mode can be driven with a fake clock. Keep `time.time()`, `time.perf_counter()` and `time.monotonic()` for scheduling, polling, timeouts, caches and the age of live data, so a sped-up clock never changes how often the sign contacts remote services.
- Aware datetimes that share a `ZoneInfo` subtract as wall-clock times and ignore DST changes. Take differences against a UTC value (for example `target_local - psclock.now(UTC)`) so countdowns stay exact across DST.
- Separate "draw one frame" from "loop until the mode changes". A pure `draw_x_frame(sign, data, config, now, elapsed)` that takes a data snapshot and timestamps can be rendered offline; a function that reads shared state and sleeps internally cannot.
- Size text to the space rather than truncating: pick the largest font that fits (6x13 → 5x7 → 4x6), so uncommon long strings degrade instead of being clipped mid-word.
- For animated effects, precompute static pixel geometry once into a module-level cache and apply only the per-frame modulation while drawing. A ~20 fps loop leaves a few milliseconds per frame, so time new draw calls in a loop.
- Derive texture and noise from a deterministic function of `(x, y)`, not `random`, so grain stays put instead of flickering every frame.

## New Display Modes
- Follow a neighboring mode's registration and lifecycle patterns. Append new `DisplayMode` members, so existing numeric IDs stay stable, and expose the mode in both `web/index.html` and `web/layout-new.html`.
- Fetch remote data in a background worker, not in the frame loop. Use timeouts, caching and retry backoff, integrate with the existing shutdown handling, and guard every request as described in "Network And Offline Mode".
- Render explicit loading, unavailable and expired-data states. Mark cached data while it is still usable; never show missing data as zero or stale data as current.

## Docker / Deployment
- The container runs with `--network host` (no port mapping; host interfaces such as `wlan0` are directly accessible). Install and update with `docker_install_and_update.sh`. nginx (`docker_nginx_planesign.conf`) serves `web/` on 80/443 and proxies `/api/` to 5055. Image and installer details are in `.github/instructions/docker.instructions.md`.

## Web Interface
- The original interface (`web/index.html`, `web/style.css`) and the new one (`web/layout-new.html`, `web/layout-new.css`) share `web/index.js`. Apply UI behavior fixes to both layouts, and bump the stylesheet and script query-string versions in the HTML to invalidate browser caches.

## Dev Environment
- The VS Code devcontainer (`.devcontainer/devcontainer.json`) is built from the project `Dockerfile` and runs with `--privileged` and `--network=host`.
- The workspace is shared with remote SSH as `pi`. The devcontainer runs as uid-1000 `ubuntu` (matching `pi`) with passwordless `sudo`, so the files it writes stay editable over SSH. If files become root-owned, run `sudo chown -R pi:pi ~/PlaneSign`.
- A per-container named volume is mounted over `.venv`, because the Pi's system Python differs from the image's. Use `.venv/bin/python`, not system Python; run `uv sync` when dependencies are missing.
- The native RGB driver build needs Pillow's `Imaging.h` from the system `python3-pil` package. If uv's Python differs from the system Python, point `CFLAGS` at the system include directory before `uv sync`.
- Launch configurations: `PlaneSign Debug` (hardware, `sudo: true`, works over SSH and in the devcontainer) and `PlaneSign Debug - Web Display` (`--web`, runs `uv sync` and starts nginx first).
- The devcontainer replaces the image's `CMD`, so `postStartCommand` starts nginx. nginx needs root for the TLS key and ports 80/443: always use `sudo service nginx start`. It is safe to run when nginx is already running.
- To drive the physical panel from the devcontainer, stop the production sign container first, then run `sudo .venv/bin/python planesign/__main__.py --mode <MODE>`.
- Only one process may drive the panel. A second instance draws over the first, and its API cannot bind port 5055, so API and lab calls silently reach the old instance.
	- Before starting one, check with `ps -eo pid,args | grep __main__.py` that none is running.
	- A `sudo` run is owned by root, so stopping or killing the shell that launched it leaves the app running. Stop it with `sudo kill <PID>` of its `__main__.py` process (the child of the `sudo` wrapper), then confirm with `ps` that every `__main__.py` process is gone before starting another.

## Testing And Visual Verification
- This project has no classic unit tests. Do not add pytest, unittest or any other automated test suite, test framework or test dependency, and do not write test files that assert on return values. Test harnesses are fine: tools that drive the real app so a person can see the result on the matrix, like the Outside lab. A harness worth keeping belongs in the app code, not in a separate test tree.
- Validate runtime and display changes by running the app with `--web` and inspecting the rendered matrix. Syntax and diagnostic checks may supplement this, but do not replace it. Documentation-only edits need no run.
- For screenshots, offline frame rendering and layout comparisons, see `.github/instructions/visual-verification.instructions.md`.

1. Check for an existing emulator or debugger before starting another. The API uses port 5055 and the frame server 5056. Reuse a suitable instance, restarting it to load Python changes. Do not terminate unrelated or user-managed processes without approval; if one holds the default ports, start an isolated instance instead (see "Running An Isolated Instance").
2. From the repository root, run the following command, or use the Web Display launch configuration. `--help` lists the testing flags (`--mode`, `--fake-time`, `--time-speed`, `--config`, `--set`, `--api-port`, `--ws-port`):

	```bash
	.venv/bin/python planesign/__main__.py --web
	```

3. With nginx running, `http://localhost/` has the controls and `http://localhost/display.html` the matrix preview. Confirm the preview is receiving frames, and reload it if its WebSocket does not reconnect after a restart.
4. Inspect the actual output (see "Capturing Frames Without A Browser"). Check readability, clipping, overlap, spacing, colors, graph labels and current-time markers, and observe every rotating phase, not just one frame.
5. Exercise the relevant edge cases through the running app: long names, 12/24-hour clocks, midnight and DST, date-specific states, negative or flat values, loading or failed data, and switching into and out of the mode. Use the fake clock instead of waiting. Report the cases you could not exercise.
6. State what was visually checked and give the preview URL. Emulator checks do not establish readability on the physical LED panel; report hardware checks separately. Leave the preview running for the user unless asked to stop it.

- Continuous INFO logs and successful HTTP requests are not input prompts; do not send terminal input or keep polling because a server is producing output.
- A `websockets ... InvalidMessage: did not receive a valid HTTP request` traceback right after the frame server starts is a port probe closing its connection; the preview still works.

### Capturing Frames Without A Browser
With `--web`, plain HTTP requests on the frame server port return the latest frame exactly as the sign drew it. This is the ground truth for inspection.

- `curl -s -o frame.png "http://127.0.0.1:5056/frame.png?scale=8"` saves a nearest-neighbour PNG (omit `scale` for the raw 128x32).
- `curl -s "http://127.0.0.1:5056/frame.txt"` prints a 1:1 character map: a header, a column ruler, row numbers and a legend. Black is `.`, very dim pixels are `:`, and each other color keeps a fixed symbol across frames. Use it to confirm exact columns, 1px overlaps, and that nothing is clipped at x=0/x=127.
- Add `?fresh=1` to wait for the next frame, or `?after=N` for a frame newer than frame N, so a capture after a mode or clock change is not the previous screen. Requests give up after 10 s with a 504; modes that draw once and then wait need a capture without `fresh`. Headers include `X-Frame-Number`, `X-Mode` and `X-Clock`.
- To check animation, compare several `?fresh=1` captures; one frame cannot prove motion.

### Controlling Time
Drive time-dependent states (moon phases, Christmas Eve, New Year, DST changes, countdowns) with the fake clock rather than waiting or reasoning about them.

- Start with `--fake-time 2026-12-24T17:59:30` (local to the sign's location without an offset), optionally with `--time-speed 60`.
- With `--web`, `/debug/clock` reads the clock; `?at=ISO[&speed=N]` sets it, `?speed=N` changes only the pace, and `?reset=1` restores real time. Setting it forces a redraw and wakes Outside's astronomy worker.
- The fake clock affects display and date logic only. Live data keeps its real fetch time, so a fake time far from now shows cached data as stale. Reset the clock when done.
- For Outside, prefer the Outside lab at `http://localhost/api/outside/lab`: it sets time, weather and holidays for Outside alone, without `--web`, and on the physical panel. See the Outside instructions.

### Running An Isolated Instance
When the default ports are taken by an instance you should not stop, or a test needs a different configuration, run a second instance alongside it:

```bash
cp sign.conf <session files>/test_sign.conf
.venv/bin/python planesign/__main__.py --web --api-port 5065 --ws-port 5066 \
	--config <session files>/test_sign.conf --set MILITARY_TIME=true --mode MOON
```

- nginx only proxies `/api/` to 5055. Call the other API directly (`curl http://127.0.0.1:5065/...`), capture frames from `http://127.0.0.1:5066/frame.png`, and preview at `http://localhost/display.html?ws_port=5066`.
- `--config PATH` reads and saves settings in that file, so `/write_config` cannot touch `sign.conf`. Keep the copy in the session workspace (it holds API keys) and delete it afterwards. `--set KEY=VALUE` (repeatable) overrides a setting without changing any file.
- Both instances share `logs/planesign.log`, `datafiles/` and `sketches/`. Stop the isolated instance when finished.

### Driving The Sign From The Terminal
- Call the Flask API at `http://127.0.0.1:5055`: for example `/set_mode/<DISPLAYMODE_NAME>`, `/status`, and the mode endpoints in `planesign/api.py`. If `curl` is missing from an older container, use `.venv/bin/python -c "import urllib.request; ..."`.
- Do not call `/write_config` on an instance that uses the real `sign.conf`: it rewrites the file from only the query parameters it receives and drops every other key. Test config-dependent formatting with `--set KEY=VALUE`, or use an isolated instance started with `--config <copy>`.
- Do not expose API keys or other secrets from `sign.conf` or configuration dumps. Redact sensitive output in logs and diagnostics.
