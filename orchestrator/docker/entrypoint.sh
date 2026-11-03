#!/bin/sh
set -eu

role="${1:-${ORCHESTRATOR_ROLE:-api}}"

case "$role" in
  api)
    exec uvicorn orchestrator.main:app --host 0.0.0.0 --port 8080
    ;;
  worker)
    exec celery -A orchestrator.celery_app:celery_app worker -l info -Q pool_reconcile,webhook_delivery -n worker@%h
    ;;
  *)
    exec "$@"
    ;;
esac
