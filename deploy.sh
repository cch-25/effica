#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT/.env"
REMOTE_DIR="/opt/perspective-news"
REMOTE_STAGE="/tmp/perspective-news-release"
DEPLOY_ENV=""

cd "$ROOT"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 명령을 찾을 수 없습니다."
}

cleanup() {
  if [[ -n "$DEPLOY_ENV" && -f "$DEPLOY_ENV" ]]; then
    rm -f "$DEPLOY_ENV"
  fi
}
trap cleanup EXIT INT TERM

need uv
need ssh
need sshpass
need rsync
[[ -f "$ENV_FILE" ]] || die "저장소 루트에 .env 파일이 필요합니다."
[[ -f "$ROOT/apps/web/package.json" ]] || die "apps/web/package.json이 없습니다. FastAPI와 Next.js를 함께 배포할 수 없습니다."

if [[ "$(uname -s)" == "Darwin" ]]; then
  mode="$(stat -f '%Lp' "$ENV_FILE")"
else
  mode="$(stat -c '%a' "$ENV_FILE")"
fi
[[ "$mode" == "600" ]] || die ".env 권한은 600이어야 합니다. 현재: $mode"

DEPLOY_ENV="$(mktemp "${TMPDIR:-/tmp}/perspective-env.XXXXXX")"
chmod 600 "$DEPLOY_ENV"

eval "$(DEPLOY_ENV="$DEPLOY_ENV" uv run python - "$ENV_FILE" <<'PY'
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

source = Path(sys.argv[1])
target = Path(os.environ["DEPLOY_ENV"])
values = {key: value for key, value in dotenv_values(source).items() if value is not None}

def required(key: str) -> str:
    value = values.get(key, "")
    if not value or value.startswith("<"):
        raise SystemExit(f"{key} must be set in the repository-root .env")
    return value

host = required("EC2_IPV4_PUBLIC_ADDRESS")
ssh_password = required("EC2_PASSWORD")
database = required("DB_ADMIN_DATABASE")
username = required("DB_ADMIN_USERNAME")
db_password = required("DB_ADMIN_PASSWORD")
database_url = make_url(required("DATABASE_URL"))
session_secret = required("SESSION_SECRET")

if not re.fullmatch(r"[A-Za-z0-9_]+", database) or not re.fullmatch(r"[A-Za-z0-9_]+", username):
    raise SystemExit("DB_ADMIN_DATABASE and DB_ADMIN_USERNAME may contain only letters, digits, and underscore")
if db_password != ssh_password:
    raise SystemExit("DB_ADMIN_PASSWORD must equal EC2_PASSWORD")
if database_url.username != username or database_url.password != db_password or database_url.database != database:
    raise SystemExit("DATABASE_URL credentials/database must match DB_ADMIN_* values")
if len(session_secret.encode()) < 32 or "placeholder" in session_secret:
    raise SystemExit("SESSION_SECRET must contain at least 32 non-placeholder bytes")

values["APP_ENV"] = "production"
values["APP_BACKEND"] = "mariadb"
values["DATABASE_URL"] = database_url.set(host="127.0.0.1", port=3306).render_as_string(hide_password=False)
values["DB_ADMIN_ALLOWED_HOST"] = "127.0.0.1"
for key, default in {
    "PUBLIC_BASE_URL": f"http://{host}",
    "WEB_BASE_URL": f"http://{host}",
    "NEXT_PUBLIC_API_BASE_URL": f"http://{host}/api/v1",
}.items():
    if not values.get(key) or values[key].startswith("<"):
        values[key] = default

deployment_only = {
    "EC2_PASSWORD", "EC2_IPV4_PUBLIC_ADDRESS", "EC2_HOST", "EC2_SSH_USER", "EC2_SSH_PORT",
    "MARIADB_BOOTSTRAP_HOST", "MARIADB_BOOTSTRAP_PORT", "MARIADB_BOOTSTRAP_USER",
    "MARIADB_BOOTSTRAP_PASSWORD",
}
with target.open("w", encoding="utf-8") as output:
    for key in sorted(values):
        if key not in deployment_only and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            output.write(f"{key}={shlex.quote(values[key])}\n")

print(f"export DEPLOY_HOST={shlex.quote(host)}")
print(f"export DEPLOY_PASSWORD={shlex.quote(ssh_password)}")
print(f"export DEPLOY_USER={shlex.quote(values.get('EC2_SSH_USER', 'ubuntu'))}")
print(f"export DEPLOY_PORT={shlex.quote(values.get('EC2_SSH_PORT', '22'))}")
PY
)"

