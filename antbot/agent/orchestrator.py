"""Orchestrator: Coordinates Planner → Guard → Executor flow.

The Orchestrator intercepts messages before they reach the agent loop.
It measures the task, creates a plan, and for chunked tasks, executes
each batch with an isolated context — so the model never sees more
than it needs.

For simple tasks (chat, 1-3 tool calls), it passes through directly
to the existing agent loop with zero overhead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from antbot.agent.guard import GuardResult, RiskLevel, review_tool_call, review_tool_result
from antbot.agent.planner import (
    ExecutionPlan,
    TaskMeasurement,
    create_plan,
    measure_task,
)

if TYPE_CHECKING:
    from antbot.agent.context import ContextBuilder
    from antbot.agent.tools.registry import ToolRegistry
    from antbot.providers.base import LLMProvider


# Default context window for local models (conservative)
DEFAULT_CONTEXT_WINDOW = 32000


class Orchestrator:
    """Coordinates task planning, safety review, and chunked execution.

    Sits between the message handler and the agent loop. For simple tasks,
    adds no overhead. For complex tasks, manages batched execution with
    context isolation.
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_builder: ContextBuilder,
        tools: ToolRegistry,
        workspace: Path,
        model: str,
        model_context_window: int = DEFAULT_CONTEXT_WINDOW,
        guard_enabled: bool = True,
    ):
        self.provider = provider
        self.context = context_builder
        self.tools = tools
        self.workspace = workspace
        self.model = model
        self.model_context_window = model_context_window
        self.guard_enabled = guard_enabled

        # Temporary storage for chunked execution
        self._temp_dir = workspace / ".antbot_tmp"
        self._temp_dir.mkdir(parents=True, exist_ok=True)

    def analyze_task(self, message: str) -> tuple[TaskMeasurement, ExecutionPlan]:
        """Measure and plan a task. Returns (measurement, plan)."""
        measurement = measure_task(message)
        plan = create_plan(message, measurement, self.model_context_window)

        if plan.is_simple:
            logger.debug("Task classified as simple — direct execution")
        else:
            logger.info(
                "Task classified as {} — {} batches, {} files, ~{} tokens",
                plan.task_type,
                plan.estimated_batches,
                measurement.file_count,
                measurement.estimated_tokens,
            )

        return measurement, plan

    def check_tool_call(self, tool_name: str, params: dict[str, Any]) -> GuardResult:
        """Run guard check on a tool call. Returns GuardResult."""
        if not self.guard_enabled:
            return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)
        return review_tool_call(tool_name, params)

    def check_tool_result(self, tool_name: str, result: str) -> GuardResult:
        """Run guard check on a tool result (output data). Returns GuardResult."""
        if not self.guard_enabled:
            return GuardResult(risk=RiskLevel.SAFE, tool_name=tool_name)
        return review_tool_result(tool_name, result)

    async def execute_chunked(
        self,
        plan: ExecutionPlan,
        run_agent_fn: Callable,
        build_messages_fn: Callable,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Execute a chunked plan with context isolation.

        Each batch gets a fresh context. Intermediate results are saved
        to disk and merged in a final phase.

        Args:
            plan: The execution plan from the planner
            run_agent_fn: The agent loop function to call for each phase
            build_messages_fn: Function to build message arrays
            on_progress: Optional callback for progress updates
        """
        if plan.is_simple:
            raise ValueError("Simple plans should not use chunked execution")

        partial_results: list[str] = []
        batch_steps = [s for s in plan.steps if s.action == "batch_read"]

        if on_progress:
            await on_progress(
                f"📋 Plan: Processing {len(batch_steps)} batches "
                f"({plan.estimated_batches} estimated)"
            )

        # Phase 1: Process each batch independently
        for i, step in enumerate(batch_steps):
            if on_progress:
                await on_progress(f"⚙️ Batch {i + 1}/{len(batch_steps)}...")

            # Build a focused prompt for this batch
            batch_files = step.context_items
            batch_prompt = (
                f"You are processing batch {i + 1} of {len(batch_steps)} "
                f"for this task: {plan.original_request}\n\n"
                f"Process these {len(batch_files)} files and provide a concise summary "
                f"of their contents and any relevant findings:\n\n"
                + "\n".join(f"- {f}" for f in batch_files[:50])  # Cap at 50 per batch
            )

            messages = build_messages_fn(
                history=[],  # Fresh context — no history
                current_message=batch_prompt,
            )

            try:
                result, _, _ = await run_agent_fn(messages)
                if result:
                    partial_results.append(f"## Batch {i + 1}\n{result}")
                    # Save partial to disk
                    partial_path = self._temp_dir / f"batch_{i + 1}.md"
                    partial_path.write_text(result, encoding="utf-8")
            except Exception as e:
                logger.error("Batch {} failed: {}", i + 1, e)
                partial_results.append(f"## Batch {i + 1}\n(Failed: {e})")

        # Phase 2: Merge all batch results
        if on_progress:
            await on_progress("🔄 Merging batch results...")

        merge_prompt = (
            f"Original task: {plan.original_request}\n\n"
            f"Below are the results from processing {len(partial_results)} batches. "
            f"Synthesize them into a single, coherent response:\n\n"
            + "\n\n---\n\n".join(partial_results)
        )

        messages = build_messages_fn(
            history=[],  # Fresh context
            current_message=merge_prompt,
        )

        final_result, _, _ = await run_agent_fn(messages)

        # Cleanup temp files
        for f in self._temp_dir.glob("batch_*.md"):
            f.unlink(missing_ok=True)

        return final_result or "Task completed but produced no output."

    def should_plan(self, message: str) -> bool:
        """Quick check: does this message likely need planning?

        Returns False for simple chat/questions and single-tool tasks.
        Returns True only for genuinely complex multi-file operations.

        Key insight: "list files in ~/Downloads" is a SINGLE tool call,
        not a complex task. Planning is for tasks like "organize 500 files
        by date" or "compare all configs across 3 directories".
        """
        msg_lower = message.lower()

        # These words indicate SIMPLE tasks — never plan
        simple_indicators = [
            "list", "show", "tree", "what's in", "what is in", "ls",
            "read", "cat", "open", "hello", "hi", "help", "who are",
            "what are", "how", "why", "tell me", "search", "find",
        ]
        if any(ind in msg_lower for ind in simple_indicators):
            return False

        # These words indicate genuinely COMPLEX multi-file tasks
        complex_indicators = [
            "organize", "consolidate", "compare all", "merge all",
            "review all", "process all", "refactor", "migrate",
            "batch", "bulk", "every file",
        ]
        return any(ind in msg_lower for ind in complex_indicators)
