"""Tests for the agent adapter registry and built-in adapters."""

import re
import pytest

from nitbench.agents.base import AgentAdapter, ScreenRenderer
from nitbench.agents.registry import get_adapter, registered_families

# Importing the package triggers registration of all built-in adapters
import nitbench.agents  # noqa: F401


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestAgentRegistry:
    def test_get_gemini_adapter(self):
        adapter = get_adapter("gemini")
        assert adapter is not None
        assert isinstance(adapter, AgentAdapter)
        assert adapter.agent_family == "gemini"

    def test_get_codex_adapter(self):
        adapter = get_adapter("codex")
        assert adapter is not None
        assert isinstance(adapter, AgentAdapter)
        assert adapter.agent_family == "codex"

    def test_unknown_family_returns_none(self):
        assert get_adapter("nonexistent_agent_xyz") is None

    def test_gemini_registered(self):
        assert "gemini" in registered_families()

    def test_codex_registered(self):
        assert "codex" in registered_families()


# ---------------------------------------------------------------------------
# GeminiAdapter tests
# ---------------------------------------------------------------------------

class TestGeminiAdapter:
    def setup_method(self):
        self.adapter = get_adapter("gemini")

    def test_ready_pattern_matches_angle_bracket(self):
        assert self.adapter.ready_pattern.search("> ")

    def test_ready_pattern_matches_unicode_prompt(self):
        assert self.adapter.ready_pattern.search("❯ ")

    def test_ready_pattern_no_match_dollar(self):
        """Shell $ prompts should NOT match the agent ready pattern."""
        assert self.adapter.ready_pattern.search("$ ") is None

    def test_ready_pattern_no_match_plain_text(self):
        assert self.adapter.ready_pattern.search("hello world") is None

    def test_ready_timeout(self):
        assert self.adapter.ready_timeout == 60.0

    def test_format_task_text_includes_aif_path(self):
        result = self.adapter.format_task_text("Do the task", "GEMINI.md")
        assert "GEMINI.md" in result
        assert "Do the task" in result
        assert "MUST follow" in result

    def test_format_task_text_empty_aif(self):
        result = self.adapter.format_task_text("Do the task", "")
        assert "Do the task" in result

    def test_build_agent_profile_has_required_keys(self):
        profile = self.adapter.build_agent_profile()
        required = {
            "agent_family", "agent_version", "model_id",
            "reasoning_level", "interaction_mode", "aut_mode", "tool_mode",
        }
        assert required.issubset(profile.keys())
        assert profile["agent_family"] == "gemini"

    def test_default_aut_command(self):
        assert self.adapter.default_aut_command == ["gemini"]

    def test_model_pattern_matches_footer(self):
        assert self.adapter.model_pattern is not None
        m = self.adapter.model_pattern.search("/model gemini-2.5-pro  45%  150/1500")
        assert m is not None
        assert m.group(1) == "gemini-2.5-pro"

    def test_model_pattern_different_model(self):
        m = self.adapter.model_pattern.search("/model gemini-2.0-flash  80%")
        assert m is not None
        assert m.group(1) == "gemini-2.0-flash"

    def test_parse_model_from_output(self):
        result = self.adapter.parse_model_from_output(
            "~/project (main*)  /model gemini-2.5-pro  45%"
        )
        assert result == "gemini-2.5-pro"

    def test_parse_model_from_output_no_match(self):
        result = self.adapter.parse_model_from_output("just some regular output")
        assert result is None

    def test_done_pattern_defaults_to_none(self):
        assert self.adapter.done_pattern is None

    def test_create_renderer_returns_screen_renderer(self):
        renderer = self.adapter.create_renderer()
        assert isinstance(renderer, ScreenRenderer)

    @pytest.mark.parametrize("footer_line,expected_model", [
        ("/model auto  45%", "auto"),
        ("/model gemini-2.0-flash  80%", "gemini-2.0-flash"),
        ("/model gemini-2.5-pro  45%  150/1500 (resets 2h)", "gemini-2.5-pro"),
        ("/model gemini-2.5-flash-preview-04-17  90%", "gemini-2.5-flash-preview-04-17"),
        ("/model gemini-3.0-pro-preview  60%  200/1500", "gemini-3.0-pro-preview"),
        ("/model gemini-3.1-pro  30%", "gemini-3.1-pro"),
        # embedded in a full footer line with path prefix
        ("~/project (main*)   /model gemini-3.0-pro-preview  50%", "gemini-3.0-pro-preview"),
    ])
    def test_model_pattern_real_model_ids(self, footer_line, expected_model):
        """Verify model_pattern extracts the correct model ID from real
        Gemini CLI footer lines across the full model ID space."""
        result = self.adapter.parse_model_from_output(footer_line)
        assert result == expected_model


