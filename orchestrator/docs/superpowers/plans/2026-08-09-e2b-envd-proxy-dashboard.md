# E2B envd Proxy and Dashboard Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Kubernetes Exec data plane with an injected E2B-compatible envd, expose it through an authenticated sandbox-aware proxy, and migrate dashboard command and terminal workflows to Connect.

**Architecture:** The orchestrator mounts the static envd binary into each main container and starts it from `postStart`. Dashboard requests reach envd through a transparent `/api/v1/sandboxes/{id}/envd/*` proxy that resolves only the requested ready Pod; dashboard Process RPCs use Connect-Web while file content uses envd's `/files` HTTP endpoint.

**Tech Stack:** Python 3.12, FastAPI, httpx, Kubernetes Python client, Go, Connect-Go, React 18, TypeScript, Connect-ES, Buf, pytest.

---

## File Map

- `orchestrator/src/orchestrator/config.py`: envd injection and proxy settings.
- `orchestrator/src/orchestrator/services/sandboxes.py`: inject envd into the main container.
- `orchestrator/src/orchestrator/services/envd_proxy.py`: stream requests to a sandbox envd.
- `orchestrator/src/orchestrator/routes/envd.py`: authenticated catch-all proxy route.
- `orchestrator/src/orchestrator/infra/kubernetes.py`: resolve a ready Pod IP; remove Exec support.
- `envd/internal/server/server.go`: remove legacy filesystem/process REST routes.
- `dashboard/src/gen/envd/`: generated envd TypeScript descriptors.
- `dashboard/src/lib/envd.ts`: Connect transport, command, and terminal helpers.
- `dashboard/src/components/Terminal.tsx`: E2B Process terminal UI.

### Task 1: Add Configurable envd Injection

**Files:**
- Modify: `orchestrator/src/orchestrator/config.py`
- Modify: `orchestrator/config.toml`
- Modify: `orchestrator/src/orchestrator/services/sandboxes.py`
- Create: `orchestrator/tests/test_envd_injection.py`
- Modify: `orchestrator/tests/test_sandbox_lifecycle.py`

- [ ] **Step 1: Write failing injection tests**

Build a Deployment with envd enabled and assert the exact mount and command:

```python
def test_build_deployment_injects_envd() -> None:
    service = build_service(EnvdConfig(enabled=True))
    deployment = build_deployment(service, build_template())
    pod_spec = deployment.spec.template.spec
    container = pod_spec.containers[0]
    volume = next(item for item in pod_spec.volumes if item.name == "envd")
    mount = next(item for item in container.volume_mounts if item.name == "envd")

    assert volume.host_path.path == "/opt/litterbox/bin/envd"
    assert volume.host_path.type == "File"
    assert mount.mount_path == "/opt/litterbox/bin/envd"
    assert mount.read_only is True
    assert container.lifecycle.post_start._exec.command == [
        "/opt/litterbox/bin/envd", "daemon",
        "--host", "0.0.0.0", "--port", "49983",
        "--filesystem-root", "/",
    ]
    assert [(item.name, item.container_port) for item in container.ports] == [("envd", 49983)]
```

Also assert disabled injection adds no envd volume, and enabled injection rejects a template with `postStart` using `ValueError("template postStart conflicts with envd injection")`.

- [ ] **Step 2: Verify the tests fail**

Run `cd orchestrator && pytest tests/test_envd_injection.py tests/test_sandbox_lifecycle.py -q`.

Expected: failure because `EnvdConfig` and Deployment injection do not exist.

- [ ] **Step 3: Add validated settings**

```python
class EnvdConfig(BaseModel):
    enabled: bool = False
    host_binary_path: str = "/opt/litterbox/bin/envd"
    container_binary_path: str = "/opt/litterbox/bin/envd"
    port: int = Field(default=49983, ge=1, le=65535)
    connect_timeout_seconds: float = Field(default=3.0, gt=0)

    @field_validator("host_binary_path", "container_binary_path")
    @classmethod
    def binary_paths_must_be_absolute(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("envd binary paths must be absolute")
        return value


class Settings(BaseModel):
    # existing settings remain
    envd: EnvdConfig = Field(default_factory=EnvdConfig)
```

