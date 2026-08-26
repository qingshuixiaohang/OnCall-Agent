"""诊断报告查询 API

提供诊断报告的查询、详情和趋势分析接口。
"""

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.core.diagnosis_report_store import ReportFilter, report_store

router = APIRouter()


@router.get("/reports")
async def list_reports(
    session_id: str | None = Query(None, description="按会话ID过滤"),
    mode: str | None = Query(None, description="诊断模式: aiops 或 multi_agent"),
    severity: str | None = Query(None, description="严重等级: critical/warning/info"),
    service_name: str | None = Query(None, description="按服务名过滤"),
    from_date: str | None = Query(None, description="起始时间 (ISO 8601)"),
    to_date: str | None = Query(None, description="截止时间 (ISO 8601)"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
):
    """列出诊断报告（分页 + 过滤）"""
    try:
        filter_ = ReportFilter(
            session_id=session_id,
            mode=mode,
            severity=severity,
            service_name=service_name,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size,
        )
        reports, total = await report_store.list(filter_)
        return {
            "code": 200,
            "data": {
                "reports": [r.model_dump() for r in reports],
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        }
    except Exception as e:
        logger.error(f"查询诊断报告列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/reports/trends")
async def get_report_trends(
    from_date: str | None = Query(None, description="起始时间 (ISO 8601)"),
    to_date: str | None = Query(None, description="截止时间 (ISO 8601)"),
    group_by: str = Query("service", description="分组维度: service/severity/date"),
):
    """诊断报告趋势聚合"""
    if group_by not in ("service", "severity", "date"):
        raise HTTPException(
            status_code=400,
            detail="group_by 只能是 service / severity / date",
        )
    try:
        result = await report_store.trends(
            from_date=from_date,
            to_date=to_date,
            group_by=group_by,
        )
        return {"code": 200, "data": result}
    except Exception as e:
        logger.error(f"查询诊断报告趋势失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/reports/{report_id}")
async def get_report(report_id: str):
    """获取单条诊断报告详情"""
    try:
        report = await report_store.get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="报告不存在")
        return {"code": 200, "data": report.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取诊断报告详情失败: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
