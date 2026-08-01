import type { ToolCall } from "../../../lib/types";
import { MetricsChart } from "./MetricsChart";
import { LogTable } from "./LogTable";
import { KnowledgeDocCard } from "./KnowledgeDocCard";
import { TopicChips } from "./TopicChips";
import { TimestampInline } from "./TimestampInline";
import { GenericToolResult } from "./GenericToolResult";

// 把 result（可能是字符串/对象）规范化为对象
function asObj(v: unknown): Record<string, unknown> | null {
  if (v == null) return null;
  if (typeof v === "string") {
    try {
      const p = JSON.parse(v);
      return typeof p === "object" && p ? (p as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }
  return typeof v === "object" ? (v as Record<string, unknown>) : null;
}

export function ToolResultRenderer({ tool }: { tool: ToolCall }) {
  const name = tool.name;
  const result = asObj(tool.result);

  // 没有结果对象时，退化通用
  if (!result) {
    return <GenericToolResult name={name} args={tool.args} result={tool.result} />;
  }

  switch (name) {
    case "query_cpu_metrics":
      return <MetricsChart data={result as never} />;
    case "query_memory_metrics":
      return <MetricsChart data={result as never} isMemory />;
    case "search_log":
      return <LogTable data={result as never} />;
    case "retrieve_knowledge":
      return <KnowledgeDocCard data={result as never} />;
    case "search_topic_by_service_name":
      return <TopicChips data={result as never} />;
    case "get_current_timestamp":
    case "get_current_time":
      return <TimestampInline value={(result.timestamp ?? result.time ?? tool.result) as never} />;
    default:
      return <GenericToolResult name={name} args={tool.args} result={tool.result} />;
  }
}
