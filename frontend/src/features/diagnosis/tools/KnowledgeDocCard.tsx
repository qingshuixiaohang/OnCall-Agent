import { useState } from "react";
import { BookOpen, ChevronDown, ChevronRight } from "lucide-react";

interface Doc {
  page_content?: string;
  metadata?: { source?: string; title?: string; score?: number; relevance?: string };
  title?: string;
  score?: number;
  relevance?: string;
  content?: string;
}
interface KnowledgeData {
  content?: string;
  docs?: Doc[];
  documents?: Doc[];
  message?: string;
}

// 星级相关度 -> 百分比
function relevancePct(doc: Doc): number | null {
  const rel = doc.relevance || doc.metadata?.relevance || "";
  if (rel.includes("高度")) return 95;
  if (rel.includes("相关")) return 75;
  if (rel.includes("部分")) return 50;
  if (rel.includes("弱")) return 25;
  const s = doc.score ?? doc.metadata?.score;
  if (typeof s === "number") return Math.round(Math.min(100, s * 100));
  return null;
}

export function KnowledgeDocCard({ data }: { data: KnowledgeData }) {
  const docs = data.docs || data.documents || [];
  if (docs.length === 0) {
    return (
      <div className="rounded-md border border-oncall-border bg-oncall-bg/50 p-2 text-xs text-oncall-muted">
        {data.content || data.message || "未检索到相关知识"}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
        <BookOpen size={13} className="text-oncall-accent2" />
        检索到 {docs.length} 篇相关文档
      </div>
      {docs.map((d, i) => (
        <DocItem key={i} doc={d} />
      ))}
    </div>
  );
}

function DocItem({ doc }: { doc: Doc }) {
  const [open, setOpen] = useState(false);
  const pct = relevancePct(doc);
  const title = doc.title || doc.metadata?.title || doc.metadata?.source || `文档 ${doc.page_content?.slice(0, 20)}`;
  const body = doc.page_content || doc.content || "";

  return (
    <div className="rounded-lg border border-oncall-border bg-oncall-bg/50 p-2.5">
      <div className="flex items-center gap-2">
        <button onClick={() => setOpen((o) => !o)} className="text-oncall-muted hover:text-oncall-accent2">
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        <span className="flex-1 truncate text-xs font-medium text-slate-200">{title}</span>
        {pct != null && (
          <div className="flex items-center gap-1.5">
            <div className="h-1.5 w-16 overflow-hidden rounded-full bg-oncall-border">
              <div className="h-full rounded-full bg-gradient-to-r from-oncall-accent to-emerald-400" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[9px] text-oncall-muted">{pct}%</span>
          </div>
        )}
      </div>
      {open && body && (
        <div className="mt-2 whitespace-pre-wrap rounded-md bg-oncall-card/40 p-2 text-[11px] leading-relaxed text-slate-300">
          {body}
        </div>
      )}
    </div>
  );
}
