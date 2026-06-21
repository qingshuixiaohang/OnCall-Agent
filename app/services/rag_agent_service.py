"""RAG Agent 服务 - 基于 LangGraph 的智能代理

使用 langchain_qwq 的 ChatQwen 原生集成，
支持真正的流式输出和更好的模型适配。
支持对话上下文自动压缩（当 token 使用量达到 70% 阈值时自动总结历史对话）。
"""

from typing import Annotated, Any, AsyncGenerator, Dict, Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.message import REMOVE_ALL_MESSAGES, add_messages
from loguru import logger
from typing_extensions import TypedDict
from langchain_qwq import ChatQwen

from app.config import config
from app.tools import get_current_time, retrieve_knowledge
from app.agent.mcp_client import get_mcp_client_with_retry

# 阿里千问大模型和langchain集成参考： https://docs.langchain.com/oss/python/integrations/chat/qwen
# 注意：需要配置环境变量 DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1 否则默认访问的是新加坡站点
# 同时也需要配置环境变量 DASHSCOPE_API_KEY=your_api_key


class AgentState(TypedDict):
    """Agent 状态"""
    messages: Annotated[Sequence[BaseMessage], add_messages]


# ============================================================================
# 上下文压缩模块
# ============================================================================

class ConversationCompressor:
    """对话上下文压缩器

    当对话消息的 token 总数超过配置的阈值（默认 70% 上下文窗口）时，
    自动使用 LLM 对历史对话进行总结，用简洁的摘要替换旧的详细消息，
    从而将上下文保持在可控范围内。

    工作原理：
        1. 用 tiktoken 计算当前所有消息的 token 总数
        2. 如果 token 数 >= 阈值，触发压缩
        3. 将消息分为三组：系统消息、旧消息（需要压缩）、最近消息（保留）
        4. 调用 LLM 对旧消息进行总结
        5. 用总结文本替换旧消息，重新组装消息列表

    Attributes:
        max_tokens: 模型上下文窗口总大小（tokens）
        threshold: 压缩触发阈值比例（0.0~1.0）
        keep_recent: 压缩后保留的最近消息条数
        summarization_model: 用于生成摘要的 LLM 实例
    """

    # 总结提示词模板
    SUMMARIZE_PROMPT = """请将以下对话历史总结为一到两段简洁的摘要。
摘要需要包含：
1. 用户问过的所有问题的要点
2. 助手执行过的关键操作（如调用了什么工具、查到了什么数据）
3. 重要的发现和结论

请直接用中文输出摘要，不要加"对话摘要："等前缀。"""

    def __init__(
        self,
        max_tokens: int = 32768,
        threshold: float = 0.7,
        keep_recent: int = 4,
    ):
        """初始化压缩器

        Args:
            max_tokens: 模型上下文窗口大小（tokens）
            threshold: 压缩触发阈值（0.0~1.0），默认 0.7 即 70%
            keep_recent: 压缩后保留的最近消息条数
        """
        self.max_tokens = max_tokens
        self.threshold = threshold
        self.keep_recent = keep_recent

        # 延迟初始化 tiktoken（避免 import 时触发大文件加载）
        self._tokenizer = None

        # 延迟初始化总结模型
        self._summarization_model = None

    @property
    def tokenizer(self):
        """懒加载 tiktoken 编码器

        使用 cl100k_base 编码（GPT-4/Qwen 系列通用 BPE 编码器），
        对中文的 token 估算较为准确（通常 1 个中文字 ≈ 1.5-2 token）。
        """
        if self._tokenizer is None:
            try:
                import tiktoken
                self._tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.info("tiktoken 编码器已加载: cl100k_base")
            except ImportError:
                logger.warning("tiktoken 未安装，将使用字符估算代替 token 计数")
                self._tokenizer = None
            except Exception as e:
                logger.warning(f"tiktoken 加载失败，将使用字符估算: {e}")
                self._tokenizer = None
        return self._tokenizer

    @property
    def summarization_model(self):
        """懒加载总结模型（使用独立的 LLM 实例，低温度以保证总结质量）"""
        if self._summarization_model is None:
            self._summarization_model = ChatQwen(
                model=config.rag_model,
                api_key=config.dashscope_api_key,
                temperature=0.3,  # 低温度确保总结准确、简洁
                streaming=False,   # 总结不需要流式
            )
        return self._summarization_model

    def count_tokens(self, messages: Sequence[BaseMessage]) -> int:
        """计算消息列表的总 token 数

        优先使用 tiktoken 精确计数；如果 tiktoken 不可用，
        则使用经验公式估算（中文约 1 字符 ≈ 1.5 token，英文约 4 字符 ≈ 1 token）。

        Args:
            messages: 消息列表

        Returns:
            int: 估算的 token 总数
        """
        total = 0
        for msg in messages:
            content = msg.content if hasattr(msg, 'content') else str(msg)
            if isinstance(content, str):
                if self._tokenizer is not None:
                    total += len(self.tokenizer.encode(content))
                else:
                    # 回退估算：中文字符约 1.5 token/字，英文约 0.25 token/字符
                    chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
                    other_chars = len(content) - chinese_chars
                    total += int(chinese_chars * 1.5 + other_chars * 0.25)
            elif isinstance(content, list):
                # 多模态内容列表（如图片+文字）
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '')
                        if self._tokenizer is not None:
                            total += len(self.tokenizer.encode(text))
                        else:
                            chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                            other_chars = len(text) - chinese_chars
                            total += int(chinese_chars * 1.5 + other_chars * 0.25)
        return total

    def _should_compress(self, messages: Sequence[BaseMessage]) -> bool:
        """判断是否需要压缩

        Args:
            messages: 当前消息列表

        Returns:
            bool: 是否需要压缩
        """
        token_count = self.count_tokens(messages)
        threshold_tokens = int(self.max_tokens * self.threshold)
        return token_count >= threshold_tokens

    async def _summarize_messages(self, messages: list[BaseMessage]) -> str:
        """对一组消息进行总结

        Args:
            messages: 需要总结的消息列表

        Returns:
            str: 总结文本
        """
        # 构建对话文本
        conversation_text_parts = []
        for msg in messages:
            if isinstance(msg, SystemMessage):
                continue  # 跳过系统消息
            role = "用户" if isinstance(msg, HumanMessage) else "助手"
            content = msg.content if hasattr(msg, 'content') else str(msg)
            if isinstance(content, list):
                # 多模态消息，只提取文本部分
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text_parts.append(block.get('text', ''))
                content = ' '.join(text_parts)
            # 截断过长的单条消息
            if len(str(content)) > 2000:
                content = str(content)[:2000] + "...(已截断)"
            conversation_text_parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(conversation_text_parts)

        summary_response = await self.summarization_model.ainvoke([
            HumanMessage(content=f"{self.SUMMARIZE_PROMPT}\n\n对话内容：\n{conversation_text}")
        ])
        summary = summary_response.content if hasattr(summary_response, 'content') else str(summary_response)
        logger.info(f"对话总结完成，摘要长度: {len(summary)} 字符")
        return summary

    async def compress(self, messages: Sequence[BaseMessage]) -> dict[str, Any] | None:
        """执行上下文压缩

        检查消息列表的 token 数，如果超过阈值则进行压缩。

        Args:
            messages: 当前消息列表

        Returns:
            dict | None: 如果执行了压缩，返回新的消息列表字典；否则返回 None
        """
        if not messages:
            return None

        # 检查是否需要压缩
        if not self._should_compress(messages):
            return None

        token_count = self.count_tokens(messages)
        threshold_tokens = int(self.max_tokens * self.threshold)
        logger.info(
            f"上下文压缩触发: token 数 {token_count} >= "
            f"阈值 {threshold_tokens} ({self.threshold*100:.0f}% × {self.max_tokens})"
        )
        logger.info(f"开始压缩对话上下文，压缩前消息数: {len(messages)}")

        try:
            # 步骤 1: 分组消息
            system_messages = []
            non_system_messages = []

            for i, msg in enumerate(messages):
                if isinstance(msg, SystemMessage) and i < 2:
                    system_messages.append(msg)
                else:
                    non_system_messages.append(msg)

            # 如果非系统消息太少，不值得压缩
            if len(non_system_messages) <= self.keep_recent + 2:
                logger.info("消息太少，跳过压缩")
                return None

            # 分离旧消息和最近消息
            split_point = max(0, len(non_system_messages) - self.keep_recent)
            old_messages = non_system_messages[:split_point]
            recent_messages = non_system_messages[split_point:]

            if not old_messages:
                logger.info("没有旧消息需要压缩")
                return None

            # 步骤 2: 调用 LLM 总结旧消息
            logger.info(f"压缩中: 总结 {len(old_messages)} 条旧消息，保留 {len(recent_messages)} 条最近消息")
            summary_text = await self._summarize_messages(old_messages)

            # 步骤 3: 重建消息列表
            new_messages = list(system_messages)
            new_messages.append(HumanMessage(
                content=f"[历史对话摘要]\n以下是之前对话的要点总结，用于帮你快速了解上下文：\n\n{summary_text}\n\n---\n以下是最近的对话："
            ))
            new_messages.extend(recent_messages)

            # 计算压缩效果
            old_tokens = self.count_tokens(messages)
            new_tokens = self.count_tokens(new_messages)
            reduction = (1 - new_tokens / old_tokens) * 100 if old_tokens > 0 else 0

            logger.info(
                f"上下文压缩完成: {len(messages)} 条消息 → {len(new_messages)} 条, "
                f"token: {old_tokens} → {new_tokens} (减少 {reduction:.1f}%)"
            )

            return {
                "messages": [
                    RemoveMessage(id=REMOVE_ALL_MESSAGES),
                    *new_messages
                ]
            }

        except Exception as e:
            logger.error(f"上下文压缩失败，回退到简单截断: {e}")
            return self._fallback_trim(messages)

    def _fallback_trim(self, messages: Sequence[BaseMessage]) -> dict[str, Any]:
        """压缩失败时的降级策略：简单截断

        保留系统消息 + 最近 N 条消息，丢弃其余。

        Args:
            messages: 原始消息列表

        Returns:
            dict: 截断后的消息列表字典
        """
        first_msg = messages[0] if messages else None
        keep_count = min(self.keep_recent + 2, len(messages))

        if first_msg and isinstance(first_msg, SystemMessage):
            recent = messages[-(keep_count - 1):] if len(messages) > keep_count else messages[1:]
            new_messages = [first_msg] + list(recent)
        else:
            recent = messages[-keep_count:] if len(messages) > keep_count else messages
            new_messages = list(recent)

        logger.warning(f"降级截断: {len(messages)} 条 → {len(new_messages)} 条")

        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *new_messages
            ]
        }


