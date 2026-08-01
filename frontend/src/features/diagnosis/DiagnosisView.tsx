import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Play } from "lucide-react";
import { aiopsDiagnose, multiAgentDiagnose } from "../../lib/api";
import { useStore } from "../../store";
import type { AIOpsEvent, MultiAgentEvent } from "../../lib/types";
import { PhaseProgress, ProgressBar } from "./PhaseProgress";
import {
  PlanCard,
  StatusPill,
  StepCard,
  ReportCard,
  ErrorCard,
  RoutingCard,
  SpecialistCard,
  aiopsPhases,
  multiPhases,
} from "./cards";

type Item =
  | { kind: "plan"; plan: string[] }
  | { kind: "status"; message: string }
  | { kind: "step"; index: number; step: string; toolCall?: { name: string; args: Record<string, unknown>; result?: unknown } }
  | { kind: "report"; report: string }
  | { kind: "error"; message: string }
  | { kind: "routing"; reason: string; specialists: string[] }
  | { kind: "specialist"; name: string; result: { summary?: string; [k: string]: unknown } };

export interface DiagnosisHandle {
  run: (text: string) => void;
}

interface Props {
  kind: "aiops" | "multi";
  onStart: () => void;
}

export const DiagnosisView = forwardRef<DiagnosisHandle, Props>(({ kind, onStart }, ref) => {
  const { sessionId, isStreaming, setStreaming } = useStore();
  const [items, setItems] = useState<Item[]>([]);
  const [phase, setPhase] = useState("planner");
  const [pct, setPct] = useState(0);
  const [pctLabel, setPctLabel] = useState("");
  const [done, setDone] = useState(false);
  const [started, setStarted] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [items, pct]);

  const push = (it: Item) => setItems((prev) => [...prev, it]);

  function reset() {
    setItems([]);
    setPhase(kind === "aiops" ? "planner" : "supervisor");
    setPct(5);
    setPctLabel("启动中...");
    setDone(false);
    setStarted(true);
  }

  function runAIOps(text: string) {
    let planLen = 0;
    let doneSteps = 0;
    aiopsDiagnose(
      sessionId,
      text,
      {
        onEvent: (ev: AIOpsEvent) => {
          switch (ev.type) {
            case "plan":
              planLen = ev.plan.length;
              setPhase("planner");
              setPct(10);
              setPctLabel("计划已制定");
              push({ kind: "plan", plan: ev.plan });
              break;
            case "status":
              setPhase(ev.stage || "executor");
              setPctLabel(ev.message);
              push({ kind: "status", message: ev.message });
              break;
            case "step_complete":
              doneSteps += 1;
              setPhase("executor");
              if (planLen > 0) setPct(Math.round((doneSteps / planLen) * 80) + 10);
              setPctLabel(`步骤 ${doneSteps}/${planLen}`);
              push({
                kind: "step",
                index: doneSteps,
                step: ev.current_step || ev.message,
                toolCall: ev.tool_call,
              });
              break;
            case "report":
              setPhase("replanner");
              setPct(90);
              setPctLabel("生成报告");
              push({ kind: "report", report: ev.report });
              break;
            case "complete":
              setPhase("complete");
              setPct(100);
              setPctLabel("完成");
              setDone(true);
              if (ev.response) push({ kind: "report", report: ev.response });
              break;
            case "error":
              push({ kind: "error", message: ev.data || ev.message || "诊断失败" });
              setDone(true);
              break;
          }
        },
        onDone: () => {
          setPhase("complete");
          setPct(100);
          setPctLabel("完成");
          setDone(true);
          setStreaming(false);
        },
        onError: (err) => {
          push({ kind: "error", message: `连接失败: ${err.message}` });
          setDone(true);
          setStreaming(false);
        },
      },
    );
  }

  function runMulti(text: string) {
    let specTotal = 0;
    let specDone = 0;
    multiAgentDiagnose(
      sessionId,
      text,
      {
        onEvent: (ev: MultiAgentEvent) => {
          switch (ev.type) {
            case "routing":
              specTotal = ev.specialists.length;
              setPhase("executing");
              setPct(15);
              setPctLabel("专家执行中");
              push({ kind: "routing", reason: ev.reason, specialists: ev.specialists });
              break;
            case "specialist_result":
              specDone += 1;
              if (specTotal > 0) setPct(Math.round((specDone / specTotal) * 70) + 15);
              setPctLabel(`专家 ${specDone}/${specTotal}`);
              push({ kind: "specialist", name: ev.name, result: ev.result });
              break;
            case "complete":
              setPhase("complete");
              setPct(100);
              setPctLabel("完成");
              setDone(true);
              if (ev.report) push({ kind: "report", report: ev.report });
              break;
            case "error":
              push({ kind: "error", message: ev.message || "诊断失败" });
              setDone(true);
              break;
          }
        },
        onDone: () => {
          setPhase("complete");
          setPct(100);
          setPctLabel("完成");
          setDone(true);
          setStreaming(false);
        },
        onError: (err) => {
          push({ kind: "error", message: `连接失败: ${err.message}` });
          setDone(true);
          setStreaming(false);
        },
      },
    );
  }

  // 命令式入口：只有被显式调用才触发，切换模式不会触发
  useImperativeHandle(ref, () => ({
    run: (text: string) => {
      if (isStreaming) return;
      reset();
      setStreaming(true);
      if (kind === "aiops") runAIOps(text);
      else runMulti(text);
    },
  }));

  const phases = kind === "aiops" ? aiopsPhases(phase) : multiPhases(phase);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="border-b border-oncall-border bg-oncall-panel/40 px-5 py-3">
        <div className="mx-auto max-w-3xl space-y-2">
          <PhaseProgress phases={phases} />
          <ProgressBar pct={done ? 100 : pct} label={done ? "完成" : pctLabel} />
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4">
        <div className="mx-auto max-w-3xl space-y-2.5">
          {!started && (
            <div className="flex h-full flex-col items-center justify-center gap-3 py-20 text-center">
              <div className="text-sm text-slate-300">
                {kind === "aiops" ? "快速诊断已就绪" : "全面诊断已就绪"}
              </div>
              <button
                onClick={onStart}
                disabled={isStreaming}
                className="flex items-center gap-2 rounded-lg border border-oncall-accent/40 bg-oncall-accent/10 px-4 py-2 text-sm font-medium text-oncall-accent2 transition hover:bg-oncall-accent/20 disabled:opacity-40"
              >
                <Play size={15} />
                开始{kind === "aiops" ? "快速" : "全面"}诊断
              </button>
              <div className="text-xs text-oncall-muted">也可以在下方输入具体问题后发送</div>
            </div>
          )}
          {started && items.length === 0 && isStreaming && (
            <div className="flex flex-col items-center justify-center gap-2 py-20 text-oncall-muted">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-oncall-accent border-t-transparent" />
              <div className="text-sm">正在分析...</div>
            </div>
          )}
          {items.map((it, i) => {
            switch (it.kind) {
              case "plan":
                return <PlanCard key={i} plan={it.plan} />;
              case "status":
                return <StatusPill key={i} message={it.message} />;
              case "step":
                return <StepCard key={i} index={it.index} step={it.step} toolCall={it.toolCall} />;
              case "report":
                return <ReportCard key={i} report={it.report} />;
              case "error":
                return <ErrorCard key={i} message={it.message} />;
              case "routing":
                return <RoutingCard key={i} reason={it.reason} specialists={it.specialists} />;
              case "specialist":
                return <SpecialistCard key={i} name={it.name} result={it.result} />;
            }
          })}
        </div>
      </div>
    </div>
  );
});

DiagnosisView.displayName = "DiagnosisView";
