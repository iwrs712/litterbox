package poolcontroller

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log/slog"
	"reflect"
	"sort"
	"time"

	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/util/workqueue"

	"github.com/iwrs712/litterbox/controller/internal/apis/v1alpha1"
)

var (
	poolGVR = schema.GroupVersionResource{
		Group:    v1alpha1.GroupName,
		Version:  v1alpha1.Version,
		Resource: "sandboxpools",
	}
	sandboxGVR = schema.GroupVersionResource{
		Group:    v1alpha1.GroupName,
		Version:  v1alpha1.Version,
		Resource: "sandboxes",
	}
)

const (
	poolLabel       = "litterbox.io/pool"
	poolStateLabel  = "litterbox.io/pool-state"
	stateCreating   = "creating"
	stateAvailable  = "available"
	stateAllocated  = "allocated"
	stateFailed     = "failed"
	defaultMaxCreat = int32(5)
	createTimeout   = 10 * time.Minute
)

type sandboxCounts struct {
	ready       int32
	creating    int32
	allocated   int32
	failed      int32
	terminating int32
}

// Controller maintains a SandboxPool's warm supply of Sandbox CRs.
type Controller struct {
	dynamic dynamic.Interface

	factory         dynamicinformer.DynamicSharedInformerFactory
	poolInformer    cache.SharedIndexInformer
	sandboxInformer cache.SharedIndexInformer

	queue workqueue.TypedRateLimitingInterface[string]
}

func New(dynamicClient dynamic.Interface, resync time.Duration) *Controller {
	controller := &Controller{
		dynamic: dynamicClient,
		queue: workqueue.NewTypedRateLimitingQueue(
			workqueue.DefaultTypedControllerRateLimiter[string](),
		),
	}
	controller.factory = dynamicinformer.NewFilteredDynamicSharedInformerFactory(
		dynamicClient,
		resync,
		metav1.NamespaceAll,
		nil,
	)
	controller.poolInformer = controller.factory.ForResource(poolGVR).Informer()
	controller.sandboxInformer = controller.factory.ForResource(sandboxGVR).Informer()

	controller.poolInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    controller.enqueueObject,
		UpdateFunc: func(_, newObj interface{}) { controller.enqueueObject(newObj) },
		DeleteFunc: controller.enqueueTombstone,
	})
	controller.sandboxInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    controller.enqueueSandboxPool,
		UpdateFunc: func(_, newObj interface{}) { controller.enqueueSandboxPool(newObj) },
		DeleteFunc: controller.enqueueSandboxPoolTombstone,
	})
	return controller
}

func (c *Controller) Run(ctx context.Context, workers int) error {
	defer c.queue.ShutDown()

	c.factory.Start(ctx.Done())
	if !cache.WaitForCacheSync(ctx.Done(), c.poolInformer.HasSynced, c.sandboxInformer.HasSynced) {
		return fmt.Errorf("timed out waiting for pool informer caches")
	}

	slog.Info("sandbox pool controller started", "workers", workers)
	for i := 0; i < workers; i++ {
		go wait.UntilWithContext(ctx, c.worker, time.Second)
	}
	<-ctx.Done()
	return nil
}

func (c *Controller) worker(ctx context.Context) {
	for c.processNextItem(ctx) {
	}
}

func (c *Controller) processNextItem(ctx context.Context) bool {
	key, shutdown := c.queue.Get()
	if shutdown {
		return false
	}
	defer c.queue.Done(key)

	if err := c.sync(ctx, key); err != nil {
		slog.Error("pool reconcile failed", "key", key, "err", err)
		c.queue.AddRateLimited(key)
		return true
	}
	c.queue.Forget(key)
	return true
}

func (c *Controller) sync(ctx context.Context, key string) error {
	obj, exists, err := c.poolInformer.GetStore().GetByKey(key)
	if err != nil || !exists {
		return err
	}
	unstructuredObj, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return fmt.Errorf("unexpected pool object %T", obj)
	}
	pool := &v1alpha1.SandboxPool{}
	if err := runtime.DefaultUnstructuredConverter.FromUnstructured(unstructuredObj.Object, pool); err != nil {
		return fmt.Errorf("decode sandbox pool: %w", err)
	}
	return c.reconcile(ctx, pool)
}

