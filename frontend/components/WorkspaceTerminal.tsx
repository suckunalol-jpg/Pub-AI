"use client";

import { useEffect, useRef, useState } from "react";

interface WorkspaceTerminalProps {
  agentId: string;
  token: string;
  className?: string;
}

export default function WorkspaceTerminal({
  agentId,
  token,
  className = "",
}: WorkspaceTerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const xtermRef = useRef<import("xterm").Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    let resizeObserver: ResizeObserver | null = null;

    async function initTerminal() {
      const { Terminal } = await import("xterm");
      const { FitAddon } = await import("xterm-addon-fit");
      const { WebLinksAddon } = await import("xterm-addon-web-links");
      await import("xterm/css/xterm.css");

      if (!terminalRef.current || !isMounted) return;

      const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily:
          "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace",
        theme: {
          background: "#0a0a0f",
          foreground: "#e2e8f0",
          cursor: "#60a5fa",
          selectionBackground: "#1e40af44",
          black: "#1e293b",
          red: "#ef4444",
          green: "#22c55e",
          yellow: "#eab308",
          blue: "#3b82f6",
          magenta: "#a855f7",
          cyan: "#06b6d4",
          white: "#f1f5f9",
          brightBlack: "#475569",
          brightRed: "#f87171",
          brightGreen: "#4ade80",
          brightYellow: "#facc15",
          brightBlue: "#60a5fa",
          brightMagenta: "#c084fc",
          brightCyan: "#22d3ee",
          brightWhite: "#ffffff",
        },
        scrollback: 1000,
        allowProposedApi: true,
      });

      const fitAddon = new FitAddon();
      const webLinksAddon = new WebLinksAddon();

      term.loadAddon(fitAddon);
      term.loadAddon(webLinksAddon);
      term.open(terminalRef.current);
      fitAddon.fit();

      xtermRef.current = term;

      // Build WebSocket URL from the configured API base
      const wsProtocol =
        window.location.protocol === "https:" ? "wss:" : "ws:";
      const apiHost =
        process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") ||
        "localhost:8000";
      const wsUrl = `${wsProtocol}//${apiHost}/api/ws/terminal/${agentId}?token=${encodeURIComponent(token)}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.binaryType = "arraybuffer";

      ws.onopen = () => {
        if (!isMounted) return;
        setConnected(true);
        setError(null);
        term.write(
          "\r\n\x1b[32m+ Connected to workspace container\x1b[0m\r\n\r\n"
        );
      };

      ws.onmessage = (event) => {
        if (!isMounted) return;
        if (event.data instanceof ArrayBuffer) {
          term.write(new Uint8Array(event.data));
        } else {
          term.write(event.data);
        }
      };

      ws.onclose = () => {
        if (!isMounted) return;
        setConnected(false);
        term.write("\r\n\x1b[31m- Connection closed\x1b[0m\r\n");
      };

      ws.onerror = () => {
        if (!isMounted) return;
        setError("WebSocket connection failed");
        setConnected(false);
      };

      // Forward terminal input to the WebSocket
      term.onData((data) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(data);
        }
      });

      // Refit on container resize
      resizeObserver = new ResizeObserver(() => {
        try {
          fitAddon.fit();
        } catch {
          // terminal may already be disposed during teardown
        }
      });
      if (terminalRef.current) {
        resizeObserver.observe(terminalRef.current);
      }
    }

    initTerminal();

    return () => {
      isMounted = false;
      resizeObserver?.disconnect();
      wsRef.current?.close();
      xtermRef.current?.dispose();
    };
  }, [agentId, token]);

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Status bar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-900 border-b border-gray-700 text-xs">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-400 animate-pulse" : "bg-red-400"
            }`}
          />
          <span className="text-gray-400">
            {connected
              ? `Workspace: ${agentId.slice(0, 8)}`
              : error || "Disconnected"}
          </span>
        </div>
        <button
          onClick={() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              wsRef.current.close();
            }
          }}
          className="text-gray-500 hover:text-gray-300 transition-colors"
          title="Disconnect"
        >
          x
        </button>
      </div>

      {/* Terminal */}
      <div
        ref={terminalRef}
        className="flex-1 min-h-0 bg-[#0a0a0f] p-1"
        style={{ fontFamily: "monospace" }}
      />
    </div>
  );
}
