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

    # ── Skill 文本注入（兼容旧有流程，仍保留） ───────────────────────────────────
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

    # ── @tool 工具集获取 ─────────────────────────────────────────────────────────
    def _get_skill_tools(self) -> list:
        """根据 skill_categories 返回对应的 LangChain @tool 工具列表"""
        if not self.skill_categories:
            return []
        from software_factory.tools.skill_tools import get_tools_for_categories
        tools = get_tools_for_categories(self.skill_categories)
        logger.debug(
            "Agent [%s] skill tools: %s",
            self.agent_name,
            [t.name for t in tools],
        )
        return tools

    # ── 带工具调用的 LLM 推理循环（LangGraph ToolNode 驱动）─────────────────────
    async def _run_with_tools(
        self,
        system_prompt: str,
        user_msg: str,
        tools: list,
        max_rounds: int = 5,
    ) -> tuple[list[dict], str]:
        """
        使用 bind_tools + ToolNode 运行 ReAct 推理循环。

        流程：
          1. LLM 绑定工具（bind_tools）
          2. 发送 system + user 消息
          3. 若 LLM 返回 tool_calls → ToolNode 执行 → 结果追加消息 → 继续
          4. 直到无 tool_calls 或达到 max_rounds

        Returns:
            tool_call_logs: 每次工具调用的详细记录（用于 progress_events）
            tool_context:   所有工具结果拼接成的上下文字符串（追加到后续 LLM 提示）
        """
        if not tools:
            return [], ""

        from langchain_core.messages import HumanMessage, SystemMessage
        from langgraph.prebuilt import ToolNode

        try:
            tool_llm = self.llm.bind_tools(tools)
        except Exception as e:
            logger.warning(
                "Agent [%s] bind_tools failed: %s — skipping tool phase", self.agent_name, e
            )
            return [], ""

        tool_executor = ToolNode(tools)
        messages: list = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ]
        tool_call_logs: list[dict] = []

        for round_num in range(max_rounds):
            try:
                response = await tool_llm.ainvoke(messages)
            except Exception as e:
                logger.warning("Agent [%s] tool-LLM call failed (round %d): %s", self.agent_name, round_num, e)
                break

            messages.append(response)

            if not getattr(response, "tool_calls", None):
                logger.debug(
                "Agent [%s] no tool calls in round %d — tool phase done",
                self.agent_name, round_num,
            )
                break

            tool_names = [tc["name"] for tc in response.tool_calls]
            logger.info(
                "Agent [%s] round %d/%d — calling tools: %s",
                self.agent_name, round_num + 1, max_rounds, tool_names,
            )


            # 执行工具调用
            try:
                tool_results = await tool_executor.ainvoke({"messages": messages})
            except Exception as e:
                logger.warning("Agent [%s] ToolNode failed: %s", self.agent_name, e)
                break

            tool_msgs = tool_results.get("messages", [])

            # 记录每次调用
            for tc in response.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                tc_id = tc.get("id", "")
                # 找对应的 ToolMessage
                tm = next(
                    (m for m in tool_msgs if getattr(m, "tool_call_id", None) == tc_id),
                    None,
                )
                result_text = tm.content if tm else ""
                logger.info(
                    "  [SkillTool] %-28s args=%-60s  =>  %s...",
                    tool_name,
                    str(tool_args)[:60],
                    str(result_text)[:80],
                )
                tool_call_logs.append({
                    "tool": tool_name,
                    "args": tool_args,
                    "result": str(result_text)[:500],
                    "round": round_num + 1,
                })

            messages.extend(tool_msgs)

        # 将工具结果拼接为可追加到提示的上下文字符串
        if tool_call_logs:
            parts = ["\n\n## 工具执行结果（以下信息来自实际工具调用，请参考）"]
            for inv in tool_call_logs:
                parts.append(f"\n### 工具: {inv['tool']}")
                if inv["args"]:
                    parts.append(f"参数: {inv['args']}")
                parts.append(f"结果:\n{inv['result']}")
            # 转义花括号，防止 ChatPromptTemplate 把工具输出中的 {var} 当成模板变量
            tool_context = "\n".join(parts).replace("{", "{{").replace("}", "}}")
        else:
            tool_context = ""

        return tool_call_logs, tool_context

    # ── LangGraph 节点调用接口 ───────────────────────────────────────────────────
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
        return {
            "error": "max retries exceeded",
            "retry_count": state["retry_count"] + 1,
            "progress_events": [],
        }

    @abstractmethod
    async def execute(self, state: "FactoryState") -> dict[str, Any]:
        """子类实现具体的 Agent 逻辑，返回 FactoryState 的更新 dict"""
        ...
