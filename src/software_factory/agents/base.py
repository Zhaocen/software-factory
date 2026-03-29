from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from software_factory.config.settings import Settings
    from software_factory.state.factory_state import FactoryState

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """所有 Agent 的基类，统一接口和错误处理"""

    agent_name: str = "base"
    skill_categories: list[str] = []   # 子类设置关联的 skill 分类

    def __init__(self, settings: "Settings"):
        self.settings = settings
        from software_factory.db.config_service import RuntimeConfig
        from software_factory.tools.llm_factory import create_llm_for_agent
        rc = RuntimeConfig.get()
        self.llm = create_llm_for_agent(
            agent_name=self.agent_name,
            settings=settings,
            agents_config=rc.agents_config if rc.agents_config else None,
            llm_providers=rc.llm_providers if rc.llm_providers else None,
            openai_compatible_api_key=settings.openai_compatible_api_key,
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
        )

    async def _load_relevant_skills(self) -> tuple[str, list[str]]:
        """从数据库加载相关 Skills，返回 (格式化文本, skill名列表)"""
        if not self.skill_categories:
            return "", []
        try:
            from software_factory.db.database import get_session
            from software_factory.db.models import Skill
            from sqlalchemy import select
            async with get_session() as session:
                result = await session.execute(
                    select(Skill).where(
                        Skill.category.in_(self.skill_categories),
                        Skill.is_active.is_(True),
                    )
                )
                skills = result.scalars().all()
            if not skills:
                return "", []
            skill_names = [s.name for s in skills]
            lines = ["\n\n## 参考技能库（请遵循以下规范）"]
            for s in skills:
                lines.append(f"\n### {s.name}\n{s.content}")
            logger.info("Agent [%s] loaded skills: %s", self.agent_name, skill_names)
            # 转义花括号，防止 ChatPromptTemplate 把代码示例中的 {var} 当作模板变量
            skills_text = "\n".join(lines).replace("{", "{{").replace("}", "}}")
            return skills_text, skill_names
        except Exception as e:
            logger.warning("Agent [%s] failed to load skills: %s", self.agent_name, e)
            return "", []

    async def __call__(self, state: "FactoryState") -> dict[str, Any]:
        """LangGraph 节点调用接口，遇到限流(429)自动退避重试"""
        logger.info("Agent [%s] starting", self.agent_name)
        max_api_retries = 4
        for attempt in range(max_api_retries):
            try:
                result = await self.execute(state)
                result.setdefault("progress_events", [])
                result["progress_events"] = result["progress_events"] + [{
                    "type": "stage_complete",
                    "stage": self.agent_name,
                    "status": "completed",
                    "message": f"{self.agent_name} 阶段完成",
                }]
                result["error"] = None
                logger.info("Agent [%s] completed", self.agent_name)
                return result
            except Exception as e:
                err_str = str(e)
                is_retriable = (
                    "429" in err_str
                    or "rate" in err_str.lower()
                    or "connection" in err_str.lower()
                    or "timeout" in err_str.lower()
                )
                if is_retriable and attempt < max_api_retries - 1:
                    wait = 2 ** (attempt + 1)  # 2s, 4s
                    logger.warning(
                        "Agent [%s] retriable error, retrying in %ds (attempt %d/%d): %s",
                        self.agent_name, wait, attempt + 1, max_api_retries, err_str[:80],
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.exception("Agent [%s] failed: %s", self.agent_name, e)
                return {
                    "error": err_str,
                    "retry_count": state["retry_count"] + 1,
                    "progress_events": [{
                        "type": "stage_error",
                        "stage": self.agent_name,
                        "status": "error",
                        "message": err_str,
                    }],
                }
        # 不会到达这里，但让类型检查器满意
        return {
            "error": "max retries exceeded",
            "retry_count": state["retry_count"] + 1,
            "progress_events": [],
        }

    @abstractmethod
    async def execute(self, state: "FactoryState") -> dict[str, Any]:
        """子类实现具体的 Agent 逻辑，返回 FactoryState 的更新 dict"""
        ...
