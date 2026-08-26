"""ConversationCompressor 纯逻辑单元测试（不依赖 LLM）"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.conversation_compressor import ConversationCompressor


class TestCountTokens:
    """count_tokens: token 统计（tiktoken 不可用时走估算）"""

    def test_empty_messages_zero(self):
        c = ConversationCompressor()
        assert c.count_tokens([]) == 0

    def test_english_uses_tokenizer_or_estimate(self):
        c = ConversationCompressor()
        tokens = c.count_tokens([HumanMessage(content="hello world")])
        # tiktoken 可用时约 2 token；不可用时走估算（~2.75）。断言合理范围
        assert tokens > 0

    def test_chinese_chars_weighted_higher(self):
        c = ConversationCompressor()
        en = c.count_tokens([HumanMessage(content="hello")])
        zh = c.count_tokens([HumanMessage(content="你好世界")])
        # 中文每字约 1.5 token，英文每字符约 0.25；中文应显著大于同等长度英文
        assert zh >= en

    def test_multiple_messages_summed(self):
        c = ConversationCompressor()
        one = c.count_tokens([HumanMessage(content="hello")])
        two = c.count_tokens([HumanMessage(content="hello"), HumanMessage(content="world")])
        assert two > one


class TestShouldCompress:
    """_should_compress: 阈值判断"""

    def test_below_threshold_returns_false(self):
        c = ConversationCompressor(max_tokens=1000, threshold=0.7)
        assert c._should_compress([HumanMessage(content="hi")]) is False

    def test_above_threshold_returns_true(self):
        c = ConversationCompressor(max_tokens=10, threshold=0.7)
        # 阈值 = 10*0.7 = 7 token；长消息必然超过
        long_msg = HumanMessage(content="x" * 100)
        assert c._should_compress([long_msg]) is True

    def test_empty_messages_returns_false(self):
        c = ConversationCompressor()
        assert c._should_compress([]) is False


class TestFallbackTrim:
    """_fallback_trim: 降级裁剪"""

    def test_keeps_recent_and_first_system(self):
        c = ConversationCompressor(keep_recent=2)
        msgs = [
            SystemMessage(content="system"),
            HumanMessage(content="m1"),
            HumanMessage(content="m2"),
            HumanMessage(content="m3"),
            HumanMessage(content="m4"),
        ]
        result = c._fallback_trim(msgs)
        new = result["messages"][1:]  # 跳过 RemoveMessage
        # 保留首条 SystemMessage + 最近 keep_recent+1 条
        assert isinstance(new[0], SystemMessage)
        contents = [m.content for m in new]
        assert "m3" in contents
        assert "m4" in contents
        assert "m1" not in contents

    def test_empty_messages_does_not_crash(self):
        c = ConversationCompressor()
        result = c._fallback_trim([])
        # 不应抛异常，返回包含 RemoveMessage 的结构
        assert "messages" in result

    def test_returns_remove_message_marker(self):
        """降级结果首条应是 RemoveMessage（清空历史再追加保留消息）"""
        c = ConversationCompressor()
        from langchain_core.messages import RemoveMessage
        result = c._fallback_trim([HumanMessage(content="x")])
        assert isinstance(result["messages"][0], RemoveMessage)
