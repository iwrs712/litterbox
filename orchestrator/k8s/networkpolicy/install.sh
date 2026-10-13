#!/usr/bin/env bash
#
# Apply the Sandbox network isolation policies.
#
#   ./install.sh                 apply (idempotent)
#   ./install.sh --dry-run       render and print, change nothing
#   ./install.sh --verify        apply, then run a live enforcement test
#   ./install.sh --delete        remove the policies
#
# Safe to re-run. Applying updates the existing policies in place.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/sandbox-networkpolicy.yaml.tmpl"

# Sandboxes live in their own namespace, not in the Orchestrator's.
SANDBOX_NAMESPACE="${SANDBOX_NAMESPACE:-default}"
SANDBOX_LABEL_KEY="${SANDBOX_LABEL_KEY:-component}"
SANDBOX_LABEL_VALUE="${SANDBOX_LABEL_VALUE:-sandbox}"

# Who is allowed to open connections INTO a Sandbox.
ORCHESTRATOR_NAMESPACE="${ORCHESTRATOR_NAMESPACE:-litterbox}"
INGRESS_NAMESPACE="${INGRESS_NAMESPACE:-kube-system}"

# Where Sandboxes are allowed to go.
DNS_NAMESPACE="${DNS_NAMESPACE:-kube-system}"
BILLING_NAMESPACE="${BILLING_NAMESPACE:-pai}"
BILLING_LABEL_KEY="${BILLING_LABEL_KEY:-app}"
BILLING_LABEL_VALUE="${BILLING_LABEL_VALUE:-runlet-traefik-billing}"
BILLING_PORT="${BILLING_PORT:-8080}"

# Cluster internal ranges that must stay unreachable from a Sandbox.
CLUSTER_POD_CIDR="${CLUSTER_POD_CIDR:-10.42.0.0/16}"
CLUSTER_SERVICE_CIDR="${CLUSTER_SERVICE_CIDR:-10.43.0.0/16}"

# Only used by --verify.
VERIFY_IMAGE="${VERIFY_IMAGE:-registry.runlet.cn/litterbox/sandbox-agent:python3.12-nodejs26-slim-amd64-mcp}"
VERIFY_RUNTIME_CLASS="${VERIFY_RUNTIME_CLASS:-kata-clh}"
# kube-router syncs its ipsets on a timer; probing sooner than this reports a
# false "still blocked" for pods that were only just created.
IPSET_SETTLE_SECONDS="${IPSET_SETTLE_SECONDS:-30}"

MODE="apply"
for arg in "$@"; do
    case "$arg" in
        --dry-run) MODE="dry-run" ;;
        --verify)  MODE="verify" ;;
        --delete)  MODE="delete" ;;
        -h|--help)
            sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "unknown argument: $arg" >&2
            exit 2
            ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }

command -v kubectl >/dev/null 2>&1 || die "kubectl not found in PATH"

render() {
    # The template uses ${NAME} placeholders; \$ keeps sed from reading them as
    # an end-of-line anchor. "|" avoids clashing with the "/" in the CIDRs.
    sed \
        -e "s|\${SANDBOX_NAMESPACE}|${SANDBOX_NAMESPACE}|g" \
        -e "s|\${SANDBOX_LABEL_KEY}|${SANDBOX_LABEL_KEY}|g" \
        -e "s|\${SANDBOX_LABEL_VALUE}|${SANDBOX_LABEL_VALUE}|g" \
        -e "s|\${ORCHESTRATOR_NAMESPACE}|${ORCHESTRATOR_NAMESPACE}|g" \
        -e "s|\${INGRESS_NAMESPACE}|${INGRESS_NAMESPACE}|g" \
        -e "s|\${DNS_NAMESPACE}|${DNS_NAMESPACE}|g" \
        -e "s|\${BILLING_NAMESPACE}|${BILLING_NAMESPACE}|g" \
        -e "s|\${BILLING_LABEL_KEY}|${BILLING_LABEL_KEY}|g" \
        -e "s|\${BILLING_LABEL_VALUE}|${BILLING_LABEL_VALUE}|g" \
        -e "s|\${BILLING_PORT}|${BILLING_PORT}|g" \
        -e "s|\${CLUSTER_POD_CIDR}|${CLUSTER_POD_CIDR}|g" \
        -e "s|\${CLUSTER_SERVICE_CIDR}|${CLUSTER_SERVICE_CIDR}|g" \
        "$TEMPLATE"
}

