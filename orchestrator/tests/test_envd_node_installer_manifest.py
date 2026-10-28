from __future__ import annotations

from pathlib import Path

import yaml


MANIFEST = Path(__file__).parents[1] / "k8s" / "envd" / "node-installer-daemonset.yaml"


def test_envd_node_installer_targets_kata_nodes_and_writes_host_binary() -> None:
    daemonset = yaml.safe_load(MANIFEST.read_text())
    pod_spec = daemonset["spec"]["template"]["spec"]
    installer = pod_spec["initContainers"][0]

    assert daemonset["kind"] == "DaemonSet"
    assert pod_spec["nodeSelector"] == {
        "katacontainers.io/kata-runtime": "true",
        "kubernetes.io/arch": "amd64",
    }
    assert installer["image"].endswith("envd-node-installer:0.1.3-amd64")
    assert installer["volumeMounts"] == [
        {"name": "envd-host-bin", "mountPath": "/host-bin"}
    ]
    assert pod_spec["volumes"] == [
        {
            "name": "envd-host-bin",
            "hostPath": {
                "path": "/opt/litterbox/bin",
                "type": "DirectoryOrCreate",
            },
        }
    ]
    command = " ".join(installer["command"])
    assert "/payload/sandbox-agent" in command
    assert "/host-bin/sandbox-agent" in command


def test_envd_node_installer_is_an_init_container() -> None:
    daemonset = yaml.safe_load(MANIFEST.read_text())
    pod_spec = daemonset["spec"]["template"]["spec"]

    assert len(pod_spec["initContainers"]) == 1
    ready = pod_spec["containers"][0]
    assert ready["name"] == "ready"
    assert ready["image"].endswith("envd-node-installer:0.1.3-amd64")
    assert ready["volumeMounts"] == [
        {"name": "envd-host-bin", "mountPath": "/host-bin", "readOnly": True}
    ]
