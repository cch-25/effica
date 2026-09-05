#!/usr/bin/env bash
set -Eeuo pipefail
exec 9>/run/lock/effica-storage-maintenance.lock
flock -n 9 || exit 0
current="$(readlink -f /opt/perspective-news/current)"
resume_api=0
resume_worker=0
systemctl is-active --quiet perspective-api && resume_api=1
systemctl is-active --quiet perspective-worker && resume_worker=1
restore_services() {
  local status=$?
  trap - EXIT
  if [[ "$resume_api" == 1 ]]; then
    systemctl start perspective-api || status=1
    ready=0
    for _ in {1..30}; do
      if curl -fsS --max-time 2 http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
        ready=1
        break
      fi
      sleep 1
    done
    [[ "$ready" == 1 ]] || status=1
  fi
  if [[ "$resume_worker" == 1 ]]; then systemctl start perspective-worker || status=1; fi
  exit "$status"
}
trap restore_services EXIT
systemctl stop perspective-worker
systemctl stop perspective-api
sudo -u perspective bash -c '
  set -Eeuo pipefail; set -a; . "$1/.env"; set +a
  export ARTICLE_RETENTION_WRITERS_STOPPED=1
  cd "$1"
  exec .venv/bin/python -m db.storage_maintenance
' -- "$current"