[[ -f "$TEMPLATE" ]] || die "template not found: $TEMPLATE"

if [[ "$MODE" == "dry-run" ]]; then
    echo "# rendered from $TEMPLATE" >&2
    echo "# SANDBOX_NAMESPACE=$SANDBOX_NAMESPACE ORCHESTRATOR_NAMESPACE=$ORCHESTRATOR_NAMESPACE" >&2
    echo "# INGRESS_NAMESPACE=$INGRESS_NAMESPACE DNS_NAMESPACE=$DNS_NAMESPACE" >&2
    echo "# BILLING=${BILLING_NAMESPACE}/${BILLING_LABEL_KEY}=${BILLING_LABEL_VALUE}:${BILLING_PORT}" >&2
    echo "# except=${CLUSTER_POD_CIDR},${CLUSTER_SERVICE_CIDR}" >&2
    render
    exit 0
fi

if [[ "$MODE" == "delete" ]]; then
    kubectl -n "$SANDBOX_NAMESPACE" delete networkpolicy sandbox-ingress sandbox-egress --ignore-not-found
    echo "removed sandbox network policies from namespace $SANDBOX_NAMESPACE" >&2
    exit 0
fi

# --- preflight -------------------------------------------------------------
# A missing namespace silently produces a policy that matches nothing, which
# looks applied but protects nothing.
for ns in "$SANDBOX_NAMESPACE" "$ORCHESTRATOR_NAMESPACE" "$INGRESS_NAMESPACE" "$DNS_NAMESPACE" "$BILLING_NAMESPACE"; do
    kubectl get namespace "$ns" >/dev/null 2>&1 || die "namespace not found: $ns"
done

# The billing rule is narrowed with a podSelector. If the label is wrong the
# rule matches no pod and Sandboxes lose their egress proxy.
if ! kubectl -n "$BILLING_NAMESPACE" get pods \
        -l "${BILLING_LABEL_KEY}=${BILLING_LABEL_VALUE}" --no-headers 2>/dev/null | grep -q .; then
    die "no pod matches ${BILLING_NAMESPACE}/${BILLING_LABEL_KEY}=${BILLING_LABEL_VALUE}; Sandboxes would lose their egress proxy"
fi

# NetworkPolicy is only enforced when a policy controller is running. On k3s
# that is built in and disabled by --disable-network-policy.
if command -v iptables-save >/dev/null 2>&1; then
    if ! iptables-save 2>/dev/null | grep -q 'KUBE-NWPLCY'; then
        echo "warning: no KUBE-NWPLCY iptables chains found." >&2
        echo "warning: the network policy controller may be disabled; the policies will not be enforced." >&2
    fi
fi

# --- apply -----------------------------------------------------------------
render | kubectl apply -f -

echo >&2
echo "applied to namespace $SANDBOX_NAMESPACE (selector ${SANDBOX_LABEL_KEY}=${SANDBOX_LABEL_VALUE})" >&2
kubectl -n "$SANDBOX_NAMESPACE" get networkpolicy sandbox-ingress sandbox-egress >&2

matched="$(kubectl -n "$SANDBOX_NAMESPACE" get pods \
    -l "${SANDBOX_LABEL_KEY}=${SANDBOX_LABEL_VALUE}" --no-headers 2>/dev/null | wc -l | tr -d ' ')"
if [[ "$matched" == "0" ]]; then
    echo >&2
    echo "note: no running pod currently matches ${SANDBOX_LABEL_KEY}=${SANDBOX_LABEL_VALUE} in $SANDBOX_NAMESPACE." >&2
    echo "note: the policies are in place and will apply to the next Sandbox created." >&2
else
    echo >&2
    echo "policies select $matched pod(s) in $SANDBOX_NAMESPACE." >&2
fi

if [[ "$MODE" != "verify" ]]; then
    exit 0
fi

# --- verify ----------------------------------------------------------------
# Both probe pods carry the Sandbox label so the real policies select them:
# this tests the shipped rules, not a copy.
TARGET="npverify-target-$$"
CLIENT="npverify-client-$$"

