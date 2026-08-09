# E2B envd Proxy and Dashboard Migration Design

## Objective

Replace the Litterbox Kubernetes Exec based data plane with the E2B-compatible
envd implementation in `sandbox-agent-go`. The dashboard must use envd for
process execution and terminal sessions. The orchestrator remains responsible
for authentication, sandbox lifecycle, and resolving a sandbox ID to its
running Pod.

This change does not convert the orchestrator control plane to the E2B control
plane API. That is a separate migration.

## Current State

The orchestrator currently implements a private data plane by executing commands
through the Kubernetes API:

- `POST /api/v1/sandboxes/{id}/exec`
- `GET /api/v1/sandboxes/{id}/files`
- `PUT /api/v1/sandboxes/{id}/files`
- `DELETE /api/v1/sandboxes/{id}/files`
- `WS /api/v1/sandboxes/{id}/terminal`
- `WS /api/v1/sandboxes/{id}/acp`

The dashboard uses the private exec endpoint and terminal WebSocket. The file
routes have no current dashboard view but are part of the private API surface.

The new Go envd listens on port `49983` and implements:

- `GET /health`
- `GET /files`
- `POST /files`
- Connect, gRPC, and gRPC-Web under `/filesystem.Filesystem/*`
- Connect, gRPC, and gRPC-Web under `/process.Process/*`

## Architecture

The browser cannot route directly to a Pod IP. The orchestrator therefore
provides an authenticated, sandbox-aware reverse proxy:

```text
Dashboard
   |
   | HTTPS + orchestrator Bearer token
   v
Orchestrator /api/v1/sandboxes/{id}/envd/*
   |
   | resolve running Pod IP, forward to http://<pod-ip>:49983
   v
envd in the main sandbox container
```

The proxy is transport-oriented. It does not translate E2B protobuf messages
into Litterbox models. Request paths, bodies, streaming responses, and relevant
protocol headers pass through unchanged after removing the orchestrator prefix.

## envd Injection

envd injection uses a configurable read-only `hostPath` volume mounted into the
main container. A Kubernetes `postStart.exec` action invokes the static binary's
detached daemon command inside the main container namespaces and cgroup:

```text
/opt/litterbox/envd/sandbox-agent daemon \
  --host 0.0.0.0 \
  --port 49983 \
  --filesystem-root /
```

Configuration controls whether injection is enabled, the host binary path,
container mount path, and envd port. Injection is cluster-wide and is not part
of the public Sandbox or Template API in this phase.

If a template already defines `postStart`, sandbox creation fails with a clear
configuration error. Kubernetes supports only one `postStart` action and
silently replacing a template hook would change existing behavior.

## Orchestrator Proxy API

The proxy is mounted at:

```text
/api/v1/sandboxes/{sandbox_id}/envd/{envd_path:path}
```

Examples:

```text
GET  /api/v1/sandboxes/{id}/envd/health
GET  /api/v1/sandboxes/{id}/envd/files?path=/workspace/result.txt
POST /api/v1/sandboxes/{id}/envd/files?path=/workspace/input.txt
POST /api/v1/sandboxes/{id}/envd/filesystem.Filesystem/Stat
POST /api/v1/sandboxes/{id}/envd/process.Process/Start
```

The proxy accepts the HTTP methods required by envd and forwards:

- request body and query string
- `Content-Type`, `Content-Encoding`, `Accept-Encoding`, and `User-Agent`
- Connect and gRPC-Web protocol headers
- response status, body stream, trailers when supported by the ASGI stack, and
  content/protocol headers

Hop-by-hop headers and the external `Authorization` header are not forwarded to
envd. Orchestrator bearer authentication remains the external trust boundary.

The proxy resolves only a Running Pod belonging to the requested sandbox. It
does not accept arbitrary upstream hosts or ports.

## Removed Orchestrator Data Plane

The private exec, file, terminal, and ACP routes listed under Current State are
removed. The associated `WorkspaceService` and Kubernetes Exec/open-shell code
are removed when no lifecycle caller remains.

Sandbox lifecycle, workspace PVC provisioning, suspend/resume, lock/unlock,
TTL, Pool, Expose, Webhook, and metrics APIs remain unchanged.

## Go envd Cleanup

The following legacy REST routes are removed from `sandbox-agent-go`:

```text
/v1/fs/*
/v1/processes/*
```

Their handlers and tests are deleted after equivalent E2B coverage is verified.

The following non-E2B features remain in this phase:

```text
/v1/skills/*
/v1/acp/*
/v1/messages/*
/v1/models/*
```

They are independent product features and are not used as the dashboard's
filesystem or process transport.

## Dashboard Migration

The dashboard adds generated TypeScript clients for the envd filesystem and
process protobuf services and uses a Connect browser transport whose base URL is
the sandbox envd proxy prefix.

The terminal workflow is:

1. Call `Process.Start` with a shell command and PTY dimensions.
2. Render stdout, stderr, and PTY output events in xterm.
3. Send input through `Process.SendInput`.
4. Resize through `Process.Update`.
5. Close stdin or send a termination signal when the terminal closes.

The command dialog uses `Process.Start` without a PTY, collects output events,
and reports the process exit result. It no longer calls the private orchestrator
exec endpoint.

The dashboard API client removes private exec and terminal WebSocket helpers.
There is no file browser to migrate in the current dashboard. Future file UI
uses envd `/files` for content transfer and Filesystem RPCs for metadata and
directory operations.

## Errors

- Missing sandbox: `404` before contacting envd.
- Stopped, suspended, or not-yet-running sandbox: `409`.
- Running Pod without an IP: `503`.
- envd connection failure or timeout: `502`.
- Invalid Connect/gRPC-Web payloads: envd response passes through unchanged.
- Existing template `postStart` while injection is enabled: sandbox creation
  fails before creating Kubernetes resources.

Streaming requests and responses are cancelled when the browser disconnects so
the orchestrator does not retain abandoned proxy tasks.

## Verification

Orchestrator tests cover:

- enabled and disabled envd injection
- hostPath volume, volume mount, daemon command, and port configuration
- template `postStart` conflict handling
- proxy path and query rewriting
- authentication boundary and header filtering
- stopped, missing, unready, and unreachable sandbox errors
- unary and streaming proxy behavior against a local h2c test server
- absence of the removed private routes

Go envd tests cover:

- E2B Filesystem and Process RPCs after legacy handlers are removed
- `/files` upload/download
- absence of `/v1/fs/*` and `/v1/processes/*`

Dashboard verification covers:

- production build and type checking
- command execution output and exit status
- interactive terminal input, output, resize, and disconnect
- stopped sandbox behavior

## Out of Scope

- E2B control-plane route and model migration
- filesystem watchers
- direct public exposure of Pod IPs or envd ports
- removal of Skills, ACP, Anthropic Messages, or Models APIs
- sidecar-based envd deployment
- Kata `guest_hook_path` injection
