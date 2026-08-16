#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT/.env"
API_PID=""
WEB_PID=""
TUNNEL_PID=""

cd "$ROOT"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 명령을 찾을 수 없습니다."
}

cleanup() {
  trap - EXIT INT TERM
  for pid in "$WEB_PID" "$API_PID" "$TUNNEL_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$WEB_PID" "$API_PID" "$TUNNEL_PID"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
}

trap cleanup EXIT INT TERM

load_env() {
  need uv
  [[ -f "$ENV_FILE" ]] || die "저장소 루트에 .env 파일이 필요합니다."
  if [[ "$(uname -s)" != "MINGW" ]]; then
    local mode
    if [[ "$(uname -s)" == "Darwin" ]]; then
      mode="$(stat -f '%Lp' "$ENV_FILE")"
    else
      mode="$(stat -c '%a' "$ENV_FILE")"
    fi
    [[ "$mode" == "600" ]] || die ".env 권한은 600이어야 합니다. 현재: $mode"
  fi
  eval "$(uv run python - "$ENV_FILE" <<'PY'
import re
import shlex
import sys
from dotenv import dotenv_values

for key, value in dotenv_values(sys.argv[1]).items():
    if value is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
        print(f"export {key}={shlex.quote(value)}")
PY
)"
}

required_env() {
  local name="$1"
  [[ -n "${!name:-}" ]] || die ".env에 $name 값이 필요합니다."
  [[ "${!name}" != \<* ]] || die ".env의 $name placeholder를 실제 값으로 교체하세요."
}

