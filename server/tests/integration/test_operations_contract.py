from __future__ import annotations

import os
import pty
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ROOT.parent
SCRIPTS = REPOSITORY_ROOT / ".ops"


def test_deploy_manifest_is_runtime_only_and_complete() -> None:
    manifest = (ROOT / "deploy.manifest").read_text(encoding="utf-8").splitlines()
    paths = {line for line in manifest if line.strip()}
    runtime_python = {
        path.relative_to(ROOT).as_posix()
        for root in (ROOT / "apps" / "api" / "app", ROOT / "apps" / "worker" / "worker", ROOT / "db")
        for path in root.rglob("*.py")
    }
    expected = runtime_python | {
        "apps/__init__.py",
        "apps/api/__init__.py",
        "apps/worker/__init__.py",
        "db/alembic.ini",
        "db/alembic/script.py.mako",
            "db/seeds/articles.json",
            "db/seeds/demo_showcase.json",
            "db/seeds/tier_policy.json",
        "pyproject.toml",
        "uv.lock",
    }
    expected |= {path.relative_to(ROOT).as_posix() for path in (ROOT / "deploy").iterdir() if path.is_file()}

    assert paths == expected
    assert not any(
        path.startswith(("client/", "tests/", "docs/", ".agents/", ".ops/", "output/"))
        for path in paths
    )
    assert not any(path.endswith((".env", ".pem", ".key", ".p12")) for path in paths)


def test_deploy_preflight_precedes_remote_mutations_and_release_is_atomic() -> None:
    source = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")

    preflight = source.index("preflight\n")
    remote_stage_mutation = source.index('"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "mkdir')
    assert preflight < remote_stage_mutation
    assert "--files-from=\"$DEPLOY_MANIFEST\"" in source
    assert '"$SERVER_DIR/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/"' in source
    assert 'RELEASES_DIR="$APP_DIR/releases"' in source
    assert 'CURRENT_LINK="$APP_DIR/current"' in source
    assert "ROLLBACK_REQUIRED=1" in source
    assert "candidate_ready=1" in source


def test_deploy_explicit_patch_pin_is_exact() -> None:
    source = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")

    assert "DEPLOY_ALLOW_DIRTY" not in source
    assert "DEPLOY_APPROVED_DIFF" in source
    assert "git diff --no-index --binary" in source
    assert "cmp -s \"$current_diff\" \"$DEPLOY_APPROVED_DIFF\"" in source
    assert "working tree diff가 DEPLOY_APPROVED_DIFF와 정확히 일치하지 않습니다" in source


def test_deploy_stops_live_services_dumps_before_migration_and_restores_on_failure() -> None:
    source = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")

    stop = source.index("\nstop_live_services\n")
    backup = source.index("\ncreate_database_backup\n", stop)
    migration = source.index("MIGRATION_ATTEMPTED=1")
    assert stop < backup < migration
    assert "mariadb-dump --add-drop-database" in source
    assert "DATABASE_BACKUP_PATH=\"$BACKUPS_DIR/$RELEASE_ID.sql.gz\"" in source
    assert "restore_database" in source
    assert "gzip -dc \"$DATABASE_BACKUP_PATH\" | sudo mariadb" in source
    assert "write_rollback_state" in source
    assert "rollback_remote_release" in source


