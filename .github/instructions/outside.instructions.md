---
description: "Use when changing Outside mode: outside.py, outside_scene.py, outside_lab.py or the Outside lab page. Covers scene artwork, draw order, determinism, weather and astronomy inputs, wildlife, holidays, corner labels, LED color tuning and the lab's override rules."
applyTo: "planesign/outside*.py, planesign/templates/outside_lab.html"
---
# Outside Mode

Outside (`outside.py` drives it, `outside_scene.py` draws it) is a 128x32 pixel-art landscape driven by local astronomy and the OpenWeather feed. Positions, sizes and timings live in named constants in `outside_scene.py`; read them there rather than relying on numbers in docs.

## Determinism
- `render_outside_frame(environment, elapsed, seed)` is pure. Texture and noise come from deterministic hashes of `(x, y)`; never use `random` while drawing.
- Occasional events (wildlife visits, lightning, shooting stars, Santa, fireworks) are scheduled per fixed time slot from `(slot, seed)`, and they never cross a slot boundary. A state is then a pure function of `elapsed`, so the forecast slider and the lab can jump without breaking an animation.
- Anything that scales with a reading (cloud shapes, firefly count, falling leaves) appears in a fixed priority order. Changing the reading then grows or shrinks the effect instead of reshuffling it.
- Wildlife schedules exclude each other: the eagle never appears during a dog outing, deer/foxes/rabbits skip outings, and the bird flock skips eagle visits. Keep these exclusions when adding animals.
- Cache static geometry and colorized layers; frames only scroll, modulate and blend. The loop runs at about 20 fps, so time any new draw call.

## Composition And Draw Order
- The single small mountain right of center keeps the horizon low, so the night sky stays open. Keep the top rows of both corners clear for the clock and temperature labels: the tree, the Big Dipper, the owl perch and shooting stars all stay below them.
- Back to front: sky gradient, stars and the Big Dipper, shooting stars, sun and moon, clouds; then fireworks and Santa (in the distance); then the land, pond reflections and fog; then the flag, leaves, wildlife, eagle, hut and dog, fireflies, tree foliage, tree wood and the owl; then rain and snow, lamp light, Christmas lights, the lightning flash and bolt. The whole frame is graded, then the corner labels are drawn. Place new elements by what should hide them.
- The tree has separate foliage and wood masks: only foliage and blossoms sway; the trunk and branches stay fixed. The bare winter tree is its own mask.
- The snow-covered roof line is drawn separately in `landscape()`; keep it aligned when the hut's geometry changes.
- Rain and snow are separate paths: rain falls as slanted streaks, snow as slow swaying flakes. Do not reuse one for the other. Winter alone does not imply snowfall.
- Sun and moon use `celestial_position`, which stays monotonic in azimuth (it does not fold back at due west). Both bodies sink into the land before `SET_ALTITUDE`, and the sunset lands right of the tree.

## Inputs
- Weather is a snapshot of the existing OpenWeather worker, never a second feed. Missing readings stay unknown, not zero. An unknown reading suppresses the effects that need it; leaves, for example, need a known wind.
- Freshness uses real time, judged by the source's `current.dt`. Forecasts use the hourly interval `[dt, dt + 3600)`. Never fall back to current weather for a missing or expired forecast, and never show unavailable or expired temperature as a current reading.
- Outside's moment is `outside.outside_time()` (the sign clock, or lab time) plus the forecast offset. Add seconds before converting to sensor-local time, so +24 h stays exact across DST.
- The astronomy worker precomputes one-minute samples with vectorized Skyfield calls, and the frame loop interpolates them. Never call Skyfield in the frame loop, and copy the table from shared state about once per second, not every frame.
- Holiday decorations come from the `HOLIDAYS` table, keyed on the displayed local date. The same table drives `holiday_features` and the lab's holiday shortcuts.

## Corner Labels
- The clock, temperature and notice choose black or light text from the luminance under their glyphs, with hysteresis, so clouds do not make them flicker. `draw_outside_frame` takes the previous styles and returns the next ones; carry them between frames. Labels have no outline or box, and they keep their style while a lightning flash is active.

## LED Color Tuning
- The palette grade and frame grade (`PALETTE_*`, `FRAME_*`, `WEATHER_DIM_*`) were tuned on the physical panel against washout. Retune them together and judge on the panel; browser previews do not reproduce LED washout.
- Avoid checkerboard dither rows in large areas such as clouds: on the panel they read as dashed lines.
- Lightning strokes hold full brightness for about 60 ms, so a 20 fps frame always catches them.

## Outside Lab (`outside_lab.py`)
- The lab is served at `/outside/lab` (`http://<sign>/api/outside/lab` through nginx). It works with `--web` and on the physical panel, with no flag. Never link it from `web/`.
- Every lab action switches the sign to Outside. Overrides affect Outside only:
  - Lab time is `shared_outside_lab_clock`, read through `outside.outside_time()`; it never touches `psclock`.
  - Lab weather is `data_dict["outside_lab_weather"]`, reported as `LIVE` (or `FORECAST` while the offset is ahead), so the scene renders exactly as it would for real weather.
  - `shared_outside_lab_version` makes the loop pick up changes on the next frame.
- Overrides clear when the sign leaves Outside, after `LAB_IDLE_SECONDS` without a lab action, on "Back to live", or on restart. Polling `/outside/lab/state` is not activity. Keep anything new self-clearing the same way.
- When adding a holiday, weather effect or time-dependent feature, make it reachable from the lab: a `HOLIDAYS` entry, a weather preset or a sun event.
