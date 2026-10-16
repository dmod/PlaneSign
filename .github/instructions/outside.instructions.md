---
description: "Use when changing Outside mode: outside.py, outside_scene.py, outside_lab.py or the Outside lab page. Covers scene artwork, draw order, determinism, weather and astronomy inputs, wildlife, holidays, corner labels, LED color tuning and the lab's override rules."
applyTo: "planesign/outside*.py, planesign/templates/outside_lab.html"
---
# Outside Mode

Outside (`outside.py` drives it, `outside_scene.py` draws it) is a 128x32 pixel-art landscape driven by local astronomy and the OpenWeather feed. Positions, sizes and timings live in named constants in `outside_scene.py`; read them there rather than relying on numbers in docs.

## Determinism
- `render_outside_frame(environment, elapsed, seed)` is pure. Texture and noise come from deterministic hashes of `(x, y)`; never use `random` while drawing.
- Occasional events (wildlife visits, lightning, shooting stars, Santa, fireworks, cannon shots, fountain burns) are scheduled per fixed time slot from `(slot, seed)`, and they never cross a slot boundary. A state is then a pure function of `elapsed`, so the forecast slider and the lab can jump without breaking an animation.
- Anything that scales with a reading (cloud shapes, firefly count, falling leaves) appears in a fixed priority order. Changing the reading then grows or shrinks the effect instead of reshuffling it.
- Wildlife schedules exclude each other: the eagle never appears during a dog outing, deer/foxes/rabbits skip outings, and the bird flock skips eagle visits. On Halloween no animals come out at all (no wildlife, birds, eagle, owl, fireflies or dog) and the tree holds its leaves, leaving the scene to its spooks. On Thanksgiving a resident tom turkey roams the meadow all day and night and hen flocks visit by day, replacing the deer, foxes and rabbits, and a V of geese replaces the bird flock; the hens skip dog outings and eagle visits and the geese skip eagle visits, but the tom is always out and shares the meadow with both. On July 4 (through the following night) the hotdog mascot has the meadow: no deer, foxes, rabbits, songbirds, eagle or owl come out, the dog and fireflies still do, and the mascot skips dog outings. While ornaments hang on the bare tree (winter days with the Christmas lights up), the owl stays away. The beach umbrella stays down on July 4, Halloween and Thanksgiving, whose props stand on its spot on the pond's right bank; visiting deer, foxes and rabbits stand under it. Keep these exclusions when adding animals.
- Cache static geometry and colorized layers; frames only scroll, modulate and blend. The loop runs at about 20 fps, so time any new draw call.

## Composition And Draw Order
- The single small mountain right of center keeps the horizon low, so the night sky stays open. Keep the top rows of both corners clear for the clock and temperature labels: the tree, the constellations, the owl perch and shooting stars all stay below them.
- Back to front: sky gradient, stars and the constellations, shooting stars, sun and moon, clouds; then fireworks and Santa (in the distance); then the land, the July 4 fountains, pond reflections (of fireworks and fountains), fog, Halloween mist, the shadow figure and jack-o'-lanterns (a rolling one passes behind the others), the Thanksgiving harvest display; then the flag, the cannon, the beach umbrella, wildlife and geese, turkeys and the pilgrims (back to front by the row each stands on; on a shared row the pilgrims stand behind the birds), eagle, hut and dog, chimney smoke, the cannon's blast smoke, fireflies, tree foliage, tree wood, falling leaves and petals (they let go from the front of the canopy), the July 4 hotdog mascot (he walks the front of the meadow, in front of the tree), the Christmas ornaments, the owl, the cobweb and the Halloween spider; then rain and snow, lamp light and the flag's floodlight beam, the cannon's fuse sparks, muzzle flash and embers, then the cannon ball (so the flash never hides it), candle glow, the shadow figure's eyes and the ghost, the harvest lantern's glow, Christmas lights, the lightning flash and bolt. The whole frame is graded, then the corner labels are drawn. Place new elements by what should hide them.
- The tree has separate foliage and wood masks: only foliage and blossoms sway; the trunk and branches stay fixed. The bare winter tree is its own mask.
- The hut comes in styles (`HUT_STYLES`). Anything that depends on its shape is built per style: the land mask, chimney mask, smoke flue, snow line, Christmas bulbs and lightning surface. Field stars keep clear of every style's land at once, so switching huts never moves a star. All styles share `HUT_DOOR`, because the dog's doorway is fixed.
- A style's `roof` outline is both the snow line and the Christmas string. The chimney sits in front of both, and both skip its mask.
- Hut panes are cut back to the backdrop, so whatever stands behind the hut shows through them. `RIDGE_GAP` keeps a treetop from filling the right-hand pane; re-check what shows through when panes or the ridge move.
- Styles give daylight colors only; dusk and night come from an Oklab fit to the hand-tuned built materials (`hut_palettes`). Do not hand-tune a style's night colors.
- Wind has no direction in the feed; every wind effect (flag, rain slant, snow drift, chimney and cannon smoke) blows to the right. Keep new ones consistent.
- The clock label sits right above the chimney, so smoke fades out below `SMOKE_CEILING` at every wind speed.
- Rain and snow are separate paths: rain falls as slanted streaks, snow as slow swaying flakes. Do not reuse one for the other. Winter alone does not imply snowfall.
- Sun and moon use `celestial_position`, which stays monotonic in azimuth (it does not fold back at due west). Both bodies sink into the land before `SET_ALTITUDE`, and the sunset lands right of the tree.

