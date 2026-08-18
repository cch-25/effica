"""Invocation-directory guards for the Python test runner."""

from __future__ import annotations

import os
import subprocess
import sys

from tests.pytest_repo_root import repo_root, rewrite_pytest_args


def test_repo_relative_pytest_args_are_rewritten_from_apps_web() -> None:
    root = repo_root()
    nested = root / "apps" / "web"
    target = (root / "apps/api/tests/test_auth_privacy.py").resolve()
    args = rewrite_pytest_args(
        ["-q", "apps/api/tests/test_auth_privacy.py::test_foo", "--tb=short"],
        cwd=nested,
        root=root,
    )
    assert args[1] == f"{target}::test_foo"


def test_existing_cwd_relative_args_become_absolute() -> None:
    root = repo_root()
    target = (root / "apps/api/tests/test_auth_privacy.py").resolve()
    args = rewrite_pytest_args(
        ["apps/api/tests/test_auth_privacy.py"],
        cwd=root,
        root=root,
    )
    assert args == [str(target)]


def test_pytest_collects_repo_paths_when_invoked_from_apps_web() -> None:
    root = repo_root()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "tests/integration/test_pytest_repo_root.py",
        ],
        cwd=root / "apps" / "web",
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "PYTHONPATH": str(root)},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_pytest_repo_root.py" in result.stdout + result.stderr
