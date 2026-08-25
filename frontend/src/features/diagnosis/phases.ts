import type { Phase } from "./PhaseProgress";

/** 将后端工作流阶段映射为前端展示状态，和卡片组件分离。 */
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