func (c *Controller) reconcile(ctx context.Context, pool *v1alpha1.SandboxPool) error {
	if pool.DeletionTimestamp != nil {
		// Owned, non-allocated sandboxes are removed by garbage collection.
		return nil
	}
	sandboxes, err := c.listSandboxes(pool)
	if err != nil {
		return err
	}
	counts := countSandboxes(sandboxes)
	target := pool.Spec.TargetReady
	maxCreating := pool.Spec.MaxCreating
	if maxCreating <= 0 {
		maxCreating = defaultMaxCreat
	}

	if err := c.markFailed(ctx, sandboxes, &counts); err != nil {
		return err
	}
	if err := c.markReady(ctx, sandboxes, &counts); err != nil {
		return err
	}
	if err := c.detachAllocated(ctx, pool, sandboxes); err != nil {
		return err
	}
	if target <= 0 {
		for _, sandbox := range sandboxes {
			if sandbox.DeletionTimestamp != nil || sandbox.Labels[poolStateLabel] == stateAllocated {
				continue
			}
			deleted, err := c.deleteSandbox(ctx, sandbox)
			if err != nil {
				return err
			}
			if deleted {
				decrementState(&counts, sandbox.Labels[poolStateLabel])
			}
		}
	} else {
		if err := c.deleteFailed(ctx, sandboxes, &counts); err != nil {
			return err
		}
		if err := c.deleteExcessAvailable(ctx, sandboxes, target, &counts); err != nil {
			return err
		}
		supply := counts.ready + counts.creating
		if supply < target {
			need := target - supply
			if capacity := maxCreating - counts.creating; need > capacity {
				need = capacity
			}
			for i := int32(0); i < need; i++ {
				if err := c.createSandbox(ctx, pool); err != nil {
					return err
				}
				counts.creating++
			}
		}
	}

	return c.updateStatus(ctx, pool, counts)
}

func (c *Controller) listSandboxes(pool *v1alpha1.SandboxPool) ([]*v1alpha1.Sandbox, error) {
	var sandboxes []*v1alpha1.Sandbox
	selector := labels.SelectorFromSet(labels.Set{poolLabel: pool.Name})
	err := cache.ListAllByNamespace(
		c.sandboxInformer.GetIndexer(),
		pool.Namespace,
		selector,
		func(obj interface{}) {
			unstructuredObj, ok := obj.(*unstructured.Unstructured)
			if !ok {
				return
			}
			sandbox := &v1alpha1.Sandbox{}
			if err := runtime.DefaultUnstructuredConverter.FromUnstructured(unstructuredObj.Object, sandbox); err != nil {
				return
			}
			sandboxes = append(sandboxes, sandbox)
		},
	)
	return sandboxes, err
}

func countSandboxes(sandboxes []*v1alpha1.Sandbox) sandboxCounts {
	var counts sandboxCounts
	for _, sandbox := range sandboxes {
		if sandbox.DeletionTimestamp != nil {
			counts.terminating++
			continue
		}
		switch sandbox.Labels[poolStateLabel] {
		case stateAvailable:
			counts.ready++
		case stateCreating:
			counts.creating++
		case stateAllocated:
			counts.allocated++
		case stateFailed:
			counts.failed++
		}
	}
	return counts
}

func decrementState(counts *sandboxCounts, state string) {
	switch state {
	case stateAvailable:
		counts.ready--
	case stateCreating:
		counts.creating--
	case stateAllocated:
		counts.allocated--
	case stateFailed:
		counts.failed--
	}
}

func (c *Controller) markFailed(ctx context.Context, sandboxes []*v1alpha1.Sandbox, counts *sandboxCounts) error {
	now := time.Now()
	for _, sandbox := range sandboxes {
		state := sandbox.Labels[poolStateLabel]
		if sandbox.DeletionTimestamp != nil ||
			(state != stateCreating && state != stateAvailable) ||
			!shouldFail(sandbox, now) {
			continue
		}
		body := map[string]interface{}{
			"metadata": map[string]interface{}{
				"labels": map[string]string{poolStateLabel: stateFailed},
			},
		}
		if err := c.patchSandbox(ctx, sandbox, body); err != nil {
			return err
		}
		decrementState(counts, state)
		counts.failed++
	}
	return nil
}

func shouldFail(sandbox *v1alpha1.Sandbox, now time.Time) bool {
	if sandbox.Status.Phase == v1alpha1.PhaseFailed {
		return true
	}
	if sandbox.Labels[poolStateLabel] != stateCreating {
		return false
	}
	created := sandbox.CreationTimestamp.Time
	return !created.IsZero() && now.Sub(created) > createTimeout
}

func (c *Controller) markReady(ctx context.Context, sandboxes []*v1alpha1.Sandbox, counts *sandboxCounts) error {
	for _, sandbox := range sandboxes {
		if sandbox.DeletionTimestamp != nil ||
			sandbox.Labels[poolStateLabel] != stateCreating ||
			sandbox.Status.Phase != v1alpha1.PhaseRunning {
			continue
		}
		body := map[string]interface{}{
			"metadata": map[string]interface{}{
				"labels": map[string]string{poolStateLabel: stateAvailable},
			},
		}
		if err := c.patchSandbox(ctx, sandbox, body); err != nil {
			return err
		}
		counts.creating--
		counts.ready++
	}
	return nil
}

