"""WorkflowFactory 测试

验证 route_from_supervisor 纯函数的路由逻辑。
"""

import pytest
from langgraph.types import Send

from app.services.workflow_factory import route_from_supervisor


class TestRouteFromSupervisor:
    """路由决策函数的纯函数测试"""

    def test_no_routing_goes_to_aggregator(self):
        """无 routing 决策时，直接返回 aggregator"""
        result = route_from_supervisor({"routing": []})
        assert result == ["aggregator"]

    def test_empty_specialists_goes_to_aggregator(self):
        """routing 中有 specialists 列表但为空时，也应返回 aggregator"""
        result = route_from_supervisor({"routing": [{"specialists": []}]})
        assert result == ["aggregator"]

    def test_single_specialist(self):
        """单个 Specialist 时，返回一个 Send 指令"""
        result = route_from_supervisor({
            "routing": [{"specialists": ["log_analyzer"], "tasks": ["分析日志"]}],
            "user_input": "CPU 高",
            "time_context": {"time": "2026-01-01"},
        })
        assert len(result) == 1
        send = result[0]
        assert isinstance(send, Send)
        assert send.node == "log_analyzer"
        assert send.arg["user_input"] == "CPU 高"
        assert send.arg["specialist_task"] == "分析日志"
        assert send.arg["time_context"] == {"time": "2026-01-01"}

    def test_multiple_specialists(self):
        """多个 Specialist 时，返回多个 Send 指令"""
        result = route_from_supervisor({
            "routing": [{
                "specialists": ["log_analyzer", "monitor_expert"],
                "tasks": ["分析日志", "查监控"],
            }],
            "user_input": "CPU 高",
        })
        assert len(result) == 2
        assert isinstance(result[0], Send)
        assert isinstance(result[1], Send)
        assert result[0].node == "log_analyzer"
        assert result[1].node == "monitor_expert"

    def test_task_out_of_range_falls_back_to_user_input(self):
        """tasks 列表长度不够时，剩余的 Specialist 使用 user_input 作为 task"""
        result = route_from_supervisor({
            "routing": [{
                "specialists": ["log_analyzer", "monitor_expert", "knowledge_retriever"],
                "tasks": ["分析日志"],
            }],
            "user_input": "默认诊断",
        })
        # 只有第一个有指定 task，其余 fallback
        assert result[0].arg["specialist_task"] == "分析日志"
        assert result[1].arg["specialist_task"] == "默认诊断"
        assert result[2].arg["specialist_task"] == "默认诊断"

    def test_no_tasks_falls_back_to_user_input(self):
        """tasks 不存在时，所有 Specialist 使用 user_input 作为 task"""
        result = route_from_supervisor({
            "routing": [{"specialists": ["log_analyzer"]}],
            "user_input": "通用诊断",
        })
        assert result[0].arg["specialist_task"] == "通用诊断"

    def test_missing_user_input_defaults_to_empty(self):
        """user_input 缺失时，task 默认为空字符串"""
        result = route_from_supervisor({
            "routing": [{"specialists": ["log_analyzer"]}],
        })
        assert result[0].arg["user_input"] == ""

    def test_latest_routing_used(self):
        """多个 routing 决策时，取最新一条"""
        result = route_from_supervisor({
            "routing": [
                {"specialists": ["log_analyzer"]},
                {"specialists": ["monitor_expert", "knowledge_retriever"]},
            ],
            "user_input": "诊断",
        })
        # 取 routing[-1] = 第二条
        assert len(result) == 2
        assert result[0].node == "monitor_expert"
        assert result[1].node == "knowledge_retriever"