SSH=(sshpass -e ssh -p "$DEPLOY_PORT" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
RSYNC_SSH="sshpass -e ssh -p $DEPLOY_PORT -o StrictHostKeyChecking=accept-new"
export SSHPASS="$DEPLOY_PASSWORD"

printf '1/5 원격 staging 디렉터리 준비\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "mkdir -p '$REMOTE_STAGE'"

printf '2/5 애플리케이션과 .env 동기화\n'
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude 'node_modules/' \
  --exclude '.next/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.mypy_cache/' \
  -e "$RSYNC_SSH" "$ROOT/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/"
rsync -az -e "$RSYNC_SSH" "$DEPLOY_ENV" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/.env"

printf '3/5 MariaDB, Python, Node.js, Nginx 및 서비스 구성\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$REMOTE_STAGE" <<'REMOTE'
set -Eeuo pipefail

APP_DIR="$1"
STAGE_DIR="$2"
SERVICE_USER="perspective"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates curl mariadb-client mariadb-server nginx python3 python3-venv rsync

if ! command -v node >/dev/null 2>&1 || ! node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 22 ? 0 : 1)'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs
fi

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --create-home --home-dir /var/lib/perspective --shell /usr/sbin/nologin "$SERVICE_USER"
fi

sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR"
sudo rsync -a --delete --exclude '.env' "$STAGE_DIR/" "$APP_DIR/"
sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0600 "$STAGE_DIR/.env" "$APP_DIR/.env"

sudo tee /etc/mysql/mariadb.conf.d/99-perspective.cnf >/dev/null <<'EOF'
[mariadbd]
bind-address = 127.0.0.1
skip-name-resolve
EOF
sudo systemctl enable --now mariadb
sudo systemctl restart mariadb

set -a
# deploy.sh generated this file with shell-safe quoting.
. "$APP_DIR/.env"
set +a

python3 - <<'PY' | sudo mariadb
import os

def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

database = os.environ["DB_ADMIN_DATABASE"]
username = sql_string(os.environ["DB_ADMIN_USERNAME"])
password = sql_string(os.environ["DB_ADMIN_PASSWORD"])
host = sql_string("127.0.0.1")
print(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
print(f"CREATE USER IF NOT EXISTS {username}@{host} IDENTIFIED BY {password};")
print(f"ALTER USER {username}@{host} IDENTIFIED BY {password};")
print(f"GRANT ALL PRIVILEGES ON `{database}`.* TO {username}@{host};")
print("FLUSH PRIVILEGES;")
PY

sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "cd '$APP_DIR' && uv sync --frozen --no-dev"
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "set -a; . '$APP_DIR/.env'; set +a; cd '$APP_DIR' && uv run alembic -c db/alembic.ini upgrade head"
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "set -a; . '$APP_DIR/.env'; set +a; cd '$APP_DIR/apps/web' && if [ -f package-lock.json ]; then npm ci; else npm install; fi && npm run build"

sudo tee /etc/systemd/system/perspective-api.service >/dev/null <<EOF
[Unit]
Description=Perspective News FastAPI
After=network-online.target mariadb.service
Wants=network-online.target
Requires=mariadb.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
KillSignal=SIGTERM
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/perspective-worker.service >/dev/null <<EOF
[Unit]
Description=Perspective News MariaDB Worker
After=network-online.target mariadb.service perspective-api.service
Requires=mariadb.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/python -m apps.worker.worker.main
Restart=on-failure
RestartSec=3
TimeoutStopSec=45
KillSignal=SIGTERM
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/systemd/system/perspective-web.service >/dev/null <<EOF
[Unit]
Description=Perspective News Next.js
After=network-online.target perspective-api.service
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$APP_DIR/apps/web
EnvironmentFile=$APP_DIR/.env
ExecStart=/usr/bin/npm run start -- --hostname 127.0.0.1 --port 3000
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
KillSignal=SIGTERM
UMask=0027
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

sudo tee /etc/nginx/sites-available/perspective-news >/dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    client_max_body_size 10m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }

    location /health/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 10s;
    }

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/perspective-news /etc/nginx/sites-enabled/perspective-news
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable perspective-api perspective-worker perspective-web nginx
sudo systemctl restart perspective-api perspective-worker perspective-web nginx
rm -rf "$STAGE_DIR"
REMOTE

printf '4/5 서비스 상태 확인\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" \
  "sudo systemctl --no-pager --full status perspective-api perspective-worker perspective-web nginx | sed -n '1,80p'"

printf '5/5 HTTP health check\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" \
  "curl --fail --silent --show-error --retry 10 --retry-delay 2 http://127.0.0.1:8000/health/ready >/dev/null"

printf '배포 완료: http://%s (TLS는 별도 최종 단계)\n' "$DEPLOY_HOST"
