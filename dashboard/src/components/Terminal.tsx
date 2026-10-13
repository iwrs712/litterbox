import { useEffect, useRef } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { apiClient } from '@/lib/api';
import { openEnvdTerminal } from '@/lib/envd';

interface TerminalProps {
  sandboxId: string;
}

export function Terminal({ sandboxId }: TerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const lastRenewedAtRef = useRef(0);
  const lastTerminalSizeRef = useRef({ cols: 0, rows: 0 });

  useEffect(() => {
    if (!terminalRef.current) return;

    const term = new XTerm({
      cursorBlink: true,
      cursorStyle: 'bar',
      fontSize: 14,
      lineHeight: 1.35,
      fontFamily: '"SF Mono", "JetBrains Mono", Monaco, Menlo, "Ubuntu Mono", Consolas, monospace',
      scrollback: 10000,
      theme: {
        background: '#141414',
        foreground: '#e2e2e2',
        cursor: '#e2e2e2',
        cursorAccent: '#141414',
        selectionBackground: '#3a3d41',
        black: '#1e1e1e',
        red: '#f44747',
        green: '#4ec9b0',
        yellow: '#dcdcaa',
        blue: '#569cd6',
        magenta: '#c586c0',
        cyan: '#9cdcfe',
        white: '#d4d4d4',
        brightBlack: '#555555',
        brightRed: '#f44747',
        brightGreen: '#23d18b',
        brightYellow: '#f5f543',
        brightBlue: '#3b8eea',
        brightMagenta: '#d670d6',
        brightCyan: '#29b8db',
        brightWhite: '#ffffff',
      },
    });

    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());
    term.open(terminalRef.current);

    let session: ReturnType<typeof openEnvdTerminal> | undefined;
    const fit = (notify = false) => {
      try {
        fitAddon.fit();
        if (notify) sendResize(term.cols, term.rows);
      } catch { /* ignore */ }
    };

    fit();
    session = openEnvdTerminal(sandboxId, { cols: Math.max(1, term.cols), rows: Math.max(1, term.rows) });

    let renewInterval: number | undefined;

    const renewTtl = async (force = false) => {
      const now = Date.now();
      if (!force && now - lastRenewedAtRef.current < 30_000) return;
      lastRenewedAtRef.current = now;
      try { await apiClient.renewSandboxTtl(sandboxId); } catch { /* ignore */ }
    };

    const sendResize = (cols: number, rows: number) => {
      if (!session || !cols || !rows) return;
      if (lastTerminalSizeRef.current.cols === cols && lastTerminalSizeRef.current.rows === rows) return;
      lastTerminalSizeRef.current = { cols, rows };
      session.resize(cols, rows);
    };

    term.writeln('\x1b[1;32mConnected\x1b[0m  \x1b[2m' + sandboxId + '\x1b[0m');
    term.writeln('');
    fit(true);
    setTimeout(() => fit(true), 50);
    void renewTtl(true);
    renewInterval = window.setInterval(() => void renewTtl(true), 60_000);

    let disposed = false;
    void (async () => {
      for await (const data of session.output) {
        if (!disposed) term.write(data);
      }
      if (!disposed) term.writeln('\n\x1b[2mconnection closed\x1b[0m');
    })();

    const dataDisposable = term.onData((data) => {
      void renewTtl();
      session?.send(new TextEncoder().encode(data));
    });
    const resizeDisposable = term.onResize(({ cols, rows }) => sendResize(cols, rows));
    const onResize = () => fit(true);
    window.addEventListener('resize', onResize);

    return () => {
      disposed = true;
      window.removeEventListener('resize', onResize);
      dataDisposable.dispose();
      resizeDisposable.dispose();
      if (renewInterval) clearInterval(renewInterval);
      session?.close();
      term.dispose();
    };
  }, [sandboxId]);

  return (
    <div
      ref={terminalRef}
      className="h-full w-full"
      style={{ background: '#141414', padding: '8px 10px 0' }}
    />
  );
}
