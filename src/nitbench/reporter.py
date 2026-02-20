import argparse
import json
import sys
import tarfile
from pathlib import Path
from typing import List

from nitbench.metrics.report import generate_report

def main():
    parser = argparse.ArgumentParser(description="NitBench Report Generator v1.0.0")
    parser.add_argument("--suite-id", type=str, required=True, help="ID of the suite")
    parser.add_argument("--suite-def", type=Path, required=True, help="Path to suite definition JSON (maps case_id to weight)")
    parser.add_argument("--run-archives", nargs="+", type=Path, help="Paths to run .tar.gz archives")
    parser.add_argument("--run-dirs", nargs="+", type=Path, help="Paths to extracted run directories containing run.json")
    parser.add_argument("--output", type=Path, required=True, help="Output path for report.json")
    
    args = parser.parse_args()
    
    try:
        # Load suite definition
        with open(args.suite_def, "r", encoding="utf-8") as f:
            suite_data = json.load(f)
            
        case_weights = suite_data.get("case_weights", {})
        
        runs = []
        
        # Load from directories
        if args.run_dirs:
            for d in args.run_dirs:
                run_json_path = d / "run.json"
                if run_json_path.exists():
                    with open(run_json_path, "r", encoding="utf-8") as f:
                        runs.append(json.load(f))
                        
        # Load from archives
        if args.run_archives:
            for archive_path in args.run_archives:
                with tarfile.open(archive_path, "r:gz") as tar:
                    try:
                        # Find run.json in the archive
                        # Need to look for any file ending in run.json
                        run_member = None
                        for member in tar.getmembers():
                            if member.name.endswith("run.json"):
                                run_member = member
                                break
                                
                        if run_member:
                            f = tar.extractfile(run_member)
                            if f:
                                runs.append(json.loads(f.read().decode("utf-8")))
                    except Exception as e:
                        print(f"Warning: Failed to extract run.json from {archive_path}: {e}", file=sys.stderr)
                        
        if not runs:
            print("No valid run.json files found.", file=sys.stderr)
            sys.exit(1)
            
        # Generate report
        report = generate_report(args.suite_id, case_weights, runs)
        
        # Write report
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            
        print(f"Report successfully generated at {args.output}")
        
    except Exception as e:
        print(f"Reporter failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
