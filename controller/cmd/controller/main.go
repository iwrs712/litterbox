package main

import (
	"context"
	"flag"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/dynamic"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
	"k8s.io/client-go/tools/leaderelection"
	"k8s.io/client-go/tools/leaderelection/resourcelock"

	"github.com/iwrs712/litterbox/controller/internal/controller"
)

func main() {
	var (
		kubeconfig              string
		leaderElect             bool
		leaderElectionNamespace string
		workers                 int
		healthAddr              string
		resync                  time.Duration
	)
	flag.StringVar(&kubeconfig, "kubeconfig", "", "Path to a kubeconfig. Defaults to in-cluster config.")
	flag.BoolVar(&leaderElect, "leader-elect", true, "Enable leader election for controller replicas.")
	flag.StringVar(&leaderElectionNamespace, "leader-election-namespace", defaultNamespace(), "Namespace for the leader election lease.")
	flag.IntVar(&workers, "workers", 4, "Number of concurrent reconcile workers.")
	flag.StringVar(&healthAddr, "health-addr", ":8090", "Address for the health probe endpoint.")
	flag.DurationVar(&resync, "resync", 10*time.Minute, "Informer resync period.")
	flag.Parse()

	slog.SetDefault(slog.New(slog.NewTextHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo})))

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	cfg, err := buildConfig(kubeconfig)
	if err != nil {
		slog.Error("load Kubernetes config", "err", err)
		os.Exit(1)
	}
	cfg.QPS = 50
	cfg.Burst = 100

	clientset, err := kubernetes.NewForConfig(cfg)
	if err != nil {
		slog.Error("create Kubernetes client", "err", err)
		os.Exit(1)
	}
	dynamicClient, err := dynamic.NewForConfig(cfg)
	if err != nil {
		slog.Error("create dynamic client", "err", err)
		os.Exit(1)
	}

	sandboxController := controller.New(clientset, dynamicClient, resync)
	startHealthServer(ctx, healthAddr)

	if !leaderElect {
		if err := sandboxController.Run(ctx, workers); err != nil {
			slog.Error("controller stopped", "err", err)
			os.Exit(1)
		}
		return
	}

	hostname, err := os.Hostname()
	if err != nil {
		hostname = "sandbox-controller"
	}
	identity := hostname + "_" + strconv.Itoa(os.Getpid())
	lock := &resourcelock.LeaseLock{
		LeaseMeta: metav1.ObjectMeta{
			Name:      "litterbox-sandbox-controller",
			Namespace: leaderElectionNamespace,
		},
		Client: clientset.CoordinationV1(),
		LockConfig: resourcelock.ResourceLockConfig{
			Identity: identity,
		},
	}

	leaderelection.RunOrDie(ctx, leaderelection.LeaderElectionConfig{
		Lock:            lock,
		LeaseDuration:   15 * time.Second,
		RenewDeadline:   10 * time.Second,
		RetryPeriod:     2 * time.Second,
		ReleaseOnCancel: true,
		Callbacks: leaderelection.LeaderCallbacks{
			OnStartedLeading: func(leaderCtx context.Context) {
				slog.Info("became leader", "identity", identity)
				if err := sandboxController.Run(leaderCtx, workers); err != nil {
					slog.Error("controller stopped", "err", err)
				}
			},
			OnStoppedLeading: func() {
				slog.Info("lost leadership", "identity", identity)
			},
		},
	})
}

func defaultNamespace() string {
	if namespace := os.Getenv("POD_NAMESPACE"); namespace != "" {
		return namespace
	}
	return "litterbox"
}

func buildConfig(kubeconfig string) (*rest.Config, error) {
	if kubeconfig != "" {
		return clientcmd.BuildConfigFromFlags("", kubeconfig)
	}
	if cfg, err := rest.InClusterConfig(); err == nil {
		return cfg, nil
	}
	return clientcmd.BuildConfigFromFlags("", clientcmd.RecommendedHomeFile)
}

func startHealthServer(ctx context.Context, addr string) {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/readyz", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	server := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 5 * time.Second,
	}
	go func() {
		slog.Info("health server listening", "addr", addr)
		if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			slog.Error("health server", "err", err)
		}
	}()
	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdownCtx)
	}()
}
