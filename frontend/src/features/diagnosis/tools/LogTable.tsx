import { ScrollText, Clock } from "lucide-react";

interface LogEntry {
  timestamp?: string;
  level?: string;
  service?: string;
  message?: string;
  source_host?: string;
}
interface LogData {
  topic_id?: string;
  query?: string;
  total?: number;
  took_ms?: number;
  logs?: LogEntry[];
  error?: string;
  message?: string;
}

const levelColor: Record<string, string> = {
  ERROR: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  CRITICAL: "bg-rose-600/25 text-rose-200 border-rose-600/40",
  WARNING: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  WARN: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  INFO: "bg-sky-500/15 text-sky-300 border-sky-500/25",
  DEBUG: "bg-slate-500/15 text-slate-400 border-slate-500/25",
};

export function LogTable({ data }: { data: LogData }) {
  const logs = data.logs || [];
  if (data.error) {
    return <div className="rounded-md border border-rose-500/30 bg-rose-500/10 p-2 text-xs text-rose-300">{data.error}</div>;
  }
  if (logs.length === 0) {
    return <div className="rounded-md border border-oncall-border bg-oncall-bg/50 p-2 text-xs text-oncall-muted">无日志记录</div>;
  }

  return (
    <div className="rounded-lg border border-oncall-border bg-oncall-bg/50">
      <div className="flex items-center justify-between border-b border-oncall-border px-3 py-1.5">
        <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
          <ScrollText size={13} className="text-oncall-accent2" />
          日志查询结果
        </div>
        <div className="flex items-center gap-2 text-[10px] text-oncall-muted">
          <span>{data.total ?? logs.length} 条</span>
          {data.took_ms != null && (
            <span className="flex items-center gap-0.5">
              <Clock size={10} /> {data.took_ms}ms
            </span>
          )}
          {data.query && <span className="font-mono">q: {data.query}</span>}
        </div>
      </div>
      <div className="max-h-56 overflow-y-auto">
        <table className="w-full text-left text-[11px]">
          <thead className="sticky top-0 bg-oncall-panel text-[9px] uppercase text-oncall-muted">
            <tr>
              <th className="px-2 py-1 font-medium">时间</th>
              <th className="px-2 py-1 font-medium">级别</th>
              <th className="px-2 py-1 font-medium">服务</th>
              <th className="px-2 py-1 font-medium">消息</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l, i) => {
              const lvl = (l.level || "").toUpperCase();
              return (
                <tr key={i} className="border-t border-oncall-border/50 hover:bg-oncall-card/40">
                  <td className="whitespace-nowrap px-2 py-1 font-mono text-slate-400">{l.timestamp || "-"}</td>
                  <td className="px-2 py-1">
                    <span className={`rounded border px-1.5 py-0.5 text-[9px] font-semibold ${levelColor[lvl] || "bg-slate-500/15 text-slate-400 border-slate-500/25"}`}>
                      {lvl || "-"}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-1 text-slate-400">{l.service || "-"}</td>
                  <td className="px-2 py-1 font-mono text-slate-200">{l.message || "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
