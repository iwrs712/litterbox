package controller

import (
	"testing"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	"github.com/iwrs712/litterbox/controller/internal/apis/v1alpha1"
)

func testSandbox() *v1alpha1.Sandbox {
	anchor := metav1.NewTime(time.Now().Add(-time.Minute))
	return &v1alpha1.Sandbox{
		TypeMeta: metav1.TypeMeta{APIVersion: "litterbox.io/v1alpha1", Kind: "Sandbox"},
		ObjectMeta: metav1.ObjectMeta{
			Name:      "abc12345",
			Namespace: "default",
			UID:       types.UID("sandbox-uid"),
			Labels: map[string]string{
				"litterbox.io/template-id": "ubuntu",
				"litterbox.io/pool-state":  "allocated",
			},
			Annotations: map[string]string{"litterbox.io/allocated-name": "demo"},
		},
		Spec: v1alpha1.SandboxSpec{
			TemplateID: "ubuntu",
			Image:      "ubuntu:22.04",
			Command:    []string{"sleep", "infinity"},
			Env:        []v1alpha1.EnvVar{{Name: "FOO", Value: "bar"}},
			Resources: v1alpha1.SandboxResources{
				Limits:   v1alpha1.ResourceList{CPU: "500m", Memory: "512Mi"},
				Requests: v1alpha1.ResourceList{CPU: "250m", Memory: "256Mi"},
			},
			NodeSelector: map[string]string{"litterbox.io/envd-version": "0.1.0"},
			HostPathMounts: []v1alpha1.HostPathMount{
				{HostPath: "/data", ContainerPath: "/data", ReadOnly: true},
			},
			Workspace: v1alpha1.WorkspaceSpec{
				Enabled:          true,
				MountPath:        "/workspace",
				Size:             "1Gi",
				StorageClassName: "local-path",
				ClaimName:        "workspace-abc12345",
			},
			Envd: v1alpha1.EnvdSpec{
				Enabled:             true,
				HostBinaryPath:      "/opt/litterbox/bin/envd",
				ContainerBinaryPath: "/opt/litterbox/envd/envd",
				Port:                49983,
			},
			Lifecycle: v1alpha1.LifecycleSpec{
				PostStart: []string{"/opt/litterbox/envd/envd", "daemon"},
				PreStop:   []string{"/bin/sh", "-c", "true"},
			},
			State:              v1alpha1.StateRunning,
			TTLSeconds:         600,
			TTLAnchor:          &anchor,
			AppArmorUnconfined: true,
			Stdin:              true,
			TTY:                true,
		},
	}
}

func TestBuildPod(t *testing.T) {
	sandbox := testSandbox()
	pod := buildPod(sandbox)

	if pod.Name != sandbox.Name || pod.Namespace != sandbox.Namespace {
		t.Fatalf("unexpected pod identity: %s/%s", pod.Namespace, pod.Name)
	}
	if pod.Labels["app"] != sandbox.Name || pod.Labels["component"] != "sandbox" {
		t.Fatalf("sandbox labels missing from pod: %#v", pod.Labels)
	}
	if pod.Labels["litterbox.io/sandbox-id"] != sandbox.Name {
		t.Fatal("sandbox-id label missing")
	}
	if len(pod.OwnerReferences) != 1 || pod.OwnerReferences[0].Kind != "Sandbox" {
		t.Fatal("pod must be owned by the Sandbox")
	}
	if pod.Annotations[specHashAnnotation] == "" {
		t.Fatal("spec hash annotation missing")
	}
	if pod.Spec.RestartPolicy != corev1.RestartPolicyAlways {
		t.Fatalf("unexpected restart policy %s", pod.Spec.RestartPolicy)
	}
	if len(pod.Spec.Containers) != 1 {
		t.Fatalf("expected one container, got %d", len(pod.Spec.Containers))
	}
	container := pod.Spec.Containers[0]
	if container.Image != sandbox.Spec.Image {
		t.Fatalf("unexpected image %s", container.Image)
	}
	if container.SecurityContext == nil || container.SecurityContext.AppArmorProfile == nil ||
		container.SecurityContext.AppArmorProfile.Type != corev1.AppArmorProfileTypeUnconfined {
		t.Fatal("sandbox container must run AppArmor unconfined")
	}
	if container.Lifecycle == nil || container.Lifecycle.PostStart == nil {
		t.Fatal("envd postStart hook missing")
	}
	if got := container.Lifecycle.PostStart.Exec.Command[0]; got != sandbox.Spec.Envd.ContainerBinaryPath {
		t.Fatalf("unexpected postStart command %s", got)
	}
	if container.Resources.Limits.Cpu().String() != "500m" {
		t.Fatalf("unexpected cpu limit %s", container.Resources.Limits.Cpu().String())
	}
	if container.ImagePullPolicy != corev1.PullIfNotPresent {
		t.Fatalf("unexpected image pull policy %s", container.ImagePullPolicy)
	}
	if len(container.VolumeMounts) != 3 {
		t.Fatalf("expected workspace, envd and host mount, got %d", len(container.VolumeMounts))
	}
	if pod.Spec.NodeSelector["litterbox.io/envd-version"] != "0.1.0" {
		t.Fatal("envd node selector missing")
	}
}

