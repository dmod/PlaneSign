---
description: "Use when screenshotting the matrix preview, rendering PlaneSign frames offline, comparing layout or artwork options side by side, or driving the preview with browser tools (Playwright). Covers cropping pitfalls, stale screenshots, animation checks and offline render harnesses."
---
# Visual Verification Techniques

## Screenshotting The Preview
- `display.html` draws `canvas#matrix` at a fixed 1024x256 CSS pixels. That is wider than the integrated browser's viewport (~892x332), so a plain screenshot silently crops both edges. Shrink it first, and do so again after every reload:

	```js
	page.evaluate(() => {
		const c = document.getElementById('matrix');
		c.style.width = '768px';
		c.style.height = '192px';
	});
	```

- Capture with the screenshot tool scoped to the canvas selector, and confirm both outer edges (x=0 and x=127) are visible before trusting it. Reload the page after restarting the emulator.
- Playwright's `locator.screenshot({ path })` writes to the browser host, not the devcontainer. Use the screenshot tool for images you need to inspect.
- Screenshots can be stale after a data or mode change. Before concluding that the sign is wrong, fetch `/frame.txt?fresh=1` or `/frame.png?fresh=1`, which are ground truth. You can also sample the canvas with `getImageData`: matrix pixel `(x, y)` is at `(x * 8 + 4, y * 8 + 4)`.
- Rotating content and animation advance on wall-clock time. Take several captures (or sample one pixel repeatedly) to see every phase and to prove motion; a single frame cannot.
- In a background tab, browsers stop scheduling animation frames, so Playwright's click waits for an element to become "stable" and times out. Use `click({ force: true })` once you have checked that nothing covers the element.
- The integrated browser only reaches ports that VS Code forwards (80 for nginx and 5056 for frames work). If a page on another port refuses to connect, forward that port, or serve the content through an existing route.

## Rendering Frames Offline
For layout and artwork work, or for states you cannot wait for, render frames directly with the real fonts, then confirm the result in the running app.

- Bootstrap:
  - Set `PLANESIGN_EMULATED_DISPLAY=1`, `import emulated_matrix`, and assign it to `sys.modules["rgbmatrix"]`.
  - Set `shared_config.local_timezone` and `shared_config.CONF` before importing the mode module.
  - Build a stub sign with `canvas = emulated_matrix.core.Canvas(128, 32)` and the fonts loaded from `fonts/`, then call the mode's frame-drawing function.
- Print `emulated_matrix.server.frame_to_text(canvas._image, "header")` for a 1:1 pixel map. It shows exact columns, 1px overlaps and clipping at x=0/x=127, which an upscaled image hides.
- Drive edge cases with synthetic data: parse a real payload once, then deep-copy and mutate it.
- Keep one-off scripts and PNGs in the session workspace. A harness that proves reusable belongs in the app (like the Outside lab), not as loose scripts in the repo.

## Comparing Layout Or Artwork Options
When a design is a judgement call, render two to four complete alternatives and show them side by side instead of describing them.

- Render every candidate from the *same* data state, and put the currently shipped version first.
- Write a small `index.html` in the session workspace with headings, `image-rendering: pixelated`, and a one-line note on what each option trades away. Serve it on a spare port (see the port note above) and give the user the URL.
- Pair the images with a short table of what changed in pixels, and ask which direction to pursue before implementing one.
- For animation, render a strip of frames across the cycle.
