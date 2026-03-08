"""Planner: Measures task scope and creates execution plans.

The Planner sits between the user request and the executor. It:
1. MEASURES: Scopes the task (file counts, sizes, complexity estimate)
2. PLANS: Creates a structured execution plan
3. DECIDES: Single-shot or chunked execution

Simple requests (chat, single tool call) bypass planning entirely.
Complex requests get a lightweight LLM call to create a plan.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from antbot.providers.base import LLMProvider


@dataclass
class TaskMeasurement:
    """Result of measuring a task's scope."""

    file_count: int = 0
    total_size_bytes: int = 0
    directory_depth: int = 0
    estimated_tokens: int = 0
    paths_referenced: list[str] = field(default_factory=list)


@dataclass
class PlanStep:
    """A single step in an execution plan."""

    action: str  # e.g., "list_dir", "batch_read", "summarize", "write"
    target: str = ""  # path or description
    batch_index: int = 0  # which batch (0 = not batched)
    batch_total: int = 0  # total batches
    context_items: list[str] = field(default_factory=list)  # specific files/items for this step


@dataclass
class ExecutionPlan:
    """Complete execution plan for a task."""

    task_type: str  # "simple" | "chunked" | "multi_phase"
    steps: list[PlanStep] = field(default_factory=list)
    context_budget: int = 24000  # max tokens per LLM call
    estimated_batches: int = 1
    original_request: str = ""

    @property
    def is_simple(self) -> bool:
        return self.task_type == "simple"


# Average tokens per character (rough estimate for mixed content)
_CHARS_PER_TOKEN = 4
# Reserve this fraction of context window for system prompt + response
_CONTEXT_RESERVE = 0.4


def _estimate_tokens(text: str) -> int:
    """Rough token count estimate."""
    return len(text) // _CHARS_PER_TOKEN


def _measure_path(path_str: str) -> TaskMeasurement:
    """Measure a filesystem path's scope."""
    path = Path(path_str).expanduser()
    measurement = TaskMeasurement()

    if not path.exists():
        return measurement

    if path.is_file():
        measurement.file_count = 1
        measurement.total_size_bytes = path.stat().st_size
        measurement.estimated_tokens = measurement.total_size_bytes // _CHARS_PER_TOKEN
        measurement.paths_referenced = [str(path)]
        return measurement

    if path.is_dir():
        try:
            for root, dirs, files in os.walk(path):
                depth = str(root).count(os.sep) - str(path).count(os.sep)
                measurement.directory_depth = max(measurement.directory_depth, depth)
                for f in files:
                    fp = Path(root) / f
                    try:
                        measurement.file_count += 1
                        measurement.total_size_bytes += fp.stat().st_size
                        measurement.paths_referenced.append(str(fp))
                    except OSError:
                        pass
                # Stop counting after 10000 files (enough to know it's big)
                if measurement.file_count > 10000:
                    break
        except PermissionError:
            pass
        measurement.estimated_tokens = measurement.total_size_bytes // _CHARS_PER_TOKEN

    return measurement


def _extract_paths(message: str) -> list[str]:
    """Extract filesystem paths from a user message."""
    import re
    # Match absolute paths, ~ paths, and /Volumes paths
    patterns = [
        r'(?:/[\w./-]+)',          # /absolute/paths
        r'(?:~/[\w./-]+)',         # ~/home/paths
    ]
    paths = []
    for pattern in patterns:
        for match in re.finditer(pattern, message):
            candidate = match.group(0).rstrip(".,;:!?)")
            if len(candidate) > 3 and Path(candidate).expanduser().exists():
                paths.append(candidate)
    return list(set(paths))


def measure_task(message: str) -> TaskMeasurement:
    """Measure the scope of a task based on the user's message."""
    paths = _extract_paths(message)
    if not paths:
        return TaskMeasurement()

    combined = TaskMeasurement()
    combined.paths_referenced = paths

    for p in paths:
        m = _measure_path(p)
        combined.file_count += m.file_count
        combined.total_size_bytes += m.total_size_bytes
        combined.directory_depth = max(combined.directory_depth, m.directory_depth)
        combined.estimated_tokens += m.estimated_tokens

    return combined


