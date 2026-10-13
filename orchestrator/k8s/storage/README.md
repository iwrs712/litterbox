# Litterbox workspace LVM pool

This directory configures the OpenEBS LocalPV-LVM pool used for persistent
sandbox workspaces. The orchestrator selects it through:

```toml
[workspace]
storage_class = "litterbox-workspace-lvm"
```

Install the OpenEBS LocalPV-LVM CSI driver first. Copy
`litterbox-workspace-pool.env.example` to a host-local configuration file,
then run the setup script as root on every Kubernetes node that may schedule a
sandbox:

```bash
./setup-litterbox-workspace-lvm.sh /etc/litterbox/workspace-pool.env
```

The script either provisions the configured dedicated block device or creates
and attaches the configured file-backed loop device. It creates or extends the
configured volume group, rescans its PV, and applies the matching StorageClass.
Loop device paths are discovered dynamically and are never persisted by number.

To grow a file-backed pool, increase `LITTERBOX_WORKSPACE_POOL_SIZE` and rerun
the script. To grow a dedicated-disk pool, grow the device or add a new PV to
the VG, then rerun the script. Existing PVCs can request a larger size because
the StorageClass has `allowVolumeExpansion: true`; their filesystem expansion
is performed by Kubernetes when the workload next mounts the claim.

Do not shrink a pool or an allocated workspace PVC. The StorageClass uses
`reclaimPolicy: Delete`, so permanent sandbox deletion releases the backing LV.
