#!/usr/bin/env bash
set -euo pipefail

CONFIG_FILE="${1:-/etc/litterbox/workspace-pool.env}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "workspace pool config not found: $CONFIG_FILE" >&2
    exit 1
fi

# shellcheck disable=SC1090
source "$CONFIG_FILE"

: "${LITTERBOX_WORKSPACE_STORAGE_CLASS:?must be set}"
: "${LITTERBOX_WORKSPACE_VG:?must be set}"

if [[ -n "${LITTERBOX_WORKSPACE_BLOCK_DEVICE:-}" && -n "${LITTERBOX_WORKSPACE_BACKING_FILE:-}" ]]; then
    echo "set either LITTERBOX_WORKSPACE_BLOCK_DEVICE or LITTERBOX_WORKSPACE_BACKING_FILE, not both" >&2
    exit 1
fi

if [[ -n "${LITTERBOX_WORKSPACE_BLOCK_DEVICE:-}" ]]; then
    device="$LITTERBOX_WORKSPACE_BLOCK_DEVICE"
    if [[ ! -b "$device" ]]; then
        echo "configured block device does not exist: $device" >&2
        exit 1
    fi
else
    : "${LITTERBOX_WORKSPACE_BACKING_FILE:?must be set when no block device is configured}"
    : "${LITTERBOX_WORKSPACE_POOL_SIZE:?must be set when no block device is configured}"

    mkdir -p "$(dirname "$LITTERBOX_WORKSPACE_BACKING_FILE")"
    if [[ ! -e "$LITTERBOX_WORKSPACE_BACKING_FILE" ]]; then
        truncate -s "$LITTERBOX_WORKSPACE_POOL_SIZE" "$LITTERBOX_WORKSPACE_BACKING_FILE"
    else
        current_size="$(stat -c%s "$LITTERBOX_WORKSPACE_BACKING_FILE")"
        requested_size="$(numfmt --from=auto "$LITTERBOX_WORKSPACE_POOL_SIZE")"
        if (( current_size < requested_size )); then
            truncate -s "$LITTERBOX_WORKSPACE_POOL_SIZE" "$LITTERBOX_WORKSPACE_BACKING_FILE"
        elif (( current_size > requested_size )); then
            echo "not shrinking existing backing file $LITTERBOX_WORKSPACE_BACKING_FILE" >&2
        fi
    fi

    device="$(losetup -j "$LITTERBOX_WORKSPACE_BACKING_FILE" | cut -d: -f1 | head -n1 || true)"
    if [[ -z "$device" ]]; then
        device="$(losetup --find --show "$LITTERBOX_WORKSPACE_BACKING_FILE")"
    else
        losetup -c "$device"
    fi
fi

if ! pvs "$device" >/dev/null 2>&1; then
    pvcreate "$device"
fi

if ! vgs "$LITTERBOX_WORKSPACE_VG" >/dev/null 2>&1; then
    vgcreate "$LITTERBOX_WORKSPACE_VG" "$device"
else
    current_vg="$(pvs --noheadings -o vg_name "$device" | xargs)"
    if [[ -z "$current_vg" ]]; then
        vgextend "$LITTERBOX_WORKSPACE_VG" "$device"
    elif [[ "$current_vg" != "$LITTERBOX_WORKSPACE_VG" ]]; then
        echo "$device already belongs to volume group $current_vg" >&2
        exit 1
    fi
fi

pvresize "$device"

sed \
    -e "s|\${LITTERBOX_WORKSPACE_STORAGE_CLASS}|${LITTERBOX_WORKSPACE_STORAGE_CLASS}|g" \
    -e "s|\${LITTERBOX_WORKSPACE_VG}|${LITTERBOX_WORKSPACE_VG}|g" \
    "$SCRIPT_DIR/litterbox-workspace-lvm-storageclass.yaml.tmpl" | kubectl apply -f -
