"""Repair malformed JSON from local LLM tool calls.

Local models (8-30B) occasionally produce broken JSON in tool calls:
- Trailing commas
- Missing closing braces/brackets
- Single quotes instead of double
- Unquoted keys
- Truncated output

This module attempts to fix common issues before falling back to json_repair library.
"""

from __future__ import annotations

import json
import re
from typing import Any

from loguru import logger


def repair_json(text: str) -> Any:
    """Attempt to parse and repair malformed JSON. Returns parsed object or raises ValueError."""

    # Step 0: Try parsing as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = text.strip()

    # Step 1: Extract JSON from markdown code blocks
    md_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
    if md_match:
        cleaned = md_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Step 2: Find the first { or [ and extract to its matching closer
    start = -1
    for i, c in enumerate(cleaned):
        if c in "{[":
            start = i
            break
    if start >= 0:
        cleaned = cleaned[start:]

    # Step 3: Replace single quotes with double quotes (careful with apostrophes)
    if "'" in cleaned and '"' not in cleaned:
        cleaned = cleaned.replace("'", '"')
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    # Step 4: Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Step 5: Close unclosed braces/brackets
    open_braces = cleaned.count("{") - cleaned.count("}")
    open_brackets = cleaned.count("[") - cleaned.count("]")
    if open_braces > 0 or open_brackets > 0:
        patched = cleaned + ("}" * max(0, open_braces)) + ("]" * max(0, open_brackets))
        try:
            return json.loads(patched)
        except json.JSONDecodeError:
            pass

    # Step 6: Quote unquoted keys
    unquoted = re.sub(r"(?<=[{,])\s*(\w+)\s*:", r' "\1":', cleaned)
    try:
        return json.loads(unquoted)
    except json.JSONDecodeError:
        pass

    # Step 7: Fall back to json_repair library (already a dependency)
    try:
        import json_repair as jr
        return jr.loads(text)
    except Exception:
        pass

    raise ValueError(f"Cannot repair JSON: {text[:200]}...")


def try_repair_tool_arguments(raw: str | dict | list) -> dict:
    """Repair tool call arguments specifically. Always returns a dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return raw[0] if raw and isinstance(raw[0], dict) else {}

    try:
        result = repair_json(str(raw))
        if isinstance(result, dict):
            return result
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return result[0]
        return {}
    except (ValueError, TypeError) as e:
        logger.warning("Failed to repair tool arguments: {}", e)
        return {}
