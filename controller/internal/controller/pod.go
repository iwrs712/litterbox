package controller

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"

	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	"github.com/iwrs712/litterbox/controller/internal/apis/v1alpha1"
)

const (
	sandboxIDLabel      = "litterbox.io/sandbox-id"
	templateIDLabel     = "litterbox.io/template-id"
	componentLabel      = "component"
	componentSandbox    = "sandbox"
	componentWorkspace  = "workspace"
	specHashAnnotation  = "litterbox.io/spec-hash"
	envdVersionLabelKey = "litterbox.io/envd-version"
)

func sandboxOwnerRef(sandbox *v1alpha1.Sandbox) metav1.OwnerReference {
	controller := true
	block := true
	return metav1.OwnerReference{
		APIVersion:         v1alpha1.GroupName + "/" + v1alpha1.Version,
		Kind:               v1alpha1.Kind,
		Name:               sandbox.Name,
		UID:                sandbox.UID,
		Controller:         &controller,
		BlockOwnerDeletion: &block,
	}
}

func specHash(sandbox *v1alpha1.Sandbox) string {
	// Only Pod-affecting fields participate. TTL and desired state change
	// frequently (every connect/set_timeout) and must not recreate a running
	// Pod; pause/resume already deletes it explicitly.
	spec := sandbox.Spec
	spec.State = ""
	spec.TTLSeconds = 0
	spec.TTLAnchor = nil
	raw, _ := json.Marshal(spec)
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:])
}

func podLabels(sandbox *v1alpha1.Sandbox) map[string]string {
	labels := map[string]string{}
	for key, value := range sandbox.Labels {
		labels[key] = value
	}
	labels["app"] = sandbox.Name
	labels[componentLabel] = componentSandbox
	labels[sandboxIDLabel] = sandbox.Name
	labels[templateIDLabel] = sandbox.Spec.TemplateID
	return labels
}

func podAnnotations(sandbox *v1alpha1.Sandbox) map[string]string {
	annotations := map[string]string{}
	for key, value := range sandbox.Annotations {
		annotations[key] = value
	}
	annotations[specHashAnnotation] = specHash(sandbox)
	return annotations
}

