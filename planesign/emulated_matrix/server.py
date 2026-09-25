"""
WebSocket server for streaming emulated matrix frames to browser clients.

Runs in a daemon thread with its own asyncio event loop.
Broadcasts raw RGBA frame data (16,384 bytes
per frame for a 128x32 display) as binary WebSocket messages.

Plain HTTP requests on the same port return the latest frame, so tools can inspect the display without a browser:
    /frame.png[?scale=8]   the frame as a PNG, optionally upscaled with nearest-neighbour
    /frame.txt             a 1:1 character map with a column ruler, row numbers and a colour legend
Both accept ?after=N to wait for a frame newer than frame N, or ?fresh=1 to wait for the next frame.
"""

import asyncio
import http
import io
import logging
import threading
import time
from urllib.parse import parse_qs, urlsplit

import psclock
import shared_config
import websockets
from modes import DisplayMode
from PIL import Image
from websockets.datastructures import Headers
from websockets.http11 import Response

logger = logging.getLogger(__name__)

_LISTEN_HOST = "0.0.0.0"
FRAME_WAIT_TIMEOUT = 10

# One symbol per colour bucket (each channel quantized to 4 levels), fixed so a colour keeps its symbol from frame
# to frame. Index 0 is the dim bucket (every channel below 64); pure black is always "."
_TEXT_SYMBOLS = ":ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%&*+=?@<>"


def frame_to_text(image, header):
    """Render an RGB image as a 1:1 character map with a column ruler, row numbers and a colour legend."""
    width, height = image.size
    pixels = image.load()
    buckets = {}
    lines = [header]
    lines.append("   " + "".join(str(x // 100) if x >= 100 else " " for x in range(width)))
    lines.append("   " + "".join(str(x // 10 % 10) if x >= 10 else " " for x in range(width)))
    lines.append("   " + "".join(str(x % 10) for x in range(width)))
    for y in range(height):
        row = []
        for x in range(width):
            r, g, b = pixels[x, y]
            if r == g == b == 0:
                row.append(".")
                continue
            symbol = _TEXT_SYMBOLS[(r >> 6) * 16 + (g >> 6) * 4 + (b >> 6)]
            total = buckets.setdefault(symbol, [0, 0, 0, 0])
            total[0] += 1
            total[1] += r
            total[2] += g
            total[3] += b
            row.append(symbol)
        lines.append(f"{y:2d} {''.join(row)}")
    lines.append("legend: . black")
    for symbol, (count, r, g, b) in sorted(buckets.items(), key=lambda item: -item[1][0]):
        lines.append(f"  {symbol} #{r // count:02x}{g // count:02x}{b // count:02x} average, {count} px")
    return "\n".join(lines) + "\n"


class FrameServer:
    """WebSocket server that broadcasts display frames to connected clients."""

    def __init__(self, width, height):
        self.port = shared_config.ws_port
        self._size = (width, height)
        self._clients: set[websockets.ServerConnection] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # (frame number, real capture time, RGBA bytes), replaced as a whole so readers on the server thread see a consistent frame
        self._latest = None

    def start(self):
        """Start the WebSocket server in a background daemon thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("WebSocket frame server starting on ws://%s:%d; frame capture at http://127.0.0.1:%d/frame.png and /frame.txt", _LISTEN_HOST, self.port, self.port)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with websockets.serve(self._handler, _LISTEN_HOST, self.port, compression=None, process_request=self._process_request):
            await asyncio.Future()  # run forever

    async def _process_request(self, connection, request):
        url = urlsplit(request.path)
        if url.path not in ("/frame.png", "/frame.txt"):
            return None  # carry on with the WebSocket handshake

        params = parse_qs(url.query)
        try:
            after = self._latest[0] if params.get("fresh") and self._latest else int(params.get("after", ["0"])[0])
            scale = min(max(int(params.get("scale", ["1"])[0]), 1), 16)
        except ValueError:
            return connection.respond(http.HTTPStatus.BAD_REQUEST, "after and scale must be integers\n")

        deadline = time.monotonic() + FRAME_WAIT_TIMEOUT
        while (self._latest is None or self._latest[0] <= after) and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        latest = self._latest
        if latest is None or latest[0] <= after:
            return connection.respond(http.HTTPStatus.GATEWAY_TIMEOUT, f"No frame newer than {after} within {FRAME_WAIT_TIMEOUT} s\n")

        number, captured, rgba = latest
        image = Image.frombytes("RGBA", self._size, rgba).convert("RGB")
        try:
            mode = DisplayMode(shared_config.shared_mode.value).name
        except ValueError:
            mode = str(shared_config.shared_mode.value)
        info = {"X-Frame-Number": str(number), "X-Frame-Age": f"{time.time() - captured:.2f}", "X-Mode": mode, "X-Clock": psclock.describe()}

        if url.path == "/frame.png":
            if scale > 1:
                image = image.resize((image.width * scale, image.height * scale), Image.NEAREST)
            buffer = io.BytesIO()
            image.save(buffer, "PNG")
            body, content_type = buffer.getvalue(), "image/png"
        else:
            header = f"frame {number} | mode {mode} | clock {info['X-Clock']} | captured {info['X-Frame-Age']} s ago | {image.width}x{image.height}"
            body, content_type = frame_to_text(image, header).encode(), "text/plain; charset=utf-8"

        headers = Headers([("Content-Type", content_type), ("Content-Length", str(len(body))), ("Cache-Control", "no-store"), *info.items()])
        return Response(http.HTTPStatus.OK, "OK", headers, body)

    async def _handler(self, websocket: websockets.ServerConnection):
        self._clients.add(websocket)
        remote = websocket.remote_address
        logger.info("Display client connected: %s", remote)
        try:
            async for _ in websocket:
                pass  # we don't expect messages from clients
        except websockets.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Display client disconnected: %s", remote)

    def broadcast(self, frame_rgba_bytes: bytes):
        """Send a frame to all connected clients. Called from the main thread."""
        self._latest = (self._latest[0] + 1 if self._latest else 1, time.time(), frame_rgba_bytes)
        if not self._clients or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._broadcast(frame_rgba_bytes), self._loop)

    async def _broadcast(self, data: bytes):
        if not self._clients:
            return
        stale = set()
        for client in self._clients:
            try:
                await client.send(data)
            except websockets.ConnectionClosed:
                stale.add(client)
        self._clients -= stale
