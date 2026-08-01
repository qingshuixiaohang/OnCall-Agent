import { useState } from "react";
import { User, Bot, Wrench, ChevronDown, ChevronRight } from "lucide-react";
import { Markdown } from "../../components/common/Markdown";

export interface ChatMsg {
  id: string;
  role: "user" | "assistant";
  content: string;
  tools?: { name: string; status: "start" | "end"; input?: unknown }[];
  streaming?: boolean;
  error?: boolean;
}

function ToolChip({ tool }: { tool: { name: string; status: "start" | "end"; input?: unknown } }) {
  const [open, setOpen] = useState(false);
  const running = tool.status === "start";
  return (
    <div className="inline-flex flex-col">
      <button
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs transition ${
          running
            ? "border-oncall-accent/40 bg-oncall-accent/10 text-oncall-accent2"
            : "border-oncall-border bg-oncall-card text-slate-400"
        }`}
      >
        <Wrench size={12} />
        <span className="font-mono">{tool.name}</span>
        {running && <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-oncall-accent" />}
        {tool.input != null && (open ? <ChevronDown size={12} /> : <ChevronRight size={12} />)}
      </button>
      {open && tool.input != null && (
        <pre className="mt-1 max-w-md overflow-x-auto rounded-md border border-oncall-border bg-oncall-bg p-2 text-[11px] text-slate-300">
          {JSON.stringify(tool.input, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function ChatMessage({ msg }: { msg: ChatMsg }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex gap-3 px-5 py-4 ${isUser ? "justify-end" : ""}`}>
      {!isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-oncall-accent to-emerald-600 text-white">
          <Bot size={17} />
        </div>
      )}
      <div className={`max-w-[78%] ${isUser ? "order-1" : ""}`}>
        {msg.tools && msg.tools.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {msg.tools.map((t, i) => (
              <ToolChip key={i} tool={t} />
            ))}
          </div>
        )}
        {msg.content && (
          <div
            className={`rounded-2xl px-4 py-2.5 ${
              isUser
                ? "bg-oncall-accent/15 text-slate-100"
                : msg.error
                  ? "border border-rose-500/30 bg-rose-500/10 text-rose-200"
                  : "bg-oncall-card text-slate-200"
            }`}
          >
            {isUser ? (
              <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
            ) : (
              <Markdown content={msg.content} />
            )}
            {msg.streaming && (
              <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-oncall-accent align-middle" />
            )}
          </div>
        )}
      </div>
      {isUser && (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-600 text-white">
          <User size={17} />
        </div>
      )}
    </div>
  );
}
