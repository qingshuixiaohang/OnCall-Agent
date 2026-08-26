"""诊断报告字段提取器

从诊断报告 Markdown 文本 + 状态元数据中启发式提取结构化字段，
供 DiagnosisReport 使用。纯函数，可独立测试。

提取策略（不侵入 Agent 核心节点）：
- severity: 基于报告/用户输入中的严重性关键词推断
- service_name: 从用户输入中的 service 提及 / 报告标题推断
- summary: 报告首段 / 非空摘要
- root_cause: 报告中"根因"段落的文本
- recommendations: 报告中"建议/处理"段落的要点列表
"""

import re
from typing import Any

# 服务名提示词（出现在用户输入或报告中，通常是带 "-" 的标识符）
_SERVICE_PATTERN = re.compile(
    r"(?<![\w-])(?:service|服务)\s*[:：=]?\s*['\"]?([a-zA-Z0-9][a-zA-Z0-9._-]{2,})",
    re.IGNORECASE,
)
_SERVICE_INLINE_PATTERN = re.compile(r"\b([a-zA-Z][a-zA-Z0-9]*(?:-[a-zA-Z0-9]+){1,})\b")

# 严重性关键词
_CRITICAL_KEYWORDS = ("严重", "critical", "宕机", "不可用", "只读", "重启", "崩溃", "oom", "挂掉", "危急")
_WARNING_KEYWORDS = ("告警", "warning", "过高", "超时", "异常", "升高", "错误", "error", "失败")


def infer_severity(text: str | None, default: str = "info") -> str:
    """根据文本中的关键词推断严重性"""
    if not text:
        return default
    lower = text.lower()
    if any(k in lower for k in _CRITICAL_KEYWORDS):
        return "critical"
    if any(k in lower for k in _WARNING_KEYWORDS):
        return "warning"
    return default


def extract_service_name(text: str | None) -> str | None:
    """从文本中提取服务名"""
    if not text:
        return None
    # 优先匹配 "service: xxx" 或 "服务 xxx"
    m = _SERVICE_PATTERN.search(text)
    if m:
        return m.group(1)
    # 退化：匹配带连字符的标识符（通常是服务名）
    for m in _SERVICE_INLINE_PATTERN.finditer(text):
        candidate = m.group(1)
        # 排除常见的非服务词
        if candidate.lower() in {"user-input", "session-id", "run-id", "service-name", "log-analyzer"}:
            continue
        return candidate
    return None


def extract_summary(text: str | None, max_len: int = 200) -> str:
    """从报告提取摘要（首行非空段落）"""
    if not text:
        return ""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines:
        return ""
    # 取第一段纯文本（非标题非列表）
    for ln in lines:
        if not ln.startswith(("#", "-", "*", ">", "|")):
            return ln[:max_len]
    return lines[0][:max_len]


def extract_root_cause(report: str | None) -> str | None:
    """从报告中提取根因段落文本"""
    if not report:
        return None
    # 匹配 "根因" 标题或关键词后的内容
    patterns = [
        re.compile(r"#{1,4}\s*(?:根因|原因分析|根因分析)[^\n]*\n+(.*?)(?=\n#{1,4}|$)", re.IGNORECASE | re.DOTALL),
        re.compile(r"(?:根因|根本原因)[:：]\s*([^\n]+)", re.IGNORECASE),
    ]
    for pat in patterns:
        m = pat.search(report)
        if m:
            text = m.group(1).strip()
            if text and not text.startswith(("#", "-", "|")):
                return text[:500]
            return None
    return None


def extract_recommendations(report: str | None, section_keywords: tuple[str, ...] = ("建议", "处理", "方案", "建议方案"), max_items: int = 5) -> list[str]:
    """从报告中提取处理建议要点列表"""
    if not report:
        return []
    items: list[str] = []
    in_section = False
    for line in report.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 进入/离开建议相关章节
        header_match = re.match(r"^#{1,6}\s*(.+)", stripped)
        if header_match:
            title = header_match.group(1)
            in_section = any(k in title for k in section_keywords)
            continue
        if in_section:
            # 列表项或纯文本行
            if stripped.startswith(("-", "*", "1.", "2.", "3.")):
                clean = re.sub(r"^[-*]\s*|\d+\.\s*", "", stripped).strip()
                if clean:
                    items.append(clean)
            elif not stripped.startswith(("|", ">")):
                # 章节内的过渡文本，若无列表项则整段视为建议
                if not items:
                    items.append(stripped[:200])
        if len(items) >= max_items:
            break
    return items


def extract_findings(report: str | None, max_findings: int = 6) -> list[dict[str, Any]]:
    """从报告提取关键发现（各小节标题 + 首句）"""
    if not report:
        return []
    findings: list[dict[str, Any]] = []
    current_title = "总览"
    current_lines: list[str] = []
    lines = report.splitlines()

    def flush():
        nonlocal findings, current_lines
        if current_lines:
            text = " ".join(current_lines).strip()
            if len(text) >= 5:
                findings.append({"title": current_title, "content": text[:300]})
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = re.match(r"^#{2,4}\s*(.+)", stripped)
        if m:
            flush()
            current_title = m.group(1).strip()
            continue
        # 收集正文第一两句
        if not stripped.startswith(("-", "*", "|", ">")):
            current_lines.append(stripped)
        if len(findings) >= max_findings:
            break
    flush()
    return findings[:max_findings]


def build_report_fields(
    *,
    report_markdown: str,
    user_input: str = "",
    state_values: dict[str, Any] | None = None,
    fallback_service: str | None = None,
) -> dict[str, Any]:
    """组合所有启发式字段提取。

    Args:
        report_markdown: 完整诊断报告
        user_input: 用户原始输入
        state_values: Agent final state（可为空）
        fallback_service: 从 state 已知的服务名（如 multi-agent 的 routing）

    Returns:
        可直接写入 DiagnosisReport 的字段 dict
    """
    combined = f"{user_input}\n{report_markdown}"
    service = extract_service_name(combined) or fallback_service

    return {
        "service_name": service,
        "severity": infer_severity(combined),
        "summary": extract_summary(report_markdown),
        "root_cause": extract_root_cause(report_markdown),
        "recommendations": extract_recommendations(report_markdown),
        "findings": extract_findings(report_markdown),
    }


# 供测试断言使用的稳定帮助（避免参数别忘）
_DEFAULT_SECTIONS = ("建议", "处理", "方案")
