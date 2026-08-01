import { Check } from "lucide-react";

export interface Phase {
  key: string;
  label: string;
  done: boolean;
  active: boolean;
}

export function PhaseProgress({ phases }: { phases: Phase[] }) {
  return (
    <div className="flex items-center gap-1">
      {phases.map((p, i) => {
        const cls = p.done
          ? "text-oncall-accent border-oncall-accent/40 bg-oncall-accent/10"
          : p.active
            ? "text-oncall-accent2 border-oncall-accent/40 bg-oncall-accent/5"
            : "text-oncall-muted border-oncall-border bg-oncall-card";
        return (
          <div key={p.key} className="flex items-center">
            <div className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${cls}`}>
              {p.done ? <Check size={10} /> : p.active ? <span className="h-1.5 w-1.5 animate-pulse-soft rounded-full bg-oncall-accent" /> : <span className="h-1.5 w-1.5 rounded-full bg-oncall-muted/40" />}
              <span>{p.label}</span>
            </div>
            {i < phases.length - 1 && <div className={`mx-0.5 h-px w-4 ${p.done ? "bg-oncall-accent/40" : "bg-oncall-border"}`} />}
          </div>
        );
      })}
    </div>
  );
}

export function ProgressBar({ pct, label }: { pct: number; label: string }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-oncall-border">
        <div className="h-full rounded-full bg-gradient-to-r from-oncall-accent to-emerald-400 transition-all duration-500" style={{ width: `${Math.max(4, pct)}%` }} />
      </div>
      <span className="text-[10px] text-oncall-muted">{label}</span>
    </div>
  );
}
