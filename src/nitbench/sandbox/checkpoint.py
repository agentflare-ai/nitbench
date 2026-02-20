from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil
import hashlib

from nitbench.sandbox.orchestrator import TranscriptLogger

class ContextProxyTracker:
    def __init__(self, proxy_type: str):
        valid_types = {"agent_action_count", "commit_count", "diff_loc", "checkpoint_index"}
        if proxy_type not in valid_types:
            raise ValueError(f"Invalid context proxy type: {proxy_type}")
        self.proxy_type = proxy_type
        self.value = 0
        
    def advance(self, amount: int = 1) -> None:
        self.value += amount

class CheckpointManager:
    def __init__(self, checkpoints_def: Dict[str, Any], workspace_repo: Path, harness_artifacts: Path, logger: TranscriptLogger):
        self.checkpoints_def = checkpoints_def
        self.workspace_repo = workspace_repo
        self.harness_artifacts = harness_artifacts
        self.logger = logger
        
        proxy_type = checkpoints_def.get("context_proxy", {}).get("type", "checkpoint_index")
        self.tracker = ContextProxyTracker(proxy_type)
        self.checkpoints = checkpoints_def.get("checkpoints", [])
        self.executed_checkpoints: List[str] = []
        self.hashes: List[Dict[str, str]] = []
        
    def _freeze_snapshot(self, checkpoint_id: str) -> None:
        """Freezes the repo state into the harness artifacts directory."""
        snapshot_dir = self.harness_artifacts / "checkpoints" / checkpoint_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        repo_copy = snapshot_dir / "repo"
        if repo_copy.exists():
            shutil.rmtree(repo_copy)
            
        shutil.copytree(self.workspace_repo, repo_copy, symlinks=True)
        
        # Calculate SHA256 of the frozen repo state
        hasher = hashlib.sha256()
        paths = sorted([p for p in repo_copy.rglob("*") if p.is_file()])
        for p in paths:
            rel_path = p.relative_to(repo_copy).as_posix()
            hasher.update(rel_path.encode("utf-8"))
            hasher.update(p.read_bytes())
            
        repo_state_sha256 = hasher.hexdigest()
        self.hashes.append({
            "checkpoint_id": checkpoint_id,
            "repo_state_sha256": repo_state_sha256
        })

    def trigger_if_needed(self, trigger_type: str, current_value: Optional[int] = None) -> None:
        """
        Evaluates triggers (at_proxy_value, end_of_run) against the current proxy state.
        Executes snapshot, marker emission, and hashing if triggered.
        """
        val = current_value if current_value is not None else self.tracker.value
        
        for cp in self.checkpoints:
            cp_id = cp.get("id")
            if cp_id in self.executed_checkpoints:
                continue
                
            trigger = cp.get("trigger", {})
            t_type = trigger.get("type")
            t_val = trigger.get("value")
            
            if t_type == trigger_type:
                if t_type == "at_proxy_value" and val >= t_val:
                    self._execute_checkpoint(cp_id, val)
                elif t_type == "end_of_run":
                    self._execute_checkpoint(cp_id, val)

    def _execute_checkpoint(self, checkpoint_id: str, proxy_value: int) -> None:
        """Internal execution of a single checkpoint."""
        self._freeze_snapshot(checkpoint_id)
        
        self.logger.log_marker({
            "type": "checkpoint",
            "checkpoint_id": checkpoint_id,
            "proxy_value": proxy_value
        })
        
        self.executed_checkpoints.append(checkpoint_id)
