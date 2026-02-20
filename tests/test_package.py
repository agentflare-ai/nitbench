import pytest
import tarfile
from pathlib import Path

from nitbench.sandbox.package import create_deployable_package

def test_create_deployable_package(tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "run_result.json").write_text("{}", encoding="utf-8")
    
    out_tar = tmp_path / "package.tar.gz"
    
    res = create_deployable_package(artifacts, out_tar)
    assert res.exists()
    
    # Verify contents
    with tarfile.open(res, "r:gz") as tar:
        names = tar.getnames()
        assert "artifacts/run_result.json" in names