Add the equivalent disabled `[envd]` block to `config.toml`. Operators enable it only after installing the binary on every schedulable node.

- [ ] **Step 4: Inject hostPath, mount, port, and lifecycle**

Append a `V1HostPathVolumeSource(type="File")`, read-only file mount, and named port. Convert `_build_container_lifecycle` into an instance method and select envd `postStart` when enabled:

```python
post_start = client.V1LifecycleHandler(
    _exec=client.V1ExecAction(command=[
        self.settings.envd.container_binary_path,
        "daemon", "--host", "0.0.0.0",
        "--port", str(self.settings.envd.port),
        "--filesystem-root", "/",
    ])
)
```

Preserve the existing template `preStop` and termination grace period. Reject, rather than overwrite, an existing template `postStart`.

- [ ] **Step 5: Verify and commit**

Run:

```bash
cd orchestrator
pytest tests/test_envd_injection.py tests/test_sandbox_lifecycle.py tests/test_workspace_pvc_provisioning.py -q
```

Expected: all selected tests pass.

Commit only these Task 1 files with `git commit -m "feat: inject envd into sandbox containers"`.

### Task 2: Add the Authenticated envd Streaming Proxy

**Files:**
- Create: `orchestrator/src/orchestrator/services/envd_proxy.py`
- Create: `orchestrator/src/orchestrator/routes/envd.py`
- Modify: `orchestrator/src/orchestrator/infra/kubernetes.py`
- Modify: `orchestrator/src/orchestrator/container.py`
- Modify: `orchestrator/src/orchestrator/main.py`
- Create: `orchestrator/tests/test_envd_proxy.py`

- [ ] **Step 1: Write failing proxy tests**

Use a fake gateway and `httpx.MockTransport` to assert:

```python
def test_proxy_rewrites_path_and_filters_auth(client, upstream_requests) -> None:
    response = client.get(
        "/api/v1/sandboxes/sbx-1/envd/files?path=%2Fworkspace%2Fa.txt",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200
    request = upstream_requests[0]
    assert request.url.path == "/files"
    assert request.url.query == b"path=%2Fworkspace%2Fa.txt"
    assert "authorization" not in request.headers
```

Add tests for `404` missing sandbox, `409` stopped sandbox, `503` ready Pod without IP, `502` connection failure, and two-chunk streaming without `ApiResponse` wrapping.

- [ ] **Step 2: Verify proxy tests fail**

Run `cd orchestrator && pytest tests/test_envd_proxy.py -q`.

Expected: failure because the service, route, and Pod-IP resolver are absent.

- [ ] **Step 3: Resolve only a ready Pod IP**

```python
def get_ready_pod_ip(self, sandbox_id: str) -> str:
    for pod in self.list_pods(f"app={sandbox_id},component=sandbox"):
        if pod.metadata.deletion_timestamp is not None or pod.status.phase != "Running":
            continue
        statuses = pod.status.container_statuses or []
        if statuses and all(status.ready for status in statuses):
            if not pod.status.pod_ip:
                raise SandboxPodAddressUnavailableError(
                    f"sandbox {sandbox_id} running Pod has no IP"
                )
            return pod.status.pod_ip
    raise SandboxNotRunningError(f"sandbox {sandbox_id} is not running")
```

- [ ] **Step 4: Implement transparent streaming**

Build the upstream request with `content=request.stream()`, send with `stream=True`, and close both response and client in the returned generator:

```python
client = httpx.AsyncClient(
    timeout=httpx.Timeout(None, connect=settings.envd.connect_timeout_seconds),
    trust_env=False,
)
upstream_request = client.build_request(
    request.method, url,
    headers=forward_request_headers(request.headers),
    content=request.stream(),
)
upstream = await client.send(upstream_request, stream=True)

async def body():
    try:
        async for chunk in upstream.aiter_raw():
            yield chunk
    finally:
        await upstream.aclose()
        await client.aclose()
```

Forward content, encoding, Connect, and gRPC-Web headers. Remove hop-by-hop headers and external `Authorization`.

- [ ] **Step 5: Register the catch-all route**

