"""Auto-detect local LLM endpoints (LM Studio, Exo, Ollama)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from loguru import logger


@dataclass
class LocalEndpoint:
    """A discovered local LLM endpoint."""

    name: str
    api_base: str
    models: list[str]
    supports_tools: bool = True


# Known local LLM endpoints to probe on startup.
_KNOWN_ENDPOINTS = [
    ("lm-studio", "http://192.168.74.179:1238/v1"),
    ("lm-studio-localhost", "http://localhost:1234/v1"),
    ("exo", "http://localhost:52415/v1"),
    ("ollama", "http://localhost:11434/v1"),
]

_PROBE_TIMEOUT = 3.0  # seconds


async def _probe_endpoint(name: str, api_base: str) -> LocalEndpoint | None:
    """Probe a single endpoint. Returns LocalEndpoint if reachable, None otherwise."""
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(f"{api_base}/models")
            if resp.status_code == 200:
                data = resp.json()
                models = []
                if isinstance(data, dict) and "data" in data:
                    models = [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
                elif isinstance(data, list):
                    models = [m.get("id", "") for m in data if isinstance(m, dict)]
                logger.info("Local LLM detected: {} at {} ({} models)", name, api_base, len(models))
                return LocalEndpoint(name=name, api_base=api_base, models=models)
    except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
        pass
    except Exception as e:
        logger.debug("Probe failed for {} ({}): {}", name, api_base, e)
    return None


async def detect_local_endpoints() -> list[LocalEndpoint]:
    """Probe all known local LLM endpoints in parallel. Returns discovered endpoints."""
    tasks = [_probe_endpoint(name, url) for name, url in _KNOWN_ENDPOINTS]
    results = await asyncio.gather(*tasks)
    return [ep for ep in results if ep is not None]


async def get_best_local_endpoint() -> LocalEndpoint | None:
    """Return the best available local endpoint, preferring endpoints with more models."""
    endpoints = await detect_local_endpoints()
    if not endpoints:
        logger.warning("No local LLM endpoints found. Configure a provider manually.")
        return None
    # Prefer endpoints with models loaded, then by priority order (LM Studio > Exo > Ollama)
    endpoints.sort(key=lambda ep: len(ep.models), reverse=True)
    best = endpoints[0]
    logger.info("Using local LLM: {} ({} models available)", best.name, len(best.models))
    return best


def add_custom_endpoint(name: str, api_base: str) -> None:
    """Register an additional endpoint to probe during detection."""
    _KNOWN_ENDPOINTS.append((name, api_base))


# --- Native tool-calling detection ---

# Models known to support OpenAI-style function calling reliably.
_NATIVE_TOOL_MODELS = frozenset({
    "qwen2.5", "qwen2", "qwen3",
    "llama-3.1", "llama-3.2", "llama-3.3", "llama3.1", "llama3.2", "llama3.3",
    "mistral", "mixtral",
    "hermes", "nous-hermes",
    "functionary",
    "command-r", "command-r-plus",
    "firefunction",
    "nexusraven",
    "gorilla",
})

# Models known to NOT support function calling (text-only output).
_TEXT_ONLY_MODELS = frozenset({
    "gemma", "gemma2", "gemma3",
    "phi", "phi-2", "phi-3", "phi-4",
    "codellama", "code-llama",
    "deepseek-coder", "deepseek-v2",
    "starcoder", "starcoder2",
    "yi",
    "tinyllama",
    "stablelm",
    "falcon",
    "mpt",
})


def detect_native_tool_support(model_name: str) -> bool:
    """Detect whether a model supports native OpenAI-style function calling.

    Returns True for models known to handle the ``tools`` parameter,
    False for text-only models, and True (optimistic) for unknown models.
    """
    name = model_name.lower().replace("_", "-")

    # Check native-support list first
    for pattern in _NATIVE_TOOL_MODELS:
        if pattern in name:
            return True

    # Check text-only list
    for pattern in _TEXT_ONLY_MODELS:
        if pattern in name:
            return False

    # Unknown model — optimistic default
    return True
