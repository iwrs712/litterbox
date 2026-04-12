#!/bin/sh
set -eu

role="${ORCHESTRATOR_ROLE:-api}"

if [ "$role" != "api" ]; then
  exit 0
fi

exec python -c "import sys, urllib.request; resp = urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2); sys.exit(0 if 200 <= resp.status < 400 else 1)"
