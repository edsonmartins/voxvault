"""WebSocket client for connecting to the Rust core server."""

import asyncio
import json
import logging

import websockets
from websockets.asyncio.client import connect

from models.schemas import TranscriptChunk

logger = logging.getLogger(__name__)


class RustBridgeClient:
    """Connects to the Rust WebSocket server and distributes transcript chunks."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self._connection = None
        self._listeners: list[asyncio.Queue] = []
        self._connected = False
        self._task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def add_listener(self) -> asyncio.Queue:
        """Add a new listener queue that receives TranslatedChunk dicts."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._listeners.append(queue)
        return queue

    def remove_listener(self, queue: asyncio.Queue) -> None:
        """Remove a listener queue."""
        self._listeners = [q for q in self._listeners if q is not queue]

    async def broadcast(self, data: dict) -> None:
        """Send data to all registered listeners."""
        dead_queues = []
        for queue in self._listeners:
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                logger.warning("Listener queue full, dropping message")
            except Exception:
                dead_queues.append(queue)

        for q in dead_queues:
            self._listeners.remove(q)

    async def connect(self, max_retries: int = 30, retry_delay: float = 2.0) -> None:
        """Connect to Rust WebSocket with retry logic.

        The Rust server may not be ready when Python starts, so we retry.
        """
        for attempt in range(1, max_retries + 1):
            try:
                self._connection = await connect(self.ws_url)
                self._connected = True
                logger.info(f"Connected to Rust core at {self.ws_url}")
                return
            except (ConnectionRefusedError, OSError) as e:
                if attempt < max_retries:
                    logger.info(
                        f"Rust WS not ready (attempt {attempt}/{max_retries}), "
                        f"retrying in {retry_delay}s..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.warning(
                        f"Could not connect to Rust core after {max_retries} attempts: {e}"
                    )
                    self._connected = False
                    return

    async def listen_loop(self) -> None:
        """Main loop: receive messages from Rust and broadcast to listeners."""
        if not self._connection:
            logger.warning("Not connected, cannot start listen loop")
            return

        try:
            async for raw_message in self._connection:
                try:
                    data = json.loads(raw_message)
                    chunk = TranscriptChunk(**data)
                    await self._on_message(chunk)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Invalid message from Rust: {e}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Rust WebSocket connection closed")
            self._connected = False
        except Exception as e:
            logger.error(f"WebSocket listen error: {e}")
            self._connected = False

    async def _on_message(self, chunk: TranscriptChunk) -> None:
        """Handle a received transcript chunk."""
        if chunk.type == "transcript":
            await self.broadcast(chunk.model_dump())
        elif chunk.type == "status":
            logger.info(f"Rust status: {chunk.text}")
            await self.broadcast(chunk.model_dump())
        elif chunk.type == "error":
            logger.error(f"Rust error: {chunk.text}")
            await self.broadcast(chunk.model_dump())

    async def start(self) -> None:
        """Start connection and listening in a background task (non-blocking)."""
        self._task = asyncio.create_task(self._connect_and_listen())

    async def _connect_and_listen(self) -> None:
        """Connect with retries and then listen. Runs as a background task."""
        await self.connect()
        if self._connected:
            await self.listen_loop()

    async def stop(self) -> None:
        """Disconnect from the Rust WebSocket."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._connection:
            await self._connection.close()
            self._connection = None

        self._connected = False
        logger.info("Disconnected from Rust core")
