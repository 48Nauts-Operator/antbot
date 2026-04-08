"""Lifecycle management for the antbot-exec Go binary."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from antbot.exec_bridge.client import ExecBridgeClient

logger = logging.getLogger(__name__)


class ExecBridgeManager:
    """Manages the Go binary lifecycle and gRPC client."""

    def __init__(
        self,
        socket_path: str = "/tmp/antbot.sock",
        binary_path: str = "~/.antbot/bin/antbot-exec",
        auto_start: bool = True,
        connect_timeout_s: int = 5,
    ) -> None:
        self._socket_path = socket_path
        self._binary_path = str(Path(binary_path).expanduser())
        self._auto_start = auto_start
        self._connect_timeout_s = connect_timeout_s
        self._client = ExecBridgeClient(socket_path)
        self._process: subprocess.Popen | None = None

    @property
    def client(self) -> ExecBridgeClient:
        return self._client

    async def start(self) -> None:
        """Start the Go binary (if auto_start) and connect."""
        # Check if socket already exists (binary already running)
        if os.path.exists(self._socket_path):
            logger.info("Socket %s exists, attempting to connect", self._socket_path)
            await self._connect()
            return

        if not self._auto_start:
            logger.warning("Go binary not running and auto_start=False")
            return

        if not os.path.exists(self._binary_path):
            logger.warning("Go binary not found at %s — exec bridge disabled", self._binary_path)
            return

        # Start the Go binary
        logger.info("Starting antbot-exec: %s", self._binary_path)
        self._process = subprocess.Popen(
            [self._binary_path, "--socket", self._socket_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for socket to appear
        for _ in range(self._connect_timeout_s * 10):
            if os.path.exists(self._socket_path):
                break
            await asyncio.sleep(0.1)
        else:
            logger.error("Timed out waiting for socket %s", self._socket_path)
            return

        await self._connect()

    async def _connect(self) -> None:
        """Connect and verify with ping."""
        await self._client.connect()
        try:
            result = await self._client.ping()
            logger.info("Connected to antbot-exec %s (uptime: %.1fs)", result["version"], result["uptime_s"])
        except Exception as e:
            logger.error("Failed to ping antbot-exec: %s", e)
            await self._client.close()

    async def stop(self) -> None:
        """Disconnect client and stop the Go binary if we started it."""
        await self._client.close()
        if self._process and self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)
            logger.info("Stopped antbot-exec")

    async def ensure_connected(self) -> ExecBridgeClient:
        """Return connected client, reconnecting if needed."""
        if not self._client.is_connected:
            await self.start()
        return self._client