## Inputs
- Weather is a snapshot of the existing OpenWeather worker, never a second feed. Missing readings stay unknown, not zero. An unknown reading suppresses the effects that need it; leaves, for example, need a known wind.
- Freshness uses real time, judged by the source's `current.dt`. Forecasts use the hourly interval `[dt, dt + 3600)`. Never fall back to current weather for a missing or expired forecast, and never show unavailable or expired temperature as a current reading.
- The weather worker pauses outside weather modes, so Outside often starts with an old payload. Until the worker's refresh lands, the reading is `PENDING`: the old readings still shape the scene, but the temperature shows `--°F` and the notice is `WX...`/`FCST...`. `CACHED` is only for a refresh that was tried and failed.
- Outside's moment is `outside.outside_time()` (the sign clock, or lab time) plus the forecast offset. Add seconds before converting to sensor-local time, so +24 h stays exact across DST.
- The astronomy worker precomputes one-minute samples with vectorized Skyfield calls, and the frame loop interpolates them. Never call Skyfield in the frame loop, and copy the table from shared state about once per second, not every frame.
- Holiday decorations come from the `HOLIDAYS` table, keyed on the displayed local date. The same table drives `holiday_features` and the lab's holiday shortcuts. A floating holiday is a day range plus a weekday (Thanksgiving's fourth Thursday always falls on November 22-28); read spans through `holiday_span_matches` / `holiday_span_start`, never by unpacking them as 3-tuples.
- A date in `HOLIDAY_NIGHTS` (July 4) keeps its whole scene up through the following night, until sunrise the next morning. "Before sunrise" is `OutsideEnvironment.before_sunrise`: the astronomy table's next sunrise falls on the displayed local date. Do not use the clock hour or the sun's azimuth, because local midnight is not solar midnight. The lab adds a "Before dawn" shortcut for these dates.
- The flag's floodlight comes on with the yard lamp at nightfall but burns until sunrise, so it follows `NIGHT_ALTITUDE` and `before_sunrise`, not the lamp's three-hour `since_nightfall` window; `since_nightfall` only reaches back `SKY_HISTORY_SECONDS`.
- The hemisphere (`OutsideEnvironment.hemisphere`, from the sign of `SENSOR_LAT`) picks the season and the constellations in `CONSTELLATIONS`. Each hemisphere also has its own field-star table, because field stars keep clear of that hemisphere's star groups. Read the hemisphere from the environment, never from `SENSOR_LAT`, so the lab's override reaches it.
- On Thanksgiving the chimney smokes all day, even when the temperature is warm or unknown.
- The beach umbrella goes by dew point, not relative humidity, and stays down while temperature, dew point or wind is unknown. Its margins need memory, so the Outside loop carries whether it is up and sets `OutsideEnvironment.beach`; `render_outside_frame` only reads that flag, which keeps it a pure function of the environment.