@pytest.mark.parametrize(
    ("script", "argument", "status"),
    [("run.sh", "--help", 0), ("deploy.sh", "--help", 0), ("deploy.sh", "maintenance", 1)],
)
def test_script_usage_needs_no_credentials_or_deploy_tools(
    tmp_path: Path, script: str, argument: str, status: int
) -> None:
    ops = tmp_path / ".ops"
    ops.mkdir()
    shutil.copy2(SCRIPTS / script, ops / script)
    result = subprocess.run(
        ["/bin/bash", str(ops / script), argument],
        env={"PATH": "/usr/bin:/bin"},
        text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == status, result.stderr
    assert "Usage:" in result.stdout + result.stderr


def test_stopping_web_mock_terminates_its_child_process(tmp_path: Path) -> None:
    ops = tmp_path / ".ops"
    ops.mkdir()
    shutil.copy2(SCRIPTS / "run.sh", ops / "run.sh")
    client = tmp_path / "client"
    (client / "node_modules").mkdir(parents=True)
    (client / "package.json").write_text("{}")
    tools = tmp_path / "bin"
    tools.mkdir()
    child_path = tmp_path / "child.pid"
    for name, body in {
        "npm": "exit 99",
        "lsof": "exit 1",
        "node": 'sleep 60 &\nchild=$!\nprintf "%s" "$child" > "$CHILD_PID_FILE"\nwait "$child"',
    }.items():
        tool = tools / name
        tool.write_text("#!/bin/bash\n" + body + "\n")
        tool.chmod(0o755)
    env = {"PATH": f"{tools}:/usr/bin:/bin", "CHILD_PID_FILE": str(child_path)}
    process = subprocess.Popen(
        ["/bin/bash", str(ops / "run.sh"), "web-mock"], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    child = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not child_path.exists():
            time.sleep(0.05)
        assert child_path.exists(), "mock service did not start"
        child = int(child_path.read_text())
        process.terminate()
        _, stderr = process.communicate(timeout=15)
        assert process.returncode == 143, stderr
        with pytest.raises(ProcessLookupError):
            os.kill(child, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        if child is not None:
            try:
                os.kill(child, 9)
            except ProcessLookupError:
                pass


def test_operations_have_only_agent_script_entrypoints_and_no_github_workflows() -> None:
    assert (SCRIPTS / "deploy.sh").is_file()
    assert (SCRIPTS / "run.sh").is_file()
    assert {path.name for path in SCRIPTS.iterdir()} == {"run.sh", "deploy.sh"}
    assert not (REPOSITORY_ROOT / "deploy.sh").exists()
    assert not (REPOSITORY_ROOT / "run.sh").exists()

    workflows = REPOSITORY_ROOT / ".github" / "workflows"
    assert not workflows.exists() or not any(workflows.glob("*.y*ml"))


def test_deploy_preflight_does_not_open_pager_in_terminal(tmp_path: Path) -> None:
    ops = tmp_path / ".ops"
    ops.mkdir()
    shutil.copy2(SCRIPTS / "deploy.sh", ops / "deploy.sh")
    shutil.copy2(SCRIPTS / "run.sh", ops / "run.sh")
    (tmp_path / "server").mkdir()
    (tmp_path / "server/deploy.manifest").write_text("")
    (tmp_path / "server/deploy").mkdir()
    (tmp_path / "server/deploy/noop.sh").write_text("#!/bin/bash\ntrue\n")
    (tmp_path / "client").mkdir()
    (tmp_path / "client/package.json").write_text("{}")
    (tmp_path / ".env").write_text("")
    (tmp_path / ".env").chmod(0o600)
    (tmp_path / ".gitignore").write_text(".env\n.ops/\nbin/\npager-called\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    git = shutil.which("git")
    assert git
    for args in (("init", "-q"), ("add", "."), ("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")):
        subprocess.run([git, *args], cwd=tmp_path, env=env, check=True, capture_output=True)
    (tmp_path / "client/package.json").write_text('{"changed": true}\n')
    tools = tmp_path / "bin"
    tools.mkdir()
    for name, body in {
        "uv": "printf '%s\\n' 'export VERCEL_TOKEN=fixture' 'export DEPLOY_HOST=127.0.0.1' 'export DEPLOY_PASSWORD=fixture' 'export DEPLOY_USER=root' 'export DEPLOY_PORT=22'",
        "vercel": "exit 0",
        "sshpass": "exit 99",
        "npm": "exit 0",
        "node": "exit 0",
        "pager": 'touch "$PAGER_MARKER"; cat >/dev/null',
    }.items():
        path = tools / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
    marker = tmp_path / "pager-called"
    env.update(PATH=f"{tools}:{env['PATH']}", GIT_PAGER=str(tools / "pager"), PAGER_MARKER=str(marker))
    for key in tuple(env):
        if key.startswith("DEPLOY_"):
            env.pop(key)
    master, slave = pty.openpty()
    try:
        result = subprocess.run(
            ["/bin/bash", str(ops / "deploy.sh"), "--preflight"], cwd=tmp_path, env=env,
            stdin=subprocess.DEVNULL, stdout=slave, stderr=slave, timeout=10,
        )
        assert result.returncode == 0  # Dirty files are valid; preflight performs no deployment.
        assert not marker.exists(), "Git opened an interactive pager during deployment"
    finally:
        os.close(slave)
        os.close(master)


@pytest.mark.parametrize("track_env", [False, True])
def test_secret_check_accepts_fixture_but_rejects_tracked_env(tmp_path: Path, track_env: bool) -> None:
    ops = tmp_path / ".ops"
    ops.mkdir()
    shutil.copy2(SCRIPTS / "run.sh", ops / "run.sh")
    fixture = tmp_path / "fixture.py"
    fixture.write_text('token_export = "export VERCEL_TOKEN=fixture"\n')
    env_file = tmp_path / ".env"
    env_file.write_text("DUMMY=fixture\n")
    env_file.chmod(0o600)
    (tmp_path / ".gitignore").write_text(".ops/\n.env\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, env=env, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, env=env, check=True)
    if track_env:
        subprocess.run(["git", "add", "-f", ".env"], cwd=tmp_path, env=env, check=True)
    result = subprocess.run(
        ["/bin/bash", str(ops / "run.sh"), "check-secrets"],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=5,
    )
    assert result.returncode == (1 if track_env else 0), result.stderr
    assert "DUMMY=fixture" not in result.stdout + result.stderr
