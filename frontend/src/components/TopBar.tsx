import { Zap, Network, LayoutGrid } from "lucide-react";
import { useStore } from "../store";
import type { View } from "../lib/types";

interface Props {
  onPickView: (v: View) => void;
}

export function TopBar({ onPickView }: Props) {
  const { view, isStreaming } = useStore();

  const chip = (v: View, icon: React.ReactNode, label: string, sub: string) => {
    const active = view === v;
    return (
      <button
        disabled={isStreaming && v !== view}
        onClick={() => onPickView(v)}
        className={`flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm font-medium transition disabled:opacity-40 ${
          active
            ? "border-oncall-accent/50 bg-oncall-accent/15 text-oncall-accent2"
            : "border-oncall-border bg-oncall-card text-slate-300 hover:border-oncall-accent/30 hover:text-white"
        }`}
      >
        {icon}
        <span className="flex flex-col items-start leading-none">
          <span>{label}</span>
          <span className="text-[10px] font-normal text-oncall-muted">{sub}</span>
        </span>
      </button>
    );
  };

  return (
    <div className="flex items-center justify-between border-b border-oncall-border bg-oncall-panel/60 px-5 py-3 backdrop-blur">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold text-white">智能 OnCall 诊断台</h1>
      </div>
      <div className="flex items-center gap-2.5">
        {chip("chat", <LayoutGrid size={15} />, "智能对话", "RAG + 工具")}
        {chip("aiops", <Zap size={15} />, "快速诊断", "Plan-Execute-Replan")}
        {chip("multi", <Network size={15} />, "全面诊断", "Supervisor + Specialist")}
      </div>
    </div>
  );
}
