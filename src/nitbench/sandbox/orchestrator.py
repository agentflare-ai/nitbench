import json
import time
from pathlib import Path
from typing import Any, Dict, List

class TranscriptEvent:
    def __init__(self, timestamp: float, event_type: str, payload: Any):
        self.timestamp = timestamp
        self.event_type = event_type
        self.payload = payload
        
    def to_json_array(self) -> List[Any]:
        return [self.timestamp, self.event_type, self.payload]


class TranscriptLogger:
    def __init__(self, log_path: Path, interaction_mode: str = "pty"):
        self.log_path = log_path
        self.interaction_mode = interaction_mode
        self.events: List[TranscriptEvent] = []
        
        # Write header immediately
        header = {
            "format": "nitbench.cast",
            "version": 1,
            "timestamp_utc": int(time.time()),
            "interaction_mode": interaction_mode
        }
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(header) + "\n")
            
    def log_input(self, data: str, timestamp: float = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        event = TranscriptEvent(ts, "i", data)
        self._write_event(event)
        
    def log_output(self, data: str, timestamp: float = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        event = TranscriptEvent(ts, "o", data)
        self._write_event(event)
        
    def log_marker(self, payload: Dict[str, Any], timestamp: float = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        event = TranscriptEvent(ts, "m", payload)
        self._write_event(event)
        
    def log_resize(self, cols: int, rows: int, timestamp: float = None) -> None:
        ts = timestamp if timestamp is not None else time.time()
        event = TranscriptEvent(ts, "r", {"cols": cols, "rows": rows})
        self._write_event(event)

    def _write_event(self, event: TranscriptEvent) -> None:
        self.events.append(event)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_json_array()) + "\n")


class BudgetEnforcer:
    def __init__(self, budgets: Dict[str, int]):
        self.budgets = budgets
        self.actions = 0
        self.commits = 0
        self.start_time = time.time()
        self.invalid_reasons: List[str] = []
        
    def record_action(self) -> None:
        self.actions += 1
        max_actions = self.budgets.get("max_agent_actions")
        if max_actions and self.actions > max_actions:
            self.invalid_reasons.append("budget_exceeded:agent_actions")
            
    def record_commit(self) -> None:
        self.commits += 1
        max_commits = self.budgets.get("max_commits")
        if max_commits is not None and self.commits > max_commits:
            self.invalid_reasons.append("budget_exceeded:commits")
            
    def check_wall_time(self) -> None:
        elapsed = time.time() - self.start_time
        max_wall = self.budgets.get("max_wall_seconds")
        if max_wall and elapsed > max_wall:
            self.invalid_reasons.append("budget_exceeded:wall_seconds")

    @property
    def is_invalid(self) -> bool:
        return len(self.invalid_reasons) > 0
