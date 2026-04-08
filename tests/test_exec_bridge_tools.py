"""Tests for exec bridge tools."""

from unittest.mock import AsyncMock, MagicMock
import pytest

from antbot.agent.tools.exec_bridge_tools import ExecHealthTool, ExecMoveTool, ExecCopyTool


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    client = AsyncMock()
    manager.ensure_connected = AsyncMock(return_value=client)
    return manager, client


@pytest.mark.asyncio
async def test_health_tool(mock_manager):
    manager, client = mock_manager
    client.ping.return_value = {"ok": True, "version": "0.1.0", "uptime_s": 42.5}

    tool = ExecHealthTool(manager)
    result = await tool.execute()
    assert "ok=True" in result
    assert "0.1.0" in result


@pytest.mark.asyncio
async def test_health_tool_unreachable():
    manager = MagicMock()
    manager.ensure_connected = AsyncMock(side_effect=RuntimeError("connection refused"))

    tool = ExecHealthTool(manager)
    result = await tool.execute()
    assert "unreachable" in result


@pytest.mark.asyncio
async def test_move_tool_dry_run(mock_manager):
    manager, client = mock_manager
    client.move.return_value = {
        "ok": True, "error": "", "src": "/a/b.pdf", "dst": "/c/d.pdf",
        "size_bytes": 1234, "checksum": "abc", "was_dry_run": True,
    }

    tool = ExecMoveTool(manager, global_dry_run=True)
    result = await tool.execute(src="/a/b.pdf", dst="/c/d.pdf")
    assert "[DRY RUN]" in result
    assert "1234 bytes" in result
    client.move.assert_called_once_with("/a/b.pdf", "/c/d.pdf", dry_run=True)


@pytest.mark.asyncio
async def test_copy_tool(mock_manager):
    manager, client = mock_manager
    client.copy.return_value = {
        "ok": True, "error": "", "src": "/a/b.pdf", "dst": "/c/d.pdf",
        "size_bytes": 5678, "checksum": "def", "was_dry_run": False,
    }

    tool = ExecCopyTool(manager, global_dry_run=False)
    result = await tool.execute(src="/a/b.pdf", dst="/c/d.pdf", dry_run=False)
    assert "Copied" in result
    assert "[DRY RUN]" not in result


@pytest.mark.asyncio
async def test_move_tool_failure(mock_manager):
    manager, client = mock_manager
    client.move.return_value = {
        "ok": False, "error": "destination exists", "src": "", "dst": "",
        "size_bytes": 0, "checksum": "", "was_dry_run": False,
    }

    tool = ExecMoveTool(manager, global_dry_run=False)
    result = await tool.execute(src="/a/b.pdf", dst="/c/d.pdf", dry_run=False)
    assert "failed" in result.lower()
    assert "destination exists" in result
