"""Codex CLI agent adapter."""

import re

from nitbench.agents.base import AgentAdapter
from nitbench.agents.registry import register


@register
class CodexAdapter(AgentAdapter):
    agent_family = "codex"
    ready_pattern = re.compile(r"Type your message|❯\s*$")
    ready_timeout = 45.0
    idle_timeout = 90.0
    default_aut_command = ["codex"]

    supported_models = ["gpt-5.3-codex", "o4-mini", "o3"]
    supported_reasoning_levels = ["low", "medium", "high"]

    # Codex footer: "gpt-5.3-codex . 85% . 34k tokens"
    # Match OpenAI model ID shapes: gpt-4.1, gpt-4.1-mini, gpt-5.3-codex, o4-mini, o3
    model_pattern = re.compile(r"\b(gpt-[\d.]+(?:-[\w-]+)?|o\d+-?\w*)\b")

    def format_task_text(self, task_text: str, aif_target_path: str) -> str:
        return (
            f"You MUST follow the Agent Instruction File at "
            f"`{aif_target_path}` before doing anything else.\n\n"
            f"{task_text}"
        )

    def aut_command_for(self, model: str, reasoning_level: str) -> list[str]:
        return ["codex", "--model", model, "--reasoning", reasoning_level]

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
