"""Force pytest to run from the repository root.

File arguments are resolved against the invocation directory.  A leftover
``cwd`` from ``apps/web`` makes ``apps/api/tests/...`` missing and can stall
collection.  This plugin chdirs to the repo root and rewrites those paths
before collection.
"""

from __future__ import annotations

import os
from pathlib import Path

_SKIP_NEXT = {
    "-c",
    "-k",
    "-m",
    "-n",
    "-o",
    "-p",
    "--basetemp",
    "--confcutdir",
    "--override-ini",
    "--rootdir",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def rewrite_pytest_args(args: list[str], *, cwd: Path, root: Path) -> list[str]:
    rewritten: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            rewritten.append(arg)
            skip_next = False
            continue
        name = arg.split("=", 1)[0]
        if name in _SKIP_NEXT:
            rewritten.append(arg)
            if "=" not in arg:
                skip_next = True
            continue
        if arg.startswith("-"):
            rewritten.append(arg)
            continue
        path_part, marker, nodeid = arg.partition("::")
        path = Path(path_part)
        if path.is_absolute():
            rewritten.append(arg)
            continue
        from_cwd = cwd / path_part
        from_root = root / path_part
        resolved: Path | None = None
        if from_cwd.exists():
            resolved = from_cwd.resolve()
        elif from_root.exists():
            resolved = from_root.resolve()
        if resolved is None:
            rewritten.append(arg)
            continue
        rewritten.append(str(resolved) + (f"{marker}{nodeid}" if marker else ""))
    return rewritten


def pytest_load_initial_conftests(early_config, parser, args) -> None:  # noqa: ARG001
    root = repo_root()
    cwd = Path.cwd()
    args[:] = rewrite_pytest_args(list(args), cwd=cwd, root=root)
    os.chdir(root)


def pytest_configure(config) -> None:  # noqa: ARG001
    os.chdir(repo_root())


def pytest_sessionstart(session) -> None:  # noqa: ARG001
    cwd = Path.cwd().resolve()
    root = repo_root()
    if cwd != root:
        raise RuntimeError(f"pytest working directory is {cwd}, expected {root}")
