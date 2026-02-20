import json
import subprocess
import os
import pty
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

class SandboxError(ValueError):
    """Exception raised for sandbox orchestration errors."""

class AutSandbox:
    """
    Mock Agent Sandbox implementation for testing harness rules.
    In a real implementation, this would wrap something like bubblewrap, Docker, or gVisor.
    """
    def __init__(self, workspace_dir: Path, case_data: Dict[str, Any]):
        self.workspace_dir = workspace_dir
        self.sandbox_rules = case_data.get("aut_sandbox", {})
        
    def _enforce_network_pre_flight(self) -> None:
        if self.sandbox_rules.get("network") == "forbidden":
            # Just an enforcement flag setup in mock
            self.network_enabled = False
        else:
            self.network_enabled = True

    def run_pty(self, command: list[str], cwd: Optional[Path] = None) -> Tuple[int, bytes, bytes]:
        """
        Runs a command in a PTY session, returning (exit_code, stdout_bytes, stderr_bytes).
        The PTY capture logic normally handles standard interaction; here we use subprocess for MVP.
        """
        self._enforce_network_pre_flight()
        
        # Check prohibited sets (simplified static check before run)
        prohibited_sets = self.sandbox_rules.get("prohibited_executable_sets", [])
        policy = self.sandbox_rules.get("prohibited_attempt_policy", {})
        
        # In a real sandboxing env, we wouldn't mount or we'd block via seccomp/LSM.
        # If aut_mode is manual, lint/format tools shouldn't be runnable.
        tool_cmd = command[0] if command else ""
        if "pylint" in tool_cmd or "black" in tool_cmd:
            if "nitbench.prohibited.lint_format.standard" in prohibited_sets:
                if policy.get("lint_format") == "invalid":
                    raise SandboxError("prohibited_tool_attempt:lint_format")

        if cwd is None:
            cwd = self.workspace_dir / "repo"

        # PTY setup simulation
        # Using subprocess for now, a full harness uses `pty.fork()` or `pmexpect`.
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Pass env with no network access flags (mocking it)
            env={"NITBENCH_NETWORK_ISOLATED": "1"}
        )
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr

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
        # In the real tool, the harness isn't passing absolute paths of its own secrets to the container.
        # So inside the container, `os.path.exists(harness_file_path)` would be False.
        # We mock this by simply enforcing that the path isn't within the allowed workspace mounts.
        try:
            harness_file_path.relative_to(self.workspace_dir)
            return True # Exposed if we put it inside the workspace
        except ValueError:
            return False # Isolated if it's outside
