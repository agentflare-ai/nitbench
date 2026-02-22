"""Claude Code agent adapter."""

import os
import re
from pathlib import Path
from typing import Optional

from nitbench.agents.base import AgentAdapter
from nitbench.agents.registry import register


@register
class ClaudeAdapter(AgentAdapter):
    agent_family = "claude"
    ready_pattern = re.compile(r"^❯", re.MULTILINE)
    ready_timeout = 60.0
    idle_timeout = 120.0
    default_aut_command = ["claude"]

    supported_models = ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5"]
    supported_reasoning_levels = ["none", "enabled"]

    # Detect model from output, e.g. "claude-sonnet-4-6" or "claude-opus-4-6"
    model_pattern = re.compile(r"(claude-[\w][\w.+-]+)")

    def __init__(self) -> None:
        self._saved_env: dict[str, str] = {}

    def pre_flight(self, workspace_repo: Path) -> None:
        """Allow nesting by removing env vars that block nested Claude Code."""
        for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
            if var in os.environ:
                self._saved_env[var] = os.environ.pop(var)

    def post_flight(self) -> None:
        """Restore env vars removed during pre_flight."""
        os.environ.update(self._saved_env)
        self._saved_env.clear()

    def format_task_text(self, task_text: str, aif_target_path: str) -> str:
        return (
            f"You MUST follow the Agent Instruction File at "
            f"`{aif_target_path}` before doing anything else.\n\n"
            f"{task_text}"
        )

    def task_cli_args(self, task_text: str, aif_target_path: str) -> list[str]:
        """Use -p (print/headless) mode for non-interactive task injection."""
        formatted = self.format_task_text(task_text, aif_target_path)
        return ["-p", formatted]

    def aut_command_for(self, model: str, reasoning_level: str) -> list[str]:
        cmd = [
            "claude",
            "--model", model,
            "--dangerously-skip-permissions",
        ]
        if reasoning_level != "none":
            cmd.extend(["--thinking", reasoning_level])
        return cmd

    def build_agent_profile(self, model: str = "claude-sonnet-4-6", reasoning_level: str = "none") -> dict:
        return {
            "agent_family": "claude",
            "agent_version": "claude-code",
            "model_id": model,
            "reasoning_level": reasoning_level,
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty",
        }
