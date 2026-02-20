import tarfile
from pathlib import Path

def create_deployable_package(harness_artifacts: Path, output_tar: Path) -> Path:
    """
    Creates a deployable `.tar.gz` package from the harness artifacts directory.
    This tarball is intended to be consumed by the automated grader module.
    """
    with tarfile.open(output_tar, "w:gz") as tar:
        tar.add(harness_artifacts, arcname=harness_artifacts.name)
        
    return output_tar
