import { useState } from "react";
import { Tag, Check, Copy } from "lucide-react";

interface TopicData {
  topic_id?: string;
  topic_name?: string;
  name?: string;
  service_name?: string;
  // 可能是列表
  topics?: TopicData[];
  [k: string]: unknown;
}

export function TopicChips({ data }: { data: TopicData }) {
  const list: TopicData[] = data.topics && Array.isArray(data.topics) ? data.topics : [data];
  const items = list.filter((t) => t.topic_id || t.topic_name || t.name);

  if (items.length === 0) {
    return <div className="rounded-md border border-oncall-border bg-oncall-bg/50 p-2 text-xs text-oncall-muted">未找到相关主题</div>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <Chip key={i} topic={t} />
      ))}
    </div>
  );
}

function Chip({ topic }: { topic: TopicData }) {
  const [copied, setCopied] = useState(false);
  const id = topic.topic_id || "";
  const name = topic.topic_name || topic.name || topic.service_name || id;
  const copy = () => {
    if (id) {
      navigator.clipboard.writeText(id).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1200);
      });
    }
  };
  return (
    <button
      onClick={copy}
      className="flex items-center gap-1.5 rounded-full border border-oncall-border bg-oncall-card px-2.5 py-1 text-xs text-slate-300 transition hover:border-oncall-accent/40 hover:text-oncall-accent2"
    >
      <Tag size={11} />
      <span className="font-mono">{name}</span>
      {id && <span className="text-[9px] text-oncall-muted">{id.slice(0, 12)}</span>}
      {copied ? <Check size={11} className="text-oncall-accent" /> : <Copy size={11} className="text-oncall-muted" />}
    </button>
  );
}