## Corner Labels
- The clock, temperature and notice choose black or light text from the luminance under their glyphs, with hysteresis, so clouds do not make them flicker. `draw_outside_frame` takes the previous styles and returns the next ones; carry them between frames. Labels have no outline or box, and they keep their style while a lightning flash is active. They sit `OVERLAY_MARGIN` pixels in from the top and outer edges: flush black text merges into the unlit border around the panel.
- Field stars and shooting stars skip a clearing around the clock and temperature, sized from the rendered labels each frame and passed into `render_outside_frame`. The clearing hides stars only; the sky gradient, clouds and everything else still draw there.

## LED Color Tuning
- The palette grade and frame grade (`PALETTE_*`, `FRAME_*`, `WEATHER_DIM_*`) were tuned on the physical panel against washout. Retune them together and judge on the panel; browser previews do not reproduce LED washout.
- Avoid checkerboard dither rows in large areas such as clouds: on the panel they read as dashed lines.
- Sprite colors pass through the frame grade, which strongly boosts chroma: muted colors like the palette's come out vivid, and already-vivid ones clip to a flat primary (the old falling leaves read as solid red). Choose them by their graded result.
- Lightning strokes hold full brightness for about 60 ms, so a 20 fps frame always catches them.

## Outside Lab (`outside_lab.py`)
- The lab is served at `/outside/lab` (`http://<sign>/api/outside/lab` through nginx). It works with `--web` and on the physical panel, with no flag. Its only link from `web/` is the "Outside lab" button in Outside's controls, which opens it in a new tab.
- Every lab action switches the sign to Outside. Overrides affect Outside only:
  - Lab time is `shared_outside_lab_clock`, read through `outside.outside_time()`; it never touches `psclock`.
  - Lab weather is `data_dict["outside_lab_weather"]`, reported as `LIVE` (or `FORECAST` while the offset is ahead), so the scene renders exactly as it would for real weather.
  - Lab moon is `data_dict["outside_lab_moon"]`: its phase and position replace the computed ones in the environment, so moonlight, halo and silver linings follow it. `MOON_POSITIONS` are picked to land in open sky; re-check them when the hut, mountain, tree or lamp moves.
  - Lab hemisphere is `data_dict["outside_lab_hemisphere"]`: it switches the constellations and the season (and the lab's season shortcuts) but not the sun and moon, which stay computed for the sign's real location.
  - Lab hut is `data_dict["outside_lab_hut"]`, a `HUT_STYLES` key; without it Outside shows `DEFAULT_HUT`.
  - `shared_outside_lab_version` makes the loop pick up changes on the next frame.
  - A lab speed of 0 pauses: the lab clock stops and the Outside loop freezes `elapsed`, so animation stops too.
- Summoning skips the loop's animation clock (`elapsed`) to just before an event's next natural start. It never changes the displayed time or weather, so the scene's own exclusions (no eagle during a dog outing, nothing on Halloween) still apply. The search runs in the Outside loop, which owns `seed` and `elapsed`; the API process only posts a request and waits for the result.
- Every occasional event belongs in `outside_scene.SUMMONS`, with an `allowed(environment)` check and a pure `active(environment, elapsed, seed)` probe. When an event's schedule lives inside its draw function, pull it out into a `*_state` function that the drawing and the probe share, so the lab cannot drift from what the sign draws.
- The page's settings (weather sliders and their ranges, presets, speeds, shortcut lists) are defined in `outside_lab.py` and rendered into the template by `page_options()`. Do not hard-code them in `outside_lab.html`. `state()` carries only what changes, since the page polls it every 2 s.
- Flask caches the template, so restart the app after editing `outside_lab.html`.
- While the lab is active (`outside.lab_active`), the top notice drops the forecast condition text, which covers too much of the scene being tuned. Status notices (`OFFLINE`, `FCST...`, `FCST~`, `SKY...`) still show.
- Overrides clear when the sign leaves Outside, after `LAB_IDLE_SECONDS` without a lab action, on "Back to live" in the lab or "Return to now" on the main page, or on restart. Polling `/outside/lab/state` is not activity. Keep anything new self-clearing the same way.
- When adding a holiday, weather effect or time-dependent feature, make it reachable from the lab: a `HOLIDAYS` entry, a weather preset, a sun event, the moon controls or a `SUMMONS` entry.
