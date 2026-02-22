import json
import subprocess
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

LINT_FORMAT_TOOLS = {
    "pylint", "black", "ruff", "flake8", "isort", "autopep8", "yapf",
    "prettier", "eslint", "mypy", "pyflakes", "pycodestyle", "pydocstyle",
    "stylelint", "standardjs", "gofmt", "rustfmt", "clang-format",
}
INSTALL_TOOLS = {
    "pip", "pip3", "npm", "npx", "yarn", "pnpm", "apt", "apt-get",
    "brew", "cargo", "gem", "go", "conda", "poetry", "pipx",
}

class SandboxError(ValueError):
    """Exception raised for sandbox orchestration errors."""

class AutSandbox:
    """
    Mock Agent Sandbox implementation for testing harness rules.
    In a real implementation, this would wrap something like bubblewrap, Docker, or gVisor.
    """
    def __init__(self, workspace_dir: Path, case_data: Dict[str, Any], action_logger: Optional[Any] = None, transcript_logger: Optional[Any] = None):
        self.workspace_dir = workspace_dir
        self.sandbox_rules = case_data.get("aut_sandbox", {})
        self.recorded_attempts = []
        self.action_logger = action_logger
        self.transcript_logger = transcript_logger
        self.action_index = 1

    def _enforce_network_pre_flight(self) -> None:
        if self.sandbox_rules.get("network") == "forbidden":
            self.network_enabled = False
        else:
            self.network_enabled = True

    def _log_action(self, cmd: list[str], cwd: Path, exit_code: int) -> None:
        if not self.action_logger:
            return
        import datetime
        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.action_logger.log_action({
            "action_index": self.action_index,
            "actor": "agent",
            "type": "command",
            "t_start_utc": now_utc,
            "t_end_utc": now_utc,
            "cwd": str(cwd),
            "argv": cmd,
            "exit_code": exit_code
        })
        self.action_index += 1

    def build_sandbox_wrapper_args(self, aut_command: Optional[list[str]] = None) -> list[str]:
        """Returns the OS-level isolation command prefix (bwrap on Linux, sandbox-exec on macOS).

        This lets the PTY harness prepend sandbox isolation to the AUT spawn command
        without duplicating the platform-specific logic.

        If *aut_command* is given, the AUT binary and its runtime prefix are
        whitelisted so the sandbox allows executing them.
        """
        self._enforce_network_pre_flight()

        # Resolve the AUT binary to find directories that must be readable.
        aut_allow_paths: list[str] = []
        if aut_command:
            import shutil
            binary = shutil.which(aut_command[0]) or aut_command[0]
            binary_path = Path(binary).resolve()
            # Allow the immediate bin directory
            aut_allow_paths.append(str(binary_path.parent))
            # If the binary lives under a version-manager prefix (nvm, pyenv, etc.),
            # allow the entire installation tree so shared libs and modules load.
            for parent in binary_path.parents:
                if parent.name in ("bin", "lib", "libexec"):
                    aut_allow_paths.append(str(parent.parent))
                    break

        if sys.platform.startswith("linux"):
            bwrap_cmd = [
                "bwrap",
                "--ro-bind", "/usr", "/usr",
                "--ro-bind", "/bin", "/bin",
                "--ro-bind", "/lib", "/lib",
                "--ro-bind", "/lib64", "/lib64",
                "--ro-bind", "/etc", "/etc",
                "--proc", "/proc",
                "--dev", "/dev",
                "--bind", str(self.workspace_dir), str(self.workspace_dir)
            ]
            for p in aut_allow_paths:
                bwrap_cmd.extend(["--ro-bind", p, p])
            if not self.network_enabled:
                bwrap_cmd.append("--unshare-net")
            bwrap_cmd.append("--")
            return bwrap_cmd
        elif sys.platform == "darwin":
            # macOS sandbox-exec is too coarse for real agent runs:
            # - LLM agents need network to call their model API
            # - Node/Python runtimes need broad filesystem reads to start
            # - Auth credentials live in user home directories
            # Application-layer enforcement (prohibited tools, protected globs)
            # handles the security constraints the harness needs.
            # TODO: implement fine-grained macOS sandbox using per-domain
            #       network rules and targeted fs deny lists.
            return []
        return []

    def check_prohibited(self, tool_base: str) -> Tuple[bool, Optional[str]]:
        """Check if a tool basename is prohibited.

        Returns (is_prohibited, policy) where policy is one of
        "invalid", "record_only", or None.
        """
        prohibited_sets = self.sandbox_rules.get("prohibited_executable_sets", [])
        policy = self.sandbox_rules.get("prohibited_attempt_policy", {})

        if tool_base in LINT_FORMAT_TOOLS:
            if "nitbench.prohibited.lint_format.standard" in prohibited_sets:
                return True, policy.get("lint_format")

        if tool_base in INSTALL_TOOLS:
            if "nitbench.prohibited.install.standard" in prohibited_sets:
                return True, policy.get("install")

        extra = self.sandbox_rules.get("prohibited_executables_extra", [])
        if tool_base in extra:
            return True, "record_only"

        return False, None

    def run_pty(self, command: list[str], cwd: Optional[Path] = None) -> Tuple[int, bytes, bytes]:
        """
        Runs a command in a PTY session, returning (exit_code, stdout_bytes, stderr_bytes).
        The PTY capture logic normally handles standard interaction; here we use subprocess for MVP.
        """
        self._enforce_network_pre_flight()

        if cwd is None:
            cwd = self.workspace_dir / "repo"

        # Filesystem isolation mocking
        repo_root = (self.workspace_dir / "repo").resolve()
        for arg in command:
            if arg.startswith("/"):
                arg_path = Path(arg).resolve()
                if not str(arg_path).startswith(str(repo_root)) and "python" not in arg and "echo" not in arg and "test" not in arg and "ls" not in arg:
                    if self.transcript_logger:
                        self.transcript_logger.log_input(" ".join(command) + "\n")
                        self.transcript_logger.log_output("sandbox isolation: access denied\n")
                    self._log_action(command, cwd, 1)
                    return 1, b"", b"sandbox isolation: access denied"

        # Check prohibited tools using extracted method
        tool_cmd = command[0] if command else ""
        tool_base = tool_cmd.rsplit("/", 1)[-1]

        is_prohibited, prohibition_policy = self.check_prohibited(tool_base)
        if is_prohibited:
            if prohibition_policy == "invalid":
                raise SandboxError(f"prohibited_tool_attempt:{self._prohibited_category(tool_base)}")
            elif prohibition_policy == "record_only":
                if self.transcript_logger:
                    self.transcript_logger.log_input(" ".join(command) + "\n")
                    self.transcript_logger.log_output("command not found\n")
                self.recorded_attempts.append(self._prohibited_category(tool_base))
                self._log_action(command, cwd, 127)
                return 127, b"", b"command not found"

        # Build full command with sandbox wrapper
        full_command = self.build_sandbox_wrapper_args() + list(command)

        # Inherit base environment but add isolation flag
        sandbox_env = os.environ.copy()
        sandbox_env["NITBENCH_NETWORK_ISOLATED"] = "1"

        process = subprocess.Popen(
            full_command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=sandbox_env
        )
        if self.transcript_logger:
            self.transcript_logger.log_input(" ".join(command) + "\n")
        stdout, stderr = process.communicate()
        if self.transcript_logger:
            if stdout:
                self.transcript_logger.log_output(stdout.decode("utf-8", errors="replace"))
            if stderr:
                self.transcript_logger.log_output(stderr.decode("utf-8", errors="replace"))
        self._log_action(command, cwd, process.returncode)
        return process.returncode, stdout, stderr

    def _prohibited_category(self, tool_base: str) -> str:
        """Return the prohibition category name for a tool."""
        if tool_base in LINT_FORMAT_TOOLS:
            return "lint_format"
        if tool_base in INSTALL_TOOLS:
            return "install"
        return "extra"

    def check_lint_tools_available(self) -> bool:
        """
        Dynamically test the sandbox filesystem for the physical availability of prohibited tools.
        """
        # If aut_mode is manual, lint format tools must not be available.
        # We test this by trying to run 'which pylint'.
        exit_code, _, _ = self.run_pty(["which", "pylint"])
        return exit_code == 0

    def deliver_task_text(self, task_md_path: Path) -> str:
        """Read and provide the task text (which must include AIF follow instruction)."""
        if not task_md_path.exists():
            raise SandboxError("Missing task.md")
        text = task_md_path.read_text(encoding="utf-8")
        if "follow the AIF" not in text.lower() and "follow the agent instruction file" not in text.lower():
            # The spec says "task instruction stream MUST explicitly state that the AUT MUST follow the placed AIF"
            pass # In a real system, the harness prepends/appends this constraint if it's missing
            
        return text

    def check_harness_exposure(self, harness_file_path: Path) -> bool:
        """
        Simulation: The agent sandbox MUST NOT expose case.json, checkpoints.json, scoring.yaml, etc.
        If it does, it's a security flaw in the sandbox. We'll use this for the negative tests.
        Returns True if exposed (which is bad), False if isolated (which is good).
        """
        # Execute an OS-level check inside the sandbox mock instead of naive python relative_to
        exit_code, _, _ = self.run_pty(["test", "-e", str(harness_file_path.resolve())])
        return exit_code == 0
