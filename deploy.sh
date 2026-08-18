#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_DIR="$ROOT/apps/web"
ENV_FILE="$ROOT/.env"
REMOTE_DIR="/opt/perspective-news"
REMOTE_STAGE=""
DEPLOY_MANIFEST="$ROOT/deploy.manifest"
VERCEL_PROJECT="${VERCEL_PROJECT:-perspective-news}"
DEPLOY_ENV=""
DEPLOY_VARS=""
RELEASE_ID=""
ALLOW_DESTRUCTIVE_MIGRATIONS="${ALLOW_DESTRUCTIVE_MIGRATIONS:-0}"
BACKUP_CONFIRMED="${BACKUP_CONFIRMED:-0}"
DEPLOY_APPROVED_DIFF="${DEPLOY_APPROVED_DIFF:-}"
REMOTE_ROLLBACK_PENDING=0
REMOTE_ROLLBACK_READY=0

cd "$ROOT"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 명령을 찾을 수 없습니다."
}

cleanup() {
  if [[ "$REMOTE_ROLLBACK_PENDING" == "1" && "$REMOTE_ROLLBACK_READY" == "1" ]]; then
    # A failure after the remote release is committed but before the public
    # checks finish must leave the previous release and database in service.
    rollback_remote_release || true
    REMOTE_ROLLBACK_PENDING=0
  fi
  if [[ -n "$DEPLOY_ENV" && -f "$DEPLOY_ENV" ]]; then
    rm -f "$DEPLOY_ENV"
  fi
  if [[ -n "$DEPLOY_VARS" && -f "$DEPLOY_VARS" ]]; then
    rm -f "$DEPLOY_VARS"
  fi
}
trap cleanup EXIT INT TERM

append_untracked_diff() {
  local output="$1"
  local path status
  while IFS= read -r -d '' path; do
    if git diff --no-index --binary -- /dev/null "$ROOT/$path" >>"$output"; then
      :
    else
      status=$?
      [[ "$status" -eq 1 ]] || return "$status"
    fi
  done < <(git ls-files --others --exclude-standard -z)
}