# ---------------------------------------------------------------------------
# CodexAdapter tests
# ---------------------------------------------------------------------------

class TestCodexAdapter:
    def setup_method(self):
        self.adapter = get_adapter("codex")

    def test_ready_pattern_matches_type_your_message(self):
        assert self.adapter.ready_pattern.search("Type your message")

    def test_ready_pattern_matches_unicode_prompt(self):
        assert self.adapter.ready_pattern.search("❯ ")

    def test_ready_pattern_no_match_dollar(self):
        assert self.adapter.ready_pattern.search("$ ") is None

    def test_ready_pattern_no_match_plain_text(self):
        assert self.adapter.ready_pattern.search("hello world") is None

    def test_ready_timeout(self):
        assert self.adapter.ready_timeout == 45.0

    def test_format_task_text_includes_aif_path(self):
        result = self.adapter.format_task_text("Do the task", "CODEX.md")
        assert "CODEX.md" in result
        assert "Do the task" in result
        assert "MUST follow" in result

    def test_build_agent_profile_has_required_keys(self):
        profile = self.adapter.build_agent_profile()
        required = {
            "agent_family", "agent_version", "model_id",
            "reasoning_level", "interaction_mode", "aut_mode", "tool_mode",
        }
        assert required.issubset(profile.keys())
        assert profile["agent_family"] == "codex"

    def test_default_aut_command(self):
        assert self.adapter.default_aut_command == ["codex"]

    def test_create_renderer_returns_screen_renderer(self):
        renderer = self.adapter.create_renderer()
        assert isinstance(renderer, ScreenRenderer)

    @pytest.mark.parametrize("text,expected_model", [
        ("gpt-5.3-codex . 85% . 34k tokens", "gpt-5.3-codex"),
        ("gpt-5.2-codex . 90% . 20k tokens", "gpt-5.2-codex"),
        ("gpt-5.1-codex . 70% . 10k tokens", "gpt-5.1-codex"),
        ("o4-mini . 95% . 5k tokens", "o4-mini"),
        ("o3 . 80% . 12k tokens", "o3"),
        ("gpt-4.1 . 60% . 8k tokens", "gpt-4.1"),
        ("gpt-4.1-mini . 50% . 6k tokens", "gpt-4.1-mini"),
    ])
    def test_model_pattern_real_model_ids(self, text, expected_model):
        """Verify model_pattern extracts the correct model ID from real
        Codex CLI footer lines across the full model ID space."""
        result = self.adapter.parse_model_from_output(text)
        assert result == expected_model

    def test_parse_model_from_output_no_match(self):
        result = self.adapter.parse_model_from_output("just some regular output")
        assert result is None

    def test_done_pattern_defaults_to_none(self):
        assert self.adapter.done_pattern is None


# ---------------------------------------------------------------------------
# ScreenRenderer tests
# ---------------------------------------------------------------------------

class TestScreenRenderer:
    def test_basic_feed_and_display(self):
        renderer = ScreenRenderer()
        renderer.feed("Hello, world!")
        assert "Hello, world!" in renderer.display()

    def test_ansi_stripped(self):
        renderer = ScreenRenderer()
        renderer.feed("\x1b[1;32mGreen bold\x1b[0m normal")
        display = renderer.display()
        assert "Green bold" in display
        assert "\x1b[" not in display

    def test_accumulates_lines(self):
        renderer = ScreenRenderer()
        renderer.feed("Line 1\n")
        renderer.feed("Line 2\n")
        display = renderer.display()
        assert "Line 1" in display
        assert "Line 2" in display
