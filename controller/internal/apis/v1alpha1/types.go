// Package v1alpha1 contains the Sandbox API types.
//
// The controller consumes objects through the dynamic client and converts
// them with runtime.DefaultUnstructuredConverter, so these types intentionally
// do not implement runtime.Object or DeepCopy methods.
package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

const (
	GroupName = "litterbox.io"
	Version   = "v1alpha1"
	Kind      = "Sandbox"
	KindPool  = "SandboxPool"

	StateRunning = "Running"
	StatePaused  = "Paused"

	PhasePending = "Pending"
	PhaseRunning = "Running"
	PhasePaused  = "Paused"
	PhaseFailed  = "Failed"

	PausedReasonUser       = "Paused"
	PausedReasonTTLExpired = "TTLExpired"
)

type EnvVar struct {
	Name  string `json:"name"`
	Value string `json:"value"`
}

type HostPathMount struct {
	HostPath      string `json:"hostPath"`
	ContainerPath string `json:"containerPath"`
	ReadOnly      bool   `json:"readOnly,omitempty"`
}

type ResourceList struct {
	CPU    string `json:"cpu"`
	Memory string `json:"memory"`
}

type SandboxResources struct {
	Limits   ResourceList `json:"limits"`
	Requests ResourceList `json:"requests"`
}

type WorkspaceSpec struct {
	Enabled          bool   `json:"enabled"`
	MountPath        string `json:"mountPath"`
	Size             string `json:"size"`
	StorageClassName string `json:"storageClassName,omitempty"`
	ClaimName        string `json:"claimName"`
}

type EnvdSpec struct {
	Enabled             bool   `json:"enabled"`
	HostBinaryPath      string `json:"hostBinaryPath,omitempty"`
	ContainerBinaryPath string `json:"containerBinaryPath,omitempty"`
	Port                int32  `json:"port,omitempty"`
}

type LifecycleSpec struct {
	PostStart                     []string `json:"postStart,omitempty"`
	PreStop                       []string `json:"preStop,omitempty"`
	TerminationGracePeriodSeconds int64    `json:"terminationGracePeriodSeconds,omitempty"`
}

type SandboxSpec struct {
	TemplateID         string            `json:"templateID"`
	Image              string            `json:"image"`
	Command            []string          `json:"command,omitempty"`
	Env                []EnvVar          `json:"env,omitempty"`
	Resources          SandboxResources  `json:"resources"`
	RuntimeClassName   string            `json:"runtimeClassName,omitempty"`
	ImagePullSecret    string            `json:"imagePullSecret,omitempty"`
	ImagePullPolicy    string            `json:"imagePullPolicy,omitempty"`
	NodeSelector       map[string]string `json:"nodeSelector,omitempty"`
	HostPathMounts     []HostPathMount   `json:"hostPathMounts,omitempty"`
	Workspace          WorkspaceSpec     `json:"workspace"`
	Envd               EnvdSpec          `json:"envd"`
	Lifecycle          LifecycleSpec     `json:"lifecycle"`
	State              string            `json:"state,omitempty"`
	TTLSeconds         int64             `json:"ttlSeconds,omitempty"`
	TTLAnchor          *metav1.Time      `json:"ttlAnchor,omitempty"`
	AppArmorUnconfined bool              `json:"appArmorUnconfined,omitempty"`
	Stdin              bool              `json:"stdin,omitempty"`
	TTY                bool              `json:"tty,omitempty"`
}

type SandboxStatus struct {
	Phase              string             `json:"phase,omitempty"`
	PodName            string             `json:"podName,omitempty"`
	PodIP              string             `json:"podIP,omitempty"`
	ExpiresAt          *metav1.Time       `json:"expiresAt,omitempty"`
	ObservedGeneration int64              `json:"observedGeneration,omitempty"`
	PausedReason       string             `json:"pausedReason,omitempty"`
	Conditions         []metav1.Condition `json:"conditions,omitempty"`
}

type Sandbox struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   SandboxSpec   `json:"spec,omitempty"`
	Status SandboxStatus `json:"status,omitempty"`
}

type SandboxList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []Sandbox `json:"items"`
}

type SandboxPoolSpec struct {
	TemplateID      string      `json:"templateID"`
	SandboxTemplate SandboxSpec `json:"sandboxTemplate"`
	TargetReady     int32       `json:"targetReady"`
	MinReady        int32       `json:"minReady,omitempty"`
	MaxCreating     int32       `json:"maxCreating,omitempty"`
}

type SandboxPoolStatus struct {
	Ready              int32 `json:"ready"`
	Creating           int32 `json:"creating"`
	Allocated          int32 `json:"allocated"`
	Failed             int32 `json:"failed"`
	Terminating        int32 `json:"terminating"`
	ObservedGeneration int64 `json:"observedGeneration"`
}

type SandboxPool struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   SandboxPoolSpec   `json:"spec,omitempty"`
	Status SandboxPoolStatus `json:"status,omitempty"`
}

type SandboxPoolList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []SandboxPool `json:"items"`
}
