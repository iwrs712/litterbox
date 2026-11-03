#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env.local ]; then
    cp .env.local.example .env.local
    echo "created .env.local from .env.local.example"
fi

base_url="$(sed -n 's/^VITE_API_BASE_URL=//p' .env.local | tail -n 1)"
if [ -n "$base_url" ] && ! curl -fsS --max-time 2 "$base_url/health" >/dev/null 2>&1; then
    echo "warning: $base_url/health is not reachable" >&2
    echo "start the local orchestrator port-forward first:" >&2
    echo "  kubectl -n litterbox port-forward svc/orchestrator 8080:8080" >&2
fi

port="${VITE_PORT:-5173}"
exec npm run dev -- --port "$port" --strictPort
