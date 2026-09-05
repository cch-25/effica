from __future__ import annotations

from pathlib import Path


def test_integrated_deployer_scopes_admin_and_uses_mariadb_stdin() -> None:
    deploy_script = Path(__file__).resolve().parents[4] / ".ops" / "deploy.sh"
    source = deploy_script.read_text(encoding="utf-8")

    assert 'host = required("VULTR_IPV4_PUBLIC_ADDRESS")' in source
    assert 'ssh_password = required("VULTR_PASSWORD")' in source
    assert "GRANT ALL PRIVILEGES ON `{database}`.*" in source
    assert "GRANT ALL PRIVILEGES ON *.*" not in source
    assert 'sudo -u "$SERVICE_USER" bash -c' in source
    assert "exec python3 -\" <<'PY' | sudo mariadb" in source
    assert "vercel --prod --yes --format=json" in source
    assert 'payload.get("deployment", payload)' in source
    assert "--retry-all-errors" in source
    assert "--password" not in source