func buildPod(sandbox *v1alpha1.Sandbox) *corev1.Pod {
	volumes := []corev1.Volume{}
	volumeMounts := []corev1.VolumeMount{}
	ports := []corev1.ContainerPort{}

	if sandbox.Spec.Workspace.Enabled {
		volumes = append(volumes, corev1.Volume{
			Name: "workspace",
			VolumeSource: corev1.VolumeSource{
				PersistentVolumeClaim: &corev1.PersistentVolumeClaimVolumeSource{
					ClaimName: sandbox.Spec.Workspace.ClaimName,
				},
			},
		})
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "workspace",
			MountPath: sandbox.Spec.Workspace.MountPath,
		})
	}

	if sandbox.Spec.Envd.Enabled {
		volumes = append(volumes, corev1.Volume{
			Name: "envd",
			VolumeSource: corev1.VolumeSource{
				HostPath: &corev1.HostPathVolumeSource{
					Path: sandbox.Spec.Envd.HostBinaryPath,
					Type: hostPathType(corev1.HostPathFile),
				},
			},
		})
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      "envd",
			MountPath: sandbox.Spec.Envd.ContainerBinaryPath,
			ReadOnly:  true,
		})
		ports = append(ports, corev1.ContainerPort{
			Name:          "envd",
			ContainerPort: sandbox.Spec.Envd.Port,
		})
	}

	for index, mount := range sandbox.Spec.HostPathMounts {
		name := fmt.Sprintf("host-mount-%d", index)
		volumes = append(volumes, corev1.Volume{
			Name: name,
			VolumeSource: corev1.VolumeSource{
				HostPath: &corev1.HostPathVolumeSource{
					Path: mount.HostPath,
					Type: hostPathType(corev1.HostPathDirectoryOrCreate),
				},
			},
		})
		volumeMounts = append(volumeMounts, corev1.VolumeMount{
			Name:      name,
			MountPath: mount.ContainerPath,
			ReadOnly:  mount.ReadOnly,
		})
	}

	env := make([]corev1.EnvVar, 0, len(sandbox.Spec.Env))
	for _, item := range sandbox.Spec.Env {
		env = append(env, corev1.EnvVar{Name: item.Name, Value: item.Value})
	}

	resources := corev1.ResourceRequirements{
		Limits: corev1.ResourceList{
			corev1.ResourceCPU:    resource.MustParse(sandbox.Spec.Resources.Limits.CPU),
			corev1.ResourceMemory: resource.MustParse(sandbox.Spec.Resources.Limits.Memory),
		},
		Requests: corev1.ResourceList{
			corev1.ResourceCPU:    resource.MustParse(sandbox.Spec.Resources.Requests.CPU),
			corev1.ResourceMemory: resource.MustParse(sandbox.Spec.Resources.Requests.Memory),
		},
	}

	var lifecycle *corev1.Lifecycle
	if len(sandbox.Spec.Lifecycle.PostStart) > 0 || len(sandbox.Spec.Lifecycle.PreStop) > 0 {
		lifecycle = &corev1.Lifecycle{}
		if len(sandbox.Spec.Lifecycle.PostStart) > 0 {
			lifecycle.PostStart = &corev1.LifecycleHandler{
				Exec: &corev1.ExecAction{Command: sandbox.Spec.Lifecycle.PostStart},
			}
		}
		if len(sandbox.Spec.Lifecycle.PreStop) > 0 {
			lifecycle.PreStop = &corev1.LifecycleHandler{
				Exec: &corev1.ExecAction{Command: sandbox.Spec.Lifecycle.PreStop},
			}
		}
	}

	container := corev1.Container{
		Name:            "main",
		Image:           sandbox.Spec.Image,
		Command:         sandbox.Spec.Command,
		Env:             env,
		Ports:           ports,
		Resources:       resources,
		VolumeMounts:    volumeMounts,
		Lifecycle:       lifecycle,
		ImagePullPolicy: pullPolicy(sandbox.Spec.ImagePullPolicy),
		Stdin:           sandbox.Spec.Stdin,
		TTY:             sandbox.Spec.TTY,
	}
	if sandbox.Spec.AppArmorUnconfined {
		container.SecurityContext = &corev1.SecurityContext{
			AppArmorProfile: &corev1.AppArmorProfile{
				Type: corev1.AppArmorProfileTypeUnconfined,
			},
		}
	}

	podSpec := corev1.PodSpec{
		RestartPolicy: corev1.RestartPolicyAlways,
		Containers:    []corev1.Container{container},
		Volumes:       volumes,
		NodeSelector:  sandbox.Spec.NodeSelector,
	}
	if sandbox.Spec.RuntimeClassName != "" {
		podSpec.RuntimeClassName = &sandbox.Spec.RuntimeClassName
	}
	if sandbox.Spec.ImagePullSecret != "" {
		podSpec.ImagePullSecrets = []corev1.LocalObjectReference{{Name: sandbox.Spec.ImagePullSecret}}
	}
	if sandbox.Spec.Lifecycle.TerminationGracePeriodSeconds > 0 {
		grace := sandbox.Spec.Lifecycle.TerminationGracePeriodSeconds
		podSpec.TerminationGracePeriodSeconds = &grace
	}

	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:            sandbox.Name,
			Namespace:       sandbox.Namespace,
			Labels:          podLabels(sandbox),
			Annotations:     podAnnotations(sandbox),
			OwnerReferences: []metav1.OwnerReference{sandboxOwnerRef(sandbox)},
		},
		Spec: podSpec,
	}
}

func buildPVC(sandbox *v1alpha1.Sandbox) *corev1.PersistentVolumeClaim {
	volumeMode := corev1.PersistentVolumeFilesystem
	labels := map[string]string{
		"app":           "litterbox",
		componentLabel:  componentWorkspace,
		sandboxIDLabel:  sandbox.Name,
		templateIDLabel: sandbox.Spec.TemplateID,
	}
	pvc := &corev1.PersistentVolumeClaim{
		ObjectMeta: metav1.ObjectMeta{
			Name:            sandbox.Spec.Workspace.ClaimName,
			Namespace:       sandbox.Namespace,
			Labels:          labels,
			OwnerReferences: []metav1.OwnerReference{sandboxOwnerRef(sandbox)},
		},
		Spec: corev1.PersistentVolumeClaimSpec{
			AccessModes: []corev1.PersistentVolumeAccessMode{corev1.ReadWriteOnce},
			VolumeMode:  &volumeMode,
			Resources: corev1.VolumeResourceRequirements{
				Requests: corev1.ResourceList{
					corev1.ResourceStorage: resource.MustParse(sandbox.Spec.Workspace.Size),
				},
			},
		},
	}
	if sandbox.Spec.Workspace.StorageClassName != "" {
		className := sandbox.Spec.Workspace.StorageClassName
		pvc.Spec.StorageClassName = &className
	}
	return pvc
}

func hostPathType(value corev1.HostPathType) *corev1.HostPathType {
	return &value
}

func pullPolicy(value string) corev1.PullPolicy {
	switch corev1.PullPolicy(value) {
	case corev1.PullAlways, corev1.PullNever, corev1.PullIfNotPresent:
		return corev1.PullPolicy(value)
	default:
		// Templates normally pin a tag, and clusters without registry access
		// should be able to reuse a locally imported image.
		return corev1.PullIfNotPresent
	}
}
