package controller

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"reflect"
	"time"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/wait"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/dynamic/dynamicinformer"
	"k8s.io/client-go/informers"
	coreinformers "k8s.io/client-go/informers/core/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/tools/cache"
	"k8s.io/client-go/util/workqueue"

	"github.com/iwrs712/litterbox/controller/internal/apis/v1alpha1"
)

var sandboxGVR = schema.GroupVersionResource{
	Group:    v1alpha1.GroupName,
	Version:  v1alpha1.Version,
	Resource: "sandboxes",
}

// Controller reconciles Sandbox custom resources into Pods and PVCs.
//
// All reads go through informer caches; the API server only receives writes.
// The controller is level-triggered: every pass compares desired and observed
// state, so a crash, a lost event or a partially created sandbox converges on
// the next pass instead of leaving a stuck intermediate state.
type Controller struct {
	clientset kubernetes.Interface
	dynamic   dynamic.Interface

	dynamicFactory  dynamicinformer.DynamicSharedInformerFactory
	informerFactory informers.SharedInformerFactory

	sandboxInformer cache.SharedIndexInformer
	podInformer     coreinformers.PodInformer
	pvcInformer     coreinformers.PersistentVolumeClaimInformer

	queue workqueue.TypedRateLimitingInterface[string]
}

func New(clientset kubernetes.Interface, dynamicClient dynamic.Interface, resync time.Duration) *Controller {
	controller := &Controller{
		clientset: clientset,
		dynamic:   dynamicClient,
		queue: workqueue.NewTypedRateLimitingQueue(
			workqueue.DefaultTypedControllerRateLimiter[string](),
		),
	}

	controller.dynamicFactory = dynamicinformer.NewFilteredDynamicSharedInformerFactory(
		dynamicClient,
		resync,
		metav1.NamespaceAll,
		nil,
	)
	controller.informerFactory = informers.NewSharedInformerFactory(clientset, resync)

	controller.sandboxInformer = controller.dynamicFactory.ForResource(sandboxGVR).Informer()
	controller.podInformer = controller.informerFactory.Core().V1().Pods()
	controller.pvcInformer = controller.informerFactory.Core().V1().PersistentVolumeClaims()

	controller.sandboxInformer.AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    controller.enqueueObject,
		UpdateFunc: func(_, newObj interface{}) { controller.enqueueObject(newObj) },
		DeleteFunc: controller.enqueueTombstone,
	})
	controller.podInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    controller.enqueuePod,
		UpdateFunc: func(_, newObj interface{}) { controller.enqueuePod(newObj) },
		DeleteFunc: controller.enqueuePodTombstone,
	})
	controller.pvcInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
		AddFunc:    controller.enqueueClaim,
		UpdateFunc: func(_, newObj interface{}) { controller.enqueueClaim(newObj) },
		DeleteFunc: controller.enqueueClaimTombstone,
	})

	return controller
}

func (c *Controller) Run(ctx context.Context, workers int) error {
	defer c.queue.ShutDown()

	c.dynamicFactory.Start(ctx.Done())
	c.informerFactory.Start(ctx.Done())

	if !cache.WaitForCacheSync(
		ctx.Done(),
		c.sandboxInformer.HasSynced,
		c.podInformer.Informer().HasSynced,
		c.pvcInformer.Informer().HasSynced,
	) {
		return fmt.Errorf("timed out waiting for informer caches to sync")
	}

	slog.Info("sandbox controller started", "workers", workers)
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
		slog.Error("reconcile failed", "key", key, "err", err)
		c.queue.AddRateLimited(key)
		return true
	}
	c.queue.Forget(key)
	return true
}

func (c *Controller) sync(ctx context.Context, key string) error {
	namespace, name, err := cache.SplitMetaNamespaceKey(key)
	if err != nil {
		return err
	}
	obj, exists, err := c.sandboxInformer.GetStore().GetByKey(key)
	if err != nil {
		return err
	}
	if !exists {
		return nil
	}
	unstructuredObj, ok := obj.(*unstructured.Unstructured)
	if !ok {
		return fmt.Errorf("unexpected object type %T for %s", obj, key)
	}
	sandbox := &v1alpha1.Sandbox{}
	if err := runtime.DefaultUnstructuredConverter.FromUnstructured(unstructuredObj.Object, sandbox); err != nil {
		return fmt.Errorf("decode sandbox %s/%s: %w", namespace, name, err)
	}
	return c.reconcile(ctx, key, sandbox)
}

