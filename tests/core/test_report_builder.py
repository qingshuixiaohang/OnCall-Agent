"""report_builder 字段提取器测试"""

from app.core.report_builder import (
    build_report_fields,
    extract_findings,
    extract_recommendations,
    extract_root_cause,
    extract_service_name,
    extract_summary,
    infer_severity,
)


class TestInferSeverity:
    def test_critical_keywords(self):
        assert infer_severity("服务严重宕机，无法恢复") == "critical"
        assert infer_severity("OOM 导致进程崩溃") == "critical"

    def test_warning_keywords(self):
        assert infer_severity("CPU 使用率过高") == "warning"
        assert infer_severity("出现告警 error 日志") == "warning"

    def test_info_default(self):
        assert infer_severity("诊断完成，一切正常") == "info"
        assert infer_severity(None) == "info"
        assert infer_severity("") == "info"

    def test_critical_overrides_warning(self):
        # 同时含 critical 和 warning，取 critical
        assert infer_severity("告警：服务严重宕机") == "critical"


class TestExtractServiceName:
    def test_explicit_service_keyword(self):
        assert extract_service_name("诊断 service: data-sync-service") == "data-sync-service"
        assert extract_service_name("服务名：api-gateway") == "api-gateway"

    def test_inline_hyphenated(self):
        assert extract_service_name("data-sync-service CPU 过高") == "data-sync-service"

    def test_none_when_no_match(self):
        assert extract_service_name("诊断一下系统") is None
        assert extract_service_name(None) is None

    def test_skip_non_service_words(self):
        # 这些词不应被当作服务名
        assert extract_service_name("user-input session-id") is None


class TestExtractSummary:
    def test_first_paragraph(self):
        report = "# 诊断报告\n\nCPU 使用率过高，达到 95%。\n\n详细内容..."
        assert "CPU 使用率过高" in extract_summary(report)

    def test_skip_headers(self):
        report = "# 标题1\n## 标题2\n实际摘要内容"
        assert extract_summary(report) == "实际摘要内容"

    def test_empty(self):
        assert extract_summary(None) == ""
        assert extract_summary("") == ""

    def test_max_len(self):
        long = "x" * 500
        assert len(extract_summary(long, max_len=100)) == 100


class TestExtractRootCause:
    def test_header_section(self):
        report = "## 根因分析\n\n数据库连接池耗尽导致请求排队。\n\n## 建议\n..."
        rc = extract_root_cause(report)
        assert rc is not None
        assert "连接池耗尽" in rc

    def test_inline_colon(self):
        report = "根因：内存泄漏导致 OOM"
        assert extract_root_cause(report) == "内存泄漏导致 OOM"

    def test_none_when_absent(self):
        assert extract_root_cause("只是一个普通报告，没有根因字段") is None
        assert extract_root_cause(None) is None


class TestExtractRecommendations:
    def test_list_items(self):
        report = "## 处理建议\n- 扩容连接池\n- 优化 SQL 查询\n- 增加监控告警"
        recs = extract_recommendations(report)
        assert recs == ["扩容连接池", "优化 SQL 查询", "增加监控告警"]

    def test_numbered_items(self):
        report = "## 建议\n1. 重启服务\n2. 清理缓存"
        recs = extract_recommendations(report)
        assert recs == ["重启服务", "清理缓存"]

    def test_empty_when_no_section(self):
        assert extract_recommendations("没有建议段落") == []
        assert extract_recommendations(None) == []

    def test_max_items(self):
        items = "\n".join(f"- 建议{i}" for i in range(10))
        report = f"## 建议\n{items}"
        assert len(extract_recommendations(report, max_items=3)) == 3


class TestExtractFindings:
    def test_sections(self):
        report = "## 日志分析\n发现 ERROR 日志激增\n## 监控\nCPU 95%"
        findings = extract_findings(report)
        titles = [f["title"] for f in findings]
        assert "日志分析" in titles
        assert "监控" in titles

    def test_empty(self):
        assert extract_findings(None) == []
        assert extract_findings("") == []


class TestBuildReportFields:
    def test_full_extraction(self):
        report = (
            "# 诊断报告\n\n"
            "data-sync-service CPU 持续过高。\n\n"
            "## 根因分析\n\n连接池耗尽。\n\n"
            "## 处理建议\n- 扩容\n- 优化\n"
        )
        fields = build_report_fields(
            report_markdown=report,
            user_input="诊断 data-sync-service CPU 过高",
        )
        assert fields["service_name"] == "data-sync-service"
        assert fields["severity"] == "warning"
        assert "CPU" in fields["summary"]
        assert fields["root_cause"] is not None
        assert "扩容" in fields["recommendations"]

    def test_fallback_service(self):
        fields = build_report_fields(
            report_markdown="简单报告",
            user_input="诊断",
            fallback_service="known-svc",
        )
        assert fields["service_name"] == "known-svc"

    def test_critical_severity(self):
        fields = build_report_fields(
            report_markdown="服务严重宕机",
            user_input="",
        )
        assert fields["severity"] == "critical"
