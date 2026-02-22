"""Interactive PTY harness for NitBench (Spec §4.2, §11, §14).

Spawns the AUT inside the sandbox via pexpect, captures transcript I/O,
detects agent actions from PTY output, advances the context proxy, triggers
checkpoints (with SIGSTOP/SIGCONT pausing for atomic snapshots), and enforces
budgets.
"""

import os
import re
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import pexpect

from nitbench.agents.base import AgentAdapter
from nitbench.sandbox.checkpoint import CheckpointManager
from nitbench.sandbox.environment import AutSandbox, SandboxError
from nitbench.sandbox.orchestrator import ActionLogger, BudgetEnforcer, TranscriptLogger
from nitbench.sandbox.validator import RunValidator


# ---------------------------------------------------------------------------
# CommandDetector
# ---------------------------------------------------------------------------

# Strip ANSI escape sequences before prompt matching.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07")

# Matches common shell prompts followed by a command.
# Requires prompt character ($, #, or %) near line start — NOT > because
# TUI agents (Gemini, Codex) render > as their input prompt constantly.
_PROMPT_RE = re.compile(
    r"^"                  # start of line
    r"[^\n]{0,40}?"       # optional username/path prefix (max 40 chars)
    r"[\$#%]\s+"          # prompt character followed by whitespace
    r"(\S+)",             # first token = command name
    re.MULTILINE,
)


class CommandDetector:
    """Heuristic detector that identifies shell command executions from raw PTY output."""

    def detect(self, line: str) -> Optional[str]:
        """Return the tool basename if *line* looks like a shell command, else None."""
        # Strip ANSI escape sequences to avoid false matches on TUI output
        clean = _ANSI_RE.sub("", line).strip()
        if not clean or len(clean) < 3:
            return None
        m = _PROMPT_RE.search(clean)
        if m is None:
            return None
        raw = m.group(1)
        # Strip absolute path to get the basename
        return raw.rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# ProxyComputer
# ---------------------------------------------------------------------------

class ProxyComputer:
    """Computes context proxy values based on the configured proxy type."""

    def __init__(self, proxy_type: str, workspace_repo: Path):
        self.proxy_type = proxy_type
        self.workspace_repo = workspace_repo
        self._action_count = 0
        self._checkpoint_count = 0

    def update(self, detected_command: Optional[str] = None) -> int:
        """Return the current proxy value, advancing if needed."""
        if self.proxy_type == "agent_action_count":
            if detected_command is not None:
                self._action_count += 1
            return self._action_count

        if self.proxy_type == "commit_count":
            return self._poll_commit_count()

        if self.proxy_type == "diff_loc":
            return self._poll_diff_loc()

        if self.proxy_type == "checkpoint_index":
            return self._checkpoint_count

        return 0

    def advance_checkpoint_index(self) -> None:
        self._checkpoint_count += 1

    # -- git polling helpers --------------------------------------------------

    def _poll_commit_count(self) -> int:
        try:
            out = subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=str(self.workspace_repo),
                stderr=subprocess.DEVNULL,
                text=True,
            )
            return int(out.strip())
        except Exception:
            return 0

    def _poll_diff_loc(self) -> int:
        try:
            out = subprocess.check_output(
                ["git", "diff", "--stat"],
                cwd=str(self.workspace_repo),
                stderr=subprocess.DEVNULL,
                text=True,
            )
            # Last line of --stat looks like: " 3 files changed, 10 insertions(+), 2 deletions(-)"
            for line in reversed(out.strip().splitlines()):
                nums = re.findall(r"(\d+)\s+(?:insertion|deletion)", line)
                if nums:
                    return sum(int(n) for n in nums)
            return 0
        except Exception:
            return 0


# ---------------------------------------------------------------------------
# InteractivePtyHarness
# ---------------------------------------------------------------------------

