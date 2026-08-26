"""RouterAgent 路由决策测试

重点测 _parse_routing 的三分支 JSON 解析 + 关键词兜底，
不依赖真实 LLM 调用。
"""

import pytest

from app.agent.router import RouterAgent


@pytest.fixture
def router():
    return RouterAgent()


class TestParseRouting:
    """_parse_routing 纯函数测试"""

    def test_direct_json(self, router: RouterAgent):
        """直接 JSON 解析"""
        content = '{"target": "aiops", "reason": "运维诊断", "question": "CPU 过高"}'
        result = router._parse_routing(content, "CPU 过高")
        assert result["target"] == "aiops"
        assert result["reason"] == "运维诊断"

    def test_json_in_code_block(self, router: RouterAgent):
        """Markdown 代码块里的 JSON"""
        content = '```json\n{"target": "multi_agent", "reason": "复杂故障", "question": "x"}\n```'
        result = router._parse_routing(content, "x")
        assert result["target"] == "multi_agent"

    def test_json_in_plain_code_block(self, router: RouterAgent):
        """无 json 标记的代码块"""
        content = '```\n{"target": "rag", "reason": "r", "question": "q"}\n```'
        result = router._parse_routing(content, "q")
        assert result["target"] == "rag"

    def test_embedded_json(self, router: RouterAgent):
        """文本中嵌入的 JSON 对象"""
        content = '分析结果如下：\n{"target": "aiops", "reason": "ok", "question": "y"}\n结束'
        result = router._parse_routing(content, "y")
        assert result["target"] == "aiops"

    def test_keyword_fallback(self, router: RouterAgent):
        """所有解析失败时用关键词兜底"""
        content = "这是一段无法解析的纯文本，没有 JSON"
        result = router._parse_routing(content, "原始问题")
        assert result["target"] in ("rag", "aiops", "multi_agent")
        assert result["question"] == "原始问题"

    def test_empty_input_returns_rag(self, router: RouterAgent):
        """空输入默认走 RAG"""
        import asyncio

        result = asyncio.run(router.route(""))
        assert result["target"] == "rag"

    def test_normalize_missing_fields(self, router: RouterAgent):
        """JSON 缺 reason/question 时能补默认值"""
        content = '{"target": "rag"}'
        result = router._parse_routing(content, "fallback q")
        assert result["target"] == "rag"
        assert "reason" in result
        assert result["question"] == "fallback q"
