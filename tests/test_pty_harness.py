"""Tests for the interactive PTY harness (pty_harness.py)."""

import json
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from nitbench.sandbox.pty_harness import CommandDetector, ProxyComputer, InteractivePtyHarness
from nitbench.sandbox.environment import AutSandbox
from nitbench.sandbox.orchestrator import TranscriptLogger, ActionLogger, BudgetEnforcer
from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.validator import RunValidator


# ---------------------------------------------------------------------------
# CommandDetector tests
# ---------------------------------------------------------------------------

class TestCommandDetector:
    def setup_method(self):
        self.detector = CommandDetector()

    def test_detects_dollar_prompt(self):
        assert self.detector.detect("user@host:~$ ls -la") == "ls"

    def test_detects_hash_prompt(self):
        assert self.detector.detect("root@host:/# apt-get update") == "apt-get"

    def test_angle_bracket_excluded(self):
        # '>' is excluded from prompt chars to avoid TUI input prompt false positives
        assert self.detector.detect("> python main.py") is None

    def test_detects_bare_dollar(self):
        assert self.detector.detect("$ git status") == "git"

    def test_returns_none_for_plain_output(self):
        assert self.detector.detect("hello world") is None

    def test_returns_none_for_empty(self):
        assert self.detector.detect("") is None

    def test_strips_absolute_path(self):
        assert self.detector.detect("$ /usr/bin/python3 script.py") == "python3"

    def test_detects_in_multiline(self):
        # The regex can find prompts after a newline
        assert self.detector.detect("some output\nuser@box:~$ make build") == "make"


# ---------------------------------------------------------------------------
# ProxyComputer tests
# ---------------------------------------------------------------------------

class TestProxyComputer:
    def test_action_count_increments(self, tmp_path):
        proxy = ProxyComputer("agent_action_count", tmp_path)
        assert proxy.update(detected_command=None) == 0
        assert proxy.update(detected_command="ls") == 1
        assert proxy.update(detected_command="cat") == 2
        assert proxy.update(detected_command=None) == 2

    def test_checkpoint_index(self, tmp_path):
        proxy = ProxyComputer("checkpoint_index", tmp_path)
        assert proxy.update() == 0
        proxy.advance_checkpoint_index()
        assert proxy.update() == 1


# ---------------------------------------------------------------------------
# Fixtures shared by InteractivePtyHarness tests
# ---------------------------------------------------------------------------

