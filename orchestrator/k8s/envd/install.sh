#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="${NAMESPACE:-litterbox}"
DAEMONSET="${DAEMONSET:-envd-node-installer}"
ENVD_VERSION="${ENVD_VERSION:-0.1.3}"
INSTALLER_IMAGE="${INSTALLER_IMAGE:-registry.runlet.cn/litterbox/envd-node-installer:${ENVD_VERSION}-amd64}"
IMAGE_PULL_SECRET="${IMAGE_PULL_SECRET:-harbor-pull-secret}"
TARGET_SELECTOR="${TARGET_SELECTOR:-katacontainers.io/kata-runtime=true,kubernetes.io/arch=amd64}"
VERSION_LABEL="${VERSION_LABEL:-litterbox.io/envd-version}"

node_count="$(kubectl get nodes -l "$TARGET_SELECTOR" --no-headers | wc -l | tr -d ' ')"
if [[ "$node_count" == "0" ]]; then
    echo "no nodes match selector: $TARGET_SELECTOR" >&2
    exit 1
fi

if ! kubectl -n "$NAMESPACE" get secret "$IMAGE_PULL_SECRET" >/dev/null 2>&1; then
    echo "image pull secret not found: $NAMESPACE/$IMAGE_PULL_SECRET" >&2
    exit 1
fi

# Stop new Sandbox scheduling while the host binary is being replaced.
kubectl label nodes -l "$TARGET_SELECTOR" "${VERSION_LABEL}-" 2>/dev/null || true

kubectl apply -f "$SCRIPT_DIR/node-installer-daemonset.yaml"
kubectl -n "$NAMESPACE" set image "daemonset/$DAEMONSET" \
    "installer=$INSTALLER_IMAGE" \
    "ready=$INSTALLER_IMAGE"
kubectl -n "$NAMESPACE" rollout status "daemonset/$DAEMONSET" --timeout=300s

desired="$(kubectl -n "$NAMESPACE" get "daemonset/$DAEMONSET" -o jsonpath='{.status.desiredNumberScheduled}')"
ready="$(kubectl -n "$NAMESPACE" get "daemonset/$DAEMONSET" -o jsonpath='{.status.numberReady}')"
if [[ "$desired" != "$node_count" || "$ready" != "$desired" ]]; then
    echo "installer is not ready on every target node: target=$node_count desired=$desired ready=$ready" >&2
    exit 1
fi

kubectl label nodes -l "$TARGET_SELECTOR" \
    "$VERSION_LABEL=$ENVD_VERSION" \
    --overwrite

kubectl get nodes -l "$TARGET_SELECTOR" \
    -L "$VERSION_LABEL"