func (c *Controller) reconcile(ctx context.Context, key string, sandbox *v1alpha1.Sandbox) error {
	namespace := sandbox.Namespace
	name := sandbox.Name

	if sandbox.DeletionTimestamp != nil {
		// Pod and PVC carry an ownerReference, so Kubernetes garbage
		// collection removes them once the Sandbox is gone.
		return nil
	}

	now := time.Now()
	var expiresAt *metav1.Time
	expired := false
	if sandbox.Spec.TTLSeconds > 0 && sandbox.Spec.TTLAnchor != nil {
		expiry := sandbox.Spec.TTLAnchor.Add(time.Duration(sandbox.Spec.TTLSeconds) * time.Second)
		expiresAt = &metav1.Time{Time: expiry}
		expired = !now.Before(expiry)
	}

	desiredRunning := sandbox.Spec.State != v1alpha1.StatePaused && !expired
	pausedReason := ""
	switch {
	case sandbox.Spec.State == v1alpha1.StatePaused:
		pausedReason = v1alpha1.PausedReasonUser
	case expired:
		pausedReason = v1alpha1.PausedReasonTTLExpired
	}

	if sandbox.Spec.Workspace.Enabled && sandbox.Spec.Workspace.ClaimName != "" {
		if err := c.ensurePVC(ctx, sandbox); err != nil {
			return err
		}
	}

	pod, err := c.podInformer.Lister().Pods(namespace).Get(name)
	if apierrors.IsNotFound(err) {
		pod = nil
	} else if err != nil {
		return err
	}

	if !desiredRunning {
		if pod != nil && pod.DeletionTimestamp == nil {
			if err := c.deletePod(ctx, pod); err != nil {
				return err
			}
		}
	} else if pod == nil {
		if _, err := c.clientset.CoreV1().Pods(namespace).Create(
			ctx, buildPod(sandbox), metav1.CreateOptions{},
		); err != nil && !apierrors.IsAlreadyExists(err) {
			return err
		}
		slog.Info("created sandbox pod", "sandbox", namespace+"/"+name)
	} else if pod.DeletionTimestamp != nil {
		c.queue.AddAfter(key, 2*time.Second)
	} else if pod.Status.Phase == corev1.PodFailed || pod.Status.Phase == corev1.PodSucceeded {
		if err := c.deletePod(ctx, pod); err != nil {
			return err
		}
	} else if pod.Annotations[specHashAnnotation] != specHash(sandbox) {
		slog.Info("sandbox spec changed, recreating pod", "sandbox", namespace+"/"+name)
		if err := c.deletePod(ctx, pod); err != nil {
			return err
		}
	}

	// TTL expiry is a time-based event. Re-enqueue exactly when the deadline
	// passes so a running sandbox is paused even when nothing else changes.
	if desiredRunning && expiresAt != nil && !expired {
		if delay := time.Until(expiresAt.Time); delay > 0 {
			c.queue.AddAfter(key, delay)
		}
	}

	status := c.computeStatus(sandbox, pod, desiredRunning, pausedReason, expiresAt)
	if reflect.DeepEqual(sandbox.Status, status) {
		return nil
	}
	return c.updateStatus(ctx, sandbox, status)
}

func (c *Controller) ensurePVC(ctx context.Context, sandbox *v1alpha1.Sandbox) error {
	claimName := sandbox.Spec.Workspace.ClaimName
	_, err := c.pvcInformer.Lister().PersistentVolumeClaims(sandbox.Namespace).Get(claimName)
	if apierrors.IsNotFound(err) {
		_, err = c.clientset.CoreV1().PersistentVolumeClaims(sandbox.Namespace).Create(
			ctx, buildPVC(sandbox), metav1.CreateOptions{},
		)
		if err != nil && !apierrors.IsAlreadyExists(err) {
			return err
		}
		slog.Info("created sandbox workspace", "sandbox", sandbox.Namespace+"/"+sandbox.Name, "pvc", claimName)
		return nil
	}
	return err
}

func (c *Controller) deletePod(ctx context.Context, pod *corev1.Pod) error {
	grace := int64(0)
	policy := metav1.DeletePropagationBackground
	err := c.clientset.CoreV1().Pods(pod.Namespace).Delete(ctx, pod.Name, metav1.DeleteOptions{
		GracePeriodSeconds: &grace,
		PropagationPolicy:  &policy,
	})
	if apierrors.IsNotFound(err) {
		return nil
	}
	if err == nil {
		slog.Info("deleted sandbox pod", "sandbox", pod.Namespace+"/"+pod.Name)
	}
	return err
}