# ============================================================================
# LangChain AgentMiddleware 实现
# ============================================================================

class CompressionMiddleware(AgentMiddleware):
    """上下文压缩中间件

    继承自 LangChain 的 AgentMiddleware 基类，
    在每次 LLM 调用前检查消息列表的 token 数，
    如果超过 70% 阈值则自动压缩历史对话。

    使用方式: create_agent(middleware=[CompressionMiddleware()])
    """

    def __init__(self):
        super().__init__()
        self.compressor = ConversationCompressor(
            max_tokens=config.context_max_tokens,
            threshold=config.context_compression_threshold,
            keep_recent=config.context_keep_recent,
        )

    async def abefore_model(
        self,
        state: AgentState,
        runtime: Any = None,
    ) -> dict[str, Any] | None:
        """在模型调用前执行上下文压缩

        Args:
            state: 当前 Agent 状态
            runtime: 运行时上下文（未使用）

        Returns:
            dict | None: state 更新字典（如压缩了上下文），或 None（无需操作）
        """
        messages = state.get("messages", [])
        return await self.compressor.compress(messages)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        """工具调用拦截（透传，不做任何修改）

        AgentMiddleware 要求子类实现此方法。
        我们不做任何拦截，直接调用 handler 执行工具。
        """
        return await handler(request)


