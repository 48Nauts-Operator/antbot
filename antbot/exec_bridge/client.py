"""Async gRPC client for the antbot-exec Go binary."""

from __future__ import annotations

from typing import AsyncIterator

import grpc
import grpc.aio

from antbot.exec_bridge.gen import antbot_pb2, antbot_pb2_grpc


class ExecBridgeClient:
    """Async client for antbot-exec over Unix socket."""

    def __init__(self, socket_path: str = "/tmp/antbot.sock") -> None:
        self._socket_path = socket_path
        self._channel: grpc.aio.Channel | None = None

    async def connect(self) -> None:
        """Open the gRPC channel."""
        self._channel = grpc.aio.insecure_channel(f"unix://{self._socket_path}")

    async def close(self) -> None:
        """Close the gRPC channel."""
        if self._channel:
            await self._channel.close()
            self._channel = None

    @property
    def is_connected(self) -> bool:
        return self._channel is not None

    def _ensure_channel(self) -> grpc.aio.Channel:
        if self._channel is None:
            raise RuntimeError("ExecBridgeClient not connected. Call connect() first.")
        return self._channel

    # ─── Health ───────────────────────────────────────

    async def ping(self) -> dict:
        """Health check. Returns {"ok": bool, "uptime_s": float, "version": str}."""
        stub = antbot_pb2_grpc.HealthStub(self._ensure_channel())
        resp = await stub.Ping(antbot_pb2.PingRequest())
        return {"ok": resp.ok, "uptime_s": resp.uptime_s, "version": resp.version}

    # ─── FileMover ────────────────────────────────────

    async def move(self, src: str, dst: str, dry_run: bool = True) -> dict:
        """Request file move."""
        stub = antbot_pb2_grpc.FileMoverStub(self._ensure_channel())
        resp = await stub.Move(antbot_pb2.MoveRequest(
            src=src, dst=dst, dry_run=dry_run, overwrite=False,
        ))
        return {
            "ok": resp.ok, "error": resp.error, "src": resp.src,
            "dst": resp.dst, "size_bytes": resp.size_bytes,
            "checksum": resp.checksum, "was_dry_run": resp.was_dry_run,
        }

    async def copy(self, src: str, dst: str, dry_run: bool = True) -> dict:
        """Request file copy."""
        stub = antbot_pb2_grpc.FileMoverStub(self._ensure_channel())
        resp = await stub.Copy(antbot_pb2.CopyRequest(
            src=src, dst=dst, dry_run=dry_run, overwrite=False,
        ))
        return {
            "ok": resp.ok, "error": resp.error, "src": resp.src,
            "dst": resp.dst, "size_bytes": resp.size_bytes,
            "checksum": resp.checksum, "was_dry_run": resp.was_dry_run,
        }

    # ─── Watcher ──────────────────────────────────────

    async def watch(self, paths: list[str], recursive: bool = True) -> AsyncIterator[dict]:
        """Start watching directories. Yields FSEvent dicts."""
        stub = antbot_pb2_grpc.WatcherStub(self._ensure_channel())
        stream = stub.Watch(antbot_pb2.WatchRequest(
            paths=paths, recursive=recursive,
        ))
        async for event in stream:
            yield {
                "path": event.path, "op": event.op,
                "size_bytes": event.size_bytes, "mime_type": event.mime_type,
                "timestamp_ms": event.timestamp_ms,
            }

    # ─── Queue ────────────────────────────────────────

    async def drain_queue(self, max_events: int = 0) -> list[dict]:
        """Drain buffered events from Go."""
        stub = antbot_pb2_grpc.QueueStub(self._ensure_channel())
        resp = await stub.Drain(antbot_pb2.DrainRequest(max_events=max_events))
        return [
            {"path": e.path, "op": e.op, "size_bytes": e.size_bytes,
             "mime_type": e.mime_type, "timestamp_ms": e.timestamp_ms}
            for e in resp.events
        ]

    # ─── ContentExtract ───────────────────────────────

    async def preview_text(self, path: str, max_bytes: int = 4096) -> dict:
        """Get text preview of a file."""
        stub = antbot_pb2_grpc.ContentExtractStub(self._ensure_channel())
        resp = await stub.PreviewText(antbot_pb2.PreviewTextRequest(
            path=path, max_bytes=max_bytes,
        ))
        return {
            "text": resp.text, "mime_type": resp.mime_type,
            "total_bytes": resp.total_bytes, "truncated": resp.truncated,
        }

    async def probe_mime(self, path: str) -> dict:
        """Probe MIME type of a file."""
        stub = antbot_pb2_grpc.ContentExtractStub(self._ensure_channel())
        resp = await stub.ProbeMime(antbot_pb2.ProbeMimeRequest(path=path))
        return {"mime_type": resp.mime_type, "size_bytes": resp.size_bytes}

    # ─── System ───────────────────────────────────────

    async def manifest(self) -> dict:
        """Collect machine manifest."""
        stub = antbot_pb2_grpc.SystemStub(self._ensure_channel())
        resp = await stub.Manifest(antbot_pb2.ManifestRequest())
        return {"ok": resp.ok, "error": resp.error, "json": resp.json}

    async def check_mount(self, path: str) -> dict:
        """Check if a path is mounted and get free space."""
        stub = antbot_pb2_grpc.SystemStub(self._ensure_channel())
        resp = await stub.CheckMount(antbot_pb2.CheckMountRequest(path=path))
        return {"mounted": resp.mounted, "free_bytes": resp.free_bytes}