func (c *Controller) detachAllocated(ctx context.Context, pool *v1alpha1.SandboxPool, sandboxes []*v1alpha1.Sandbox) error {
	for _, sandbox := range sandboxes {
		if sandbox.Labels[poolStateLabel] != stateAllocated || !hasPoolOwner(sandbox, pool) {
			continue
		}
		remaining := make([]metav1.OwnerReference, 0, len(sandbox.OwnerReferences))
		for _, ref := range sandbox.OwnerReferences {
			if ref.Kind == v1alpha1.KindPool && ref.Name == pool.Name {
				continue
			}
			remaining = append(remaining, ref)
		}
		body := map[string]interface{}{
			"metadata": map[string]interface{}{"ownerReferences": remaining},
		}
		if err := c.patchSandbox(ctx, sandbox, body); err != nil {
			return err
		}
	}
	return nil
}

func (c *Controller) deleteFailed(ctx context.Context, sandboxes []*v1alpha1.Sandbox, counts *sandboxCounts) error {
	for _, sandbox := range sandboxes {
		if sandbox.DeletionTimestamp != nil || sandbox.Labels[poolStateLabel] != stateFailed {
			continue
		}
		deleted, err := c.deleteSandbox(ctx, sandbox)
		if err != nil {
			return err
		}
		if deleted {
			counts.failed--
		}
	}
	return nil
}

func (c *Controller) deleteExcessAvailable(ctx context.Context, sandboxes []*v1alpha1.Sandbox, target int32, counts *sandboxCounts) error {
	excess := counts.ready - target
	if excess <= 0 {
		return nil
	}
	available := make([]*v1alpha1.Sandbox, 0, counts.ready)
	for _, sandbox := range sandboxes {
		if sandbox.DeletionTimestamp == nil && sandbox.Labels[poolStateLabel] == stateAvailable {
			available = append(available, sandbox)
		}
	}
	sort.Slice(available, func(i, j int) bool {
		return available[i].CreationTimestamp.Before(&available[j].CreationTimestamp)
	})
	for _, sandbox := range available {
		if excess <= 0 {
			break
		}
		deleted, err := c.deleteSandbox(ctx, sandbox)
		if err != nil {
			return err
		}
		if deleted {
			counts.ready--
			excess--
		}
	}
	return nil
}

func (c *Controller) createSandbox(ctx context.Context, pool *v1alpha1.SandboxPool) error {
	for attempt := 0; attempt < 5; attempt++ {
		id, err := randomID()
		if err != nil {
			return err
		}
		sandbox := buildPoolSandbox(pool, id)
		unstructuredObj, err := runtime.DefaultUnstructuredConverter.ToUnstructured(sandbox)
		if err != nil {
			return err
		}
		_, err = c.dynamic.Resource(sandboxGVR).Namespace(pool.Namespace).Create(
			ctx,
			&unstructured.Unstructured{Object: unstructuredObj},
			metav1.CreateOptions{},
		)
		if apierrors.IsAlreadyExists(err) {
			continue
		}
		if err == nil {
			slog.Info("created pool sandbox", "pool", pool.Namespace+"/"+pool.Name, "sandbox", id)
		}
		return err
	}
	return fmt.Errorf("could not allocate a unique sandbox id")
}

func buildPoolSandbox(pool *v1alpha1.SandboxPool, id string) *v1alpha1.Sandbox {
	spec := pool.Spec.SandboxTemplate
	spec.Workspace.ClaimName = "workspace-" + id
	spec.State = v1alpha1.StateRunning
	spec.TTLSeconds = 0
	spec.TTLAnchor = nil

	labels := map[string]string{
		"app":                       id,
		"component":                 "sandbox",
		"litterbox.io/sandbox-id":   id,
		"litterbox.io/template-id":  pool.Spec.TemplateID,
		poolLabel:                   pool.Name,
		"litterbox.io/pool-managed": "true",
		poolStateLabel:              stateCreating,
	}
	annotations := map[string]string{
		"litterbox.io/created-at":       time.Now().UTC().Format(time.RFC3339Nano),
		"litterbox.io/workspace-config": workspaceConfigAnnotation(spec.Workspace),
	}
	controller := true
	block := true
	return &v1alpha1.Sandbox{
		TypeMeta: metav1.TypeMeta{
			APIVersion: v1alpha1.GroupName + "/" + v1alpha1.Version,
			Kind:       v1alpha1.Kind,
		},
		ObjectMeta: metav1.ObjectMeta{
			Name:        id,
			Namespace:   pool.Namespace,
			Labels:      labels,
			Annotations: annotations,
			OwnerReferences: []metav1.OwnerReference{{
				APIVersion:         v1alpha1.GroupName + "/" + v1alpha1.Version,
				Kind:               v1alpha1.KindPool,
				Name:               pool.Name,
				UID:                pool.UID,
				Controller:         &controller,
				BlockOwnerDeletion: &block,
			}},
		},
		Spec: spec,
	}
}

