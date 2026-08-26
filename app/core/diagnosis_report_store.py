"""诊断报告数据模型与持久化存储

使用独立 SQLite 数据库存储结构化的诊断报告，
支持按时间、服务、严重等级过滤和趋势聚合。
"""

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import aiosqlite
from loguru import logger
from pydantic import BaseModel, Field


class DiagnosisReport(BaseModel):
    """结构化诊断报告"""

    id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str = ""
    run_id: str = ""
    mode: str = ""                          # "aiops" | "multi_agent"
    service_name: str | None = None
    severity: str = "info"                  # "critical" | "warning" | "info"
    summary: str = ""
    root_cause: str | None = None
    recommendations: list[str] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    report_markdown: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    duration_seconds: float | None = None
    status: str = "completed"               # "completed" | "failed" | "abstained"


class TrendFilter(BaseModel):
    """趋势查询过滤条件"""
    from_date: str | None = None
    to_date: str | None = None
    group_by: str = "service"               # "service" | "severity" | "date"


class ReportFilter(BaseModel):
    """报告列表过滤条件"""
    session_id: str | None = None
    mode: str | None = None
    severity: str | None = None
    service_name: str | None = None
    from_date: str | None = None
    to_date: str | None = None
    page: int = 1
    page_size: int = 20


class ReportStore:
    """诊断报告持久化存储

    使用独立 SQLite 数据库，与 checkpointer 分离。
    """

    _CREATE_SQL = """
    CREATE TABLE IF NOT EXISTS diagnosis_reports (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL DEFAULT '',
        run_id TEXT NOT NULL DEFAULT '',
        mode TEXT NOT NULL DEFAULT '',
        service_name TEXT,
        severity TEXT NOT NULL DEFAULT 'info',
        summary TEXT NOT NULL DEFAULT '',
        root_cause TEXT,
        recommendations TEXT NOT NULL DEFAULT '[]',
        findings TEXT NOT NULL DEFAULT '[]',
        report_markdown TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        duration_seconds REAL,
        status TEXT NOT NULL DEFAULT 'completed'
    );
    CREATE INDEX IF NOT EXISTS idx_reports_created_at ON diagnosis_reports(created_at);
    CREATE INDEX IF NOT EXISTS idx_reports_session ON diagnosis_reports(session_id);
    CREATE INDEX IF NOT EXISTS idx_reports_service ON diagnosis_reports(service_name);
    CREATE INDEX IF NOT EXISTS idx_reports_severity ON diagnosis_reports(severity);
    CREATE INDEX IF NOT EXISTS idx_reports_mode ON diagnosis_reports(mode);
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def initialize(self):
        """初始化数据库并建表"""
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(self._CREATE_SQL)
        await self._conn.commit()
        logger.info(f"ReportStore 初始化完成: {self._db_path}")

    async def close(self):
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def save(self, report: DiagnosisReport) -> str:
        """保存一条诊断报告"""
        if not self._conn:
            raise RuntimeError("ReportStore 未初始化，请先调用 initialize()")
        await self._conn.execute(
            """INSERT INTO diagnosis_reports
               (id, session_id, run_id, mode, service_name, severity,
                summary, root_cause, recommendations, findings,
                report_markdown, created_at, duration_seconds, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.id,
                report.session_id,
                report.run_id,
                report.mode,
                report.service_name,
                report.severity,
                report.summary,
                report.root_cause,
                _json_dumps(report.recommendations),
                _json_dumps([_serialize_finding(f) for f in report.findings]),
                report.report_markdown,
                report.created_at,
                report.duration_seconds,
                report.status,
            ),
        )
        await self._conn.commit()
        logger.debug(f"诊断报告已保存: {report.id}")
        return report.id

    async def get(self, report_id: str) -> DiagnosisReport | None:
        """按 ID 获取单条报告"""
        if not self._conn:
            return None
        cursor = await self._conn.execute(
            "SELECT * FROM diagnosis_reports WHERE id = ?", (report_id,)
        )
        row = await cursor.fetchone()
        return _row_to_report(row) if row else None

    async def list(self, filter_: ReportFilter | None = None) -> tuple[list[DiagnosisReport], int]:
        """列出报告（分页 + 过滤）"""
        if not self._conn:
            return [], 0
        if filter_ is None:
            filter_ = ReportFilter()

        where_clauses: list[str] = []
        params: list[Any] = []

        if filter_.session_id:
            where_clauses.append("session_id = ?")
            params.append(filter_.session_id)
        if filter_.mode:
            where_clauses.append("mode = ?")
            params.append(filter_.mode)
        if filter_.severity:
            where_clauses.append("severity = ?")
            params.append(filter_.severity)
        if filter_.service_name:
            where_clauses.append("service_name = ?")
            params.append(filter_.service_name)
        if filter_.from_date:
            where_clauses.append("created_at >= ?")
            params.append(filter_.from_date)
        if filter_.to_date:
            where_clauses.append("created_at <= ?")
            params.append(filter_.to_date)

        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # 总数
        cursor = await self._conn.execute(f"SELECT COUNT(*) FROM diagnosis_reports{where_sql}", params)
        row = await cursor.fetchone()
        total = row[0] if row else 0

        # 分页
        offset = (filter_.page - 1) * filter_.page_size
        cursor = await self._conn.execute(
            f"SELECT * FROM diagnosis_reports{where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [filter_.page_size, offset],
        )
        rows = await cursor.fetchall()
        reports = [_row_to_report(r) for r in rows if r]
        return reports, total

    async def trends(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        group_by: str = "service",
    ) -> dict[str, Any]:
        """趋势聚合

        Args:
            from_date: 起始时间 ISO 字符串
            to_date: 截止时间 ISO 字符串
            group_by: 分组维度 ("service" | "severity" | "date")

        Returns:
            { "series": [...], "summary": {...} }
        """
        if not self._conn:
            return {"series": [], "summary": {}}

        where_clauses: list[str] = []
        params: list[Any] = []

        if from_date:
            where_clauses.append("created_at >= ?")
            params.append(from_date)
        if to_date:
            where_clauses.append("created_at <= ?")
            params.append(to_date)
        where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        # 总体统计
        cursor = await self._conn.execute(
            f"""SELECT
                   COUNT(*) as total,
                   severity,
                   COUNT(*) as cnt
               FROM diagnosis_reports{where_sql}
               GROUP BY severity""",
            params,
        )
        rows = await cursor.fetchall()
        by_severity: dict[str, int] = {}
        total = 0
        for row in rows:
            by_severity[row["severity"]] = row["cnt"]
            total += row["cnt"]

        # 按服务统计
        service_where = where_sql + " AND service_name IS NOT NULL" if where_sql else " WHERE service_name IS NOT NULL"
        cursor = await self._conn.execute(
            f"""SELECT service_name, COUNT(*) as cnt
               FROM diagnosis_reports{service_where}
               GROUP BY service_name
               ORDER BY cnt DESC LIMIT 20""",
            params,
        )
        rows = await cursor.fetchall()
        by_service: dict[str, int] = {row["service_name"]: row["cnt"] for row in rows}

        # 按时间序列
        if group_by == "date":
            cursor = await self._conn.execute(
                f"""SELECT DATE(created_at) as date, COUNT(*) as cnt
                   FROM diagnosis_reports{where_sql}
                   GROUP BY DATE(created_at)
                   ORDER BY date ASC""",
                params,
            )
            series = [{"date": row["date"], "count": row["cnt"]} for row in await cursor.fetchall()]
        elif group_by == "service":
            service_where = where_sql + " AND service_name IS NOT NULL" if where_sql else " WHERE service_name IS NOT NULL"
            cursor = await self._conn.execute(
                f"""SELECT service_name, COUNT(*) as cnt
                   FROM diagnosis_reports{service_where}
                   GROUP BY service_name
                   ORDER BY cnt DESC""",
                params,
            )
            series = [{"service": row["service_name"], "count": row["cnt"]} for row in await cursor.fetchall()]
        elif group_by == "severity":
            series = [{"severity": k, "count": v} for k, v in by_severity.items()]
        else:
            series = []

        return {
            "series": series,
            "summary": {
                "total_reports": total,
                "by_severity": by_severity,
                "by_service": by_service,
            },
        }


# ============================================================================
# 内部工具
# ============================================================================


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _serialize_finding(finding: dict[str, Any]) -> dict[str, Any]:
    """确保 finding 中的复杂类型可 JSON 序列化"""
    return {k: _safe_value(v) for k, v in finding.items()}


def _safe_value(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    return str(v)


def _row_to_report(row: aiosqlite.Row) -> DiagnosisReport:
    """将数据库行转换为 DiagnosisReport"""
    return DiagnosisReport(
        id=row["id"],
        session_id=row["session_id"],
        run_id=row["run_id"],
        mode=row["mode"],
        service_name=row["service_name"],
        severity=row["severity"],
        summary=row["summary"],
        root_cause=row["root_cause"],
        recommendations=json.loads(row["recommendations"] or "[]"),
        findings=json.loads(row["findings"] or "[]"),
        report_markdown=row["report_markdown"],
        created_at=row["created_at"],
        duration_seconds=row["duration_seconds"],
        status=row["status"],
    )


# 全局单例（由 lifespan 初始化）
report_store = ReportStore(db_path="reports.db")
