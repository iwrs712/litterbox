import { createClient, type Client, type Interceptor } from '@connectrpc/connect';
import { createConnectTransport } from '@connectrpc/connect-web';
import { Process, Signal, type ProcessEvent } from '@/gen/envd/process/process_pb';
import type { ExecCommandResponse } from '@/types/sandbox';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
const TOKEN = (import.meta.env.VITE_API_BEARER_TOKEN as string || '').trim();
const AUTO_RESTORE = (import.meta.env.VITE_ENVD_AUTO_RESTORE as string || '').trim() === 'true';

function authHeaders(): Record<string, string> {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

export function envdBaseUrl(sandboxId: string): string {
  return `${BASE_URL}/api/v1/sandboxes/${encodeURIComponent(sandboxId)}/envd`;
}

export async function restoreEnvdWorkspace(sandboxId: string): Promise<void> {
  if (!AUTO_RESTORE) return;

  const base = envdBaseUrl(sandboxId);
  const health = await fetch(`${base}/health`, { headers: authHeaders() });
  if (!health.ok) return;

  const state = await health.json().catch(() => null) as { workspace?: string } | null;
  if (state?.workspace !== 'restoring') return;

  const response = await fetch(`${base}/v1/workspace/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: '{}',
  });
  if (!response.ok) {
    throw new Error(`workspace restore failed (${response.status})`);
  }
}

const authInterceptor: Interceptor = (next) => async (request) => {
  if (TOKEN) request.header.set('Authorization', `Bearer ${TOKEN}`);
  return next(request);
};

function processClient(sandboxId: string): Client<typeof Process> {
  return createClient(Process, createConnectTransport({
    baseUrl: envdBaseUrl(sandboxId),
    interceptors: [authInterceptor],
    useBinaryFormat: true,
  }));
}

export async function runEnvdCommand(
  sandboxId: string,
  command: string[],
  cwd = '/workspace',
): Promise<ExecCommandResponse> {
  if (command.length === 0) throw new Error('command must not be empty');

  await restoreEnvdWorkspace(sandboxId);

  const startedAt = performance.now();
  const stdout = new TextDecoder();
  const stderr = new TextDecoder();
  let stdoutText = '';
  let stderrText = '';
  let end: { exitCode: number; error?: string } | undefined;

  for await (const response of processClient(sandboxId).start({
    process: { cmd: command[0], args: command.slice(1), envs: {}, cwd },
    stdin: false,
  })) {
    const event = response.event?.event;
    if (!event) continue;
    if (event.case === 'data') {
      const output = event.value.output;
      if (output.case === 'stdout') stdoutText += stdout.decode(output.value, { stream: true });
      if (output.case === 'stderr') stderrText += stderr.decode(output.value, { stream: true });
    }
    if (event.case === 'end') {
      end = { exitCode: event.value.exitCode, error: event.value.error };
    }
  }

  stdoutText += stdout.decode();
  stderrText += stderr.decode();
  if (!end) throw new Error('envd command ended without an end event');
  if (end.error) throw new Error(end.error);

  return {
    exit_code: end.exitCode,
    stdout: stdoutText,
    stderr: stderrText,
    execution_time_ms: Math.round(performance.now() - startedAt),
  };
}

class AsyncTextQueue implements AsyncIterable<string> {
  private values: string[] = [];
  private readers: Array<(result: IteratorResult<string>) => void> = [];
  private closed = false;

  push(value: string) {
    const reader = this.readers.shift();
    if (reader) reader({ value, done: false });
    else if (!this.closed) this.values.push(value);
  }

  close() {
    this.closed = true;
    for (const reader of this.readers.splice(0)) reader({ value: undefined, done: true });
  }

  [Symbol.asyncIterator](): AsyncIterator<string> {
    return {
      next: () => {
        const value = this.values.shift();
        if (value !== undefined) return Promise.resolve({ value, done: false });
        if (this.closed) return Promise.resolve({ value: undefined, done: true });
        return new Promise((resolve) => this.readers.push(resolve));
      },
    };
  }
}

export interface EnvdTerminalSession {
  output: AsyncIterable<string>;
  send(data: Uint8Array): void;
  resize(cols: number, rows: number): void;
  close(): void;
}

function ptyEventData(event: ProcessEvent): Uint8Array | undefined {
  if (event.event.case !== 'data') return undefined;
  const output = event.event.value.output;
  return output.case === 'pty' ? output.value : undefined;
}

export async function openEnvdTerminal(
  sandboxId: string,
  size: { cols: number; rows: number },
): Promise<EnvdTerminalSession> {
  await restoreEnvdWorkspace(sandboxId);

  const client = processClient(sandboxId);
  const abort = new AbortController();
  const output = new AsyncTextQueue();
  const decoder = new TextDecoder();
  const pendingInput: Uint8Array[] = [];
  let pid: number | undefined;
  let closed = false;
  let requestedSize = size;
  let writes = Promise.resolve();

  const selector = () => ({ selector: { case: 'pid' as const, value: pid! } });
  const sendNow = (data: Uint8Array) => {
    writes = writes.then(async () => {
      await client.sendInput({
        process: selector(),
        input: { input: { case: 'pty', value: data } },
      });
    }).catch((error) => output.push(`\r\n[terminal input error: ${error instanceof Error ? error.message : String(error)}]\r\n`));
  };
  const updateSize = () => {
    if (!pid || !requestedSize.cols || !requestedSize.rows) return;
    void client.update({
      process: selector(),
      pty: { size: { cols: requestedSize.cols, rows: requestedSize.rows } },
    }).catch(() => undefined);
  };

  void (async () => {
    try {
      for await (const response of client.start({
        process: {
          cmd: '/bin/sh',
          args: ['-lc', 'if command -v bash >/dev/null 2>&1; then exec bash -il; else exec sh -il; fi'],
          envs: {},
          cwd: '/workspace',
        },
        pty: { size: { cols: Math.max(1, size.cols), rows: Math.max(1, size.rows) } },
        stdin: true,
        tag: `dashboard-terminal-${crypto.randomUUID()}`,
      }, { signal: abort.signal })) {
        const event = response.event;
        if (event?.event.case === 'start') {
          pid = event.event.value.pid;
          for (const data of pendingInput.splice(0)) sendNow(data);
          updateSize();
          continue;
        }
        const data = event ? ptyEventData(event) : undefined;
        if (data) output.push(decoder.decode(data, { stream: true }));
        if (event?.event.case === 'end' && event.event.value.error) {
          output.push(`\r\n[terminal exited: ${event.event.value.error}]\r\n`);
        }
      }
    } catch (error) {
      if (!closed && !abort.signal.aborted) {
        output.push(`\r\n[terminal connection error: ${error instanceof Error ? error.message : String(error)}]\r\n`);
      }
    } finally {
      const remainder = decoder.decode();
      if (remainder) output.push(remainder);
      output.close();
    }
  })();

  return {
    output,
    send(data) {
      if (closed) return;
      if (pid) sendNow(data);
      else pendingInput.push(data);
    },
    resize(cols, rows) {
      requestedSize = { cols, rows };
      updateSize();
    },
    close() {
      if (closed) return;
      closed = true;
      if (pid) void client.sendSignal({ process: selector(), signal: Signal.SIGTERM }).catch(() => undefined);
      abort.abort();
      output.close();
    },
  };
}
