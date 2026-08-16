#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT/apps/web"
ENV_FILE="$ROOT/.env"
REMOTE_DIR="/opt/perspective-news"
REMOTE_STAGE="/tmp/perspective-news-release"
VERCEL_PROJECT="${VERCEL_PROJECT:-perspective-news}"
DEPLOY_ENV=""
DEPLOY_VARS=""

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
  if [[ -n "$DEPLOY_VARS" && -f "$DEPLOY_VARS" ]]; then
    rm -f "$DEPLOY_VARS"
  fi
}
trap cleanup EXIT INT TERM

for command in uv ssh sshpass rsync curl vercel; do
  need "$command"
done
[[ -f "$ENV_FILE" ]] || die "저장소 루트에 .env 파일이 필요합니다."
[[ -f "$WEB_DIR/package.json" ]] || die "apps/web/package.json이 없습니다."

if [[ "$(uname -s)" == "Darwin" ]]; then
  mode="$(stat -f '%Lp' "$ENV_FILE")"
else
  mode="$(stat -c '%a' "$ENV_FILE")"
fi
[[ "$mode" == "600" ]] || die ".env 권한은 600이어야 합니다. 현재: $mode"

DEPLOY_ENV="$(mktemp "${TMPDIR:-/tmp}/perspective-env.XXXXXX")"
DEPLOY_VARS="$(mktemp "${TMPDIR:-/tmp}/perspective-vars.XXXXXX")"
chmod 600 "$DEPLOY_ENV" "$DEPLOY_VARS"

DEPLOY_ENV="$DEPLOY_ENV" uv run python - "$ENV_FILE" >"$DEPLOY_VARS" <<'PY'
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

# These are replaced with the actual Vercel production URL after the frontend deploy.
values["PUBLIC_BASE_URL"] = f"http://{host}"
values["WEB_BASE_URL"] = f"http://{host}"
values["NEXT_PUBLIC_API_MODE"] = "real"

deployment_only = {
    "EC2_PASSWORD", "EC2_IPV4_PUBLIC_ADDRESS", "EC2_HOST", "EC2_SSH_USER", "EC2_SSH_PORT",
    "MARIADB_BOOTSTRAP_HOST", "MARIADB_BOOTSTRAP_PORT", "MARIADB_BOOTSTRAP_USER",
    "MARIADB_BOOTSTRAP_PASSWORD", "API_BACKEND_URL", "VERCEL_PROJECT",
}
with target.open("w", encoding="utf-8") as output:
    for key in sorted(values):
        if key not in deployment_only and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            output.write(f"{key}={shlex.quote(values[key])}\n")

print(f"export DEPLOY_HOST={shlex.quote(host)}")
print(f"export DEPLOY_PASSWORD={shlex.quote(ssh_password)}")
print(f"export DEPLOY_USER={shlex.quote(values.get('EC2_SSH_USER', 'ubuntu'))}")
print(f"export DEPLOY_PORT={shlex.quote(values.get('EC2_SSH_PORT', '22'))}")
api_host = host.replace(".", "-") + ".sslip.io"
print(f"export API_HOST={shlex.quote(api_host)}")
print(f"export BACKEND_ORIGIN={shlex.quote(f'https://{api_host}')}")
PY
# The generated file is mode 600 and all values are shell-quoted by Python.
. "$DEPLOY_VARS"

SSH=(sshpass -e ssh -p "$DEPLOY_PORT" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
RSYNC_SSH="sshpass -e ssh -p $DEPLOY_PORT -o StrictHostKeyChecking=accept-new"
export SSHPASS="$DEPLOY_PASSWORD"

printf '1/7 EC2 backend staging 디렉터리 준비\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "rm -rf '$REMOTE_STAGE' && mkdir -p '$REMOTE_STAGE'"

printf '2/7 FastAPI, worker, DB 파일만 EC2에 동기화\n'
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude '.venv/' \
  --exclude 'apps/web/' \
  --exclude 'node_modules/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.mypy_cache/' \
  -e "$RSYNC_SSH" "$ROOT/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/"
rsync -az -e "$RSYNC_SSH" "$DEPLOY_ENV" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/.env"

printf '3/7 EC2를 API/worker 전용 호스트로 구성\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$REMOTE_STAGE" "$API_HOST" <<'REMOTE'
set -Eeuo pipefail

APP_DIR="$1"
STAGE_DIR="$2"
SERVICE_USER="perspective"
API_HOST="$3"

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
  ca-certificates certbot curl mariadb-client mariadb-server nginx \
  python3 python3-certbot-nginx python3-venv rsync

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  sudo useradd --system --create-home --home-dir /var/lib/perspective --shell /usr/sbin/nologin "$SERVICE_USER"
fi

sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR"
sudo rsync -a --delete --exclude '.env' --exclude '.venv/' "$STAGE_DIR/" "$APP_DIR/"
sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0600 "$STAGE_DIR/.env" "$APP_DIR/.env"

# Next.js production processes and artifacts are forbidden on EC2.
sudo systemctl disable --now perspective-web.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/perspective-web.service
sudo rm -rf "$APP_DIR/apps/web"

sudo tee /etc/mysql/mariadb.conf.d/99-perspective.cnf >/dev/null <<'EOF'
[mariadbd]
bind-address = 127.0.0.1
skip-name-resolve
EOF
sudo systemctl enable --now mariadb
sudo systemctl restart mariadb

sudo -u "$SERVICE_USER" bash -c "set -a; . '$APP_DIR/.env'; set +a; exec python3 -" <<'PY' | sudo mariadb
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
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 \
  /var/lib/perspective /var/lib/perspective/.cache /var/lib/perspective/.cache/uv
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "cd '$APP_DIR' && uv sync --frozen --no-dev"
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "set -a; . '$APP_DIR/.env'; set +a; cd '$APP_DIR' && uv run alembic -c db/alembic.ini upgrade head"

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

sudo tee /etc/nginx/sites-available/perspective-news >/dev/null <<'EOF'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name __API_HOST__;
    client_max_body_size 10m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
    }

    location /health/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 10s;
    }

    # EC2 never serves the Next.js frontend. Vercel is the only production web host.
    location / {
        default_type text/plain;
        return 404 'frontend is deployed on Vercel\n';
    }
}
EOF
sudo sed -i "s/__API_HOST__/$API_HOST/g" /etc/nginx/sites-available/perspective-news

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/perspective-news /etc/nginx/sites-enabled/perspective-news
sudo nginx -t
sudo systemctl enable --now nginx
sudo certbot --nginx --non-interactive --agree-tos --register-unsafely-without-email \
  --redirect --keep-until-expiring -d "$API_HOST"