func TestBuildPVC(t *testing.T) {
	sandbox := testSandbox()
	pvc := buildPVC(sandbox)

	if pvc.Name != "workspace-abc12345" {
		t.Fatalf("unexpected claim name %s", pvc.Name)
	}
	if pvc.Namespace != sandbox.Namespace {
		t.Fatalf("unexpected namespace %s", pvc.Namespace)
	}
	if len(pvc.OwnerReferences) != 1 || pvc.OwnerReferences[0].Kind != "Sandbox" {
		t.Fatal("pvc must be owned by the Sandbox")
	}
	if pvc.Spec.StorageClassName == nil || *pvc.Spec.StorageClassName != "local-path" {
		t.Fatal("storage class not propagated")
	}
	if got := pvc.Spec.Resources.Requests.Storage().String(); got != "1Gi" {
		t.Fatalf("unexpected storage request %s", got)
	}
}

func TestSpecHashChangesWithSpec(t *testing.T) {
	sandbox := testSandbox()
	first := specHash(sandbox)
	if first != specHash(sandbox) {
		t.Fatal("spec hash must be deterministic")
	}

	sandbox.Spec.TTLSeconds = 5
	sandbox.Spec.TTLAnchor = nil
	sandbox.Spec.State = v1alpha1.StatePaused
	if first != specHash(sandbox) {
		t.Fatal("TTL and desired state must not change the pod template hash")
	}

	sandbox.Spec.Image = "ubuntu:24.04"
	if first == specHash(sandbox) {
		t.Fatal("spec hash must change when the pod template changes")
	}
}

func TestComputeStatusRunning(t *testing.T) {
	sandbox := testSandbox()
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{Name: sandbox.Name},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
			PodIP: "10.42.0.9",
			Conditions: []corev1.PodCondition{
				{Type: corev1.PodReady, Status: corev1.ConditionTrue},
			},
		},
	}
	controller := &Controller{}
	status := controller.computeStatus(sandbox, pod, true, "", nil)
	if status.Phase != v1alpha1.PhaseRunning {
		t.Fatalf("unexpected phase %s", status.Phase)
	}
	if status.PodIP != "10.42.0.9" || status.PodName != sandbox.Name {
		t.Fatalf("pod identity not reported: %#v", status)
	}
	if len(status.Conditions) != 1 || status.Conditions[0].Status != metav1.ConditionTrue {
		t.Fatalf("ready condition missing: %#v", status.Conditions)
	}
}

func TestComputeStatusPendingAndPaused(t *testing.T) {
	sandbox := testSandbox()
	controller := &Controller{}

	pending := controller.computeStatus(sandbox, nil, true, "", nil)
	if pending.Phase != v1alpha1.PhasePending {
		t.Fatalf("unexpected phase %s", pending.Phase)
	}

	paused := controller.computeStatus(sandbox, nil, false, v1alpha1.PausedReasonTTLExpired, nil)
	if paused.Phase != v1alpha1.PhasePaused || paused.PausedReason != v1alpha1.PausedReasonTTLExpired {
		t.Fatalf("unexpected paused status %#v", paused)
	}
}

func TestComputeStatusFailedPod(t *testing.T) {
	sandbox := testSandbox()
	pod := &corev1.Pod{Status: corev1.PodStatus{Phase: corev1.PodFailed}}
	status := (&Controller{}).computeStatus(sandbox, pod, true, "", nil)
	if status.Phase != v1alpha1.PhaseFailed {
		t.Fatalf("unexpected phase %s", status.Phase)
	}
}