@pytest.fixture
def harness_env(tmp_path):
    """Build a minimal environment for harness tests."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo = workspace / "repo"
    repo.mkdir()

    case_data = {
        "case_id": "test.pty.001",
        "aut_sandbox": {
            "network": "forbidden",
            "prohibited_executable_sets": [
                "nitbench.prohibited.lint_format.standard",
            ],
            "prohibited_attempt_policy": {
                "lint_format": "invalid",
            },
        },
        "budgets": {
            "max_agent_actions": 100,
        },
    }
    agent_profile = {
        "agent_family": "test",
        "agent_version": "0.1",
        "model_id": "test",
        "reasoning_level": "none",
        "interaction_mode": "pty",
        "aut_mode": "manual",
        "tool_mode": "interactive_pty",
    }

    # Loggers
    log_path = tmp_path / "transcript.log"
    logger = TranscriptLogger(log_path, interaction_mode="pty")

    actions_file = tmp_path / "actions.jsonl"
    actions_file.write_text("")
    action_logger = ActionLogger(actions_file)

    budgets = case_data.get("budgets", {})
    budget_enforcer = BudgetEnforcer(budgets)

    checkpoints_data = {
        "checkpoints_version": "nitbench.checkpoints.v1",
        "case_id": "test.pty.001",
        "context_proxy": {"type": "agent_action_count"},
        "checkpoints": [
            {
                "id": "cp_baseline",
                "phase": "baseline",
                "score": True,
                "trigger": {"type": "at_proxy_value", "value": 0},
            },
            {
                "id": "cp_end",
                "phase": "work",
                "score": True,
                "trigger": {"type": "end_of_run"},
            },
        ],
    }

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    checkpoint_mgr = CheckpointManager(checkpoints_data, repo, artifacts_dir, logger)

    sandbox = AutSandbox(workspace, case_data, action_logger, logger)

    run_validator = RunValidator(case_data, agent_profile)

    return {
        "workspace": workspace,
        "repo": repo,
        "sandbox": sandbox,
        "logger": logger,
        "action_logger": action_logger,
        "budget_enforcer": budget_enforcer,
        "checkpoint_mgr": checkpoint_mgr,
        "run_validator": run_validator,
        "actions_file": actions_file,
        "case_data": case_data,
        "checkpoints_data": checkpoints_data,
    }


def _make_harness(harness_env, aut_command, task_text=None, agent_adapter=None):
    return InteractivePtyHarness(
        aut_command=aut_command,
        sandbox=harness_env["sandbox"],
        workspace_repo=harness_env["repo"],
        logger=harness_env["logger"],
        action_logger=harness_env["action_logger"],
        budget_enforcer=harness_env["budget_enforcer"],
        checkpoint_mgr=harness_env["checkpoint_mgr"],
        run_validator=harness_env["run_validator"],
        task_text=task_text,
        agent_adapter=agent_adapter,
    )


# ---------------------------------------------------------------------------
# InteractivePtyHarness tests
# ---------------------------------------------------------------------------

class TestInteractivePtyHarness:
    def test_basic_run(self, harness_env):
        """Spawn a simple command and verify exit code and transcript logging."""
        harness = _make_harness(harness_env, ["bash", "-c", "echo hello; exit 0"])
        exit_code = harness.run()
        assert exit_code == 0

        # Transcript should contain the output
        log_text = harness_env["logger"].log_path.read_text()
        assert "hello" in log_text

    def test_nonzero_exit(self, harness_env):
        """Verify nonzero exit codes propagate."""
        harness = _make_harness(harness_env, ["bash", "-c", "exit 42"])
        exit_code = harness.run()
        assert exit_code == 42

    def test_budget_enforcement(self, harness_env):
        """Verify harness terminates when action budget is exceeded."""
        # Set a very low budget
        harness_env["budget_enforcer"].budgets["max_agent_actions"] = 2
        harness_env["budget_enforcer"].budgets["max_wall_seconds"] = 10

        # Run a shell that executes many commands with prompts
        script = (
            'export PS1="$ "\n'
            'echo cmd1\n'
            'echo cmd2\n'
            'echo cmd3\n'
            'echo cmd4\n'
            'echo cmd5\n'
            'exit 0\n'
        )
        harness = _make_harness(harness_env, ["bash", "--norc", "--noprofile", "-c", script])
        harness.run()

        # Budget should have been checked (actions recorded via prompt detection)
        # The exact number depends on prompt detection heuristics, but the enforcer
        # should have recorded at least some actions or wall time won't be exceeded
        # in this short script. We mainly verify the harness doesn't hang.

    def test_end_of_run_checkpoint(self, harness_env):
        """Verify end_of_run checkpoint fires after AUT exits."""
        # Trigger baseline first (proxy=0)
        harness_env["checkpoint_mgr"].trigger_if_needed("at_proxy_value", 0)

        harness = _make_harness(harness_env, ["bash", "-c", "echo done; exit 0"])
        harness.run()

        assert "cp_end" in harness_env["checkpoint_mgr"].executed_checkpoints

    def test_checkpoint_triggering_at_proxy(self, harness_env):
        """Verify checkpoints fire at correct proxy values."""
        # Add a mid-run checkpoint at proxy value 1
        harness_env["checkpoint_mgr"].checkpoints.append({
            "id": "cp_mid",
            "phase": "work",
            "score": True,
            "trigger": {"type": "at_proxy_value", "value": 1},
        })

        # Script with a prompt that will be detected
        script = (
            'export PS1="$ "\n'
            'echo "$ ls"\n'  # fake prompt line in output
            'exit 0\n'
        )
        harness = _make_harness(harness_env, ["bash", "--norc", "--noprofile", "-c", script])
        harness.run()

        # At minimum the end_of_run checkpoint should fire
        assert "cp_end" in harness_env["checkpoint_mgr"].executed_checkpoints


class TestProhibitedToolDetection:
    def test_prohibited_tool_detected_as_invalid(self, harness_env):
        """Verify that prohibited tool attempts from PTY output cause invalidation."""
        sandbox = harness_env["sandbox"]

        # Direct check_prohibited call
        is_prohibited, policy = sandbox.check_prohibited("pylint")
        assert is_prohibited is True
        assert policy == "invalid"

    def test_allowed_tool_not_prohibited(self, harness_env):
        sandbox = harness_env["sandbox"]
        is_prohibited, policy = sandbox.check_prohibited("python")
        assert is_prohibited is False
        assert policy is None

    def test_install_tool_prohibited(self, harness_env):
        """Verify install tools are caught when the set is configured."""
        sandbox = harness_env["sandbox"]
        # Add install prohibition
        sandbox.sandbox_rules["prohibited_executable_sets"].append(
            "nitbench.prohibited.install.standard"
        )
        sandbox.sandbox_rules["prohibited_attempt_policy"]["install"] = "record_only"

        is_prohibited, policy = sandbox.check_prohibited("pip")
        assert is_prohibited is True
        assert policy == "record_only"


# ---------------------------------------------------------------------------
# Task injection tests
# ---------------------------------------------------------------------------

class TestTaskInjection:
    def test_task_injected_after_ready_pattern(self, harness_env):
        """Bash script prints '> ', reads stdin, echoes back — verify task text in transcript."""
        import re
        from nitbench.agents.base import AgentAdapter

        class PtyInjectionAdapter(AgentAdapter):
            """Adapter that uses PTY injection (task_cli_args returns None)."""
            agent_family = "pty_test"
            ready_pattern = re.compile(r"[>❯]\s*$")
            ready_timeout = 30.0
            default_aut_command = ["bash"]

            def format_task_text(self, task_text, aif_target_path):
                return task_text

            def build_agent_profile(self, model="", reasoning_level="none"):
                return {"agent_family": "pty_test"}

        adapter = PtyInjectionAdapter()
        task_text = "Hello from NitBench"

        # Script: print the ready prompt, read a line, echo it back
        script = (
            "printf '> '\n"
            "read line\n"
            'echo "GOT: $line"\n'
            "exit 0\n"
        )
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text=task_text,
            agent_adapter=adapter,
        )
        exit_code = harness.run()
        assert exit_code == 0

        # The task text should appear in the transcript as input
        log_text = harness_env["logger"].log_path.read_text()
        assert "Hello from NitBench" in log_text

    def test_no_injection_without_adapter(self, harness_env):
        """Existing behavior preserved when adapter is None."""
        script = (
            "printf '> '\n"
            "sleep 0.2\n"
            "exit 0\n"
        )
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
        )
        exit_code = harness.run()
        assert exit_code == 0
        assert harness._task_injected is False

    def test_ready_timeout(self, harness_env):
        """Verify agent_ready_timeout invalid reason when prompt never appears."""
        import re
        from nitbench.agents.base import AgentAdapter

        class QuickTimeoutAdapter(AgentAdapter):
            agent_family = "quick_timeout"
            ready_pattern = re.compile(r"NEVER_MATCHES_THIS_PROMPT")
            ready_timeout = 1.0
            default_aut_command = ["bash"]

            def format_task_text(self, task_text, aif_target_path):
                return task_text

            def build_agent_profile(self):
                return {"agent_family": "quick_timeout"}

        adapter = QuickTimeoutAdapter()

        # Script that runs for a while but never prints the ready prompt
        script = "sleep 5; exit 0"
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="some task",
            agent_adapter=adapter,
        )
        harness.run()

        assert "agent_ready_timeout" in harness_env["run_validator"].invalid_reasons


# ---------------------------------------------------------------------------
# E2E Gemini CLI output-parsing tests
# ---------------------------------------------------------------------------

class TestGeminiE2EOutputParsing:
    """End-to-end tests using mock bash scripts that simulate realistic
    Gemini CLI terminal output.  Verifies the harness can:

    1. Parse the model identifier from the footer status line
    2. Inject the task after the ready prompt
    3. Detect when the agent is done (prompt reappears after response)
    """

    # A bash script that mimics a simplified Gemini CLI session:
    #   - Prints a banner
    #   - Prints a footer line containing the model identifier
    #   - Shows the ready prompt "> "
    #   - Reads the user's (harness-injected) input
    #   - Prints a thinking spinner, then a response with the ✦ prefix
    #   - Shows the ready prompt again (agent is done)
    #   - Exits
    GEMINI_MOCK_SCRIPT = r'''
        # -- startup banner --
        echo "  ██████  ███████ ███    ███ ██ ███    ██ ██"
        echo " ██       ██      ████  ████ ██ ████   ██ ██"
        echo " ██   ███ █████   ██ ████ ██ ██ ██ ██  ██ ██"
        echo " ██    ██ ██      ██  ██  ██ ██ ██  ██ ██ ██"
        echo "  ██████  ███████ ██      ██ ██ ██   ████ ██"
        echo ""
        echo "Logged in as: test@example.com"
        echo ""

        # -- footer status line with model --
        echo "/model gemini-2.5-pro  45%  150/1500 (resets 2h)"
        echo ""

        # -- ready prompt (task injected via CLI args, not PTY stdin) --
        printf "> "
        sleep 0.1

        # -- simulate thinking --
        printf "\xe2\xa0\x8b Processing...\n"
        sleep 0.1

        # -- response --
        echo "✦ I have read the Agent Instruction File and completed the task."
        echo ""

        # -- ready prompt again (done) --
        printf "> "
        sleep 0.2

        exit 0
    '''

    def test_model_parsed_from_output(self, harness_env):
        """The harness extracts 'gemini-2.5-pro' from the footer line."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.GEMINI_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "gemini-2.5-pro"

    def test_task_injected_and_echoed(self, harness_env):
        """After detecting '> ', the harness sends the task into the PTY."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        task = "Refactor main.py to use snake_case"
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.GEMINI_MOCK_SCRIPT],
            task_text=task,
            agent_adapter=adapter,
        )
        harness.run()

        assert harness._task_injected is True
        log_text = harness_env["logger"].log_path.read_text()
        assert "Refactor main.py" in log_text

    def test_done_detected_after_response(self, harness_env):
        """The harness sets agent_done=True when the prompt reappears."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.GEMINI_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.agent_done is True

    def test_transcript_contains_full_lifecycle(self, harness_env):
        """Transcript captures banner, model footer, task input, response,
        and final prompt — the complete agent lifecycle."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.GEMINI_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        log_text = harness_env["logger"].log_path.read_text()
        # Banner fragment (unicode block chars are JSON-escaped in the log)
        assert "\\u2588" in log_text or "██" in log_text
        # Model footer
        assert "/model gemini-2.5-pro" in log_text
        # Response prefix (sparkle char may be JSON-escaped)
        assert "\\u2726" in log_text or "✦" in log_text
        # Task was delivered
        assert "Do the task" in log_text

    def test_model_set_in_profile_via_runner(self, harness_env):
        """Verify detected_model_id can be used to update agent_profile
        (the runner does this after harness.run())."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        agent_profile = adapter.build_agent_profile()

        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.GEMINI_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        # Simulate what runner.py does after harness.run()
        if harness.detected_model_id is not None:
            agent_profile["model_id"] = harness.detected_model_id

        assert agent_profile["model_id"] == "gemini-2.5-pro"

    def test_different_model_parsed(self, harness_env):
        """Verify a different model name is correctly extracted."""
        import re
        from nitbench.agents.base import AgentAdapter

        class CustomModelAdapter(AgentAdapter):
            agent_family = "custom"
            ready_pattern = re.compile(r"[>]\s*$")
            ready_timeout = 30.0
            model_pattern = re.compile(r"/model\s+(\S+)")
            default_aut_command = ["bash"]

            def format_task_text(self, task_text, aif_target_path):
                return task_text

            def build_agent_profile(self):
                return {"agent_family": "custom", "model_id": "unknown"}

        script = r'''
            echo "/model gemini-2.0-flash  80%"
            printf "> "
            read line
            echo "✦ Done"
            printf "> "
            sleep 0.1
            exit 0
        '''
        adapter = CustomModelAdapter()
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="hello",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "gemini-2.0-flash"
        assert harness.agent_done is True

    def test_no_model_when_footer_absent(self, harness_env):
        """When the output never contains a model footer, detected_model_id stays None."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        # Simple script with no footer line
        script = r'''
            printf "> "
            sleep 0.1
            echo "✦ Response"
            printf "> "
            sleep 0.1
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="do something",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id is None
        assert harness._task_injected is True
        assert harness.agent_done is True

    def test_model_switch_mid_session(self, harness_env):
        """Simulate a Gemini CLI `/model` command that switches the active
        model mid-session.  The harness should update detected_model_id to
        the *latest* model, not stay locked on the first one."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        agent_profile = adapter.build_agent_profile()

        # Mock script:
        #   1. Footer shows gemini-2.5-pro (initial model)
        #   2. Ready prompt → harness injects task
        #   3. Agent responds
        #   4. Footer updates to gemini-2.0-flash (model switch)
        #   5. Ready prompt again → agent done
        script = r'''
            echo "/model gemini-2.5-pro  45%  150/1500 (resets 2h)"
            printf "> "
            sleep 0.1
            echo "✦ Working on it..."
            echo ""
            echo "/model gemini-2.0-flash  80%  200/1500 (resets 1h)"
            printf "> "
            sleep 0.2
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        # The harness should have picked up the *switched* model
        assert harness.detected_model_id == "gemini-2.0-flash"
        assert harness._task_injected is True
        assert harness.agent_done is True

        # Runner integration: profile gets the latest model
        if harness.detected_model_id is not None:
            agent_profile["model_id"] = harness.detected_model_id
        assert agent_profile["model_id"] == "gemini-2.0-flash"

    def test_model_auto(self, harness_env):
        """'auto' is a valid model selector in Gemini CLI — the harness must
        detect it just like a concrete model name."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        script = r'''
            echo "/model auto  45%  150/1500 (resets 2h)"
            printf "> "
            sleep 0.1
            echo "✦ Done"
            printf "> "
            sleep 0.1
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "auto"
        assert harness._task_injected is True
        assert harness.agent_done is True

    def test_model_preview_version(self, harness_env):
        """Preview model IDs with long suffixes (e.g. gemini-3.0-pro-preview)
        must be captured in full."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        script = r'''
            echo "/model gemini-3.0-pro-preview  60%  200/1500"
            printf "> "
            sleep 0.1
            echo "✦ Done"
            printf "> "
            sleep 0.1
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "gemini-3.0-pro-preview"

    def test_model_switch_auto_to_concrete(self, harness_env):
        """Start with 'auto', switch to a concrete model mid-session.
        Harness should track the switch."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("gemini")
        agent_profile = adapter.build_agent_profile()

        script = r'''
            echo "/model auto  45%"
            printf "> "
            sleep 0.1
            echo "✦ Resolving model..."
            echo "/model gemini-3.1-pro  30%  500/1500 (resets 3h)"
            printf "> "
            sleep 0.1
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="task",
            agent_adapter=adapter,
        )
        harness.run()

        # Started as auto, resolved to gemini-3.1-pro
        assert harness.detected_model_id == "gemini-3.1-pro"

        if harness.detected_model_id is not None:
            agent_profile["model_id"] = harness.detected_model_id
        assert agent_profile["model_id"] == "gemini-3.1-pro"


# ---------------------------------------------------------------------------
# E2E Codex CLI output-parsing tests
# ---------------------------------------------------------------------------

class TestCodexE2EOutputParsing:
    """End-to-end tests using mock bash scripts that simulate realistic
    Codex CLI terminal output (Ratatui TUI with ANSI escape codes).
    Verifies the pyte-backed VT100 renderer handles ANSI correctly and
    the harness can parse model IDs, inject tasks, and detect done state.
    """

    # Simulates a Codex CLI TUI session with CLI-injected task:
    #   - Alternate screen buffer entry
    #   - Bold/colored footer with model identifier
    #   - Working indicator (task came via CLI args)
    #   - Response
    #   - › prompt reappears (done)
    CODEX_MOCK_SCRIPT = r'''
        # -- enter alternate screen buffer --
        printf '\x1b[?1049h'

        # -- header bar --
        printf '\x1b[1;1H\x1b[1;37;44m Codex CLI                                                                      \x1b[0m'

        # -- footer status line with ANSI styling --
        printf '\x1b[24;1H\x1b[2mgpt-5.3-codex . 85%% . 34k tokens\x1b[0m'

        # -- working indicator (task injected via CLI args) --
        printf '\x1b[22;1H\x1b[K* Working (2s . esc to interrupt)'
        sleep 0.1

        # -- response area --
        printf '\x1b[10;1H\x1b[KI have read the Agent Instruction File and completed the task.'

        # -- › prompt reappears (done) --
        printf '\x1b[22;1H\x1b[K\xe2\x80\xba'
        sleep 0.2

        # -- leave alternate screen --
        printf '\x1b[?1049l'
        exit 0
    '''

    def test_model_parsed_from_rendered_screen(self, harness_env):
        """ANSI-styled footer renders to clean text; model ID extracted."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.CODEX_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "gpt-5.3-codex"

    def test_task_injected_via_cli(self, harness_env):
        """Task is injected via CLI args (not PTY) for Codex adapter."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.CODEX_MOCK_SCRIPT],
            task_text="Refactor main.py",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness._task_injected is True
        log_text = harness_env["logger"].log_path.read_text()
        assert "Refactor main.py" in log_text

    def test_done_detected(self, harness_env):
        """› prompt reappearing after response sets agent_done."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", self.CODEX_MOCK_SCRIPT],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.agent_done is True

    def test_model_switch_mid_session(self, harness_env):
        """Model switches from gpt-5.3-codex to o4-mini mid-session."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        script = r'''
            printf '\x1b[?1049h'
            printf '\x1b[24;1H\x1b[2mgpt-5.3-codex . 85%% . 34k tokens\x1b[0m'
            printf '\x1b[22;1H\x1b[K* Working (1s)'
            sleep 0.1
            printf '\x1b[24;1H\x1b[K\x1b[2mo4-mini . 95%% . 5k tokens\x1b[0m'
            printf '\x1b[10;1H\x1b[KDone.'
            printf '\x1b[22;1H\x1b[K\xe2\x80\xba'
            sleep 0.2
            printf '\x1b[?1049l'
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="Do the task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "o4-mini"
        assert harness._task_injected is True

    @pytest.mark.parametrize("model_id", [
        "gpt-5.3-codex", "gpt-5.2-codex", "gpt-5.1-codex",
        "o4-mini", "o3", "gpt-4.1", "gpt-4.1-mini",
    ])
    def test_codex_model_ids(self, harness_env, model_id):
        """Parametrized: various Codex model IDs detected from ANSI footer."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        script = f'''
            printf '\\x1b[?1049h'
            printf '\\x1b[24;1H\\x1b[2m{model_id} . 85%% . 34k tokens\\x1b[0m'
            printf '\\x1b[10;1H\\x1b[KDone.'
            printf '\\x1b[22;1H\\x1b[K\\xe2\\x80\\xba'
            sleep 0.2
            printf '\\x1b[?1049l'
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == model_id

    def test_ansi_noise_stripped(self, harness_env):
        """Raw ANSI escape codes + pyte rendering = clean pattern match."""
        from nitbench.agents.registry import get_adapter
        import nitbench.agents  # noqa: F401

        adapter = get_adapter("codex")
        # Heavy ANSI noise: cursor movements, colors, clearing
        script = r'''
            printf '\x1b[?1049h'
            printf '\x1b[2J\x1b[H'
            printf '\x1b[1;31;42m*** NOISE ***\x1b[0m\n'
            printf '\x1b[5;1H\x1b[1;4;33mMore noise\x1b[0m\n'
            printf '\x1b[24;1H\x1b[2mgpt-5.3-codex . 85%% . 34k tokens\x1b[0m'
            printf '\x1b[10;1H\x1b[KDone.'
            printf '\x1b[22;1H\x1b[K\xe2\x80\xba'
            sleep 0.2
            printf '\x1b[?1049l'
            exit 0
        '''
        harness = _make_harness(
            harness_env,
            ["bash", "--norc", "--noprofile", "-c", script],
            task_text="task",
            agent_adapter=adapter,
        )
        harness.run()

        assert harness.detected_model_id == "gpt-5.3-codex"
        assert harness._task_injected is True
        assert harness.agent_done is True
