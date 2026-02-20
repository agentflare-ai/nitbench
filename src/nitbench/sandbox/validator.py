import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from nitbench.sandbox.environment import AutSandbox
from nitbench.sandbox.orchestrator import BudgetEnforcer, TranscriptLogger

class RunValidator:
    """
    Handles run invalidation logic, tamper detection, and hash recording.
    """
    def __init__(self, case_data: Dict[str, Any], agent_profile: Dict[str, Any]):
        self.case_data = case_data
        self.agent_profile = agent_profile
        
        self.invalid_reasons: List[str] = []
        self.hashes: Dict[str, Any] = {
            "hashes_version": "nitbench.hashes.v1",
            "spec_version": "1.0.0",
            "case_id": case_data.get("case_id"),
            "checkpoints": []
        }
        
    def record_agent_profile(self) -> None:
        """Records canonical JSON of agent profile and detects mid-run switches (simulation)."""
        # "Agent Profile canonical JSON encoding"
        # json.dumps with sort_keys=True
        profile_json = json.dumps(self.agent_profile, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.hashes["agent_profile_sha256"] = hashlib.sha256(profile_json).hexdigest()

    def check_agent_profile_switch(self, new_profile: Dict[str, Any]) -> None:
        """Called if harness detects AUT switching reasoning levels mid-run."""
        if new_profile != self.agent_profile:
             self.invalid_reasons.append("model_or_reasoning_switch")

    def detect_tampering(self, action_type: str, argv: List[str], cwd: str) -> None:
        """
        Detects oracle tampering or sandbox escapes from action logs.
        For MVP, we just use simple string matching. Real world would need more robust parsing.
        """
        cmd_str = " ".join(argv).lower()
        
        # Oracle tampering
        tamper_keywords = ["oracle_bundle", "scoring.yaml", "result.json", "checkpoints.json"]
        if any(kw in cmd_str for kw in tamper_keywords):
            self.invalid_reasons.append("oracle_tampering_attempt")
            
        # Sandbox escape attempt
        escape_keywords = ["../..", "/etc/passwd", "/root", "/var/run"] # Simple heuristic
        if any(kw in cmd_str for kw in escape_keywords):
            self.invalid_reasons.append("sandbox_escape_attempt")

        # Network attempt
        network_cmds = ["curl", "wget", "ping", "netcat", "nc"]
        if argv and argv[0].lower() in network_cmds:
            self.invalid_reasons.append("network_attempt")

    def check_aif_modification(self, placed_aif_path: Path, initial_hash: str) -> None:
        """
        Verifies if AIF was modified.
        """
        allow_mod = self.case_data.get("allow_aif_modification", False)
        
        if not placed_aif_path.exists():
            if not allow_mod:
                self.invalid_reasons.append("aif_modified")
            return
            
        current_hash = hashlib.sha256(placed_aif_path.read_bytes()).hexdigest()
        if current_hash != initial_hash and not allow_mod:
            self.invalid_reasons.append("aif_modified")

    @property
    def is_run_valid(self) -> bool:
        return len(self.invalid_reasons) == 0