class InteractivePtyHarness:
    """Main PTY event loop that runs the AUT inside the sandbox."""

    COLS = 80
    ROWS = 24
    READ_TIMEOUT = 0.5  # seconds between pexpect reads

    def __init__(
        self,
        aut_command: list[str],
        sandbox: AutSandbox,
        workspace_repo: Path,
        logger: TranscriptLogger,
        action_logger: ActionLogger,
        budget_enforcer: BudgetEnforcer,
        checkpoint_mgr: CheckpointManager,
        run_validator: RunValidator,
        task_text: Optional[str] = None,
        agent_adapter: Optional[AgentAdapter] = None,
    ):
        self.aut_command = aut_command
        self.sandbox = sandbox
        self.workspace_repo = workspace_repo
        self.logger = logger
        self.action_logger = action_logger
        self.budget_enforcer = budget_enforcer
        self.checkpoint_mgr = checkpoint_mgr
        self.run_validator = run_validator
        self.task_text = task_text
        self.agent_adapter = agent_adapter
        self._detector = CommandDetector()
        self._task_injected = False
        self._cli_injected = False  # True when task was injected via CLI args (not PTY)
        self.detected_model_id: Optional[str] = None
        self.agent_done = False
        self.aif_read_count: int = 0
        self._aif_pattern: Optional[re.Pattern] = None

        # Universal VT100 screen renderer — all adapters use it
        self._renderer = agent_adapter.create_renderer() if agent_adapter else None

        proxy_type = checkpoint_mgr.checkpoints_def.get("context_proxy", {}).get("type", "checkpoint_index")
        self._proxy = ProxyComputer(proxy_type, workspace_repo)

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def run(self) -> int:
        """Spawn the AUT, run the event loop, return the AUT exit code."""
        wrapper = self.sandbox.build_sandbox_wrapper_args(aut_command=self.aut_command)
        full_cmd = wrapper + self.aut_command

        # CLI-based task injection: append adapter args to the command
        if self.agent_adapter is not None and self.task_text is not None:
            aif_target = self._detect_aif_target()
            # Compile AIF read-detection pattern for this adapter
            if aif_target:
                self._aif_pattern = self.agent_adapter.aif_read_pattern(Path(aif_target).name)
            cli_args = self.agent_adapter.task_cli_args(self.task_text, aif_target)
            if cli_args is not None:
                full_cmd = full_cmd + cli_args
                formatted = self.agent_adapter.format_task_text(self.task_text, aif_target)
                self.logger.log_input(formatted + "\n")
                self._task_injected = True  # skip PTY injection
                self._cli_injected = True   # no idle timeout — wait for process exit

        self._spawn_time = time.monotonic()

        child = pexpect.spawn(
            full_cmd[0],
            args=full_cmd[1:],
            cwd=str(self.workspace_repo),
            encoding=None,  # raw bytes
            timeout=self.READ_TIMEOUT,
        )
        child.setwinsize(self.ROWS, self.COLS)
        self.logger.log_resize(self.COLS, self.ROWS)

        exit_code = self._event_loop(child)

        # End-of-run checkpoint
        self.checkpoint_mgr.trigger_if_needed("end_of_run")

        return exit_code

    # --------------------------------------------------------------------- #
    # Event loop internals
    # --------------------------------------------------------------------- #

    DONE_IDLE_TIMEOUT = 10.0  # seconds of inactivity after agent_done before terminating

    def _event_loop(self, child: pexpect.spawn) -> int:
        buf = b""
        action_index = 1
        done_since: Optional[float] = None  # monotonic time when agent_done was first set
        last_output_time = time.monotonic()

        while child.isalive():
            # -- budget: wall time -----------------------------------------
            self.budget_enforcer.check_wall_time()
            if self.budget_enforcer.is_invalid:
                self._terminate(child)
                break

            # -- read PTY output -------------------------------------------
            try:
                chunk = child.read_nonblocking(size=4096, timeout=self.READ_TIMEOUT)
            except pexpect.TIMEOUT:
                # Check ready timeout on idle reads
                if not self._task_injected and self.agent_adapter is not None:
                    elapsed = time.monotonic() - self._spawn_time
                    if elapsed > self.agent_adapter.ready_timeout:
                        self.run_validator.invalid_reasons.append("agent_ready_timeout")
                        self._terminate(child)
                        break
                # Agent finished and idle — terminate after grace period
                if self.agent_done:
                    if done_since is None:
                        done_since = time.monotonic()
                    elif time.monotonic() - done_since > self.DONE_IDLE_TIMEOUT:
                        self._terminate(child)
                        break
                # Idle timeout: no output for too long after task injection.
                # Applies to both PTY-injected and CLI-injected agents.
                # Headless agents (e.g. Claude -p) exit via EOF before this fires.
                # TUI agents (e.g. Codex --full-auto) may sit at their prompt
                # after completion, producing only cursor blink noise.
                elif self._task_injected and self.agent_adapter is not None:
                    idle_elapsed = time.monotonic() - last_output_time
                    if idle_elapsed > self.agent_adapter.idle_timeout:
                        # Log screen state for diagnostics before terminating
                        if self._renderer is not None:
                            screen_state = self._renderer.display()
                            self.logger.log_marker({
                                "type": "idle_timeout",
                                "idle_seconds": round(idle_elapsed, 1),
                                "screen_state": screen_state,
                            })
                        # CLI-injected TUI agents (e.g. Codex) idle-out after
                        # completing work — this is expected, not an error.
                        if not self._cli_injected:
                            self.run_validator.invalid_reasons.append("agent_idle_timeout")
                        self._terminate(child)
                        break
                continue
            except pexpect.EOF:
                break

            if not chunk:
                continue

            # New output received — reset idle timers
            done_since = None
            last_output_time = time.monotonic()

            # Log raw output bytes
            text = chunk.decode("utf-8", errors="replace")
            self.logger.log_output(text)

            # AIF read detection: scan new output chunk for file-read tool calls
            if self._aif_pattern is not None and self._aif_pattern.search(text):
                self.aif_read_count += 1
                self.logger.log_marker({
                    "type": "aif_read",
                    "aif_read_count": self.aif_read_count,
                })

            # Feed output to renderer (stateful — accumulates all output)
            if self._renderer is not None:
                self._renderer.feed(text)

            # Get rendered screen text for pattern matching
            screen_text = self._renderer.display() if self._renderer else text

            # Model detection: scan rendered screen for model identifier.
            # Always update — the agent may switch models mid-session
            # (e.g. Gemini CLI `/model` command, Codex footer change).
            if self.agent_adapter is not None:
                parsed = self.agent_adapter.parse_model_from_output(screen_text)
                if parsed is not None:
                    self.detected_model_id = parsed

            # Task injection: check rendered screen for ready pattern
            if not self._task_injected:
                self._maybe_inject_task(child, screen_text)
            elif not self.agent_done and self.agent_adapter is not None:
                # After task injection, detect when agent is done responding
                done_pat = self.agent_adapter.done_pattern or self.agent_adapter.ready_pattern
                if done_pat.search(screen_text):
                    self.agent_done = True

            # Accumulate into line buffer for command detection
            buf += chunk
            lines = buf.split(b"\n")
            buf = lines.pop()  # keep incomplete trailing line

            for raw_line in lines:
                line_str = raw_line.decode("utf-8", errors="replace")
                cmd = self._detector.detect(line_str)
                if cmd is None:
                    continue

                # -- detected command --------------------------------------
                self._log_detected_action(cmd, action_index)
                action_index += 1

                self.budget_enforcer.record_action()

                # Prohibited tool check
                is_prohibited, policy = self.sandbox.check_prohibited(cmd)
                if is_prohibited:
                    if policy == "invalid":
                        self.run_validator.invalid_reasons.append(
                            f"prohibited_tool_attempt:{self.sandbox._prohibited_category(cmd)}"
                        )
                    elif policy == "record_only":
                        self.sandbox.recorded_attempts.append(
                            self.sandbox._prohibited_category(cmd)
                        )

                # Advance proxy
                proxy_val = self._proxy.update(detected_command=cmd)

                # Checkpoint trigger (with SIGSTOP/SIGCONT for atomicity)
                self._maybe_checkpoint(child, "at_proxy_value", proxy_val)

                # Re-check budgets after action
                if self.budget_enforcer.is_invalid:
                    self._terminate(child)
                    break

        # Drain remaining output after EOF
        try:
            remaining = child.read_nonblocking(size=65536, timeout=0.1)
            if remaining:
                self.logger.log_output(remaining.decode("utf-8", errors="replace"))
        except (pexpect.TIMEOUT, pexpect.EOF):
            pass

        child.close()
        return child.exitstatus if child.exitstatus is not None else child.status

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def _detect_aif_target(self) -> str:
        """Return the workspace-relative AIF filename, or empty string."""
        for candidate in ("GEMINI.md", "CODEX.md", "CLAUDE.md", "STYLE.md", "AIF.md"):
            if (self.workspace_repo / candidate).exists():
                return candidate
        return ""

    def _maybe_inject_task(self, child: pexpect.spawn, screen_text: str) -> None:
        """Send task text into the PTY once the agent's ready prompt is detected."""
        if self._task_injected:
            return
        if self.agent_adapter is None or self.task_text is None:
            return

        if not self.agent_adapter.ready_pattern.search(screen_text):
            return

        # Format and send
        aif_target = self._detect_aif_target()
        formatted = self.agent_adapter.format_task_text(self.task_text, aif_target)
        self.logger.log_input(formatted + "\n")
        # Collapse to a single line for TUI agents that use Enter as submit.
        # Use \r (CR) instead of \n (LF) — raw PTY terminals interpret CR as Enter.
        oneline = " ".join(formatted.split())
        child.send(oneline + "\r")
        self._task_injected = True

        # Reset the renderer so the startup prompt (e.g. ❯) doesn't
        # persist in the screen buffer and falsely trigger done_pattern.
        if self._renderer is not None:
            self._renderer.reset()

    def _maybe_checkpoint(self, child: pexpect.spawn, trigger_type: str, proxy_val: int) -> None:
        """Trigger a checkpoint if needed, pausing the AUT with SIGSTOP/SIGCONT."""
        before = len(self.checkpoint_mgr.executed_checkpoints)
        # Peek: would this trigger?  We compare before/after executed list length.
        # To avoid freezing when no checkpoint fires, we SIGSTOP only if one actually triggers.
        # Unfortunately trigger_if_needed is void, so we do the stop/continue unconditionally
        # only when we know a checkpoint *should* fire.

        should_fire = self._checkpoint_would_fire(trigger_type, proxy_val)
        if not should_fire:
            return

        try:
            os.kill(child.pid, signal.SIGSTOP)
        except OSError:
            pass

        self.checkpoint_mgr.trigger_if_needed(trigger_type, proxy_val)

        try:
            os.kill(child.pid, signal.SIGCONT)
        except OSError:
            pass

        after = len(self.checkpoint_mgr.executed_checkpoints)
        if after > before:
            self._proxy.advance_checkpoint_index()

    def _checkpoint_would_fire(self, trigger_type: str, proxy_val: int) -> bool:
        """Return True if at least one un-executed checkpoint matches."""
        for cp in self.checkpoint_mgr.checkpoints:
            cp_id = cp.get("id")
            if cp_id in self.checkpoint_mgr.executed_checkpoints:
                continue
            trigger = cp.get("trigger", {})
            if trigger.get("type") != trigger_type:
                continue
            if trigger_type == "at_proxy_value" and proxy_val >= trigger.get("value", 0):
                return True
            if trigger_type == "end_of_run":
                return True
        return False

    def _log_detected_action(self, cmd: str, action_index: int) -> None:
        import datetime

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.action_logger.log_action({
            "action_index": action_index,
            "actor": "agent",
            "type": "command",
            "t_start_utc": now_utc,
            "t_end_utc": now_utc,
            "cwd": str(self.workspace_repo),
            "argv": [cmd],
            "exit_code": 0,
        })

    @staticmethod
    def _terminate(child: pexpect.spawn) -> None:
        """Send SIGTERM then SIGKILL if needed."""
        if not child.isalive():
            return
        child.terminate(force=False)
        try:
            child.expect(pexpect.EOF, timeout=3)
        except pexpect.TIMEOUT:
            child.terminate(force=True)
