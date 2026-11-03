package poolcontroller

import (
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"

	"github.com/iwrs712/litterbox/controller/internal/apis/v1alpha1"
)

func testPool() *v1alpha1.SandboxPool {
	return &v1alpha1.SandboxPool{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "ubuntu",
			Namespace: "default",
			UID:       types.UID("pool-uid"),
		},
		Spec: v1alpha1.SandboxPoolSpec{
			TemplateID:  "ubuntu",
			TargetReady: 2,
			MaxCreating: 5,
			SandboxTemplate: v1alpha1.SandboxSpec{
				TemplateID: "ubuntu",
				Image:      "ubuntu:22.04",
				Resources: v1alpha1.SandboxResources{
					Limits:   v1alpha1.ResourceList{CPU: "500m", Memory: "512Mi"},
					Requests: v1alpha1.ResourceList{CPU: "500m", Memory: "512Mi"},
				},
				Workspace: v1alpha1.WorkspaceSpec{
					Enabled:          true,
					MountPath:        "/workspace",
					Size:             "1Gi",
					StorageClassName: "local-path",
				},
				Envd:  v1alpha1.EnvdSpec{Enabled: true, Port: 49983},
				State: v1alpha1.StateRunning,
			},
		},
	}
}

func TestBuildPoolSandbox(t *testing.T) {
	pool := testPool()
	sandbox := buildPoolSandbox(pool, "abc12345")

	if sandbox.Name != "abc12345" || sandbox.Namespace != pool.Namespace {
		t.Fatalf("unexpected sandbox identity %s/%s", sandbox.Namespace, sandbox.Name)
	}
	if sandbox.Labels[poolLabel] != pool.Name ||
		sandbox.Labels[poolStateLabel] != stateCreating ||
		sandbox.Labels["litterbox.io/pool-managed"] != "true" {
		t.Fatalf("pool labels missing: %#v", sandbox.Labels)
	}
	if sandbox.Spec.Workspace.ClaimName != "workspace-abc12345" {
		t.Fatalf("workspace claim not rewritten: %s", sandbox.Spec.Workspace.ClaimName)
	}
	if sandbox.Spec.TTLSeconds != 0 || sandbox.Spec.TTLAnchor != nil {
		t.Fatal("pool sandboxes must start without TTL")
	}
	if len(sandbox.OwnerReferences) != 1 || sandbox.OwnerReferences[0].Kind != v1alpha1.KindPool {
		t.Fatal("pool sandbox must be owned by the pool")
	}
	if sandbox.Annotations["litterbox.io/workspace-config"] == "" {
		t.Fatal("workspace annotation missing")
	}
}

func TestCountSandboxes(t *testing.T) {
	sandboxes := []*v1alpha1.Sandbox{
		{ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateCreating}}},
		{ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateAvailable}}},
		{ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateAvailable}}},
		{ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateAllocated}}},
		{ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateFailed}}},
		{ObjectMeta: metav1.ObjectMeta{
			DeletionTimestamp: &metav1.Time{},
			Labels:            map[string]string{poolStateLabel: stateAvailable},
		}},
	}

	counts := countSandboxes(sandboxes)

	if counts.creating != 1 || counts.ready != 2 || counts.allocated != 1 ||
		counts.failed != 1 || counts.terminating != 1 {
		t.Fatalf("unexpected counts: %#v", counts)
	}
}

func TestShouldFail(t *testing.T) {
	now := time.Now()
	running := &v1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateCreating}},
	}
	failed := &v1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{Labels: map[string]string{poolStateLabel: stateCreating}},
		Status:     v1alpha1.SandboxStatus{Phase: v1alpha1.PhaseFailed},
	}
	stale := &v1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Labels:            map[string]string{poolStateLabel: stateCreating},
			CreationTimestamp: metav1.NewTime(now.Add(-createTimeout - time.Minute)),
		},
	}
	available := &v1alpha1.Sandbox{
		ObjectMeta: metav1.ObjectMeta{
			Labels:            map[string]string{poolStateLabel: stateAvailable},
			CreationTimestamp: metav1.NewTime(now.Add(-createTimeout - time.Minute)),
		},
	}

	if shouldFail(running, now) {
		t.Fatal("a fresh creating sandbox must not fail")
	}
	if !shouldFail(failed, now) {
		t.Fatal("a Failed phase must be marked failed")
	}
	if !shouldFail(stale, now) {
		t.Fatal("a creating sandbox past the timeout must fail")
	}
	if shouldFail(available, now) {
		t.Fatal("available sandboxes do not fail on age alone")
	}
}

func TestWorkspaceConfigAnnotationUsesSnakeCase(t *testing.T) {
	annotation := workspaceConfigAnnotation(v1alpha1.WorkspaceSpec{
		Enabled:          true,
		MountPath:        "/workspace",
		Size:             "1Gi",
		StorageClassName: "local-path",
	})

	want := `{"enabled":true,"mount_path":"/workspace","size":"1Gi","storage_class":"local-path"}`
	if annotation != want {
		t.Fatalf("unexpected annotation:\n got %s\nwant %s", annotation, want)
	}
}
