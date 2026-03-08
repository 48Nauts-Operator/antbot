"""Tests for model name → native/react classification."""

from antbot.providers.local_detect import detect_native_tool_support


class TestNativeToolSupport:
    """Models known to support native function calling."""

    def test_qwen_models(self):
        assert detect_native_tool_support("qwen2.5-72b-instruct") is True
        assert detect_native_tool_support("Qwen2.5-Coder-32B") is True
        assert detect_native_tool_support("qwen3-8b") is True

    def test_llama_models(self):
        assert detect_native_tool_support("llama-3.1-8b-instruct") is True
        assert detect_native_tool_support("llama-3.2-3b") is True
        assert detect_native_tool_support("llama-3.3-70b") is True
        assert detect_native_tool_support("meta-llama3.1-instruct") is True

    def test_mistral_models(self):
        assert detect_native_tool_support("mistral-7b-instruct") is True
        assert detect_native_tool_support("mixtral-8x7b") is True

    def test_hermes_models(self):
        assert detect_native_tool_support("hermes-3-llama-3.1-8b") is True
        assert detect_native_tool_support("nous-hermes-2") is True

    def test_functionary(self):
        assert detect_native_tool_support("functionary-small-v3.2") is True


class TestTextOnlyModels:
    """Models known to NOT support function calling."""

    def test_gemma_models(self):
        assert detect_native_tool_support("gemma-3-27b-it") is False
        assert detect_native_tool_support("gemma2-9b") is False
        assert detect_native_tool_support("google/gemma3-12b") is False

    def test_phi_models(self):
        assert detect_native_tool_support("phi-3-mini") is False
        assert detect_native_tool_support("phi-4-14b") is False

    def test_codellama(self):
        assert detect_native_tool_support("codellama-34b") is False
        assert detect_native_tool_support("code-llama-13b") is False

    def test_deepseek_coder(self):
        assert detect_native_tool_support("deepseek-coder-33b") is False

    def test_starcoder(self):
        assert detect_native_tool_support("starcoder2-15b") is False


class TestUnknownModels:
    """Unknown models default to True (optimistic)."""

    def test_unknown_model(self):
        assert detect_native_tool_support("some-new-model-v1") is True

    def test_gpt4(self):
        assert detect_native_tool_support("gpt-4") is True

    def test_claude(self):
        assert detect_native_tool_support("claude-3.5-sonnet") is True


class TestCaseInsensitive:
    """Detection should be case-insensitive."""

    def test_upper_case(self):
        assert detect_native_tool_support("GEMMA-3-27B") is False

    def test_mixed_case(self):
        assert detect_native_tool_support("Qwen2.5-72B-Instruct") is True

    def test_underscore_normalization(self):
        assert detect_native_tool_support("deepseek_coder_33b") is False
