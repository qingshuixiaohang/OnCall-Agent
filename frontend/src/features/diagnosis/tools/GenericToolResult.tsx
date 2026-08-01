import { useState } from "react";
import { Terminal, ChevronDown, ChevronRight } from "lucide-react";

export function GenericToolResult({ name, args, result }: { name: string; args?: unknown; result?: unknown }) {
  const [openArgs, setOpenArgs] = useState(false);
  const [openRes, setOpenRes] = useState(false);
  const resStr = result == null ? "" : typeof result === "string" ? result : JSON.stringify(result, null, 2);
  const argsStr = args == null ? "" : typeof args === "string" ? args : JSON.stringify(args, null, 2);

  return (
    <div className="rounded-lg border border-oncall-border bg-oncall-bg/50 p-3">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-300">
        <Terminal size={13} className="text-oncall-accent2" />
        <span className="font-mono">{name}</span>
      </div>
      {argsStr && (
        <div className="mb-1.5">
          <button
            onClick={() => setOpenArgs((o) => !o)}
            className="flex items-center gap-1 text-[10px] text-oncall-muted hover:text-slate-300"
          >
            {openArgs ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            参数
          </button>
          {openArgs && (
            <pre className="mt-1 max-h-40 overflow-auto rounded-md border border-oncall-border bg-oncall-card/40 p-2 text-[11px] text-slate-300">
              {argsStr}
            </pre>
          )}
        </div>
      )}
      {resStr && (
        <div>
          <button
            onClick={() => setOpenRes((o) => !o)}
            className="flex items-center gap-1 text-[10px] text-oncall-muted hover:text-slate-300"
          >
            {openRes ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
            结果 ({resStr.length > 200 ? "截断" : "完整"})
          </button>
          {openRes && (
            <pre className="mt-1 max-h-60 overflow-auto rounded-md border border-oncall-border bg-oncall-card/40 p-2 text-[11px] text-slate-300">
              {resStr.length > 800 ? resStr.slice(0, 800) + "\n...[截断]" : resStr}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
