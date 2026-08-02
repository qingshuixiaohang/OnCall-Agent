import { useState } from "react";
import { ListChecks, CheckCircle2, FileText, Network, Cpu, BookOpen, Loader2, AlertCircle, Circle } from "lucide-react";
import { Markdown } from "../../components/common/Markdown";
import { PhaseProgress, ProgressBar, type Phase } from "./PhaseProgress";
import { ToolResultRenderer } from "./tools/ToolResultRenderer";
import type { ToolCall } from "../../lib/types";

// ===== PlanCard =====
export function PlanCard({ plan }: { plan: string[] }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="animate-fade-slide rounded-xl border border-oncall-border bg-oncall-card/70 p-3">
      <button onClick={() => setCollapsed((c) => !c)} className="mb-2 flex w-full items-center gap-2 text-left">
        <ListChecks size={15} className="text-oncall-accent2" />
        <span className="text-sm font-medium text-slate-200">执行计划</span>
        <span className="rounded-full bg-oncall-accent/15 px-2 py-0.5 text-[10px] text-oncall-accent2">{plan.length} 步</span>
      </button>
      {!collapsed && (
        <ol className="space-y-1 pl-1">
          {plan.map((s, i) => (
            <li key={i} className="flex items-start gap-2 text-xs text-slate-300">
              <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-oncall-border text-[9px] text-oncall-muted">{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ===== StatusPill =====
export function StatusPill({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-oncall-border bg-oncall-card/40 px-3 py-1.5 text-xs text-slate-400">
      <Loader2 size={13} className="animate-spin text-oncall-accent2" />
      {message}
    </div>
  );
}

// ===== StepCard =====
export function StepCard({ index, step, toolCall }: { index: number; step: string; toolCall?: ToolCall }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="animate-fade-slide rounded-xl border border-oncall-border bg-oncall-card/70 p-3">
      <button onClick={() => setCollapsed((c) => !c)} className="mb-2 flex w-full items-center gap-2 text-left">
        <CheckCircle2 size={15} className="text-oncall-accent" />
        <span className="text-sm font-medium text-slate-200">步骤 {index}</span>
        <span className="flex-1 truncate text-xs text-slate-400">{step}</span>
      </button>
      {!collapsed && toolCall && toolCall.name && (
        <div className="mt-1 pl-1">
          <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-oncall-muted">
            <Cpu size={11} /> 工具调用: <span className="font-mono text-oncall-accent2">{toolCall.name}</span>
          </div>
          <ToolResultRenderer tool={toolCall} />
        </div>
      )}
    </div>
  );
}

// ===== ReportCard =====
export function ReportCard({ report }: { report: string }) {
  return (
    <div className="animate-fade-slide rounded-xl border border-oncall-accent/30 bg-oncall-accent/5 p-4">
      <div className="mb-2 flex items-center gap-2">
        <FileText size={16} className="text-oncall-accent" />
        <span className="text-sm font-semibold text-white">诊断报告</span>
      </div>
      <Markdown content={report} />
    </div>
  );
}

// ===== ErrorCard =====
export function ErrorCard({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3">
      <AlertCircle size={16} className="mt-0.5 shrink-0 text-rose-400" />
      <div className="text-sm text-rose-200">{message}</div>
    </div>
  );
}

// ===== RoutingCard =====
const specialistIcon: Record<string, React.ReactNode> = {
  log_analyzer: <FileText size={13} />,
  monitor_expert: <Cpu size={13} />,
  knowledge_retriever: <BookOpen size={13} />,
};
const specialistLabel: Record<string, string> = {
  log_analyzer: "日志分析",
  monitor_expert: "监控分析",
  knowledge_retriever: "知识检索",
};

export function RoutingCard({ reason, specialists }: { reason: string; specialists: string[] }) {
  return (
    <div className="animate-fade-slide rounded-xl border border-oncall-border bg-oncall-card/70 p-3">
      <div className="mb-2 flex items-center gap-2">
        <Network size={15} className="text-oncall-accent2" />
        <span className="text-sm font-medium text-slate-200">路由决策</span>
      </div>
      {reason && <p className="mb-2 text-xs text-slate-400">{reason}</p>}
      <div className="flex flex-wrap gap-1.5">
        {specialists.map((s) => (
          <span key={s} className="flex items-center gap-1.5 rounded-full border border-oncall-accent/30 bg-oncall-accent/10 px-2.5 py-1 text-xs text-oncall-accent2">
            {specialistIcon[s] || <Circle size={11} />}
            {specialistLabel[s] || s}
          </span>
        ))}
      </div>
    </div>
  );
}

// ===== SpecialistCard =====
export function SpecialistCard({ name, result }: { name: string; result: { summary?: string; [k: string]: unknown } }) {
  const [collapsed, setCollapsed] = useState(false);
  const summary = result.summary || "";
  const toolCalls = Array.isArray(result.tool_calls)
    ? result.tool_calls.filter((tool): tool is ToolCall => Boolean(tool && typeof tool === "object"))
    : [];
  return (
    <div className="animate-fade-slide rounded-xl border border-oncall-border bg-oncall-card/70 p-3">
      <button onClick={() => setCollapsed((c) => !c)} className="mb-2 flex w-full items-center gap-2 text-left">
        <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-oncall-accent/15 text-oncall-accent2">
          {specialistIcon[name] || <Circle size={13} />}
        </span>
        <span className="text-sm font-medium text-slate-200">{specialistLabel[name] || name}</span>
        <CheckCircle2 size={14} className="ml-auto text-oncall-accent" />
      </button>
      {summary && !collapsed && <Markdown content={summary} className="text-xs" />}
      {!collapsed && toolCalls.length > 0 && (
        <div className="mt-3 space-y-2 border-t border-oncall-border pt-2">
          {toolCalls.map((tool, index) => <ToolResultRenderer key={`${tool.name}-${index}`} tool={tool} />)}
        </div>
      )}
    </div>
  );
}

// 阶段映射工厂
export function aiopsPhases(phase: string): Phase[] {
  switch (phase) {
    case "planner":
      return [{ key: "plan", label: "制定计划", done: false, active: true }];
    case "executor":
      return [
        { key: "plan", label: "制定计划", done: true, active: false },
        { key: "exec", label: "执行步骤", done: false, active: true },
      ];
    case "replanner":
      return [
        { key: "plan", label: "制定计划", done: true, active: false },
        { key: "exec", label: "执行步骤", done: true, active: false },
        { key: "report", label: "生成报告", done: false, active: true },
      ];
    default:
      return [
        { key: "plan", label: "制定计划", done: true, active: false },
        { key: "exec", label: "执行步骤", done: true, active: false },
        { key: "report", label: "生成报告", done: true, active: false },
      ];
  }
}

export function multiPhases(phase: string): Phase[] {
  switch (phase) {
    case "supervisor":
      return [{ key: "route", label: "分析路由", done: false, active: true }];
    case "executing":
      return [
        { key: "route", label: "分析路由", done: true, active: false },
        { key: "exec", label: "专家并行", done: false, active: true },
      ];
    case "aggregating":
      return [
        { key: "route", label: "分析路由", done: true, active: false },
        { key: "exec", label: "专家并行", done: true, active: false },
        { key: "agg", label: "汇总分析", done: false, active: true },
      ];
    default:
      return [
        { key: "route", label: "分析路由", done: true, active: false },
        { key: "exec", label: "专家并行", done: true, active: false },
        { key: "agg", label: "汇总分析", done: true, active: false },
      ];
  }
}

export { PhaseProgress, ProgressBar };
