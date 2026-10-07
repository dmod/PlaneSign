---
description: "Use when changing the Free Sketch drawing modal in the web UI (web/index.js, web/*.css, web/*.html): modal scrolling, fullscreen, touch drawing, and how to verify them in the browser."
applyTo: "web/**"
---
# Free Sketch Modal

- The backdrop is fixed to the viewport. Keep the inner `.free_sketch_modal` bounded with `max-height: 100%`, `overflow-y: auto` and `overscroll-behavior-y: contain`; otherwise a tall centered dialog hides its header and lower controls with no way to scroll.
- Fullscreen reuses the same scrollable dialog at `width: 100%` and `height: 100%` of the backdrop. Verify both native fullscreen and the CSS fallback used when `requestFullscreen` is unavailable or rejected.
- Keep `touch-action: none` on `#free_sketch_canvas` only: gestures on the canvas draw, and gestures over the controls or dialog padding scroll. Never disable touch scrolling on the whole modal.
- To verify:
  - Check portrait and short landscape viewports (for example 390x480 and 844x390). Reach the top and bottom by touch and inspect the controls and the saved-sketch gallery.
  - Confirm that scrolling neither moves the background page nor changes canvas pixels, and that strokes still reach the live matrix.
  - Undo test strokes; do not save or delete sketches.
- For gesture tests, derive coordinates from the dialog's actual bounds, padding and scrollbar width, not from `innerWidth` or a fixed offset. Start outside the canvas and the scrollbar track; the fixed layout toggle can intercept gestures near the top of the page.
- If the sign is already in `FREE_SKETCH`, loading the controls can open the modal automatically and cover the mode button. Check for it before clicking.