```python
@router.api_route(
    "/api/v1/sandboxes/{sandbox_id}/envd/{envd_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_envd(sandbox_id: str, envd_path: str, request: Request, container=Depends(get_container)):
    container.sandbox_service.get_sandbox(sandbox_id)
    return await container.envd_proxy_service.proxy(sandbox_id, envd_path, request)
```

Map domain errors to `404/409/503/502` without wrapping successful upstream responses.

- [ ] **Step 6: Verify and commit**

Run `cd orchestrator && pytest tests/test_envd_proxy.py tests/test_api_bearer_auth.py -q`.

Expected: all selected tests pass. Commit Task 2 files with `git commit -m "feat: proxy sandbox envd traffic"`.

### Task 3: Remove the Orchestrator Kubernetes Exec Data Plane

**Files:**
- Modify: `orchestrator/src/orchestrator/routes/sandboxes.py`
- Delete: `orchestrator/src/orchestrator/routes/ws.py`
- Delete: `orchestrator/src/orchestrator/services/workspace.py`
- Modify: `orchestrator/src/orchestrator/main.py`
- Modify: `orchestrator/src/orchestrator/container.py`
- Modify: `orchestrator/src/orchestrator/infra/kubernetes.py`
- Modify: `orchestrator/src/orchestrator/domain/models.py`
- Modify: `orchestrator/tests/test_api_bearer_auth.py`
- Modify: `orchestrator/tests/test_sandbox_suspension.py`
- Modify: `orchestrator/tests/integration/test_api.py`

- [ ] **Step 1: Write route-removal assertions**

```python
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/sandboxes/sbx-1/exec"),
        ("get", "/api/v1/sandboxes/sbx-1/files"),
        ("put", "/api/v1/sandboxes/sbx-1/files?path=/workspace/a"),
        ("delete", "/api/v1/sandboxes/sbx-1/files?path=/workspace/a"),
    ],
)
def test_private_data_plane_routes_are_removed(client, method, path) -> None:
    assert getattr(client, method)(path).status_code == 404
```

Replace terminal WebSocket auth tests with assertions that `/terminal` and `/acp` no longer upgrade.

- [ ] **Step 2: Verify route-removal tests fail**

Run `cd orchestrator && pytest tests/test_api_bearer_auth.py tests/test_sandbox_suspension.py -q`.

Expected: failures because the private routes still exist.

- [ ] **Step 3: Delete private routes and dead services**

Remove `exec`, `files`, terminal, and ACP routes. Remove `ws.router`, `workspace_service`, `WorkspaceService`, and these private models:

```text
ExecCommandRequest, ExecCommandResult, FileKind, FileView, FileNode,
FileListResponse, FileWriteResult, FileDeleteResult
```

Remove `SandboxService.exec_command()` and Kubernetes Gateway helpers used only for Exec:

```text
_container_name, _exec_stream, _collect_exec_response, exec_command,
exec_shell, open_shell, open_acp
```

Retain normal CoreV1 construction, Pod listing, `get_ready_pod_ip`, and all lifecycle/storage methods.

- [ ] **Step 4: Replace integration coverage**

Replace old Kubernetes Exec integration checks with:

```python
health = client.get(f"/api/v1/sandboxes/{created_sandbox}/envd/health")
assert health.status_code == 200
assert client.post(f"/api/v1/sandboxes/{created_sandbox}/exec").status_code == 404
```

Skip the health assertion when envd injection is intentionally disabled in the integration environment.

- [ ] **Step 5: Verify and commit**

Run `cd orchestrator && pytest -q`.

Expected: all tests pass. Commit Task 3 files with `git commit -m "refactor: remove kubernetes exec data plane"`.

### Task 4: Remove Legacy Go Filesystem and Process REST APIs

**Files:**
- Modify: `envd/internal/server/server.go`
- Modify: `envd/internal/server/server_test.go`
- Delete or reduce: legacy REST-specific tests under `envd/internal/server/`

- [ ] **Step 1: Write a failing route-removal test**