prepare_remote_db() {
  load_env
  required_env EC2_IPV4_PUBLIC_ADDRESS
  required_env EC2_PASSWORD
  required_env DATABASE_URL
  required_env SESSION_SECRET
  [[ ${#SESSION_SECRET} -ge 32 ]] || die "SESSION_SECRET은 최소 32자여야 합니다."
  need ssh
  need sshpass

  local tunnel_port="${DB_TUNNEL_PORT:-13306}"
  local ssh_user="${EC2_SSH_USER:-ubuntu}"
  local ssh_port="${EC2_SSH_PORT:-22}"

  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$tunnel_port" -sTCP:LISTEN >/dev/null 2>&1; then
    die "로컬 포트 $tunnel_port 가 이미 사용 중입니다. DB_TUNNEL_PORT를 변경하세요."
  fi

  SSHPASS="$EC2_PASSWORD" sshpass -e ssh \
    -p "$ssh_port" \
    -o StrictHostKeyChecking=accept-new \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -N -L "127.0.0.1:${tunnel_port}:127.0.0.1:3306" \
    "${ssh_user}@${EC2_IPV4_PUBLIC_ADDRESS}" &
  TUNNEL_PID=$!
  sleep 1
  kill -0 "$TUNNEL_PID" 2>/dev/null || die "원격 MariaDB SSH 터널을 열지 못했습니다."

  export DATABASE_URL
  DATABASE_URL="$(DATABASE_URL="$DATABASE_URL" DB_TUNNEL_PORT="$tunnel_port" uv run python - <<'PY'
import os
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"]).set(
    host="127.0.0.1", port=int(os.environ["DB_TUNNEL_PORT"])
)
print(url.render_as_string(hide_password=False))
PY
)"
  export APP_ENV=local
  export APP_BACKEND=mariadb
  export PUBLIC_BASE_URL="http://127.0.0.1:8000"
  export WEB_BASE_URL="http://127.0.0.1:3000"
  export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000/api/v1"
}

sync_python() {
  need uv
  uv sync --frozen
}

prepare_web() {
  [[ -f "$ROOT/apps/web/package.json" ]] || die "apps/web/package.json이 없습니다. Next.js 앱을 먼저 추가하세요."
  need node
  need npm
  if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
    if [[ -f "$ROOT/apps/web/package-lock.json" ]]; then
      (cd "$ROOT/apps/web" && npm ci)
    else
      (cd "$ROOT/apps/web" && npm install)
    fi
  fi
}

check_db() {
  uv run python - <<'PY'
import asyncio
from sqlalchemy import text
from apps.api.app.core.config import get_settings
from apps.api.app.db.session import create_engine, dispose_engine

async def main() -> None:
    engine = create_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            version = (await connection.execute(text("SELECT VERSION()"))).scalar_one()
            print(f"MariaDB connection ready: {version}")
    finally:
        await dispose_engine()

asyncio.run(main())
PY
}

openapi() {
  uv run python - "$@" <<'PY'
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from apps.api.app.main import app

ROOT = Path.cwd()
CONTRACT = ROOT / "contracts" / "openapi.json"
CHECKSUM = ROOT / "contracts" / "checksum.txt"
METHODS = {"get", "post", "put", "patch", "delete"}
EXPECTED_OPERATIONS = {
    ("GET", "/health/live"), ("GET", "/health/ready"),
    ("GET", "/api/v1/auth/{provider}/start"), ("GET", "/api/v1/auth/{provider}/callback"),
    ("POST", "/api/v1/auth/logout"), ("GET", "/api/v1/me"),
    ("GET", "/api/v1/consents"), ("POST", "/api/v1/me/consents"),
    ("POST", "/api/v1/me/questionnaire-responses"), ("PATCH", "/api/v1/me/demographics"),
    ("POST", "/api/v1/me/export"), ("DELETE", "/api/v1/me"),
    ("GET", "/api/v1/feed"), ("GET", "/api/v1/issues"),
    ("GET", "/api/v1/issues/{issue_id}"), ("GET", "/api/v1/issues/{issue_id}/articles"),
    ("GET", "/api/v1/articles/{article_id}"), ("GET", "/api/v1/articles/{article_id}/assessments"),
    ("GET", "/api/v1/articles/{article_id}/score"), ("GET", "/api/v1/articles/{article_id}/score-history"),
    ("GET", "/api/v1/compare"), ("GET", "/api/v1/sources/{source_id}"),
    ("POST", "/api/v1/articles/{article_id}/read-sessions"), ("GET", "/api/v1/r/{token}"),
    ("POST", "/api/v1/read-sessions/{read_session_id}/return"),
    ("GET", "/api/v1/articles/{article_id}/votes/aggregate"),
    ("PUT", "/api/v1/articles/{article_id}/vote"), ("DELETE", "/api/v1/articles/{article_id}/vote"),
    ("GET", "/api/v1/me/credits"), ("GET", "/api/v1/me/progress"),
    ("GET", "/api/v1/me/efficacy"), ("POST", "/api/v1/me/efficacy-responses"),
    ("GET", "/api/v1/visualization/points"), ("GET", "/api/v1/visualization/timeline"),
    ("POST", "/api/v1/share-cards"), ("GET", "/api/v1/share-cards/{share_card_id}"),
    ("GET", "/api/v1/public/share/{public_token}"), ("GET", "/api/v1/public/share/{public_token}/image"),
    ("DELETE", "/api/v1/share-cards/{share_card_id}"),
    ("GET", "/api/v1/admin/sources"), ("POST", "/api/v1/admin/sources"),
    ("GET", "/api/v1/admin/sources/{source_id}"), ("PATCH", "/api/v1/admin/sources/{source_id}"),
    ("POST", "/api/v1/admin/sources/{source_id}/crawl"), ("GET", "/api/v1/admin/crawls"),
    ("POST", "/api/v1/admin/issues/{issue_id}/merge"), ("POST", "/api/v1/admin/issues/{issue_id}/split"),
    ("PATCH", "/api/v1/admin/issues/{issue_id}"), ("GET", "/api/v1/admin/models"),
    ("POST", "/api/v1/admin/models"), ("GET", "/api/v1/admin/models/{model_id}"),
    ("PATCH", "/api/v1/admin/models/{model_id}"), ("POST", "/api/v1/admin/articles/{article_id}/analyze"),
    ("GET", "/api/v1/admin/analysis-runs/{run_id}"), ("GET", "/api/v1/admin/weights"),
    ("POST", "/api/v1/admin/weights"), ("POST", "/api/v1/admin/weights/{weight_id}/simulate"),
    ("POST", "/api/v1/admin/weights/{weight_id}/publish"), ("POST", "/api/v1/admin/weights/{weight_id}/rollback"),
    ("GET", "/api/v1/admin/autopilot/recommendations"),
    ("POST", "/api/v1/admin/autopilot/recommendations/generate"),
    ("POST", "/api/v1/admin/autopilot/recommendations/{recommendation_id}/approve"),
    ("POST", "/api/v1/admin/autopilot/recommendations/{recommendation_id}/reject"),
    ("PUT", "/api/v1/admin/autopilot/settings"), ("GET", "/api/v1/admin/jobs"),
    ("POST", "/api/v1/admin/jobs/{job_id}/retry"), ("POST", "/api/v1/admin/jobs/{job_id}/cancel"),
    ("GET", "/api/v1/admin/audit"), ("GET", "/api/v1/admin/metrics/efficacy"),
}
VERSIONED_ADMIN_MUTATIONS = {
    ("PATCH", "/api/v1/admin/sources/{source_id}"),
    ("PATCH", "/api/v1/admin/issues/{issue_id}"),
    ("PATCH", "/api/v1/admin/models/{model_id}"),
    ("POST", "/api/v1/admin/weights/{weight_id}/publish"),
    ("POST", "/api/v1/admin/weights/{weight_id}/rollback"),
    ("PUT", "/api/v1/admin/autopilot/settings"),
}

schema = app.openapi()
payload = (json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
digest = hashlib.sha256(payload).hexdigest()
actual = {(method.upper(), path) for path, item in schema["paths"].items() for method in item if method in METHODS}
errors: list[str] = []
if actual != EXPECTED_OPERATIONS:
    errors.append(f"operation inventory differs: missing={sorted(EXPECTED_OPERATIONS-actual)}, extra={sorted(actual-EXPECTED_OPERATIONS)}")
ids = [item[method]["operationId"] for item in schema["paths"].values() for method in item if method in METHODS]
duplicates = sorted({value for value in ids if ids.count(value) > 1})
if duplicates:
    errors.append(f"duplicate operationId values: {duplicates}")
for method, path in actual:
    operation = schema["paths"][path][method.lower()]
    codes = set(operation.get("responses", {}))
    if "400" not in codes or "422" not in codes:
        errors.append(f"stable error schemas missing: {method} {path}")
    params = {parameter["name"] for parameter in operation.get("parameters", [])}
    if path.startswith("/api/v1/admin/") and method in {"POST", "PUT", "PATCH", "DELETE"} and "Idempotency-Key" not in params:
        errors.append(f"Idempotency-Key missing: {method} {path}")
    if (method, path) in VERSIONED_ADMIN_MUTATIONS and "If-Match" not in params:
        errors.append(f"If-Match missing: {method} {path}")

parser = argparse.ArgumentParser()
parser.add_argument("--write", action="store_true")
args = parser.parse_args()
if args.write:
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_bytes(payload)
    CHECKSUM.write_text(f"sha256  {digest}  openapi.json\n")
else:
    if not CONTRACT.exists() or CONTRACT.read_bytes() != payload:
        errors.append("committed contracts/openapi.json differs from executable FastAPI OpenAPI")
    if not CHECKSUM.exists() or CHECKSUM.read_text() != f"sha256  {digest}  openapi.json\n":
        errors.append("contracts/checksum.txt does not match normalized OpenAPI")
if errors:
    print("\n".join(f"ERROR: {error}" for error in errors))
    raise SystemExit(1)
print(f"OpenAPI verified: {len(EXPECTED_OPERATIONS)} operations, sha256={digest}")
PY
}

verify_paths() {
  local bad
  bad="$(git status --porcelain=v1 | awk '{print substr($0,4)}' | grep -E '^(apps/web/|apps/web/tests/|docs/decisions/mas-a/)' || true)"
  if [[ -n "$bad" ]]; then
    printf 'MAS_B ownership violation:\n%s\n' "$bad" >&2
    return 1
  fi
  printf 'MAS_B path ownership verified\n'
}

start_all() {
  prepare_remote_db
  sync_python
  prepare_web
  uv run alembic -c db/alembic.ini upgrade head
  uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000 &
  API_PID=$!
  (cd "$ROOT/apps/web" && npm run dev -- --hostname 127.0.0.1 --port 3000) &
  WEB_PID=$!
  printf 'FastAPI: http://127.0.0.1:8000 | Next.js: http://127.0.0.1:3000 | DB: EC2 SSH tunnel\n'
  while kill -0 "$API_PID" 2>/dev/null && kill -0 "$WEB_PID" 2>/dev/null; do
    sleep 1
  done
  wait "$API_PID" 2>/dev/null || true
  wait "$WEB_PID" 2>/dev/null || true
  return 1
}

usage() {
  cat <<'EOF'
Usage: ./run.sh [command]

  start         원격 MariaDB 터널 + FastAPI + Next.js 통합 실행 (기본값)
  api           원격 MariaDB를 사용하는 FastAPI 실행
  worker        원격 MariaDB를 사용하는 백그라운드 worker 실행
  check-db      원격 MariaDB 연결 점검
  migrate       원격 MariaDB Alembic 마이그레이션
  seed [args]   원격 MariaDB 개발 시드 적용
  test          백엔드 단위 테스트
  integration   통합 테스트
  openapi       OpenAPI 계약 검증 (--write로 갱신)
  verify        lint, type check, test, OpenAPI, 소유 경로 전체 검증
EOF
}

command_name="${1:-start}"
if [[ $# -gt 0 ]]; then shift; fi

case "$command_name" in
  start)
    start_all
    ;;
  api)
    prepare_remote_db
    sync_python
    uv run uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8000
    ;;
  worker)
    prepare_remote_db
    sync_python
    uv run python -m apps.worker.worker.main
    ;;
  check-db)
    prepare_remote_db
    sync_python
    check_db
    ;;
  migrate)
    prepare_remote_db
    sync_python
    uv run alembic -c db/alembic.ini upgrade head
    ;;
  seed)
    prepare_remote_db
    sync_python
    uv run python -m db.seeds.seed "$@"
    ;;
  test)
    sync_python
    uv run pytest apps/api/tests apps/worker/tests "$@"
    ;;
  integration)
    sync_python
    uv run pytest tests/integration "$@"
    ;;
  openapi)
    sync_python
    openapi "$@"
    ;;
  verify)
    sync_python
    uv run ruff check apps db tests
    uv run mypy apps/api/app apps/worker/worker
    uv run pytest
    openapi
    verify_paths
    ;;
  help|-h|--help)
    usage
    ;;
  *)
    usage >&2
    die "알 수 없는 command: $command_name"
    ;;
esac
