"""Validate the actual rsync release without starting services or connecting to a DB."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path, PurePosixPath

RUNTIME_ROOTS = ("apps/api/app", "apps/worker/worker", "db")
ENTRYPOINTS = (
    "apps.api.app.main",
    "apps.worker.worker.main",
    "db.article_retention",
    "db.storage_maintenance",
)


def stage_artifact(server: Path, manifest: Path, target: Path) -> None:
    for entry in manifest.read_text().splitlines():
        path = PurePosixPath(entry)
        if (
            not entry
            or not path.parts
            or path.is_absolute()
            or ".." in path.parts
            or path.parts[0] not in {"apps", "db", "deploy", "pyproject.toml", "uv.lock"}
            or any(part.startswith(".") or part in {"tests", "__pycache__"} for part in path.parts)
            or (server / entry).is_symlink()
            or not (server / entry).exists()
        ):
            raise ValueError(f"Invalid deployment manifest entry: {entry!r}")
    # Match deploy.sh exactly, including --files-from's directory semantics.
    subprocess.run(
        [
            "rsync", "-az", "--delete", "--prune-empty-dirs",
            f"--files-from={manifest}", f"{server}/", f"{target}/",
        ],
        check=True,
    )


def check_completeness(server: Path, target: Path) -> None:
    missing = sorted(
        str(path.relative_to(server))
        for root in RUNTIME_ROOTS
        for path in (server / root).rglob("*.py")
        if "__pycache__" not in path.parts
        and not (target / path.relative_to(server)).is_file()
    )
    if missing:
        raise ValueError("Deployment artifact is missing runtime modules:\n" + "\n".join(missing))


def check_imports(target: Path, modules: tuple[str, ...] = ENTRYPOINTS) -> None:
    # -I -S skips PYTHONPATH, the checkout and editable-install .pth files.
    # Add only this venv's third-party packages and the staged release.
    libraries = [sysconfig.get_path("purelib"), sysconfig.get_path("platlib")]
    program = """
import importlib
import pathlib
import sys

stage = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(stage), *sys.argv[2:4]]
for name in sys.argv[4:]:
    module = importlib.import_module(name)
    if name == 'apps.worker.worker.main':
        module.build_default_registry()
for name, module in list(sys.modules.items()):
    if name.split('.')[0] in {'apps', 'db'} and getattr(module, '__file__', None):
        if not pathlib.Path(module.__file__).resolve().is_relative_to(stage):
            raise SystemExit(f'Module escaped deployment artifact: {name}')
print('Staged API, worker and maintenance imports passed (no services started).')
"""
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", program, str(target), *libraries, *modules],
        cwd=target,
        env={
            "PATH": os.environ.get("PATH", ""),
            "APP_ENV": "test",
            "APP_BACKEND": "memory",
        },
        check=True,
        timeout=60,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    server = Path(__file__).resolve().parents[1]
    manifest = (args.manifest or server / "deploy.manifest").resolve()
    output = server.parent / "output"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="deploy-artifact-", dir=output) as directory:
        target = Path(directory)
        stage_artifact(server, manifest, target)
        check_completeness(server, target)
        check_imports(target)
    print("Deployment manifest and staged runtime checks passed.")


if __name__ == "__main__":
    main()
