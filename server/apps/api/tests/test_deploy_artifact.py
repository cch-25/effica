from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from deploy.check_artifact import check_completeness, check_imports, stage_artifact


def test_missing_runtime_module_rejected_before_deployment(tmp_path: Path) -> None:
    server = tmp_path / "server"
    module = server / "apps/api/app/new_feature.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 1\n")
    target = tmp_path / "stage"
    target.mkdir()
    with pytest.raises(ValueError, match="apps/api/app/new_feature.py"):
        check_completeness(server, target)


def test_directory_manifest_uses_actual_rsync_recursion(tmp_path: Path) -> None:
    server = tmp_path / "server"
    module = server / "apps/api/app/nested/feature.py"
    module.parent.mkdir(parents=True)
    module.write_text("VALUE = 1\n")
    manifest = server / "deploy.manifest"
    manifest.write_text("apps/api/app/\n")
    target = tmp_path / "stage"
    target.mkdir()
    stage_artifact(server, manifest, target)
    with pytest.raises(ValueError, match="nested/feature.py"):
        check_completeness(server, target)


def test_staged_import_cannot_fall_back_to_checkout(tmp_path: Path, monkeypatch) -> None:
    # The actual checkout contains this module. It must not rescue an empty release.
    server = Path(__file__).resolve().parents[3]
    monkeypatch.setenv("PYTHONPATH", str(server))
    with pytest.raises(subprocess.CalledProcessError):
        check_imports(tmp_path, ("apps.api.app.main",))


def test_staged_import_uses_release_files(tmp_path: Path) -> None:
    package = tmp_path / "apps"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "staged.py").write_text("VALUE = 1\n")
    check_imports(tmp_path, ("apps.staged",))


@pytest.mark.parametrize("missing", [
    "apps/api/app/demo_account.py",
    "apps/api/app/domains/issues/coverage.py",
    "apps/api/app/domains/sharing/ideology.py",
])
def test_service_import_fails_when_release_omits_required_module(
    tmp_path: Path, capfd, missing: str,
) -> None:
    server = Path(__file__).resolve().parents[3]
    manifest = tmp_path / "deploy.manifest"
    entries = (server / "deploy.manifest").read_text().splitlines()
    manifest.write_text("\n".join(entry for entry in entries if entry != missing) + "\n")
    target = tmp_path / "stage"
    target.mkdir()
    stage_artifact(server, manifest, target)
    with pytest.raises(subprocess.CalledProcessError):
        check_imports(target)
    assert f"No module named '{missing[:-3].replace('/', '.')}'" in capfd.readouterr().err


@pytest.mark.parametrize("entry", ["../.env", "/etc/passwd", "apps/api/tests/", ".env", "."])
def test_unsafe_manifest_entry_rejected(tmp_path: Path, entry: str) -> None:
    manifest = tmp_path / "deploy.manifest"
    manifest.write_text(entry + "\n")
    with pytest.raises(ValueError, match="Invalid deployment manifest entry"):
        stage_artifact(tmp_path, manifest, tmp_path / "stage")
