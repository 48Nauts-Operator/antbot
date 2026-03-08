"""Tests for smart tool selection by message keywords."""

from antbot.agent.tools.strategy import select_tools_for_message


def _make_tool_def(name: str) -> dict:
    return {"function": {"name": name, "description": f"{name} tool", "parameters": {}}}


def _make_defs(*names: str) -> list[dict]:
    return [_make_tool_def(n) for n in names]


def _tool_names(defs: list[dict]) -> set[str]:
    return {d["function"]["name"] for d in defs}


def test_returns_all_when_max_zero():
    """max_tools=0 means no filtering."""
    defs = _make_defs("read_file", "exec", "docker", "git")
    result = select_tools_for_message("anything", defs, {}, 0)
    assert len(result) == 4


def test_returns_all_when_under_limit():
    """Don't filter if already under limit."""
    defs = _make_defs("read_file", "exec")
    result = select_tools_for_message("anything", defs, {}, 5)
    assert len(result) == 2


def test_core_tools_always_included():
    """read_file and exec should always be in the selection."""
    defs = _make_defs("read_file", "exec", "docker", "git", "http_request", "process")
    categories = {"docker": "devops", "git": "devops", "http_request": "devops", "process": "devops"}
    result = select_tools_for_message("check something", defs, categories, 3)
    names = _tool_names(result)
    assert "read_file" in names
    assert "exec" in names


def test_devops_keywords_boost_devops_tools():
    """Docker/git keywords should boost devops tools."""
    defs = _make_defs("read_file", "exec", "docker", "git", "web_search", "web_fetch")
    categories = {
        "docker": "devops", "git": "devops",
        "web_search": "web", "web_fetch": "web",
    }
    result = select_tools_for_message("show running docker containers", defs, categories, 4)
    names = _tool_names(result)
    assert "docker" in names
    assert "read_file" in names


def test_web_keywords_boost_web_tools():
    """Web-related keywords boost web tools."""
    defs = _make_defs("read_file", "exec", "web_search", "web_fetch", "docker", "git")
    categories = {
        "web_search": "web", "web_fetch": "web",
        "docker": "devops", "git": "devops",
    }
    result = select_tools_for_message("search the web for python tutorials", defs, categories, 4)
    names = _tool_names(result)
    assert "web_search" in names
    assert "web_fetch" in names


def test_filesystem_keywords_boost_filesystem_tools():
    """File-related keywords boost filesystem tools."""
    defs = _make_defs("read_file", "write_file", "exec", "docker")
    categories = {"read_file": "filesystem", "write_file": "filesystem", "docker": "devops"}
    result = select_tools_for_message("read the config file", defs, categories, 3)
    names = _tool_names(result)
    assert "read_file" in names
    assert "write_file" in names
