"""Tests for ReAct text parsing."""

from antbot.agent.tools.strategy import parse_react_response


def test_standard_react_format():
    """Parse clean Thought/Action/Action Input format."""
    text = (
        "Thought: I need to list the files.\n"
        'Action: exec\n'
        'Action Input: {"command": "ls -la"}'
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "exec"
    assert calls[0].arguments == {"command": "ls -la"}
    assert final is None


def test_final_answer():
    """Parse Final Answer without tool calls."""
    text = (
        "Thought: I know this already.\n"
        "Final Answer: The capital of France is Paris."
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 0
    assert final == "The capital of France is Paris."


def test_malformed_json_repaired():
    """Action Input with trailing comma should be repaired."""
    text = (
        "Thought: Let me check.\n"
        "Action: read_file\n"
        'Action Input: {"path": "/tmp/test.txt",}'
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments["path"] == "/tmp/test.txt"


def test_hermes_xml_format():
    """Parse Hermes-style <tool_call> XML."""
    text = '<tool_call>{"name": "exec", "arguments": {"command": "pwd"}}</tool_call>'
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "exec"
    assert calls[0].arguments == {"command": "pwd"}
    assert final is None


def test_no_match_returns_text():
    """Plain text with no ReAct format returns as final answer."""
    text = "Hello! I'm here to help."
    calls, final = parse_react_response(text)
    assert len(calls) == 0
    assert final == "Hello! I'm here to help."


def test_empty_text():
    """Empty text returns empty results."""
    calls, final = parse_react_response("")
    assert len(calls) == 0
    assert final is None


def test_action_before_final_answer():
    """When Action comes before Final Answer, Action is parsed."""
    text = (
        "Thought: Let me check first.\n"
        "Action: exec\n"
        'Action Input: {"command": "whoami"}\n'
        "Final Answer: Done."
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "exec"
    assert final is None


def test_final_answer_before_action():
    """When Final Answer comes before Action, Final Answer wins."""
    text = (
        "Thought: I already know.\n"
        "Final Answer: 42\n"
        "Action: exec\n"
        'Action Input: {"command": "echo 42"}'
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 0
    assert final == "42"


def test_action_with_non_json_input():
    """Action Input that isn't JSON wraps as {'input': ...}."""
    text = (
        "Thought: Let me run this.\n"
        "Action: exec\n"
        "Action Input: list all files"
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].arguments.get("input") == "list all files"


def test_action_without_input():
    """Action without Action Input gives empty arguments."""
    text = (
        "Thought: Let me check.\n"
        "Action: docker\n"
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "docker"
    assert calls[0].arguments == {}


def test_gemma_tool_request_format():
    """Parse Gemma-style [TOOL_REQUEST] tags."""
    text = (
        'Okay, I will list the files.\n'
        '[TOOL_REQUEST]\n'
        '{"name": "list_dir", "arguments": {"path": "/workspace"}}\n'
        '[END_TOOL_REQUEST]'
    )
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "list_dir"
    assert calls[0].arguments == {"path": "/workspace"}
    assert final is None


def test_gemma_tool_request_inline():
    """Parse Gemma [TOOL_REQUEST] on a single line."""
    text = '[TOOL_REQUEST]{"name": "exec", "arguments": {"command": "ls"}}[END_TOOL_REQUEST]'
    calls, final = parse_react_response(text)
    assert len(calls) == 1
    assert calls[0].name == "exec"
    assert calls[0].arguments == {"command": "ls"}
