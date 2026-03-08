"""Tests for the Space-Ant tool."""

import pytest

from antbot.agent.tools.space_tool import SpaceAntTool, _human_size


@pytest.fixture
def tool():
    return SpaceAntTool()


class TestToolProperties:
    def test_name(self, tool):
        assert tool.name == "space_ant"

    def test_category(self, tool):
        assert tool.category == "devops"

    def test_parameters_schema(self, tool):
        params = tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]
        assert params["properties"]["action"]["enum"] == ["scan", "clean"]
        assert "action" in params["required"]

    def test_to_schema(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "space_ant"


class TestHumanSize:
    def test_bytes(self):
        assert _human_size(500) == "500 B"

    def test_kilobytes(self):
        result = _human_size(1024 * 5)
        assert "KB" in result

    def test_megabytes(self):
        result = _human_size(1024 * 1024 * 100)
        assert "MB" in result

    def test_gigabytes(self):
        result = _human_size(1024 * 1024 * 1024 * 2)
        assert "GB" in result

    def test_zero(self):
        assert _human_size(0) == "0 B"


class TestValidation:
    def test_valid_scan(self, tool):
        errors = tool.validate_params({"action": "scan"})
        assert errors == []

    def test_valid_clean_with_confirm(self, tool):
        errors = tool.validate_params({"action": "clean", "confirm": True})
        assert errors == []

    def test_missing_action(self, tool):
        errors = tool.validate_params({})
        assert len(errors) > 0

    def test_invalid_action(self, tool):
        errors = tool.validate_params({"action": "destroy"})
        assert len(errors) > 0


class TestCleanSafetyGate:
    @pytest.mark.asyncio
    async def test_clean_without_confirm_blocked(self, tool):
        result = await tool.execute(action="clean", confirm=False)
        assert "confirm=true" in result

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="nuke")
        assert "Error" in result


class TestScan:
    @pytest.mark.asyncio
    async def test_scan_returns_report(self, tool):
        """Scan should complete and return a report string."""
        result = await tool.execute(action="scan")
        assert "Space-Ant Scan Report" in result
        # Should contain the cleanup instruction
        assert "space_ant" in result

    @pytest.mark.asyncio
    async def test_scan_has_categories(self, tool):
        """Scan report should include category headers."""
        result = await tool.execute(action="scan")
        # At least one category should appear (even if some are empty on this machine)
        assert "##" in result or "No significant disk waste" in result