func (c *Controller) computeStatus(
	sandbox *v1alpha1.Sandbox,
	pod *corev1.Pod,
	desiredRunning bool,
	pausedReason string,
	expiresAt *metav1.Time,
) v1alpha1.SandboxStatus {
	status := v1alpha1.SandboxStatus{
		ObservedGeneration: sandbox.Generation,
		ExpiresAt:          expiresAt,
		Conditions:         append([]metav1.Condition(nil), sandbox.Status.Conditions...),
	}

	ready := false
	if pod != nil {
		status.PodName = pod.Name
		status.PodIP = pod.Status.PodIP
		ready = podReady(pod)
	}

	switch {
	case !desiredRunning:
		status.Phase = v1alpha1.PhasePaused
		status.PausedReason = pausedReason
	case pod == nil:
		status.Phase = v1alpha1.PhasePending
	case pod.Status.Phase == corev1.PodFailed:
		status.Phase = v1alpha1.PhaseFailed
	case ready:
		status.Phase = v1alpha1.PhaseRunning
	default:
		status.Phase = v1alpha1.PhasePending
	}

	conditionStatus := metav1.ConditionFalse
	reason := "PodNotReady"
	message := "sandbox pod is not ready"
	if status.Phase == v1alpha1.PhaseRunning {
		conditionStatus = metav1.ConditionTrue
		reason = "PodReady"
		message = "sandbox pod is ready"
	} else if status.Phase == v1alpha1.PhasePaused {
		reason = pausedReason
		message = "sandbox is paused"
	} else if status.Phase == v1alpha1.PhaseFailed {
		reason = "PodFailed"
		message = "sandbox pod failed"
	}
	meta.SetStatusCondition(&status.Conditions, metav1.Condition{
		Type:               "Ready",
		Status:             conditionStatus,
		Reason:             reason,
		Message:            message,
		ObservedGeneration: sandbox.Generation,
	})

	return status
}

func (c *Controller) updateStatus(
	ctx context.Context,
	sandbox *v1alpha1.Sandbox,
	status v1alpha1.SandboxStatus,
) error {
	statusMap, err := runtime.DefaultUnstructuredConverter.ToUnstructured(&status)
	if err != nil {
		return fmt.Errorf("encode status: %w", err)
	}
	// JSON merge patch keeps omitted keys. Clear fields that no longer apply so
	// a resumed sandbox does not carry a stale pausedReason or pod address.
	if status.ExpiresAt == nil {
		statusMap["expiresAt"] = nil
	}
	if status.PausedReason == "" {
		statusMap["pausedReason"] = nil
	}
	if status.PodName == "" {
		statusMap["podName"] = nil
	}
	if status.PodIP == "" {
		statusMap["podIP"] = nil
	}
	body, err := json.Marshal(map[string]interface{}{"status": statusMap})
	if err != nil {
		return fmt.Errorf("encode status patch: %w", err)
	}
	_, err = c.dynamic.Resource(sandboxGVR).Namespace(sandbox.Namespace).Patch(
		ctx,
		sandbox.Name,
		types.MergePatchType,
		body,
		metav1.PatchOptions{},
		"status",
	)
	if err != nil {
		return fmt.Errorf("update sandbox status: %w", err)
	}
	slog.Info(
		"sandbox status updated",
		"sandbox", sandbox.Namespace+"/"+sandbox.Name,
		"phase", status.Phase,
		"podIP", status.PodIP,
	)
	return nil
}

func podReady(pod *corev1.Pod) bool {
	if pod.DeletionTimestamp != nil || pod.Status.Phase != corev1.PodRunning {
		return false
	}
	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodReady {
			return condition.Status == corev1.ConditionTrue
		}
	}
	return false
}

func (c *Controller) enqueueObject(obj interface{}) {
	key, err := cache.MetaNamespaceKeyFunc(obj)
	if err != nil {
		slog.Error("enqueue sandbox", "err", err)
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

func (c *Controller) enqueuePod(obj interface{}) {
	pod, ok := obj.(*corev1.Pod)
	if !ok {
		return
	}
	sandboxID := pod.Labels[sandboxIDLabel]
	if sandboxID == "" {
		return
	}
	c.queue.Add(pod.Namespace + "/" + sandboxID)
}

func (c *Controller) enqueuePodTombstone(obj interface{}) {
	if tombstone, ok := obj.(cache.DeletedFinalStateUnknown); ok {
		obj = tombstone.Obj
	}
	c.enqueuePod(obj)
}

func (c *Controller) enqueueClaim(obj interface{}) {
	claim, ok := obj.(*corev1.PersistentVolumeClaim)
	if !ok {
		return
	}
	sandboxID := claim.Labels[sandboxIDLabel]
	if sandboxID == "" {
		return
	}
	c.queue.Add(claim.Namespace + "/" + sandboxID)
}

func (c *Controller) enqueueClaimTombstone(obj interface{}) {
	if tombstone, ok := obj.(cache.DeletedFinalStateUnknown); ok {
		obj = tombstone.Obj
	}
	c.enqueueClaim(obj)
}
