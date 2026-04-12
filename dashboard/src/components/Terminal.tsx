import { useEffect, useRef, useState } from 'react';
import { Terminal as XTerm } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import { WebLinksAddon } from '@xterm/addon-web-links';
import '@xterm/xterm/css/xterm.css';
import { apiClient } from '@/lib/api';

interface TerminalProps {
  sandboxId: string;
}

export function Terminal({ sandboxId }: TerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
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

    const fit = (notify = false) => {
      try {
        fitAddon.fit();
        if (notify) sendResize(term.cols, term.rows);
      } catch { /* ignore */ }
    };

    setTimeout(() => fit(), 0);

    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080';
    const url = new URL(baseUrl);
    const wsProtocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${url.host}/api/v1/sandboxes/${sandboxId}/terminal`;

    let renewInterval: number | undefined;

    const renewTtl = async (force = false) => {
      const now = Date.now();
      if (!force && now - lastRenewedAtRef.current < 30_000) return;
      lastRenewedAtRef.current = now;
      try { await apiClient.renewSandboxTtl(sandboxId); } catch { /* ignore */ }
    };

    let ws: WebSocket;

    const sendResize = (cols: number, rows: number) => {
      if (ws?.readyState !== WebSocket.OPEN || !cols || !rows) return;
      if (lastTerminalSizeRef.current.cols === cols && lastTerminalSizeRef.current.rows === rows) return;
      lastTerminalSizeRef.current = { cols, rows };
      ws.send(JSON.stringify({ type: 'resize', cols, rows }));
    };

    try {
      ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        term.writeln('\x1b[1;32m✓ Connected\x1b[0m  \x1b[2m' + sandboxId + '\x1b[0m');
        term.writeln('');
        fit(true);
        setTimeout(() => fit(true), 50);
        void renewTtl(true);
        renewInterval = window.setInterval(() => void renewTtl(true), 60_000);
      };

      ws.onmessage = (event) => {
        if (typeof event.data !== 'string') return;
        try {
          const msg = JSON.parse(event.data);
          if ((msg.type === 'stdout' || msg.type === 'stderr') && msg.data) {
            term.write(msg.data);
          }
        } catch {
          term.write(event.data);
        }
      };

      ws.onerror = () => {
        term.writeln('\x1b[1;31m✗ Connection error\x1b[0m');
      };

      ws.onclose = () => {
        if (renewInterval) clearInterval(renewInterval);
        term.writeln('\n\x1b[2m— connection closed —\x1b[0m');
      };

      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          void renewTtl();
          try { ws.send(JSON.stringify({ type: 'stdin', data })); } catch { /* ignore */ }
        }
      });

      const onResize = () => fit(true);
      window.addEventListener('resize', onResize);

      return () => {
        window.removeEventListener('resize', onResize);
        if (renewInterval) clearInterval(renewInterval);
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) ws.close();
        term.dispose();
      };
    } catch {
      return () => { term.dispose(); };
    }
  }, [sandboxId]);

  return (
    <div
      ref={terminalRef}
      className="h-full w-full"
      style={{ background: '#141414', padding: '8px 10px 0' }}
    />
  );
}