def create_plan(
    message: str,
    measurement: TaskMeasurement,
    model_context_window: int = 32000,
) -> ExecutionPlan:
    """Create an execution plan based on the task measurement.

    Args:
        message: The user's request
        measurement: Result of measuring referenced paths
        model_context_window: The model's context window in tokens
    """
    usable_context = int(model_context_window * (1 - _CONTEXT_RESERVE))

    # Simple task: no files or small scope
    if measurement.file_count == 0 or measurement.estimated_tokens < usable_context * 0.5:
        return ExecutionPlan(
            task_type="simple",
            steps=[PlanStep(action="direct", target=message)],
            context_budget=usable_context,
            estimated_batches=1,
            original_request=message,
        )

    # Chunked task: files exceed context window
    # Calculate batch size based on average file size
    if measurement.file_count > 0:
        avg_tokens_per_file = measurement.estimated_tokens // measurement.file_count
        # How many files fit in one batch (leave room for instructions + response)
        files_per_batch = max(1, usable_context // max(1, avg_tokens_per_file + 500))
        num_batches = (measurement.file_count + files_per_batch - 1) // files_per_batch
    else:
        files_per_batch = 10
        num_batches = 1

    steps = []

    # Step 1: Scan directory
    for path in measurement.paths_referenced[:5]:  # Max 5 paths
        steps.append(PlanStep(action="list_dir", target=path))

    # Step 2: Batch read + process
    all_files = measurement.paths_referenced
    for i in range(num_batches):
        batch_start = i * files_per_batch
        batch_end = min(batch_start + files_per_batch, len(all_files))
        batch_files = all_files[batch_start:batch_end]

        steps.append(PlanStep(
            action="batch_read",
            target=f"Batch {i + 1}/{num_batches}",
            batch_index=i,
            batch_total=num_batches,
            context_items=batch_files,
        ))
        steps.append(PlanStep(
            action="summarize_batch",
            target=f"Summarize batch {i + 1}",
            batch_index=i,
            batch_total=num_batches,
        ))

    # Step 3: Merge all batch summaries
    steps.append(PlanStep(action="merge_summaries", target="Final synthesis"))

    # Step 4: Write output
    steps.append(PlanStep(action="write_output", target="Write final result"))

    logger.info(
        "Plan created: {} files, {} tokens, {} batches (context budget: {})",
        measurement.file_count, measurement.estimated_tokens, num_batches, usable_context,
    )

    return ExecutionPlan(
        task_type="chunked",
        steps=steps,
        context_budget=usable_context,
        estimated_batches=num_batches,
        original_request=message,
    )


async def create_smart_plan(
    message: str,
    measurement: TaskMeasurement,
    provider: LLMProvider,
    model: str,
    model_context_window: int = 32000,
) -> ExecutionPlan:
    """Use the LLM to create a smarter plan for complex tasks.

    This is a lightweight LLM call (~500 tokens) that lets the model
    decide the best execution strategy.
    """
    # For small tasks, skip the LLM and use rule-based planning
    usable_context = int(model_context_window * (1 - _CONTEXT_RESERVE))
    if measurement.estimated_tokens < usable_context * 0.5:
        return create_plan(message, measurement, model_context_window)

    # For large tasks, ask the LLM for a plan
    planning_prompt = f"""You are a task planner. Create a brief execution plan.

Task: {message}

Scope:
- Files referenced: {measurement.file_count}
- Total data size: {measurement.total_size_bytes // 1024}KB
- Estimated tokens: {measurement.estimated_tokens}
- Context budget per step: {usable_context} tokens

Respond with a brief plan (2-5 steps). Keep it concise.
Focus on: what to read, how to batch it, what to produce."""

    try:
        response = await provider.chat(
            messages=[
                {"role": "system", "content": "You are a task planner. Be concise."},
                {"role": "user", "content": planning_prompt},
            ],
            model=model,
            max_tokens=500,
            temperature=0.1,
        )
        logger.info("Smart plan created via LLM: {}", response.content[:200] if response.content else "empty")
    except Exception as e:
        logger.warning("Smart planning failed, falling back to rule-based: {}", e)

    # Always fall back to rule-based plan (LLM plan is for logging/future use)
    return create_plan(message, measurement, model_context_window)