cleanup() {
    kubectl -n "$SANDBOX_NAMESPACE" delete pod "$TARGET" "$CLIENT" --ignore-not-found --wait=false >/dev/null 2>&1 || true
}
trap cleanup EXIT

runtime_class_arg=""
if kubectl get runtimeclass "$VERIFY_RUNTIME_CLASS" >/dev/null 2>&1; then
    runtime_class_arg="$VERIFY_RUNTIME_CLASS"
else
    echo "warning: runtimeclass $VERIFY_RUNTIME_CLASS not found; verifying with the default runtime" >&2
fi

echo >&2
echo "running enforcement test in $SANDBOX_NAMESPACE..." >&2

kubectl -n "$SANDBOX_NAMESPACE" apply -f - >/dev/null <<EOF
apiVersion: v1
kind: Pod
metadata:
  name: $TARGET
  labels:
    ${SANDBOX_LABEL_KEY}: ${SANDBOX_LABEL_VALUE}
    npverify: target
spec:
  $( [[ -n "$runtime_class_arg" ]] && echo "runtimeClassName: $runtime_class_arg" )
  restartPolicy: Never
  containers:
    - name: probe
      image: $VERIFY_IMAGE
      command: ["python3", "-m", "http.server", "8080"]
---
apiVersion: v1
kind: Pod
metadata:
  name: $CLIENT
  labels:
    ${SANDBOX_LABEL_KEY}: ${SANDBOX_LABEL_VALUE}
    npverify: client
spec:
  $( [[ -n "$runtime_class_arg" ]] && echo "runtimeClassName: $runtime_class_arg" )
  restartPolicy: Never
  containers:
    - name: probe
      image: $VERIFY_IMAGE
      command: ["sleep", "600"]
EOF

kubectl -n "$SANDBOX_NAMESPACE" wait --for=condition=Ready "pod/$TARGET" "pod/$CLIENT" --timeout=240s >/dev/null

echo "waiting ${IPSET_SETTLE_SECONDS}s for the policy controller to sync..." >&2
sleep "$IPSET_SETTLE_SECONDS"

target_ip="$(kubectl -n "$SANDBOX_NAMESPACE" get pod "$TARGET" -o jsonpath='{.status.podIP}')"

result="$(kubectl -n "$SANDBOX_NAMESPACE" exec "$CLIENT" -- python3 - "$target_ip" <<'PY'
import socket, sys
ip = sys.argv[1]
s = socket.socket(); s.settimeout(6)
try:
    s.connect((ip, 8080))
    print("OPEN")
except Exception:
    print("BLOCKED")
finally:
    s.close()
PY
)"

status=0
if [[ "$result" == "BLOCKED" ]]; then
    echo "  PASS  sandbox -> sandbox is blocked" >&2
else
    echo "  FAIL  sandbox -> sandbox is OPEN (sidecar is reachable)" >&2
    status=1
fi

for probe in "runlet-traefik-billing.${BILLING_NAMESPACE}.svc.cluster.local:${BILLING_PORT}:billing proxy" \
             "github.com:443:public internet" \
             "postgres.${ORCHESTRATOR_NAMESPACE}.svc.cluster.local:5432:orchestrator postgres"; do
    host="${probe%%:*}"; rest="${probe#*:}"; port="${rest%%:*}"; label="${rest#*:}"
    outcome="$(kubectl -n "$SANDBOX_NAMESPACE" exec "$CLIENT" -- python3 - "$host" "$port" <<'PY'
import socket, sys
host, port = sys.argv[1], int(sys.argv[2])
s = socket.socket(); s.settimeout(6)
try:
    s.connect((host, port))
    print("OPEN")
except Exception:
    print("BLOCKED")
finally:
    s.close()
PY
)"
    case "$label" in
        "orchestrator postgres")
            want="BLOCKED" ;;
        *)
            want="OPEN" ;;
    esac
    if [[ "$outcome" == "$want" ]]; then
        echo "  PASS  $label is $want" >&2
    else
        echo "  FAIL  $label is $outcome, expected $want" >&2
        status=1
    fi
done

exit "$status"
