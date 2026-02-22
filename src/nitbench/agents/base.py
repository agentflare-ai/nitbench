"""Base class for NitBench agent adapters.

An AgentAdapter provides the harness with agent-specific knowledge:
- How to detect when the CLI is ready for input
- How to format the task text for delivery
- What metadata to record in the agent profile
- How to parse the model identifier from live PTY output
- How to detect when the agent has finished responding
"""

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import pyte


class _RobustScreen(pyte.Screen):
    """pyte.Screen subclass that tolerates private-mode CSI sequences.

    Some modern CLIs (Gemini, etc.) emit ``CSI ? ... m`` (private SGR)
    which pyte dispatches with ``private=True``.  The stock Screen
    rejects the unexpected kwarg — we simply ignore it.
    """

    def select_graphic_rendition(self, *attrs, **kwargs):
        kwargs.pop("private", None)
        return super().select_graphic_rendition(*attrs, **kwargs)


class ScreenRenderer:
    """Stateful VT100 screen buffer — feed raw output, read rendered text."""

    def __init__(self, cols: int = 80, rows: int = 24):
        self.screen = _RobustScreen(cols, rows)
        self.stream = pyte.Stream(self.screen)

    def feed(self, text: str) -> None:
        self.stream.feed(text)

    def display(self) -> str:
        return "\n".join(self.screen.display)

    def reset(self) -> None:
        """Clear the screen buffer so stale content doesn't affect pattern matching."""
        self.screen.reset()


class AgentAdapter(ABC):
    """Abstract base for agent family adapters.

    Subclasses define the ready-prompt pattern, task formatting, and profile
    metadata for a specific CLI agent (gemini, qwen, claude, etc.).
    """

    agent_family: str
    """Short identifier, e.g. ``"gemini"``, ``"qwen"``."""

    ready_pattern: re.Pattern
    """Regex that matches the agent's "ready for input" prompt in PTY output."""

    ready_timeout: float = 30.0
    """Seconds to wait for the ready prompt before declaring timeout."""

    idle_timeout: float = 120.0
    """Seconds of no PTY output (after task injection) before the harness terminates the agent."""

    default_aut_command: list[str] = []
    """Default command to spawn this agent when ``--aut-command`` is omitted."""

    supported_models: list[str] = []
    """List of model identifiers this agent supports for ``--all-models`` sweeps."""

    supported_reasoning_levels: list[str] = ["none"]
    """List of reasoning levels this agent supports for ``--all-reasoning-levels`` sweeps."""

    model_pattern: Optional[re.Pattern] = None
    """Regex with one capture group that extracts the model identifier from
    the agent's PTY output (e.g. a footer status line)."""

    done_pattern: Optional[re.Pattern] = None
    """Regex that signals the agent has finished responding.  When ``None``
    the harness falls back to :attr:`ready_pattern` (prompt reappearing)."""

    @abstractmethod
    def format_task_text(self, task_text: str, aif_target_path: str) -> str:
        """Return the text to send into the PTY after the ready prompt.

        Parameters
        ----------
        task_text:
            Raw task text from ``task.md``.
        aif_target_path:
            Workspace-relative path where the AIF was placed (e.g. ``"GEMINI.md"``).
        """

    @abstractmethod
    def build_agent_profile(self, model: str = "", reasoning_level: str = "none") -> dict:
        """Return agent profile metadata for ``run.json``.

        Parameters
        ----------
        model:
            Model identifier override.  When empty, use the adapter's default.
        reasoning_level:
            Reasoning level override.
        """

    def create_renderer(self) -> ScreenRenderer:
        """Return a VT100 screen renderer.  All adapters use rendering by
        default.  Override to customize screen dimensions."""
        return ScreenRenderer()

    def pre_flight(self, workspace_repo: "Path") -> None:
        """Called before the AUT is spawned.  Override to set up agent config."""

    def post_flight(self) -> None:
        """Called after the AUT exits.  Override to clean up agent config."""

    def task_cli_args(self, task_text: str, aif_target_path: str) -> Optional[list[str]]:
        """Return extra CLI args to inject the task at spawn time.

        When this returns a list, the harness appends these args to the AUT
        command and skips PTY-based task injection.  Return ``None`` (default)
        to inject via PTY after the ready prompt.
        """
        return None

    def aut_command_for(self, model: str, reasoning_level: str) -> list[str]:
        """Build the CLI command to spawn this agent with a specific model+reasoning combo.

        Default implementation returns :attr:`default_aut_command` unchanged.
        Subclasses should override to inject ``--model`` / ``--reasoning`` flags.
        """
        return list(self.default_aut_command)

    def aif_read_pattern(self, aif_filename: str) -> Optional[re.Pattern]:
        """Return a regex that matches this agent's tool-use output when reading *aif_filename*.

        Override in subclasses.  Returns ``None`` (default) when detection is
        not possible (e.g. CLI-injected agents that don't stream tool calls).
        """
        return None

    def parse_model_from_output(self, output: str) -> Optional[str]:
        """Extract the model identifier from *output*, or ``None``.

        Returns the *last* match found in *output* so that model switches
        (where old and new model lines coexist on the rendered screen) are
        handled correctly.
        """
        if self.model_pattern is None:
            return None
        matches = self.model_pattern.findall(output)
        return matches[-1] if matches else None
