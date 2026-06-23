import { useEffect, useRef } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";

function wsUrl(wsBase: string, path: string): string {
  let base = wsBase.trim();
  if (base) {
    base = base.replace(/^http/, "ws").replace(/\/$/, "");
  } else {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    base = `${proto}://${location.host}`;
  }
  return `${base}/ws/terminal?path=${encodeURIComponent(path)}`;
}

export function Terminal({ path, wsBase = "" }: { path: string; wsBase?: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const term = new XTerm({
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
      fontSize: 13,
      cursorBlink: true,
      theme: { background: "#0b0e14", foreground: "#c9d1d9", cursor: "#58a6ff" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current);
    fit.fit();

    const ws = new WebSocket(wsUrl(wsBase, path));
    ws.binaryType = "arraybuffer";

    const sendResize = () => {
      fit.fit();
      if (ws.readyState === WebSocket.OPEN)
        ws.send(JSON.stringify({ type: "resize", rows: term.rows, cols: term.cols }));
    };

    ws.onmessage = (e) =>
      term.write(typeof e.data === "string" ? e.data : new Uint8Array(e.data));
    ws.onopen = () => {
      sendResize();
      term.writeln("\x1b[2m# pyverify web terminal — try: uv run pyverify run . --yes\x1b[0m");
    };
    ws.onclose = () => term.writeln("\r\n\x1b[31m[terminal disconnected]\x1b[0m");

    term.onData((d) => ws.readyState === WebSocket.OPEN && ws.send(d));

    const ro = new ResizeObserver(() => sendResize());
    ro.observe(ref.current);

    return () => {
      ro.disconnect();
      ws.close();
      term.dispose();
    };
  }, [path, wsBase]);

  return <div className="terminal" ref={ref} />;
}
