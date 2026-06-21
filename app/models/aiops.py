"""
AIOps 请求和响应模型
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class AIOpsRequest(BaseModel):
    """AIOps 诊断请求"""

    session_id: Optional[str] = Field(
        default="default",
        description="会话ID，用于追踪诊断历史"
    )

    question: Optional[str] = Field(
        default=None,
        description="用户自定义的诊断问题（自然语言）。例如：'诊断 data-sync-service 的 CPU 过高问题'。如果不提供，将执行默认的全系统告警诊断"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "session_id": "session-123",
                "question": "诊断 data-sync-service 服务的 CPU 使用率过高问题"
            }
        }


class AlertInfo(BaseModel):
    """告警信息"""
    alertname: str
    severity: str
    instance: str
    duration: str
    description: Optional[str] = None


class DiagnosisResponse(BaseModel):
    """诊断响应（非流式）"""

    code: int = 200
    message: str = "success"
    data: Dict[str, Any]

    class Config:
        json_schema_extra = {
            "example": {
                "code": 200,
                "message": "success",
                "data": {
                    "status": "completed",
                    "target_alert": {
                        "alertname": "HighCPUUsage",
                        "severity": "critical"
                    },
                    "diagnosis": {
                        "root_cause": "数据库连接池耗尽",
                        "recommendations": ["扩容数据库连接池", "优化SQL查询"]
                    }
                }
            }
        }