```go
func TestLegacyDataPlaneRoutesAreRemoved(t *testing.T) {
    handler := New(testConfig(t))
    cases := []struct{ method, path string }{
        {http.MethodGet, "/v1/fs/entries?path=/"},
        {http.MethodGet, "/v1/fs/file?path=/missing"},
        {http.MethodPost, "/v1/processes/run"},
        {http.MethodGet, "/v1/processes/1"},
    }
    for _, tc := range cases {
        request := httptest.NewRequest(tc.method, tc.path, nil)
        response := httptest.NewRecorder()
        handler.ServeHTTP(response, request)
        if response.Code != http.StatusNotFound {
            t.Fatalf("%s %s returned %d, want 404", tc.method, tc.path, response.Code)
        }
    }
}
```

- [ ] **Step 2: Verify the Go test fails**

Run:

```bash
cd envd
go test ./internal/server -run TestLegacyDataPlaneRoutesAreRemoved -count=1
```

Expected: failures because old routes still return their existing results.

- [ ] **Step 3: Remove registrations and unreachable handlers**

The mux must retain only the E2B data plane and explicitly retained product features:

```go
mux.Handle(filesystemPath, filesystemHandler)
mux.Handle(processPath, processHandler)
mux.Handle("/files", envd.NewFilesHandler(filesystem))
mux.HandleFunc("GET /health", server.health)
mux.HandleFunc("GET /{$}", server.root)

mux.HandleFunc("PUT /v1/skills/{slug}", server.installSkill)
mux.HandleFunc("DELETE /v1/skills/{slug}", server.removeSkill)
mux.HandleFunc("POST /v1/acp/{id}", server.acpPost)
mux.HandleFunc("GET /v1/acp/{id}", server.acpEvents)
mux.HandleFunc("GET /v1/acp", server.acpStats)
mux.HandleFunc("DELETE /v1/acp/{id}", server.acpDelete)
mux.HandleFunc("POST /v1/messages", server.anthropicMessagesProxy)
mux.HandleFunc("POST /v1/messages/{path...}", server.anthropicMessagesProxy)
mux.HandleFunc("GET /v1/models", server.anthropicMessagesProxy)
mux.HandleFunc("GET /v1/models/{path...}", server.anthropicMessagesProxy)
```

Delete unreachable filesystem/process REST handlers. Use `rg` to preserve helpers still called by Skills or ACP, then run `goimports`.

- [ ] **Step 4: Verify and commit**

Run:

```bash
cd envd
make generate
make test
go test -race ./...
go vet ./...
make build-linux-amd64
```

Expected: all checks pass and the artifact remains a static x86-64 ELF. Commit with `git commit -m "refactor: remove legacy envd REST data plane"`.

### Task 5: Generate Dashboard Connect Clients

**Files:**
- Modify: `dashboard/package.json`
- Modify: `dashboard/package-lock.json`
- Create: `dashboard/buf.gen.yaml`
- Create: `dashboard/src/gen/envd/filesystem/filesystem_pb.ts`
- Create: `dashboard/src/gen/envd/process/process_pb.ts`
- Create: `dashboard/src/lib/envd.ts`
- Create: `dashboard/src/lib/envd.test.ts`

- [ ] **Step 1: Write failing envd URL and transport tests**

```ts
describe('envdBaseUrl', () => {
  it('routes through the authenticated orchestrator proxy', () => {
    expect(envdBaseUrl('sbx/a')).toBe(
      'http://localhost:8080/api/v1/sandboxes/sbx%2Fa/envd'
    );
  });
});
```

Add an interceptor test that verifies the configured bearer token is attached to Connect requests.

- [ ] **Step 2: Install runtime and generation dependencies**

```bash
cd dashboard
npm install @bufbuild/protobuf@^2 @connectrpc/connect@^2 @connectrpc/connect-web@^2
npm install --save-dev @bufbuild/protoc-gen-es@^2
```

Keep `package-lock.json` authoritative; do not mechanically regenerate `pnpm-lock.yaml`.

- [ ] **Step 3: Add deterministic Buf generation**

```yaml
version: v2
plugins:
  - local: protoc-gen-es
    out: src/gen/envd
    opt:
      - target=ts
      - import_extension=none
inputs:
  - directory: ../envd/proto
```

Add `"generate:envd": "buf generate --template buf.gen.yaml"` and make `build` run generation before TypeScript/Vite. Run `npm run generate:envd` and commit generated descriptors.