verify_working_tree_approval() {
  local current_diff status
  if git diff --quiet HEAD -- && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    return 0
  fi
  [[ -n "$DEPLOY_APPROVED_DIFF" ]] || die "working tree가 dirty입니다. 정확히 승인된 patch를 DEPLOY_APPROVED_DIFF로 지정하세요."
  [[ -f "$DEPLOY_APPROVED_DIFF" ]] || die "DEPLOY_APPROVED_DIFF 파일을 찾을 수 없습니다: $DEPLOY_APPROVED_DIFF"
  [[ "$DEPLOY_APPROVED_DIFF" == /* ]] || die "DEPLOY_APPROVED_DIFF는 절대 경로여야 합니다."
  case "$DEPLOY_APPROVED_DIFF" in
    "$ROOT"/*) die "DEPLOY_APPROVED_DIFF는 저장소 밖의 읽기 전용 승인 patch여야 합니다." ;;
  esac

  current_diff="$(mktemp "${TMPDIR:-/tmp}/perspective-approved-diff.XXXXXX")"
  git diff --binary HEAD -- >"$current_diff"
  append_untracked_diff "$current_diff" || {
    status=$?
    rm -f "$current_diff"
    return "$status"
  }
  if ! cmp -s "$current_diff" "$DEPLOY_APPROVED_DIFF"; then
    rm -f "$current_diff"
    die "working tree diff가 DEPLOY_APPROVED_DIFF와 정확히 일치하지 않습니다. 배포를 중단합니다."
  fi
  rm -f "$current_diff"
}

for command in uv ssh sshpass rsync curl vercel git node npm; do
  need "$command"
done
[[ -f "$ENV_FILE" ]] || die "저장소 루트에 .env 파일이 필요합니다."
[[ -f "$WEB_DIR/package.json" ]] || die "apps/web/package.json이 없습니다."
[[ -f "$DEPLOY_MANIFEST" ]] || die "deploy.manifest가 없습니다."

if [[ "$(uname -s)" == "Darwin" ]]; then
  mode="$(stat -f '%Lp' "$ENV_FILE")"
else
  mode="$(stat -c '%a' "$ENV_FILE")"
fi
[[ "$mode" == "600" ]] || die ".env 권한은 600이어야 합니다. 현재: $mode"

if [[ -f "$WEB_DIR/.env.local" ]]; then
  if [[ "$(uname -s)" == "Darwin" ]]; then
    web_env_mode="$(stat -f '%Lp' "$WEB_DIR/.env.local")"
  else
    web_env_mode="$(stat -c '%a' "$WEB_DIR/.env.local")"
  fi
  [[ "$web_env_mode" == "600" ]] || die "apps/web/.env.local 권한은 600이어야 합니다. 현재: $web_env_mode"
fi

while IFS= read -r -d '' path; do
  case "$path" in
    .env.example|*/.env.example) ;;
    .env|*/.env|.env.*|*/.env.*|*.pem|*.key|*.p12)
      die "secret-bearing file must not be tracked or staged: $path" ;;
  esac
done < <(git ls-files --cached --others --exclude-standard -z)

private_key_pattern='BEGIN[[:space:]]+(RSA|EC|OPENSSH|PRIVATE)[[:space:]]+KEY'
access_key_prefix='AKIA'
vercel_key_name='VERCEL_OIDC_TOKEN'
if git grep -nE "$private_key_pattern|${access_key_prefix}[0-9A-Z]{16}|${vercel_key_name}[[:space:]]*=[[:space:]]*[^<[:space:]]" -- ':!*.example'; then
  die "tracked secret material detected; remove it and rotate the credential"
fi

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

preflight() {
  printf '0/8 배포 preflight: 승인된 working tree와 검증 게이트 실행\n'
  git diff --check
  git diff --cached --check
  verify_working_tree_approval

  while IFS= read -r manifest_path; do
    [[ -n "$manifest_path" ]] || continue
    if [[ "$manifest_path" == */ ]]; then
      [[ -d "$ROOT/${manifest_path%/}" ]] || die "deploy.manifest directory is missing: $manifest_path"
    else
      [[ -f "$ROOT/$manifest_path" ]] || die "deploy.manifest file is missing: $manifest_path"
    fi
    case "$manifest_path" in
      apps/web/*|tests/*|docs/*|.agents/*|.playwright-cli/*|output/*|PPT_VIDEO/*)
        die "deploy.manifest contains a non-runtime path: $manifest_path" ;;
    esac
  done < "$DEPLOY_MANIFEST"

  uv sync --frozen --all-groups
  uv run ruff check apps db tests
  uv run mypy apps tests
  uv run pytest
  (cd "$WEB_DIR" && npm ci)
  (cd "$WEB_DIR" && npm test)
  (cd "$WEB_DIR" && npm run lint)
  (cd "$WEB_DIR" && npm run typecheck)
  (cd "$WEB_DIR" && NEXT_PUBLIC_API_MODE=real npm run build)
  (cd "$WEB_DIR" && npx playwright install chromium)
  (cd "$WEB_DIR" && npm run test:e2e)
  (cd "$WEB_DIR" && npm run test:a11y)
  (cd "$WEB_DIR" && npm run test:e2e:real)
  ./run.sh openapi
  uv lock --check
  dependency_snapshot="$(mktemp "${TMPDIR:-/tmp}/perspective-python-freeze.XXXXXX")"
  uv pip freeze --exclude-editable >"$dependency_snapshot"
  [[ -s "$dependency_snapshot" ]] || die "uv pip freeze returned no installed dependencies"
  uv run --no-project --with pip-audit pip-audit \
      --requirement "$dependency_snapshot" --no-deps --disable-pip --strict --format=columns
  rm -f "$dependency_snapshot"
  (cd "$WEB_DIR" && npm audit --audit-level=high)
  printf '배포 preflight 통과: 원격 mutation을 시작합니다.\n'
}

RELEASE_ID="${DEPLOY_RELEASE_ID:-$(date -u +%Y%m%d%H%M%S)-$(git rev-parse --short HEAD)}"
[[ "$RELEASE_ID" =~ ^[A-Za-z0-9._-]+$ ]] || die "DEPLOY_RELEASE_ID has unsafe characters"
[[ "$ALLOW_DESTRUCTIVE_MIGRATIONS" == "0" || "$ALLOW_DESTRUCTIVE_MIGRATIONS" == "1" ]] || die "ALLOW_DESTRUCTIVE_MIGRATIONS must be 0 or 1"
[[ "$BACKUP_CONFIRMED" == "0" || "$BACKUP_CONFIRMED" == "1" ]] || die "BACKUP_CONFIRMED must be 0 or 1"
REMOTE_STAGE="/tmp/perspective-news-stage-$RELEASE_ID"
preflight

SSH=(sshpass -e ssh -p "$DEPLOY_PORT" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
RSYNC_SSH="sshpass -e ssh -p $DEPLOY_PORT -o StrictHostKeyChecking=accept-new"
export SSHPASS="$DEPLOY_PASSWORD"

rollback_remote_release() {
  [[ "$REMOTE_ROLLBACK_READY" == "1" ]] || return 1
  "${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$RELEASE_ID" <<'REMOTE_ROLLBACK'
set -Eeuo pipefail
APP_DIR="$1"
RELEASE_ID="$2"
CURRENT_LINK="$APP_DIR/current"
RELEASE_DIR="$APP_DIR/releases/$RELEASE_ID"
STATE_PATH="$APP_DIR/.rollback-$RELEASE_ID"
[[ -f "$STATE_PATH" ]] || exit 0
mapfile -t state < <(sudo cat "$STATE_PATH")
PREVIOUS_RELEASE="${state[0]:-}"
DATABASE_BACKUP_PATH="${state[1]:-}"
restore_status=0
if [[ -n "$DATABASE_BACKUP_PATH" && -s "$DATABASE_BACKUP_PATH" ]]; then
  sudo gzip -dc "$DATABASE_BACKUP_PATH" | sudo mariadb || restore_status=$?
else
  echo "rollback database backup is missing: $DATABASE_BACKUP_PATH" >&2
  restore_status=1
fi
if [[ "$restore_status" == "0" && -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
  next_link="${CURRENT_LINK}.next.$$"
  sudo rm -f "$next_link"
  sudo ln -s "$PREVIOUS_RELEASE" "$next_link"
  sudo mv -Tf "$next_link" "$CURRENT_LINK"
  sudo systemctl daemon-reload
  sudo systemctl restart perspective-api
  sudo systemctl restart perspective-worker
else
  echo "rollback database restore failed; services remain stopped" >&2
  sudo systemctl stop perspective-api || true
  sudo systemctl stop perspective-worker || true
  if [[ -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
    next_link="${CURRENT_LINK}.next.$$"
    sudo rm -f "$next_link"
    sudo ln -s "$PREVIOUS_RELEASE" "$next_link"
    sudo mv -Tf "$next_link" "$CURRENT_LINK"
  fi
fi
sudo rm -f "$STATE_PATH"
if [[ -d "$RELEASE_DIR" && "$RELEASE_DIR" != "$CURRENT_LINK" ]]; then
  sudo rm -rf "$RELEASE_DIR"
fi
exit "$restore_status"
REMOTE_ROLLBACK
}

finalize_remote_release() {
  [[ "$REMOTE_ROLLBACK_READY" == "1" ]] || return 1
  "${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" sudo rm -f "$REMOTE_DIR/.rollback-$RELEASE_ID"
}
REMOTE_ROLLBACK_READY=1

printf '1/8 EC2 backend staging 디렉터리 준비\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" "rm -rf '$REMOTE_STAGE' && mkdir -p '$REMOTE_STAGE'"

printf '2/8 allowlist manifest로 FastAPI, worker, DB runtime만 EC2에 동기화\n'
rsync -az --delete --prune-empty-dirs --files-from="$DEPLOY_MANIFEST" \
  -e "$RSYNC_SSH" "$ROOT/" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/"
rsync -az -e "$RSYNC_SSH" "$DEPLOY_ENV" "$DEPLOY_USER@$DEPLOY_HOST:$REMOTE_STAGE/.env"

printf '3/8 EC2를 API/worker 전용 호스트로 구성\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" "$REMOTE_STAGE" "$API_HOST" "$RELEASE_ID" "$ALLOW_DESTRUCTIVE_MIGRATIONS" "$BACKUP_CONFIRMED" <<'REMOTE'
set -Eeuo pipefail

APP_DIR="$1"
STAGE_DIR="$2"
SERVICE_USER="perspective"
API_HOST="$3"
RELEASE_ID="$4"
ALLOW_DESTRUCTIVE_MIGRATIONS="$5"
BACKUP_CONFIRMED="$6"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_LINK="$APP_DIR/current"
RELEASE_DIR="$RELEASES_DIR/$RELEASE_ID"
BACKUPS_DIR="$APP_DIR/backups"
DATABASE_BACKUP_PATH="$BACKUPS_DIR/$RELEASE_ID.sql.gz"
ROLLBACK_STATE_PATH="$APP_DIR/.rollback-$RELEASE_ID"
PREVIOUS_RELEASE=""
ROLLBACK_REQUIRED=0
MIGRATION_ATTEMPTED=0
LIVE_SERVICES_STOPPED=0

atomic_switch() {
  local target="$1"
  local next_link="${CURRENT_LINK}.next.$$"
  sudo rm -f "$next_link"
  sudo ln -s "$target" "$next_link"
  sudo mv -Tf "$next_link" "$CURRENT_LINK"
}

stop_live_services() {
  local service
  for service in perspective-api perspective-worker; do
    if sudo systemctl cat "$service.service" >/dev/null 2>&1; then
      sudo systemctl stop "$service.service"
      if sudo systemctl is-active --quiet "$service.service"; then
        echo "service remained active while preparing migration: $service" >&2
        return 1
      fi
    fi
  done
  LIVE_SERVICES_STOPPED=1
}

create_database_backup() {
  sudo install -d -o root -g root -m 0700 "$BACKUPS_DIR"
  # Use the local MariaDB root socket account so the dump includes every
  # object required to restore a failed migration, including DROP/CREATE DB.
  sudo bash -c "set -o pipefail; mariadb-dump --add-drop-database --databases '$DB_ADMIN_DATABASE' --single-transaction --routines --events --triggers | gzip -c > '$DATABASE_BACKUP_PATH'"
  sudo test -s "$DATABASE_BACKUP_PATH"
  sudo gzip -t "$DATABASE_BACKUP_PATH"
  sudo chmod 0600 "$DATABASE_BACKUP_PATH"
}

restore_database() {
  [[ -s "$DATABASE_BACKUP_PATH" ]] || {
    echo "database backup is missing or empty: $DATABASE_BACKUP_PATH" >&2
    return 1
  }
  sudo gzip -dc "$DATABASE_BACKUP_PATH" | sudo mariadb
}

write_rollback_state() {
  printf '%s\n%s\n' "$PREVIOUS_RELEASE" "$DATABASE_BACKUP_PATH" \
    | sudo tee "$ROLLBACK_STATE_PATH" >/dev/null
  sudo chmod 0600 "$ROLLBACK_STATE_PATH"
}

rollback_release() {
  local exit_code="${1:-$?}"
  local restore_status=0
  # This function is invoked by ERR; disable the trap while restoring so a
  # second command failure cannot recurse and hide the original failure.
  trap - ERR
  if [[ "$MIGRATION_ATTEMPTED" == "1" ]]; then
    restore_database || restore_status=$?
  fi
  if [[ "$restore_status" == "0" && "$ROLLBACK_REQUIRED" == "1" && -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
    atomic_switch "$PREVIOUS_RELEASE" || true
    sudo systemctl daemon-reload || true
    sudo systemctl restart perspective-api || true
    sudo systemctl restart perspective-worker || true
  elif [[ "$ROLLBACK_REQUIRED" == "1" && -z "$PREVIOUS_RELEASE" ]]; then
    sudo rm -f "$CURRENT_LINK"
  elif [[ "$restore_status" != "0" ]]; then
    echo "database restore failed; leaving services stopped for manual recovery" >&2
    sudo systemctl stop perspective-api || true
    sudo systemctl stop perspective-worker || true
    if [[ -n "$PREVIOUS_RELEASE" && -d "$PREVIOUS_RELEASE" ]]; then
      atomic_switch "$PREVIOUS_RELEASE" || true
    fi
  fi
  sudo rm -f "$ROLLBACK_STATE_PATH"
  if [[ -d "$RELEASE_DIR" && "$RELEASE_DIR" != "$CURRENT_LINK" ]]; then
    sudo rm -rf "$RELEASE_DIR"
  fi
  if [[ -d "$STAGE_DIR" ]]; then
    sudo rm -rf "$STAGE_DIR"
  fi
  exit "$exit_code"
}
trap rollback_release ERR

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

sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$APP_DIR" "$RELEASES_DIR"
if [[ -L "$CURRENT_LINK" ]]; then
  PREVIOUS_RELEASE="$(readlink -f "$CURRENT_LINK")"
fi
ROLLBACK_REQUIRED=1
sudo mv "$STAGE_DIR" "$RELEASE_DIR"
sudo chown "$SERVICE_USER:$SERVICE_USER" "$RELEASE_DIR/.env"
sudo chmod 0600 "$RELEASE_DIR/.env"
set -a
. "$RELEASE_DIR/.env"
set +a

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

sudo -u "$SERVICE_USER" bash -c "set -a; . '$RELEASE_DIR/.env'; set +a; exec python3 -" <<'PY' | sudo mariadb
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

sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$RELEASE_DIR"
sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 \
  /var/lib/perspective /var/lib/perspective/.cache /var/lib/perspective/.cache/uv
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "cd '$RELEASE_DIR' && uv sync --frozen --no-dev"
stop_live_services
create_database_backup
if grep -R -n -E -i 'drop_(table|column|index)|drop[[:space:]]+(table|column|index)' "$RELEASE_DIR/db/alembic/versions" >/dev/null 2>&1; then
  if [[ "$ALLOW_DESTRUCTIVE_MIGRATIONS" != "1" || "$BACKUP_CONFIRMED" != "1" ]]; then
    echo "destructive migration detected; require ALLOW_DESTRUCTIVE_MIGRATIONS=1 and BACKUP_CONFIRMED=1" >&2
    rollback_release 1
  fi
fi
MIGRATION_ATTEMPTED=1
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c "set -a; . '$RELEASE_DIR/.env'; set +a; cd '$RELEASE_DIR' && uv run alembic -c db/alembic.ini upgrade head"
write_rollback_state

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
WorkingDirectory=$APP_DIR/current
EnvironmentFile=$APP_DIR/current/.env
ExecStart=$APP_DIR/current/.venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1
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
WorkingDirectory=$APP_DIR/current
EnvironmentFile=$APP_DIR/current/.env
ExecStart=$APP_DIR/current/.venv/bin/python -m apps.worker.worker.main
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

# Start the candidate on an isolated port and validate MariaDB readiness before
# changing the live symlink. The current release remains untouched on failure.
candidate_log="/tmp/perspective-news-${RELEASE_ID}.log"
sudo -u "$SERVICE_USER" env HOME=/var/lib/perspective bash -c \
  "set -a; . '$RELEASE_DIR/.env'; set +a; cd '$RELEASE_DIR'; exec .venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 18000" \
  >"$candidate_log" 2>&1 &
candidate_pid=$!
candidate_ready=0
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18000/health/ready >/dev/null; then
    candidate_ready=1
    break
  fi
  sleep 1
done
kill "$candidate_pid" 2>/dev/null || true
wait "$candidate_pid" 2>/dev/null || true
if [[ "$candidate_ready" != "1" ]]; then
  cat "$candidate_log" >&2 || true
  rollback_release 1
fi

# Drain the old worker before switching. A stop timeout is a failed release,
# so the ERR trap restores the previous symlink and services.
if sudo systemctl is-active --quiet perspective-worker; then
  sudo systemctl stop perspective-worker
fi
ROLLBACK_REQUIRED=1
atomic_switch "$RELEASE_DIR"
sudo systemctl daemon-reload
sudo systemctl restart perspective-api
sudo systemctl restart perspective-worker
sudo systemctl restart nginx
if ! curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health/ready >/dev/null; then
  cat "$candidate_log" >&2 || true
  rollback_release 1
fi
sudo systemctl is-active --quiet perspective-api
sudo systemctl is-active --quiet perspective-worker
ROLLBACK_REQUIRED=0
rm -f "$candidate_log"
REMOTE
REMOTE_ROLLBACK_PENDING=1

printf '4/8 EC2 API readiness 확인\n'
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-all-errors "$BACKEND_ORIGIN/health/ready" >/dev/null

printf '5/8 Vercel 프로젝트와 production 환경변수 구성\n'
if [[ ! -f "$WEB_DIR/.vercel/project.json" ]]; then
  if ! vercel project inspect "$VERCEL_PROJECT" --yes >/dev/null 2>&1; then
    vercel project add "$VERCEL_PROJECT" >/dev/null
  fi
  vercel link --yes --project "$VERCEL_PROJECT" --cwd "$WEB_DIR" >/dev/null
fi
vercel env add API_BACKEND_URL production --value "$BACKEND_ORIGIN" --force --no-sensitive --yes --cwd "$WEB_DIR" >/dev/null
vercel env add NEXT_PUBLIC_API_MODE production --value real --force --no-sensitive --yes --cwd "$WEB_DIR" >/dev/null

printf '6/8 Next.js를 Vercel production에 배포\n'
VERCEL_DEPLOYMENT_URL="$(vercel --prod --yes --format=json --cwd "$WEB_DIR" | uv run python -c '
import json, sys

payload = json.load(sys.stdin)
deployment = payload.get("deployment", payload)
url = deployment.get("url")
if not isinstance(url, str) or not url:
    raise SystemExit("Vercel deployment JSON does not contain a URL")
print(url if url.startswith("https://") else "https://" + url)
')"
[[ "$VERCEL_DEPLOYMENT_URL" == https://* ]] || die "Vercel production URL을 확인하지 못했습니다: $VERCEL_DEPLOYMENT_URL"
VERCEL_URL="$(vercel inspect "$VERCEL_DEPLOYMENT_URL" --format=json --cwd "$WEB_DIR" | uv run python -c '
import json, sys
data = json.load(sys.stdin)
aliases = data.get("aliases") or []
print("https://" + aliases[0] if aliases else "https://" + data["url"])
')"
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-all-errors "$VERCEL_URL" >/dev/null
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-all-errors "$VERCEL_URL/api/v1/issues" >/dev/null

printf '7/8 EC2의 공개 URL/OAuth 경계를 Vercel origin으로 고정\n'
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" sudo python3 - "$REMOTE_DIR/current/.env" "$VERCEL_URL" <<'PY'
from __future__ import annotations

import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
origin = sys.argv[2].rstrip("/")
backup = path.with_name(".env.before-vercel")
backup.write_bytes(path.read_bytes())
backup.chmod(0o600)
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
"${SSH[@]}" "$DEPLOY_USER@$DEPLOY_HOST" bash -s -- "$REMOTE_DIR" <<'REMOTE_FINAL'
set -Eeuo pipefail
APP_DIR="$1"
ENV_PATH="$APP_DIR/current/.env"
BACKUP_PATH="$APP_DIR/current/.env.before-vercel"
if ! sudo systemctl restart perspective-api perspective-worker \
  || ! sudo systemctl is-active --quiet perspective-api perspective-worker \
  || ! curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8000/health/ready >/dev/null; then
  sudo cp "$BACKUP_PATH" "$ENV_PATH"
  sudo chown perspective:perspective "$ENV_PATH"
  sudo chmod 0600 "$ENV_PATH"
  sudo systemctl restart perspective-api perspective-worker || true
  exit 1
fi
sudo rm -f "$BACKUP_PATH"
! sudo systemctl is-enabled --quiet perspective-web 2>/dev/null
test ! -d "$APP_DIR/apps/web"
test -L "$APP_DIR/current"
REMOTE_FINAL

curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-all-errors "$VERCEL_URL/api/v1/issues" >/dev/null
finalize_remote_release
REMOTE_ROLLBACK_PENDING=0
printf '8/8 배포 완료: %s (Next.js: Vercel, API/worker/DB: EC2)\n' "$VERCEL_URL"
