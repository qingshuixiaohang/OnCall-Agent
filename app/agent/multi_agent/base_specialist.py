"""Specialist Agent 基类

设计决策：
1. 抽象基类确保所有 Specialist 都有统一的 run() 接口
2. 通用 LLM 创建逻辑集中在基类，避免重复
3. 子类只需实现 _execute()，关注各自的核心逻辑
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
from langchain_qwq import ChatQwen
from loguru import logger

from app.config import config
from app.agent.multi_agent.state import MultiAgentState


class BaseSpecialist(ABC):
    """Specialist Agent 抽象基类"""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.llm = self._create_llm()

    def _create_llm(self) -> ChatQwen:
        """从配置创建 LLM 实例，保持与现有代码一致"""
        return ChatQwen(
            model=config.rag_model,
            api_key=config.dashscope_api_key,
            temperature=0,
        )

    @abstractmethod
    async def _execute(self, state: MultiAgentState) -> Dict[str, Any]:
        """子类必须实现： Specialist 的核心执行逻辑"""
        ...

    async def run(self, state: MultiAgentState) -> Dict[str, Any]:
        """
        执行 Specialist 的完整流程
        
        统一包装执行逻辑，记录日志并处理异常，
        确保每个 Specialist 失败时不会拖垮整个系统。
        """
        logger.info(f"=== {self.name} 开始执行 ===")

        try:
            result = await self._execute(state)
            result.setdefault("specialist_name", self.name)
            result.setdefault("status", "success")
            logger.info(f"=== {self.name} 执行完成 ===")
            return result

        except Exception as e:
            logger.error(f"{self.name} 执行失败: {e}", exc_info=True)
            return {
                "specialist_name": self.name,
                "status": "error",
                "error": str(e),
            }