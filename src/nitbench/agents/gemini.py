"""Gemini CLI agent adapter."""

import json
import re
from pathlib import Path
from typing import Optional

from nitbench.agents.base import AgentAdapter
from nitbench.agents.registry import register

_TRUSTED_FOLDERS_PATH = Path.home() / ".gemini" / "trustedFolders.json"


@register
class GeminiAdapter(AgentAdapter):
    agent_family = "gemini"
    ready_pattern = re.compile(r"(Type your message|[❯>]\s*$)")
    ready_timeout = 60.0
    idle_timeout = 60.0
    default_aut_command = ["gemini"]

    supported_models = ["gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    supported_reasoning_levels = ["none"]

    # Footer line:  /model gemini-2.5-pro  45%  150/1500 (resets 2h)
    model_pattern = re.compile(r"/model\s+([\w][\w.+-]+)")

    # done_pattern = None → falls back to ready_pattern (prompt reappears)

    def __init__(self) -> None:
        self._trusted_path: Optional[str] = None

    def pre_flight(self, workspace_repo: Path) -> None:
        """Pre-trust the workspace so Gemini skips the trust dialog."""
        key = str(workspace_repo.resolve())
        data = {}
        if _TRUSTED_FOLDERS_PATH.exists():
            data = json.loads(_TRUSTED_FOLDERS_PATH.read_text())
        if key not in data:
            data[key] = "TRUST_FOLDER"
            _TRUSTED_FOLDERS_PATH.write_text(json.dumps(data, indent=2))
            self._trusted_path = key

    def post_flight(self) -> None:
        """Remove the workspace trust entry added by pre_flight."""
        if self._trusted_path and _TRUSTED_FOLDERS_PATH.exists():
            data = json.loads(_TRUSTED_FOLDERS_PATH.read_text())
            data.pop(self._trusted_path, None)
            _TRUSTED_FOLDERS_PATH.write_text(json.dumps(data, indent=2))
            self._trusted_path = None

    def format_task_text(self, task_text: str, aif_target_path: str) -> str:
        return (
            f"You MUST follow the Agent Instruction File at "
            f"`{aif_target_path}` before doing anything else.\n\n"
            f"{task_text}"
        )

    def task_cli_args(self, task_text: str, aif_target_path: str) -> list[str]:
        """Inject the task via ``-i`` (prompt-interactive) instead of PTY.

        Also adds ``--yolo`` so Gemini auto-approves tool calls (file edits,
        shell commands) without waiting for user confirmation.
        """
        formatted = self.format_task_text(task_text, aif_target_path)
        return ["--yolo", "-i", formatted]

    def aut_command_for(self, model: str, reasoning_level: str) -> list[str]:
        return ["gemini", "-m", model]

    def build_agent_profile(self, model: str = "gemini-2.5-pro", reasoning_level: str = "none") -> dict:
        return {
            "agent_family": "gemini",
            "agent_version": "gemini-cli",
            "model_id": model,
            "reasoning_level": reasoning_level,
            "interaction_mode": "pty",
            "aut_mode": "manual",
            "tool_mode": "interactive_pty",
        }
