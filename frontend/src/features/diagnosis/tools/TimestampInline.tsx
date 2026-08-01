import { Clock } from "lucide-react";

export function TimestampInline({ value }: { value: number | string }) {
  return (
    <div className="inline-flex items-center gap-1.5 rounded-md border border-oncall-border bg-oncall-bg/50 px-2 py-1 text-xs text-slate-300">
      <Clock size={12} className="text-oncall-accent2" />
      <span className="font-mono">{String(value)}</span>
    </div>
  );
}
