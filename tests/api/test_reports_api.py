"""诊断报告 API 测试

用 httpx.AsyncClient + ASGITransport 驱动 FastAPI app，
避免 TestClient 跨 event loop 访问 aiosqlite 连接的隐患。
"""

import tempfile
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from app.core.diagnosis_report_store import DiagnosisReport, report_store


@pytest.fixture
async def app_client():
    """每个测试使用独立的临时数据库 + AsyncClient"""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    original_path = report_store._db_path
    report_store._db_path = db_path
    await report_store.initialize()

    from app.main import app
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await report_store.close()
    report_store._db_path = original_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def test_report():
    return DiagnosisReport(
        session_id="s1",
        run_id="r1",
        mode="aiops",
        service_name="data-sync",
        severity="warning",
        summary="CPU 过高",
        report_markdown="# 诊断报告\nCPU 过高",
        status="completed",
    )


class TestReportsAPI:
    async def test_list_reports_empty(self, app_client: httpx.AsyncClient):
        """空数据库返回空列表"""
        response = await app_client.get("/api/reports")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["reports"] == []
        assert data["data"]["total"] == 0

    async def test_list_reports_with_data(
        self, app_client: httpx.AsyncClient, test_report: DiagnosisReport
    ):
        """有数据时返回列表"""
        await report_store.save(test_report)
        response = await app_client.get("/api/reports")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["total"] == 1
        assert data["data"]["reports"][0]["summary"] == "CPU 过高"

    async def test_get_report(
        self, app_client: httpx.AsyncClient, test_report: DiagnosisReport
    ):
        """按 ID 获取单条报告"""
        saved_id = await report_store.save(test_report)
        response = await app_client.get(f"/api/reports/{saved_id}")
        assert response.status_code == 200
        assert response.json()["data"]["id"] == saved_id

    async def test_get_report_not_found(self, app_client: httpx.AsyncClient):
        """不存在的 ID 返回 404"""
        response = await app_client.get("/api/reports/nonexistent")
        assert response.status_code == 404

    async def test_list_reports_filter_by_mode(self, app_client: httpx.AsyncClient):
        """按 mode 过滤"""
        await report_store.save(
            DiagnosisReport(mode="aiops", report_markdown="r1", status="completed")
        )
        await report_store.save(
            DiagnosisReport(
                mode="multi_agent", report_markdown="r2", status="completed"
            )
        )
        response = await app_client.get("/api/reports?mode=aiops")
        assert response.status_code == 200
        assert response.json()["data"]["total"] == 1

    async def test_trends(self, app_client: httpx.AsyncClient):
        """趋势聚合"""
        await report_store.save(
            DiagnosisReport(
                severity="critical",
                service_name="svc-a",
                report_markdown="r1",
                status="completed",
            )
        )
        await report_store.save(
            DiagnosisReport(
                severity="warning",
                service_name="svc-b",
                report_markdown="r2",
                status="completed",
            )
        )
        response = await app_client.get("/api/reports/trends?group_by=severity")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["summary"]["total_reports"] == 2
        assert data["summary"]["by_severity"]["critical"] == 1