func workspaceConfigAnnotation(workspace v1alpha1.WorkspaceSpec) string {
	payload := struct {
		Enabled      bool   `json:"enabled"`
		MountPath    string `json:"mount_path"`
		Size         string `json:"size"`
		StorageClass string `json:"storage_class,omitempty"`
	}{
		Enabled:      workspace.Enabled,
		MountPath:    workspace.MountPath,
		Size:         workspace.Size,
		StorageClass: workspace.StorageClassName,
	}
	raw, _ := json.Marshal(payload)
	return string(raw)
}

func (c *Controller) patchSandbox(ctx context.Context, sandbox *v1alpha1.Sandbox, body map[string]interface{}) error {
	raw, err := json.Marshal(body)
	if err != nil {
		return err
	}
	_, err = c.dynamic.Resource(sandboxGVR).Namespace(sandbox.Namespace).Patch(
		ctx,
		sandbox.Name,
		types.MergePatchType,
		raw,
		metav1.PatchOptions{},
	)
	if apierrors.IsNotFound(err) {
		return nil
	}
	return err
}

func (c *Controller) deleteSandbox(ctx context.Context, sandbox *v1alpha1.Sandbox) (bool, error) {
	resourceVersion := sandbox.ResourceVersion
	policy := metav1.DeletePropagationBackground
	err := c.dynamic.Resource(sandboxGVR).Namespace(sandbox.Namespace).Delete(
		ctx,
		sandbox.Name,
		metav1.DeleteOptions{
			Preconditions:     &metav1.Preconditions{ResourceVersion: &resourceVersion},
			PropagationPolicy: &policy,
		},
	)
	if apierrors.IsNotFound(err) || apierrors.IsConflict(err) {
		// A concurrent claim or delete won; the next event reconciles again.
		return false, nil
	}
	if err != nil {
		return false, err
	}
	slog.Info("deleted pool sandbox", "sandbox", sandbox.Namespace+"/"+sandbox.Name)
	return true, nil
}

func hasPoolOwner(sandbox *v1alpha1.Sandbox, pool *v1alpha1.SandboxPool) bool {
	for _, ref := range sandbox.OwnerReferences {
		if ref.Kind == v1alpha1.KindPool && ref.Name == pool.Name {
			return true
		}
	}
	return false
}

func (c *Controller) updateStatus(ctx context.Context, pool *v1alpha1.SandboxPool, counts sandboxCounts) error {
	status := v1alpha1.SandboxPoolStatus{
		Ready:              counts.ready,
		Creating:           counts.creating,
		Allocated:          counts.allocated,
		Failed:             counts.failed,
		Terminating:        counts.terminating,
		ObservedGeneration: pool.Generation,
	}
	if reflect.DeepEqual(pool.Status, status) {
		return nil
	}
	statusMap, err := runtime.DefaultUnstructuredConverter.ToUnstructured(&status)
	if err != nil {
		return err
	}
	raw, err := json.Marshal(map[string]interface{}{"status": statusMap})
	if err != nil {
		return err
	}
	_, err = c.dynamic.Resource(poolGVR).Namespace(pool.Namespace).Patch(
		ctx,
		pool.Name,
		types.MergePatchType,
		raw,
		metav1.PatchOptions{},
		"status",
	)
	if err != nil {
		return err
	}
	slog.Info(
		"pool status updated",
		"pool", pool.Namespace+"/"+pool.Name,
		"ready", status.Ready,
		"creating", status.Creating,
		"allocated", status.Allocated,
	)
	return nil
}

func randomID() (string, error) {
	raw := make([]byte, 4)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return hex.EncodeToString(raw), nil
}

func (c *Controller) enqueueObject(obj interface{}) {
	key, err := cache.MetaNamespaceKeyFunc(obj)
	if err != nil {
		slog.Error("enqueue pool", "err", err)
		return
	}
	c.queue.Add(key)
}

func (c *Controller) enqueueTombstone(obj interface{}) {
	if tombstone, ok := obj.(cache.DeletedFinalStateUnknown); ok {
		obj = tombstone.Obj
	}
	c.enqueueObject(obj)
}

func (c *Controller) enqueueSandboxPool(obj interface{}) {
	unstructuredObj, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return
	}
	poolName := unstructuredObj.GetLabels()[poolLabel]
	if poolName == "" {
		return
	}
	c.queue.Add(unstructuredObj.GetNamespace() + "/" + poolName)
}

func (c *Controller) enqueueSandboxPoolTombstone(obj interface{}) {
	if tombstone, ok := obj.(cache.DeletedFinalStateUnknown); ok {
		obj = tombstone.Obj
	}
	c.enqueueSandboxPool(obj)
}
