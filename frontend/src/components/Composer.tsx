import { useRef, useState } from "react";
import { Send, Paperclip, ChevronDown, Loader2 } from "lucide-react";
import { useStore } from "../store";
import type { Mode } from "../lib/types";

interface Props {
  onSend: (text: string) => void;
  onUpload?: (file: File) => void;
}

export function Composer({ onSend, onUpload }: Props) {
  const { mode, setMode, isStreaming, view } = useStore();
  const [text, setText] = useState("");
  const [modeOpen, setModeOpen] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const t = text.trim();
    if (!t || isStreaming) return;
    onSend(t);
    setText("");
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const modes: { key: Mode; label: string; sub: string }[] = [
    { key: "quick", label: "快速", sub: "非流式对话" },
    { key: "stream", label: "流式", sub: "流式对话" },
  ];

  const placeholder =
    view === "aiops"
      ? "描述要诊断的故障，或直接发送开始全系统诊断"
      : view === "multi"
        ? "描述问题，或直接发送开始全面诊断"
        : "问问智能 OnCall 助手";

  return (
    <div className="border-t border-oncall-border bg-oncall-panel/40 px-5 py-3.5 backdrop-blur">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-oncall-border bg-oncall-card px-3 py-2 focus-within:border-oncall-accent/40">
          <div className="relative flex items-center">
            <button
              onClick={() => fileRef.current?.click()}
              disabled={isStreaming}
              className="rounded-lg p-1.5 text-oncall-muted transition hover:bg-oncall-accent/10 hover:text-oncall-accent2 disabled:opacity-40"
              title="上传文件"
            >
              <Paperclip size={18} />
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.markdown,.pdf,.docx"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f && onUpload) onUpload(f);
                e.target.value = "";
              }}
            />
          </div>

          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={onKey}
            placeholder={placeholder}
            maxLength={1000}
            className="flex-1 bg-transparent py-1.5 text-sm text-slate-100 placeholder:text-oncall-muted focus:outline-none"
          />

          {view === "chat" && (
            <div className="relative">
              <button
                onClick={() => setModeOpen((o) => !o)}
                className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-slate-300 transition hover:bg-oncall-accent/10"
              >
                {modes.find((m) => m.key === mode)?.label}
                <ChevronDown size={13} />
              </button>
              {modeOpen && (
                <div className="absolute bottom-full right-0 mb-2 w-36 rounded-lg border border-oncall-border bg-oncall-panel p-1 shadow-xl">
                  {modes.map((m) => (
                    <button
                      key={m.key}
                      onClick={() => {
                        setMode(m.key);
                        setModeOpen(false);
                      }}
                      className={`flex w-full flex-col items-start rounded-md px-2.5 py-1.5 text-left transition hover:bg-oncall-card ${
                        mode === m.key ? "text-oncall-accent2" : "text-slate-300"
                      }`}
                    >
                      <span className="text-xs font-medium">{m.label}</span>
                      <span className="text-[10px] text-oncall-muted">{m.sub}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <button
            onClick={submit}
            disabled={isStreaming || !text.trim()}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-oncall-accent to-emerald-600 text-white transition hover:opacity-90 disabled:opacity-40"
          >
            {isStreaming ? <Loader2 size={17} className="animate-spin" /> : <Send size={17} />}
          </button>
        </div>
      </div>
    </div>
  );
}
