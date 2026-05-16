"""
WebSocket server for streaming emulated matrix frames to browser clients.

Runs in a daemon thread with its own asyncio event loop.
Listens on port 5001 and broadcasts raw RGBA frame data (16,384 bytes
per frame for a 128x32 display) as binary WebSocket messages.
"""

import asyncio
import logging
import threading

import websockets

logger = logging.getLogger(__name__)

_LISTEN_HOST = "0.0.0.0"
_LISTEN_PORT = 5001


class FrameServer:
    """WebSocket server that broadcasts display frames to connected clients."""

    def __init__(self):
        self._clients: set[websockets.ServerConnection] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the WebSocket server in a background daemon thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("WebSocket frame server starting on ws://%s:%d", _LISTEN_HOST, _LISTEN_PORT)

    def _run(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with websockets.serve(self._handler, _LISTEN_HOST, _LISTEN_PORT, compression=None):
            await asyncio.Future()  # run forever

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
