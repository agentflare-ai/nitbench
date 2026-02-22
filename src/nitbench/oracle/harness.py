import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

class OracleHarness:
    """
    Executes oracles against a frozen repository snapshot.
    Ensures network isolation, limits side-effects, and parses results.
    """
    def __init__(self, scoring_data: Dict[str, Any]):
        self.oracles = scoring_data.get("oracles", [])
        
    def execute_all(self, checkpoint_id: str, snapshot_tgz: Path, output_dir: Path) -> Dict[str, Any]:
        """
        Runs all oracles against the snapshot and returns the collated results.
        """
        import tarfile
        import tempfile
        
        results = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            with tarfile.open(snapshot_tgz, "r:gz") as tar:
                def is_within_directory(directory, target):
                    abs_directory = os.path.abspath(directory)
                    abs_target = os.path.abspath(target)
                    prefix = os.path.commonprefix([abs_directory, abs_target])
                    return prefix == abs_directory

                def safe_extract(tar, path=".", members=None, *, numeric_owner=False):
                    for member in tar.getmembers():
                        member_path = os.path.join(path, member.name)
                        if not is_within_directory(path, member_path):
                            raise Exception("Attempted Path Traversal in Tar File")
                    tar.extractall(path, members, numeric_owner=numeric_owner)

                safe_extract(tar, temp_root)
                
            snapshot_root = temp_root / "repo"
            
            for oracle_def in self.oracles:
                oracle_id = oracle_def["id"]
                oracle_out_dir = output_dir / "checkpoints" / checkpoint_id / "oracles" / oracle_id
                oracle_out_dir.mkdir(parents=True, exist_ok=True)
                
                res = self._execute_oracle(oracle_def, snapshot_root, oracle_out_dir)
                results[oracle_id] = res
            
        return results

    def _execute_oracle(self, oracle_def: Dict[str, Any], snapshot_root: Path, out_dir: Path) -> Dict[str, Any]:
        # 1. Prepare environment to ignore repo configs
        env = os.environ.copy()
        env["PYLINTRC"] = "/dev/null" # Example: Force pylint to ignore local .pylintrc
        env["RUFF_CONFIG"] = "/dev/null"
        
        # 2. Setup CWD and Command
        cwd = snapshot_root / oracle_def.get("cwd", ".")
        mutates = oracle_def.get("mutates_snapshot", False)
        if mutates:
            import shutil
            copy_dir = out_dir / "snapshot_copy"
            if copy_dir.exists():
                shutil.rmtree(copy_dir)
            shutil.copytree(snapshot_root, copy_dir, symlinks=True)
            cwd = copy_dir / oracle_def.get("cwd", ".")

        command = oracle_def.get("command", [])
        timeout = oracle_def.get("timeout_seconds", 30)
        
        # 3. Execute
        stdout_path = out_dir / "stdout.log"
        stderr_path = out_dir / "stderr.log"
        
        exit_code = -1
        try:
            with open(stdout_path, "wb") as f_out, open(stderr_path, "wb") as f_err:
                process = subprocess.run(
                    command,
                    cwd=cwd,
                    env=env,
                    stdout=f_out,
                    stderr=f_err,
                    timeout=timeout,
                    check=False
                )
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            # Handle timeout
            pass
        except FileNotFoundError:
            # Handle missing executable
            pass
            
        # 4. Parse Results
        counting = oracle_def.get("counting", {})
        stdout_str = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
        stderr_str = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
        
        error_count, warning_count, info_count = self._parse_counts(counting, exit_code, stdout_str, stderr_str, cwd)
        
        # 5. Classify Status
        expected_codes = oracle_def.get("expected_exit_codes", {})
        ok_codes = expected_codes.get("ok", [0])
        violation_codes = expected_codes.get("violations", [1])
        
        if exit_code in ok_codes:
            status = "ok"
        elif exit_code in violation_codes:
            status = "violations"
        else:
            status = "tool_error"
            
        # 6. Save result.json
        result_data = {
            "oracle_id": oracle_def.get("id"),
            "status": status,
            "exit_code": exit_code,
            "error_count": error_count,
            "warning_count": warning_count,
            "info_count": info_count
        }
        
        with open(out_dir / "result.json", "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)
            
        return result_data

    def _parse_counts(self, counting: Dict[str, Any], exit_code: int, stdout_str: str, stderr_str: str = "", cwd: Path = None) -> Tuple[int, int, int]:
        mode = counting.get("mode", "exit_code")
        
        if mode == "exit_code":
            # Just binary pass/fail
            errs = 1 if exit_code != 0 else 0
            return (errs, 0, 0)
            
        elif mode == "regex":
            err_re = counting.get("regex_error", "")
            warn_re = counting.get("regex_warning", "")
            info_re = counting.get("regex_info", "")
            
            errs = len(re.findall(err_re, stdout_str, re.MULTILINE)) if err_re else 0
            warns = len(re.findall(warn_re, stdout_str, re.MULTILINE)) if warn_re else 0
            infos = len(re.findall(info_re, stdout_str, re.MULTILINE)) if info_re else 0
            return (errs, warns, infos)
            
        elif mode == "json_stdout":
            json_source = counting.get("json_source", "stdout")
            target_str = stderr_str if json_source == "stderr" else stdout_str
            try:
                data = json.loads(target_str)
                # Naive array length assumption for MVP
                if isinstance(data, list):
                    return (len(data), 0, 0)
            except json.JSONDecodeError:
                pass
                
        elif mode == "json_file":
            filepath = counting.get("file_path", "")
            if filepath and cwd:
                full_path = cwd / filepath
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            return (len(data), 0, 0)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                    
        elif mode == "sarif_file":
            filepath = counting.get("file_path", "")
            if filepath and cwd:
                full_path = cwd / filepath
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        errs, warns, infos = 0, 0, 0
                        for run in data.get("runs", []):
                            for res in run.get("results", []):
                                level = res.get("level", "warning")
                                if level == "error": errs += 1
                                elif level == "warning": warns += 1
                                elif level == "note": infos += 1
                        return (errs, warns, infos)
                except (FileNotFoundError, json.JSONDecodeError):
                    pass
                    
        return (0, 0, 0)
