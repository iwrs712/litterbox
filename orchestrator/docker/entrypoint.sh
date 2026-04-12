#!/bin/sh
set -eu

role="${1:-${ORCHESTRATOR_ROLE:-api}}"
ttl_pid=""

cleanup() {
  if [ -n "${ttl_pid}" ] && kill -0 "${ttl_pid}" 2>/dev/null; then
    kill "${ttl_pid}" 2>/dev/null || true
    wait "${ttl_pid}" 2>/dev/null || true
  fi
}

case "$role" in
  api)
    exec uvicorn orchestrator.main:app --host 0.0.0.0 --port 8080
    ;;
  worker)
    trap cleanup INT TERM EXIT
    python -m orchestrator.worker_runner ttl &
    ttl_pid="$!"
    exec celery -A orchestrator.celery_app:celery_app worker -l info -Q pool_reconcile,webhook_delivery -n worker@%h
    ;;
  *)
    exec "$@"
    ;;
esac
