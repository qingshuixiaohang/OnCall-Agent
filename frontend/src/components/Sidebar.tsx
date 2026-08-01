import { useEffect, useState } from "react";
import { Plus, MessageSquare, Trash2, Activity, Bot } from "lucide-react";
import { listSessions, deleteSession } from "../lib/api";
import { useStore } from "../store";
import type { SessionItem } from "../lib/types";

export function Sidebar() {
  const { sessionId, setSessionId, setView, newSession } = useStore();
  const [sessions, setSessions] = useState<SessionItem[]>([]);

  const refresh = () => {
    listSessions().then(setSessions).catch(() => setSessions([]));
  };

  useEffect(() => {
    refresh();
  }, [sessionId]);

  const onDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    await deleteSession(id);
    refresh();
  };

  return (
    <aside className="flex h-full w-60 shrink-0 flex-col border-r border-oncall-border bg-oncall-panel">
      <div className="flex items-center gap-2.5 border-b border-oncall-border px-4 py-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-oncall-accent to-emerald-600 text-white">
          <Bot size={18} />
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold text-white">智能OnCall助手</div>
          <div className="text-[11px] text-oncall-muted">AI 驱动智能运维</div>
        </div>
      </div>

      <div className="px-3 py-3">
        <button
          onClick={() => {
            newSession();
            refresh();
          }}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-oncall-border bg-oncall-card px-3 py-2.5 text-sm font-medium text-slate-200 transition hover:border-oncall-accent/40 hover:bg-oncall-accent/10"
        >
          <Plus size={16} />
          新建对话
        </button>
      </div>

      <div className="px-3 pb-2 text-[11px] font-medium uppercase tracking-wide text-oncall-muted">
        近期对话
      </div>

      <div className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 && (
          <div className="px-2 py-6 text-center text-xs text-oncall-muted">暂无历史对话</div>
        )}
        {sessions.map((s, i) => {
          // 兼容后端返回字符串 thread_id 或对象 {session_id,...} 两种形态
          const sid = typeof s === "string" ? s : (s?.session_id ?? "");
          const title = typeof s === "string" ? s : (s?.title ?? s?.session_id ?? "");
          if (!sid) return null;
          const active = sid === sessionId;
          return (
            <div
              key={sid || i}
              onClick={() => {
                setSessionId(sid);
                setView("chat");
              }}
              className={`group flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-2 text-sm transition ${
                active ? "bg-oncall-accent/15 text-white" : "text-slate-300 hover:bg-oncall-card"
              }`}
            >
              <MessageSquare size={14} className="shrink-0 text-oncall-muted" />
              <span className="flex-1 truncate">
                {(title || sid).slice(0, 18)}
              </span>
              <button
                onClick={(e) => onDelete(sid, e)}
                className="hidden text-oncall-muted hover:text-rose-400 group-hover:block"
              >
                <Trash2 size={13} />
              </button>
            </div>
          );
        })}
      </div>

      <div className="border-t border-oncall-border px-3 py-3">
        <div className="flex items-center gap-2 text-[11px] text-oncall-muted">
          <Activity size={13} className="text-oncall-accent" />
          <span>SuperBizAgent v1.2</span>
        </div>
      </div>
    </aside>
  );
}