sudo systemctl daemon-reload
sudo systemctl enable perspective-api perspective-worker nginx
sudo systemctl restart perspective-api perspective-worker nginx
rm -rf "$STAGE_DIR"
REMOTE

printf '4/7 EC2 API readiness 확인\n'
curl --fail --silent --show-error --retry 10 --retry-delay 2 "$BACKEND_ORIGIN/health/ready" >/dev/null

printf '5/7 Vercel 프로젝트와 production 환경변수 구성\n'
if [[ ! -f "$WEB_DIR/.vercel/project.json" ]]; then
  if ! vercel project inspect "$VERCEL_PROJECT" --yes >/dev/null 2>&1; then
    vercel project add "$VERCEL_PROJECT" >/dev/null
  fi
  vercel link --yes --project "$VERCEL_PROJECT" --cwd "$WEB_DIR" >/dev/null
fi
vercel env add API_BACKEND_URL production --value "$BACKEND_ORIGIN" --force --no-sensitive --yes --cwd "$WEB_DIR" >/dev/null
vercel env add NEXT_PUBLIC_API_MODE production --value real --force --no-sensitive --yes --cwd "$WEB_DIR" >/dev/null

printf '6/7 Next.js를 Vercel production에 배포\n'
VERCEL_DEPLOYMENT_URL="$(vercel --prod --yes --cwd "$WEB_DIR")"
[[ "$VERCEL_DEPLOYMENT_URL" == https://* ]] || die "Vercel production URL을 확인하지 못했습니다: $VERCEL_DEPLOYMENT_URL"
VERCEL_URL="$(vercel inspect "$VERCEL_DEPLOYMENT_URL" --format=json --cwd "$WEB_DIR" | uv run python -c '
import json, sys
data = json.load(sys.stdin)
aliases = data.get("aliases") or []
print("https://" + aliases[0] if aliases else "https://" + data["url"])
')"
curl --fail --silent --show-error --retry 10 --retry-delay 2 "$VERCEL_URL" >/dev/null
curl --fail --silent --show-error --retry 10 --retry-delay 2 "$VERCEL_URL/api/v1/issues" >/dev/null

printf '7/7 EC2의 공개 URL/OAuth 경계를 Vercel origin으로 고정\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" sudo python3 - "$REMOTE_DIR/.env" "$VERCEL_URL" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
updates = {
    "PUBLIC_BASE_URL": origin,
    "WEB_BASE_URL": origin,
    "OAUTH_REDIRECT_ALLOWLIST": ",".join(
        f"{origin}/api/v1/auth/{provider}/callback" for provider in ("kakao", "naver", "google", "mock")
    ),
}
lines = path.read_text(encoding="utf-8").splitlines()
kept = [line for line in lines if line.partition("=")[0] not in updates]
kept.extend(f"{key}={shlex.quote(value)}" for key, value in updates.items())
path.write_text("\n".join(kept) + "\n", encoding="utf-8")
PY
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" \
  "sudo systemctl restart perspective-api perspective-worker && sudo systemctl is-active --quiet perspective-api perspective-worker && ! sudo systemctl is-enabled --quiet perspective-web 2>/dev/null && test ! -d '$REMOTE_DIR/apps/web'"

curl --fail --silent --show-error --retry 10 --retry-delay 2 "$VERCEL_URL/api/v1/issues" >/dev/null
printf '배포 완료: %s (Next.js: Vercel, API/worker/DB: EC2)\n' "$VERCEL_URL"