# ============================================================================
# RagAgentService
# ============================================================================

class RagAgentService:
    """RAG Agent 服务 - 使用 LangGraph + ChatQwen 原生集成"""

    def __init__(self, streaming: bool = True):
        """初始化 RAG Agent 服务

        Args:
            streaming: 是否启用流式输出，默认为 True
        """
        self.model_name = config.rag_model
        self.streaming = streaming
        # 系统提示词在 _initialize_agent 中动态构建（需要 MCP 工具信息）
        self.system_prompt = ""

        self.model = ChatQwen(
            model=self.model_name,
            api_key=config.dashscope_api_key,
            temperature=0.7,
            streaming=streaming,
        )

        # 定义基础工具
        self.tools = [retrieve_knowledge, get_current_time]

        # MCP 客户端（延迟初始化，使用全局管理）
        self.mcp_tools: list = []

        # 创建内存检查点（用于会话管理）
        self.checkpointer = MemorySaver()

        # Agent 初始化（会在异步方法中完成）
        self.agent = None
        self._agent_initialized = False

        logger.info(f"RAG Agent 服务初始化完成 (ChatQwen), model={self.model_name}, streaming={streaming}")

    async def _initialize_agent(self):
        """异步初始化 Agent（包括 MCP 工具和动态系统提示词）"""
        if self._agent_initialized:
            return

        # 使用全局 MCP 客户端管理器（带重试拦截器）
        mcp_client = await get_mcp_client_with_retry()

        # 获取 MCP 工具（网络问题不阻塞 Agent 启动）
        try:
            mcp_tools = await mcp_client.get_tools()
            logger.info(f"成功加载 {len(mcp_tools)} 个 MCP 工具")
        except Exception as e:
            logger.warning(f"MCP 工具加载失败（将使用基础工具继续）: {e}")
            mcp_tools = []

        # 将 MCP 工具添加到实例变量中
        self.mcp_tools = mcp_tools

        # 合并所有工具
        all_tools = self.tools + self.mcp_tools

        # 动态构建系统提示词（基于实际可用的工具）
        self.system_prompt = self._build_system_prompt(all_tools)

        # 创建上下文压缩中间件
        compression_middleware = CompressionMiddleware()

        self.agent = create_agent(
            self.model,
            tools=all_tools,
            checkpointer=self.checkpointer,
            system_prompt=self.system_prompt,
            middleware=[compression_middleware],
        )

        self._agent_initialized = True

        if all_tools:
            tool_names = [tool.name if hasattr(tool, "name") else str(tool) for tool in all_tools]
            logger.info(f"可用工具列表: {', '.join(tool_names)}")
            logger.info(f"系统提示词已动态构建，长度: {len(self.system_prompt)} 字符")
            logger.info(
                f"上下文压缩已启用: max_tokens={config.context_max_tokens}, "
                f"threshold={config.context_compression_threshold*100:.0f}%, "
                f"keep_recent={config.context_keep_recent}"
            )

    def _build_system_prompt(self, all_tools: list | None = None) -> str:
        """
        构建系统提示词（动态版本 - 基于实际可用工具）

        当传入 all_tools 时，会提取工具名称和描述来增强提示词；
        否则使用通用版本（用于初始化阶段）。

        Args:
            all_tools: 所有可用工具的列表（本地 + MCP）

        Returns:
            str: 系统提示词
        """
        from textwrap import dedent

        # 提取工具描述信息
        tool_descriptions = self._extract_tool_descriptions(all_tools) if all_tools else ""

        base_prompt = dedent("""
            你是一个专业的智能运维（AIOps）助手，能够使用多种工具来帮助用户排查系统问题、查询日志和监控数据。

            ## 核心能力
            1. **日志查询与分析**: 查询腾讯云 CLS（Cloud Log Service）中的日志，支持按级别、关键词、时间范围筛选
            2. **监控指标查询**: 查询服务的 CPU 使用率、内存使用率等监控数据
            3. **知识检索**: 从内部知识库中检索相关的运维经验和最佳实践
            4. **时间查询**: 获取当前时间戳，用于日志查询的时间范围计算

            {tool_section}

            ## 工具使用核心原则

            ### 原则 1：使用精确的工具名称
            你必须使用系统提供的工具列表中**精确的工具名称**。不要自作主张地创造或猜测工具名。
            例如：查询日志的工具叫 `search_log`，不是什么 `query_logs`、`TextToSearchLogQuery` 或其他变体。

            ### 原则 2：查询日志前必须先找到 Topic
            日志查询的标准工作流（必须严格遵循）：
            ```
            步骤1: search_topic_by_service_name(service_name="服务名")
                   -> 获取真实的 topic_id
            步骤2: get_current_timestamp()
                   -> 获取当前毫秒时间戳
            步骤3: 计算 start_time = current_ts - (N分钟 * 60 * 1000)
            步骤4: search_log(topic_id=步骤1获取的ID, start_time=步骤3计算值, end_time=步骤2获取值, query="查询条件")
            ```
            禁止跳过步骤1直接调用 search_log！topic_id 必须来自 search_topic_by_service_name 的返回结果。
            禁止编造 topic_id（如 "topic-1234567890"）！

            ### 原则 3：监控指标查询可直接进行
            查询 CPU 或内存使用率不需要预先查找任何 ID：
            ```
            query_cpu_metrics(service_name="服务名")
            query_memory_metrics(service_name="服务名")
            ```
            可选传入 start_time（格式: "YYYY-MM-DD HH:MM:SS"）和 end_time 来指定时间范围。

            ## 自然语言到工具调用的映射示例

            | 用户提问 | 正确的工具调用流程 |
            |---------|-----------------|
            | "查询所有 ERROR 级别的日志" | 1. search_topic_by_service_name -> 2. get_current_timestamp -> 3. search_log(query="level:ERROR") |
            | "查看 data-sync-service 的 CPU" | 直接 query_cpu_metrics(service_name="data-sync-service") |
            | "最近有什么错误日志？" | 1. search_topic_by_service_name -> 2. get_current_timestamp -> 3. search_log(query="level:ERROR") |
            | "帮我查一下内存使用情况" | 直接 query_memory_metrics(service_name="data-sync-service") |
            | "data-sync-service 的日志主题是什么？" | search_topic_by_service_name(service_name="data-sync-service", fuzzy=True) |
            | "北京地区有哪些日志主题？" | get_region_code_by_name("北京") -> search_topic_by_service_name |

            ## 常见错误及避免方法

            1. **错误**: 直接传入自己编造的 topic_id（如 "topic-1234567890"）
               **正确**: 必须先用 search_topic_by_service_name 查询真实的 topic_id

            2. **错误**: 使用不存在的工具名（如 query_logs、TextToSearchLogQuery）
               **正确**: 只使用系统提供的工具清单中列出的精确名称

            3. **错误**: 跳过知识检索直接回答运维问题
               **正确**: 当用户询问运维操作建议时，先用 retrieve_knowledge 检索相关经验文档

            4. **错误**: 工具调用失败后放弃
               **正确**: 分析失败原因，尝试替代方案（如换个服务名重新搜索 topic）

            ## 回答风格要求（极其重要！必须严格遵守！）

            ### 禁止事项
            1. **禁止暴露思考过程**: 不要在回答中出现"我需要先..."、"接下来我将..."、"让我来..."等内心独白
            2. **禁止展示步骤编号**: 不要出现"步骤1/2/3"、"第一步...第二步..."等中间步骤罗列
            3. **禁止预告工具调用**: 不要说"我将使用XX工具查询"、"让我调用XX接口"等预告
            4. **禁止边想边说**: 不要在调用工具的同时输出思考过程，所有工具调用在后台静默完成

            ### 正确做法
            1. **静默执行**: 所有工具调用在内部完成，用户不需要知道调用了哪些工具
            2. **只输出最终答案**: 等所有工具调用完成后，一次性给出结构清晰、内容完整的最终回答
            3. **直接呈现结果**: 用表格、列表等形式直接展示数据，不要附赠"怎么查的"说明
            4. **失败时简洁说明**: 工具失败时直接告知结果和建议，不要叙述失败过程

            ### 对比示例

            错误示范（绝对禁止）：
            "为了查询日志，我需要先获取 topic ID。让我使用 search_topic_by_service_name...
            好的，已获取 topic_id。现在获取时间戳... 步骤2完成。接下来查询日志..."

            正确示范（必须遵循）：
            "最近15分钟内查到 3 条 ERROR 日志：

            | 时间 | 服务 | 错误信息 |
            |------|------|---------|
            | 10:30 | data-sync | 连接超时 |
            | 10:32 | data-sync | 重试失败 |

            建议优先排查 data-sync-service 的网络连接。"

            ## 其他回答要求
            - 保持友好、专业的语气
            - 回答简洁明了，重点突出
            - 基于工具返回的真实数据，不编造信息
            - 如果工具调用失败，诚实地告知用户失败原因并建议替代方案
            - 如有不确定的地方，明确说明
        """).strip()

        # 如果有工具描述，替换占位符；否则移除占位符行
        if tool_descriptions:
            return base_prompt.replace("{tool_section}", tool_descriptions)
        else:
            return base_prompt.replace("{tool_section}", "")

    def _extract_tool_descriptions(self, tools: list) -> str:
        """从工具列表中提取名称和描述的摘要

        Args:
            tools: 工具对象列表

        Returns:
            str: 格式化的工具描述
        """
        from textwrap import dedent

        descriptions = []
        for tool in tools:
            name = getattr(tool, "name", str(tool))
            desc = getattr(tool, "description", "")
            if desc:
                # 取描述的前120个字符作为摘要
                short_desc = desc[:120].replace("\n", " ").strip()
                descriptions.append(f"  - **`{name}`**: {short_desc}")
            else:
                descriptions.append(f"  - **`{name}`**")

        if descriptions:
            joined = "\n".join(descriptions)
            return dedent(f"""
                ## 可用工具清单

                {joined}

                以上是你可以使用的所有工具。请严格遵守工具名称和参数要求。
            """).strip()
        return ""

    async def query(
        self,
        question: str,
        session_id: str,
    ) -> str:
        """
        非流式处理用户问题（一次性返回完整答案）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Returns:
            str: 完整答案
        """
        try:
            await self._initialize_agent()

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（非流式）: {question}")

            # 构建消息列表（系统提示 + 用户问题）
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            result = await self.agent.ainvoke(
                input=agent_input,
                config=config_dict,
            )

            # 提取最终答案
            messages_result = result.get("messages", [])
            if messages_result:
                last_message = messages_result[-1]
                answer = last_message.content if hasattr(last_message, 'content') else str(last_message)

                # 记录工具调用
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    tool_names = [tc.get("name", "unknown") for tc in last_message.tool_calls]
                    logger.info(f"[会话 {session_id}] Agent 调用了工具: {tool_names}")

                logger.info(f"[会话 {session_id}] RAG Agent 查询完成（非流式）")
                return answer

            logger.warning(f"[会话 {session_id}] Agent 返回结果为空")
            return "抱歉，我无法处理您的请求。请稍后重试。"

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（非流式）: {e}")
            return f"抱歉，处理请求时出现错误: {str(e)}"

    async def query_stream(
        self,
        question: str,
        session_id: str,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        流式处理用户问题（逐步返回答案片段）

        Args:
            question: 用户问题
            session_id: 会话ID（作为 thread_id）

        Yields:
            Dict[str, Any]: 包含流式数据的字典
                - type: "content" | "tool_call" | "tool_result" | "search_results" | "complete" | "error"
                - data: 具体内容
        """
        try:
            await self._initialize_agent()

            logger.info(f"[会话 {session_id}] RAG Agent 收到查询（流式）: {question}")

            # 构建消息列表（系统提示 + 用户问题）
            messages = [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=question)
            ]

            # 构建 Agent 输入
            agent_input = {"messages": messages}

            # 配置 thread_id（用于会话持久化）
            config_dict = {
                "configurable": {
                    "thread_id": session_id
                }
            }

            has_error = False
            error_messages: list[str] = []

            async for token, metadata in self.agent.astream(
                input=agent_input,
                config=config_dict,
                stream_mode="messages",
            ):
                node_name = metadata.get('langgraph_node', 'unknown') if isinstance(metadata, dict) else 'unknown'
                message_type = type(token).__name__

                if message_type in ("AIMessage", "AIMessageChunk"):
                    content_blocks = getattr(token, 'content_blocks', None)

                    if content_blocks and isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get('type') == 'text':
                                text_content = block.get('text', '')
                                if text_content:
                                    yield {
                                        "type": "content",
                                        "data": text_content,
                                        "node": node_name
                                    }
                            elif isinstance(block, dict) and block.get('type') == 'tool_use':
                                # 工具调用请求块（某些模型使用 content_blocks 传递 tool_use）
                                tool_name = block.get('name', 'unknown')
                                tool_input = block.get('input', {})
                                logger.info(f"[会话 {session_id}] 工具调用: {tool_name}")
                                yield {
                                    "type": "tool_call",
                                    "data": {
                                        "tool": tool_name,
                                        "status": "start",
                                        "input": tool_input
                                    },
                                    "node": node_name
                                }

                    # 检查是否包含 tool_calls（传统方式）
                    if hasattr(token, 'tool_calls') and token.tool_calls:
                        for tc in token.tool_calls:
                            tool_name = tc.get("name", "unknown")
                            tool_args = tc.get("args", {})
                            logger.info(f"[会话 {session_id}] 工具调用: {tool_name}")
                            yield {
                                "type": "tool_call",
                                "data": {
                                    "tool": tool_name,
                                    "status": "start",
                                    "input": tool_args
                                },
                                "node": node_name
                            }

                elif message_type == "ToolMessage":
                    # 工具调用结果
                    tool_name = getattr(token, 'name', 'unknown')
                    tool_content = getattr(token, 'content', '')
                    is_error = getattr(token, 'status', '') == 'error' if hasattr(token, 'status') else False

                    logger.info(f"[会话 {session_id}] 工具结果: {tool_name}, is_error={is_error}")

                    if is_error:
                        error_messages.append(f"工具 `{tool_name}` 调用失败: {tool_content[:200]}")
                        has_error = True

                    yield {
                        "type": "tool_result",
                        "data": {
                            "tool": tool_name,
                            "status": "error" if is_error else "success",
                            "content_preview": str(tool_content)[:300] if tool_content else ""
                        },
                        "node": node_name
                    }

            # 如果有工具错误，在完成前发送警告
            if has_error and error_messages:
                logger.warning(f"[会话 {session_id}] 部分工具调用失败: {error_messages}")
                yield {
                    "type": "warning",
                    "data": {
                        "message": "部分工具调用出现问题",
                        "details": error_messages
                    }
                }

            logger.info(f"[会话 {session_id}] RAG Agent 查询完成（流式）")
            yield {"type": "complete"}

        except Exception as e:
            logger.error(f"[会话 {session_id}] RAG Agent 查询失败（流式）: {e}")
            yield {
                "type": "error",
                "data": str(e)
            }

    def get_session_history(self, session_id: str) -> list:
        """
        获取会话历史（从 MemorySaver checkpointer 中读取）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            list: 消息历史列表 [{"role": "user|assistant", "content": "...", "timestamp": "..."}]
        """
        try:
            # 使用 checkpointer 的 get 方法获取最新的检查点
            config = {"configurable": {"thread_id": session_id}}

            # 获取该 thread 的最新检查点
            checkpoint_tuple = self.checkpointer.get(config)

            if not checkpoint_tuple:
                logger.info(f"获取会话历史: {session_id}, 消息数量: 0")
                return []

            # checkpoint_tuple 可能是命名元组或普通元组，安全地提取 checkpoint
            # 通常第一个元素是 checkpoint 数据
            if hasattr(checkpoint_tuple, 'checkpoint'):
                checkpoint_data = checkpoint_tuple.checkpoint  # type: ignore
            else:
                # 如果是普通元组，第一个元素是 checkpoint
                checkpoint_data = checkpoint_tuple[0] if checkpoint_tuple else {}

            # 从检查点中提取消息
            messages = checkpoint_data.get("channel_values", {}).get("messages", [])

            # 转换为前端需要的格式
            history = []
            for msg in messages:
                # 跳过系统消息
                if isinstance(msg, SystemMessage):
                    continue

                role = "user" if isinstance(msg, HumanMessage) else "assistant"
                content = msg.content if hasattr(msg, 'content') else str(msg)

                # 提取时间戳（如果有的话）
                timestamp = getattr(msg, 'timestamp', None)
                if timestamp:
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": timestamp
                    })
                else:
                    from datetime import datetime
                    history.append({
                        "role": role,
                        "content": content,
                        "timestamp": datetime.now().isoformat()
                    })

            logger.info(f"获取会话历史: {session_id}, 消息数量: {len(history)}")
            return history

        except Exception as e:
            logger.error(f"获取会话历史失败: {session_id}, 错误: {e}")
            return []

    def clear_session(self, session_id: str) -> bool:
        """
        清空会话历史（从 MemorySaver checkpointer 中删除）

        Args:
            session_id: 会话ID（即 thread_id）

        Returns:
            bool: 是否成功
        """
        try:
            # 使用 checkpointer 的 delete_thread 方法删除该 thread 的所有检查点
            self.checkpointer.delete_thread(session_id)

            logger.info(f"已清除会话历史: {session_id}")
            return True

        except Exception as e:
            logger.error(f"清空会话历史失败: {session_id}, 错误: {e}")
            return False

    async def cleanup(self):
        """清理资源"""
        try:
            logger.info("清理 RAG Agent 服务资源...")
            # MCP 客户端由全局管理器统一管理，无需手动清理
            logger.info("RAG Agent 服务资源已清理")
        except Exception as e:
            logger.error(f"清理资源失败: {e}")


# 全局单例 - 启用流式输出
rag_agent_service = RagAgentService(streaming=True)