- [ ] **Step 4: Implement authenticated Connect transport**

```ts
import { createClient, type Interceptor } from '@connectrpc/connect';
import { createConnectTransport } from '@connectrpc/connect-web';
import { Process } from '@/gen/envd/process/process_pb';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
const TOKEN = (import.meta.env.VITE_API_BEARER_TOKEN as string || '').trim();

export function envdBaseUrl(sandboxId: string): string {
  return `${BASE_URL}/api/v1/sandboxes/${encodeURIComponent(sandboxId)}/envd`;
}

const authInterceptor: Interceptor = (next) => async (request) => {
  if (TOKEN) request.header.set('Authorization', `Bearer ${TOKEN}`);
  return next(request);
};

export function createProcessClient(sandboxId: string) {
  return createClient(Process, createConnectTransport({
    baseUrl: envdBaseUrl(sandboxId),
    interceptors: [authInterceptor],
    useBinaryFormat: true,
  }));
}
```

- [ ] **Step 5: Verify and commit**

Run `cd dashboard && npm run generate:envd && npm test -- --run src/lib/envd.test.ts && npm run build`.

Expected: generation, tests, TypeScript, and Vite build pass. Commit with `git commit -m "feat: add dashboard envd connect client"`.

### Task 6: Migrate Dashboard Command Execution

**Files:**
- Modify: `dashboard/src/lib/api.ts`
- Modify: `dashboard/src/store/sandboxStore.ts`
- Modify: `dashboard/src/types/sandbox.ts`
- Modify: `dashboard/src/lib/envd.ts`
- Modify: `dashboard/src/lib/envd.test.ts`

- [ ] **Step 1: Write the command aggregation test**

Feed `collectCommand()` a fake async stream containing start, split UTF-8 stdout, stderr, and end events:

```ts
expect(await collectCommand(stream, 100)).toEqual({
  exit_code: 7,
  stdout: 'hello\n',
  stderr: 'failed\n',
  execution_time_ms: expect.any(Number),
});
```

Assert keepalive events are ignored, missing end events fail, and `EndEvent.error` is surfaced.

- [ ] **Step 2: Verify the command tests fail**

Run `cd dashboard && npm test -- --run src/lib/envd.test.ts`.

Expected: failure because `collectCommand` and `runEnvdCommand` are absent.

- [ ] **Step 3: Execute commands with Process.Start**

```ts
export async function runEnvdCommand(
  sandboxId: string,
  command: string[],
  cwd = '/workspace',
): Promise<ExecCommandResponse> {
  if (command.length === 0) throw new Error('command must not be empty');
  const startedAt = performance.now();
  const stream = createProcessClient(sandboxId).start({
    process: { cmd: command[0], args: command.slice(1), envs: {}, cwd },
    stdin: false,
  });
  return collectCommand(stream, startedAt);
}
```

Use streaming `TextDecoder` instances for stdout/stderr and map the end event to the existing `ExecCommandResponse`.

- [ ] **Step 4: Remove the private REST command client**

Delete `ApiClient.execCommand()` and `ExecCommandRequest`. Change the Zustand action to renew TTL and call `runEnvdCommand(sandboxId, command)`. Keep `ExecCommandResponse` so the existing command dialog rendering does not change.

- [ ] **Step 5: Verify and commit**

Run `cd dashboard && npm test -- --run src/lib/envd.test.ts && npm run build`.

Expected: tests and build pass. Commit with `git commit -m "feat: execute dashboard commands through envd"`.

### Task 7: Migrate the Dashboard Terminal to E2B Process RPCs

**Files:**
- Modify: `dashboard/src/components/Terminal.tsx`
- Modify: `dashboard/src/lib/api.ts`
- Modify: `dashboard/src/lib/envd.ts`
- Create: `dashboard/src/lib/envd-terminal.test.ts`

- [ ] **Step 1: Write terminal session tests**

Use a fake Process client to verify input buffering until the start event reports a PID:

```ts
const session = openEnvdTerminal('sbx-1', { cols: 80, rows: 24 }, fakeClient);
session.send(new TextEncoder().encode('pwd\n'));
expect(fakeClient.sendInput).not.toHaveBeenCalled();
emitStart({ pid: 42 });
await flushPromises();
expect(fakeClient.sendInput).toHaveBeenCalledWith(expect.objectContaining({
  process: { selector: { case: 'pid', value: 42 } },
}));
```

Also cover PTY output, serialized inputs, resize through `Update`, end events, and best-effort `SIGTERM` on close.

- [ ] **Step 2: Verify terminal tests fail**

Run `cd dashboard && npm test -- --run src/lib/envd-terminal.test.ts`.

Expected: failure because `openEnvdTerminal` is absent.

- [ ] **Step 3: Implement the Process terminal session**

Start the PTY stream with:

```ts
client.start({
  process: {
    cmd: '/bin/sh',
    args: ['-lc', 'if command -v bash >/dev/null 2>&1; then exec bash -il; else exec sh -il; fi'],
    envs: {},
    cwd: '/workspace',
  },
  pty: { size: { cols, rows } },
  stdin: true,
  tag: `dashboard-terminal-${crypto.randomUUID()}`,
}, { signal: abortController.signal });
```

Return `output`, `send`, `resize`, and `close`. Buffer input before PID discovery, serialize `SendInput`, call `Update` for PTY resize, and abort the stream after termination.

- [ ] **Step 4: Replace the WebSocket terminal component**

Remove `buildWebSocketUrl()` and bind xterm to the new session:

```ts
const session = openEnvdTerminal(sandboxId, { cols: term.cols, rows: term.rows });
const outputTask = (async () => {
  for await (const chunk of session.output) term.write(chunk);
})();
const dataDisposable = term.onData((data) => session.send(encoder.encode(data)));
const resizeDisposable = term.onResize(({ cols, rows }) => session.resize(cols, rows));
```

On React cleanup, dispose callbacks, close the session, and let the output task settle. Preserve current reconnect and error UI with protocol-neutral wording.

- [ ] **Step 5: Verify and commit**

Run `cd dashboard && npm test -- --run src/lib/envd-terminal.test.ts src/lib/envd.test.ts && npm run build`.

Expected: tests and build pass. Commit with `git commit -m "feat: run dashboard terminal through envd"`.

### Task 8: End-to-End Verification and Deployment Documentation

**Files:**
- Modify: `orchestrator/ARCHITECTURE.md`
- Modify: `envd/deploy/kata/README.md`

- [ ] **Step 1: Document installation and enablement**

Document:

```bash
sudo install -D -m 0755 \
  envd/bin/envd-linux-amd64 \
  /opt/litterbox/bin/envd
```

```toml
[envd]
enabled = true
host_binary_path = "/opt/litterbox/bin/envd"
container_binary_path = "/opt/litterbox/bin/envd"
port = 49983
connect_timeout_seconds = 3.0
```

State that the binary must exist on every schedulable Kata node before enabling injection.

- [ ] **Step 2: Run complete local verification**

```bash
cd orchestrator
pytest -q
python -m compileall -q src

cd ../envd
make generate
make test
go test -race ./...
go vet ./...
make build-linux-amd64
file bin/envd-linux-amd64

cd ../dashboard
npm run generate:envd
npm test -- --run
npm run build
```

Expected: every command succeeds; the envd artifact is an x86-64 statically linked ELF.

- [ ] **Step 3: Verify a configured cluster**

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "$ORCHESTRATOR/api/v1/sandboxes/$SANDBOX_ID/envd/health"
```

Expected: unwrapped envd health JSON. In dashboard verify command output/exit status, interactive terminal input/output/resize, suspend yielding proxy `409`, and resume restoring access.

- [ ] **Step 4: Verify removed routes**

```bash
curl -i -X POST "$ORCHESTRATOR/api/v1/sandboxes/$SANDBOX_ID/exec"
curl -i "http://$POD_IP:49983/v1/fs/entries?path=/"
curl -i -X POST "http://$POD_IP:49983/v1/processes/run"
```

Expected: all return `404`.

- [ ] **Step 5: Commit documentation and inspect scope**

Commit documentation with `git commit -m "docs: describe envd data plane deployment"`. Inspect `git status --short` and confirm no unrelated pre-existing user changes were staged or reverted.
