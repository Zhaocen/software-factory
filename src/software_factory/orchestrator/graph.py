from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from software_factory.agents.architecture import ArchitectureAgent
from software_factory.agents.coding import CodingAgent
from software_factory.agents.devops import DevOpsAgent
from software_factory.agents.requirements import RequirementsAgent
from software_factory.agents.testing import TestingAgent
from software_factory.agents.ui_ux import UIUXAgent
from software_factory.state.factory_state import FactoryStage, FactoryState
from software_factory.tools.docker_executor import DockerExecutor

if TYPE_CHECKING:
    from software_factory.config.settings import Settings

logger = logging.getLogger(__name__)


def _human_clarify_node(state: FactoryState) -> dict:
    """
    等待用户输入的节点。
    实际执行时通过 interrupt_before 暂停，用户通过 /clarify API 提供输入后继续。
    此函数在恢复执行时被调用，将消息中的最新用户输入追加到 user_input。
    """
    messages = state.get("messages", [])
    # 找到最新的 HumanMessage 作为澄清回复
    latest_human = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human = msg.content
            break

    # 将澄清内容追加到原始需求中
    updated_input = state["user_input"]
    if latest_human:
        updated_input = f"{state['user_input']}\n\n用户补充说明：{latest_human}"

    return {
        "user_input": updated_input,
        "current_stage": FactoryStage.REQUIREMENTS,
    }


def _has_error(state: FactoryState) -> bool:
    """agent 返回了 error（无论重试次数）"""
    return bool(state.get("error"))


def _route_after_requirements(state: FactoryState) -> str:
    """需求分析后的路由"""
    if _has_error(state):
        return FactoryStage.FAILED

    # 澄清路径下 requirements 尚未生成，必须先检查是否需要澄清
    current = state.get("current_stage", FactoryStage.ARCHITECTURE)
    if current == FactoryStage.CLARIFYING:
        return "clarify"

    if state.get("requirements") is None:
        return FactoryStage.FAILED

    return "continue"


def _route_after_testing(state: FactoryState) -> str:
    """测试后的路由：通过则继续，失败则回退编码"""
    if _has_error(state) and state.get("current_stage") != FactoryStage.CODING:
        return FactoryStage.FAILED

    # testing agent 设置了 current_stage = CODING 表示需要回退重试
    if state.get("current_stage") == FactoryStage.CODING:
        return "retry_coding"

    return "continue"


def _route_generic(state: FactoryState) -> str:
    """通用路由：有 error 即失败"""
    if _has_error(state):
        return FactoryStage.FAILED
    return "continue"


def build_factory_graph(settings: "Settings"):
    """构建并编译 AI 软件工厂的 LangGraph 状态图"""

    # 实例化工具
    docker_executor = DockerExecutor(settings)

    # 实例化所有 Agent
    requirements_agent = RequirementsAgent(settings)
    architecture_agent = ArchitectureAgent(settings)
    uiux_agent = UIUXAgent(settings)
    coding_agent = CodingAgent(settings)
    testing_agent = TestingAgent(settings, docker_executor=docker_executor)
    devops_agent = DevOpsAgent(settings)

    checkpointer = MemorySaver()
    builder = StateGraph(FactoryState)

    # --- 添加节点 ---
    builder.add_node("requirements_agent", requirements_agent)
    builder.add_node("architecture_agent", architecture_agent)
    builder.add_node("uiux_agent", uiux_agent)
    builder.add_node("coding_agent", coding_agent)
    builder.add_node("testing_agent", testing_agent)
    builder.add_node("devops_agent", devops_agent)
    builder.add_node("human_clarify", _human_clarify_node)

    # --- 入口 ---
    builder.set_entry_point("requirements_agent")

    # --- 需求分析后路由 ---
    builder.add_conditional_edges(
        "requirements_agent",
        _route_after_requirements,
        {
            "clarify": "human_clarify",
            "continue": "architecture_agent",
            FactoryStage.FAILED: END,
        },
    )

    # 澄清后重新分析需求
    builder.add_edge("human_clarify", "requirements_agent")

    # 架构 → UI/UX（含失败检查）
    builder.add_conditional_edges(
        "architecture_agent",
        _route_generic,
        {"continue": "uiux_agent", FactoryStage.FAILED: END},
    )

    # UI/UX → 编码
    builder.add_conditional_edges(
        "uiux_agent",
        _route_generic,
        {"continue": "coding_agent", FactoryStage.FAILED: END},
    )

    # 编码 → 测试
    builder.add_conditional_edges(
        "coding_agent",
        _route_generic,
        {"continue": "testing_agent", FactoryStage.FAILED: END},
    )

    # 测试后路由（可回退）
    builder.add_conditional_edges(
        "testing_agent",
        _route_after_testing,
        {
            "continue": "devops_agent",
            "retry_coding": "coding_agent",
            FactoryStage.FAILED: END,
        },
    )

    # DevOps → 结束
    builder.add_edge("devops_agent", END)

    # interrupt_before human_clarify，等待用户输入
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_clarify"],
    )
