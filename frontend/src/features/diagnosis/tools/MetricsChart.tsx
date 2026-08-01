import { Cpu, MemoryStick, AlertTriangle } from "lucide-react";

interface DataPoint {
  timestamp: string;
  value: number;
  used_gb?: number;
  total_gb?: number;
}
interface MetricsData {
  service_name?: string;
  metric_name?: string;
  interval?: string;
  data_points?: DataPoint[];
  statistics?: {
    avg?: number;
    max?: number;
    min?: number;
    p95?: number;
    average?: number;
    spike_detected?: boolean;
  };
  alert_info?: { triggered?: boolean; threshold?: number; message?: string };
  alert?: { triggered?: boolean; threshold?: number; message?: string };
}

export function MetricsChart({ data, isMemory }: { data: MetricsData; isMemory?: boolean }) {
  const pts = data.data_points || [];
  const stats = data.statistics || {};
  const alert = data.alert_info || data.alert || {};
  const avg = stats.avg ?? stats.average;
  const Icon = isMemory ? MemoryStick : Cpu;
  const spike = stats.spike_detected || alert.triggered;
  const triggered = alert.triggered || stats.spike_detected;

  // SVG 折线
  const W = 280;
  const H = 64;
  const pad = 4;
  if (pts.length < 2) {
    return (
      <div className="rounded-lg border border-oncall-border bg-oncall-bg/50 p-3 text-xs text-oncall-muted">
        {data.service_name || "未知服务"} 无可用数据点
      </div>
    );
  }
  const values = pts.map((p) => p.value);
  const maxV = Math.max(...values, 1);
  const minV = Math.min(...values, 0);
  const range = maxV - minV || 1;
  const stepX = (W - pad * 2) / (pts.length - 1);
  const coords = pts.map((p, i) => {
    const x = pad + i * stepX;
    const y = H - pad - ((p.value - minV) / range) * (H - pad * 2);
    return [x, y] as const;
  });
  const path = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const areaPath = `${path} L${coords[coords.length - 1][0].toFixed(1)},${H - pad} L${coords[0][0].toFixed(1)},${H - pad} Z`;

  return (
    <div className="rounded-lg border border-oncall-border bg-oncall-bg/50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
          <Icon size={14} className={isMemory ? "text-sky-400" : "text-oncall-accent2"} />
          {data.service_name || "服务"} · {isMemory ? "内存" : "CPU"}使用率
        </div>
        <span className="text-[10px] text-oncall-muted">{data.interval || "1m"}</span>
      </div>

      <svg width={W} height={H} className="w-full">
        <defs>
          <linearGradient id="mg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="rgba(16,185,129,0.35)" />
            <stop offset="100%" stopColor="rgba(16,185,129,0)" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#mg)" />
        <path d={path} fill="none" stroke={isMemory ? "#38bdf8" : "#34d399"} strokeWidth="1.5" />
      </svg>

      <div className="mt-2 grid grid-cols-4 gap-1.5">
        <Stat label="均值" value={fmt(avg)} />
        <Stat label="P95" value={fmt(stats.p95)} />
        <Stat label="最大" value={fmt(stats.max)} accent={spike ? "amber" : undefined} />
        <Stat label="最小" value={fmt(stats.min)} />
      </div>

      {triggered && (
        <div className="mt-2 flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[11px] text-amber-300">
          <AlertTriangle size={12} />
          {alert.message || "检测到异常峰值"}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value?: string | number; accent?: "amber" }) {
  return (
    <div className="rounded-md bg-oncall-card/60 px-1.5 py-1 text-center">
      <div className="text-[9px] text-oncall-muted">{label}</div>
      <div className={`text-xs font-semibold ${accent === "amber" ? "text-amber-400" : "text-slate-200"}`}>
        {value != null ? value : "-"}
      </div>
    </div>
  );
}

const fmt = (v?: number) => (v != null ? `${v}%` : "-");
