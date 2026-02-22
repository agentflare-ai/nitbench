"""Codex CLI agent adapter."""

import re
from typing import Optional

from nitbench.agents.base import AgentAdapter
from nitbench.agents.registry import register


@register
class CodexAdapter(AgentAdapter):
    agent_family = "codex"
    # Codex TUI uses › (U+203A) as its input prompt, not ❯ (U+276F).
    ready_pattern = re.compile(r"[›❯]\s*$", re.MULTILINE)
    ready_timeout = 45.0
    idle_timeout = 90.0
    default_aut_command = ["codex"]

    supported_models = [
        "gpt-5.3-codex",
        "gpt-5.3-codex-spark",
        "gpt-5.2-codex",
        "gpt-5.1-codex-max",
        "gpt-5.2",
        "gpt-5.1-codex-mini",
    ]
    supported_reasoning_levels = ["medium", "low", "high", "xhigh"]

    # Codex footer: "gpt-5.3-codex . 85% . 34k tokens"
    # Match OpenAI model ID shapes: gpt-4.1, gpt-4.1-mini, gpt-5.3-codex, o4-mini, o3
    model_pattern = re.compile(r"\b(gpt-[\d.]+(?:-[\w-]+)?|o\d+-?\w*)\b")

    def format_task_text(self, task_text: str, aif_target_path: str) -> str:
        return (
            f"You MUST follow the Agent Instruction File at "
            f"`{aif_target_path}` before doing anything else.\n\n"
            f"{task_text}"
        )

    def task_cli_args(self, task_text: str, aif_target_path: str) -> list[str]:
        """Inject the task as a positional prompt argument.

        TUI input areas don't respond reliably to PTY \\r/\\n for submission,
        so we pass the prompt on the command line instead.
        """
        formatted = self.format_task_text(task_text, aif_target_path)
        return [formatted]

    def aut_command_for(self, model: str, reasoning_level: str) -> list[str]:
        return [
            "codex", "--model", model,
            "-c", f"model_reasoning_effort={reasoning_level}",
            "--full-auto",
        ]

    def aif_read_pattern(self, aif_filename: str) -> Optional[re.Pattern]:
        # Codex reads files two ways:
        #   1. Dedicated tool: read_file with path argument
        #   2. Shell command (cat/head/etc.) — TUI renders as "Read  <filename>"
        esc = re.escape(aif_filename)
        return re.compile(rf'read_file\S*{esc}\b|Read\s+{esc}\b|cat\s+\S*{esc}\b')

    def build_agent_profile(self, model: str = "gpt-5.3-codex", reasoning_level: str = "medium") -> dict:
        return {
            "agent_family": "codex",
            "agent_version": "codex-cli",
            "model_id": model,
            "reasoning_level": reasoning_level,
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty",
        }
