"""Tests for tool strategy prepare/parse round-trip."""

from antbot.agent.tools.strategy import NativeToolStrategy, ReactToolStrategy
from antbot.providers.base import LLMResponse, ToolCallRequest


SAMPLE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]


class TestNativeStrategy:
    def test_prepare_passthrough(self):
        """Native strategy returns inputs unchanged."""
        strategy = NativeToolStrategy()
        messages = [{"role": "user", "content": "hello"}]
        out_msgs, out_tools = strategy.prepare_request(messages, SAMPLE_TOOLS)
        assert out_msgs is messages
        assert out_tools is SAMPLE_TOOLS

    def test_parse_passthrough(self):
        """Native strategy returns response unchanged."""
        strategy = NativeToolStrategy()
        resp = LLMResponse(content="hello", tool_calls=[])
        assert strategy.parse_response(resp) is resp

    def test_format_tool_result(self):
        """Native strategy formats as standard tool message."""
        strategy = NativeToolStrategy()
        msg = strategy.format_tool_result("call_1", "exec", "output")
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "call_1"
        assert msg["content"] == "output"


class TestReactStrategy:
    def test_prepare_injects_prompt_and_removes_tools(self):
        """ReAct strategy adds prompt to system message and sets tools to None."""
        strategy = ReactToolStrategy()
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "list files"},
        ]
        out_msgs, out_tools = strategy.prepare_request(messages, SAMPLE_TOOLS)
        assert out_tools is None
        assert "Action:" in out_msgs[0]["content"]
        assert "exec" in out_msgs[0]["content"]

    def test_prepare_creates_system_message_if_missing(self):
        """ReAct strategy creates a system message if none exists."""
        strategy = ReactToolStrategy()
        messages = [{"role": "user", "content": "list files"}]
        out_msgs, out_tools = strategy.prepare_request(messages, SAMPLE_TOOLS)
        assert out_tools is None
        assert out_msgs[0]["role"] == "system"
        assert "Action:" in out_msgs[0]["content"]

    def test_parse_extracts_tool_call(self):
        """ReAct strategy extracts tool call from text."""
        strategy = ReactToolStrategy()
        strategy.prepare_request([], SAMPLE_TOOLS)  # Initialize tool defs

        resp = LLMResponse(
            content=(
                "Thought: I need to list files.\n"
                "Action: exec\n"
                'Action Input: {"command": "ls"}'
            ),
            tool_calls=[],
        )
        result = strategy.parse_response(resp)
        assert result.has_tool_calls
        assert result.tool_calls[0].name == "exec"
        assert result.tool_calls[0].arguments == {"command": "ls"}

    def test_parse_extracts_final_answer(self):
        """ReAct strategy extracts final answer from text."""
        strategy = ReactToolStrategy()
        resp = LLMResponse(
            content="Thought: I know this.\nFinal Answer: It's 42.",
            tool_calls=[],
        )
        result = strategy.parse_response(resp)
        assert not result.has_tool_calls
        assert result.content == "It's 42."

    def test_parse_passthrough_native_tool_calls(self):
        """If model produces native tool calls, ReAct strategy passes them through."""
        strategy = ReactToolStrategy()
        tc = ToolCallRequest(id="1", name="exec", arguments={"command": "pwd"})
        resp = LLMResponse(content=None, tool_calls=[tc])
        result = strategy.parse_response(resp)
        assert result is resp

    def test_format_tool_result_as_observation(self):
        """ReAct strategy formats tool results as Observation messages."""
        strategy = ReactToolStrategy()
        msg = strategy.format_tool_result("call_1", "exec", "file1.txt\nfile2.txt")
        assert msg["role"] == "user"
        assert msg["content"].startswith("Observation:")
        assert "file1.txt" in msg["content"]

    def test_prepare_with_no_tools(self):
        """ReAct strategy with empty tools returns messages unchanged."""
        strategy = ReactToolStrategy()
        messages = [{"role": "user", "content": "hello"}]
        out_msgs, out_tools = strategy.prepare_request(messages, [])
        assert out_msgs is messages
        assert out_tools is None
