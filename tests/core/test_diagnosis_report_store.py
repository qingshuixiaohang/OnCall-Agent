"""ReportStore 测试

使用临时文件测试 SQLite 存储层。
"""

import tempfile
from pathlib import Path

import pytest

from app.core.diagnosis_report_store import (
    DiagnosisReport,
    ReportFilter,
    ReportStore,
)


@pytest.fixture
async def store():
    """创建临时 SQLite 数据库的 ReportStore"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    s = ReportStore(db_path)
    await s.initialize()
    yield s
    await s.close()
    Path(db_path).unlink(missing_ok=True)


def _make_report(**kwargs) -> DiagnosisReport:
    defaults = {
        "session_id": "s1",
        "run_id": "r1",
        "mode": "aiops",
        "service_name": "data-sync",
        "severity": "warning",
        "summary": "CPU 使用率过高",
        "root_cause": "数据库连接池耗尽",
        "recommendations": ["扩容连接池", "优化 SQL"],
        "findings": [{"type": "cpu", "value": 95}],
        "report_markdown": "# 诊断报告\nCPU 过高",
        "status": "completed",
    }
    defaults.update(kwargs)
    return DiagnosisReport(**defaults)


class TestReportStore:
    async def test_save_and_get(self, store: ReportStore):
        """保存后能按 ID 取出"""
        report = _make_report()
        saved_id = await store.save(report)

        fetched = await store.get(saved_id)
        assert fetched is not None
        assert fetched.id == report.id
        assert fetched.service_name == "data-sync"
        assert fetched.severity == "warning"
        assert fetched.summary == "CPU 使用率过高"
        assert fetched.recommendations == ["扩容连接池", "优化 SQL"]
        assert fetched.findings == [{"type": "cpu", "value": 95}]

    async def test_get_nonexistent(self, store: ReportStore):
        """不存在的 ID 返回 None"""
        fetched = await store.get("nonexistent")
        assert fetched is None

    async def test_list_empty(self, store: ReportStore):
        """空数据库返回空列表"""
        reports, total = await store.list()
        assert reports == []
        assert total == 0

    async def test_list_with_filter(self, store: ReportStore):
        """按 mode 过滤"""
        await store.save(_make_report(mode="aiops", id="1"))
        await store.save(_make_report(mode="multi_agent", id="2"))

        reports, total = await store.list(ReportFilter(mode="aiops"))
        assert total == 1
        assert reports[0].id == "1"

    async def test_list_with_time_range(self, store: ReportStore):
        """按时间范围过滤"""
        await store.save(_make_report(id="1", created_at="2026-01-01T00:00:00Z"))
        await store.save(_make_report(id="2", created_at="2026-01-15T00:00:00Z"))
        await store.save(_make_report(id="3", created_at="2026-02-01T00:00:00Z"))

        reports, total = await store.list(ReportFilter(
            from_date="2026-01-01",
            to_date="2026-01-31",
        ))
        assert total == 2
        assert {r.id for r in reports} == {"1", "2"}

    async def test_list_pagination(self, store: ReportStore):
        """分页正确"""
        for i in range(5):
            await store.save(_make_report(id=str(i)))

        reports, total = await store.list(ReportFilter(page=1, page_size=2))
        assert total == 5
        assert len(reports) == 2

        reports2, _ = await store.list(ReportFilter(page=2, page_size=2))
        assert len(reports2) == 2

    async def test_trends_by_severity(self, store: ReportStore):
        """按严重等级的趋势统计"""
        await store.save(_make_report(id="1", severity="critical"))
        await store.save(_make_report(id="2", severity="warning"))
        await store.save(_make_report(id="3", severity="warning"))
        await store.save(_make_report(id="4", severity="info"))

        result = await store.trends(group_by="severity")
        assert result["summary"]["by_severity"] == {"critical": 1, "warning": 2, "info": 1}
        assert result["summary"]["total_reports"] == 4

    async def test_trends_by_service(self, store: ReportStore):
        """按服务的趋势统计"""
        await store.save(_make_report(id="1", service_name="svc-a"))
        await store.save(_make_report(id="2", service_name="svc-b"))
        await store.save(_make_report(id="3", service_name="svc-a"))

        result = await store.trends(group_by="service")
        assert len(result["series"]) >= 2
        by_svc = {s["service"]: s["count"] for s in result["series"]}
        assert by_svc["svc-a"] == 2
        assert by_svc["svc-b"] == 1

    async def test_trends_time_filtered(self, store: ReportStore):
        """趋势聚合支持时间过滤"""
        await store.save(_make_report(id="1", created_at="2026-01-01T00:00:00Z"))
        await store.save(_make_report(id="2", created_at="2026-02-01T00:00:00Z"))

        result = await store.trends(from_date="2026-01-01", to_date="2026-01-31")
        assert result["summary"]["total_reports"] == 1

    async def test_save_with_all_fields(self, store: ReportStore):
        """保存包含所有字段的报告"""
        report = DiagnosisReport(
            id="full",
            session_id="s1",
            run_id="r1",
            mode="aiops",
            service_name="api-gateway",
            severity="critical",
            summary="服务不可用",
            root_cause="OOM",
            recommendations=["加内存", "加限流"],
            findings=[{"type": "memory", "value": 99.9}],
            report_markdown="# 完整报告\n...",
            duration_seconds=120.5,
            status="completed",
        )
        saved_id = await store.save(report)
        fetched = await store.get(saved_id)
        assert fetched is not None
        assert fetched.duration_seconds == 120.5
        assert fetched.service_name == "api-gateway"
        assert fetched.status == "completed"
