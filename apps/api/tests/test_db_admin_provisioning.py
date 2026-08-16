from __future__ import annotations

from pathlib import Path


def test_integrated_deployer_scopes_admin_and_uses_mariadb_stdin() -> None:
    deploy_script = Path(__file__).resolve().parents[3] / "deploy.sh"
    source = deploy_script.read_text(encoding="utf-8")

    assert "DB_ADMIN_PASSWORD must equal EC2_PASSWORD" in source
    assert "GRANT ALL PRIVILEGES ON `{database}`.*" in source
    assert "GRANT ALL PRIVILEGES ON *.*" not in source
    assert "python3 - <<'PY' | sudo mariadb" in source
    assert "--password" not in source
