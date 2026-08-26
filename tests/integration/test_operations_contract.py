from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".agents" / "scripts"


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

    assert paths == expected
    assert not any(
        path.startswith(("apps/web/", "tests/", "docs/", ".agents/", "output/", "PPT_VIDEO/"))
        for path in paths
    )
    assert not any(path.endswith((".env", ".pem", ".key", ".p12")) for path in paths)


def test_deploy_preflight_precedes_remote_mutations_and_release_is_atomic() -> None:
    source = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")

    preflight = source.index("preflight\n")
    remote_stage_mutation = source.index('"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "rm -rf')
    assert preflight < remote_stage_mutation
    assert "uv run ruff check apps db tests" in source
    assert "uv run mypy apps tests" in source
    assert "npm run typecheck" in source
    assert "npm run build" in source
    assert "pip-audit" in source
    assert "uv pip freeze --exclude-editable" in source
    assert "--path \"$ROOT/.venv\"" not in source
    assert "--files-from=\"$DEPLOY_MANIFEST\"" in source
    assert 'RELEASES_DIR="$APP_DIR/releases"' in source
    assert 'CURRENT_LINK="$APP_DIR/current"' in source
    assert "ROLLBACK_REQUIRED=1" in source
    assert "candidate_ready=1" in source


def test_deploy_dirty_override_is_an_exact_approved_patch() -> None:
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


def test_preflight_and_verify_include_headless_mock_a11y_and_real_flows() -> None:
    deploy = (SCRIPTS / "deploy.sh").read_text(encoding="utf-8")
    run = (SCRIPTS / "run.sh").read_text(encoding="utf-8")

    for source in (deploy, run):
        assert "npm run test:e2e" in source
        assert "npm run test:a11y" in source
        assert "npm run test:e2e:real" in source


def test_operations_have_only_agent_script_entrypoints_and_no_github_workflows() -> None:
    assert (SCRIPTS / "deploy.sh").is_file()
    assert (SCRIPTS / "run.sh").is_file()
    assert not (ROOT / "deploy.sh").exists()
    assert not (ROOT / "run.sh").exists()

    workflows = ROOT / ".github" / "workflows"
    assert not workflows.exists() or not any(workflows.glob("*.y*ml"))
