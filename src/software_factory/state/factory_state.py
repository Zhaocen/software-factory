from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Artifact 数据模型
# ---------------------------------------------------------------------------

@dataclass
class UserStory:
    id: str
    title: str
    description: str
    acceptance_criteria: list[str]
    priority: Literal["high", "medium", "low"] = "medium"


@dataclass
class RequirementsArtifact:
    """需求分析 Agent 的输出产物"""
    project_name: str
    project_description: str
    user_stories: list[UserStory]
    functional_requirements: list[str]
    non_functional_requirements: list[str]
    tech_constraints: list[str]
    out_of_scope: list[str]
    raw_text: str = ""


@dataclass
class APIEndpoint:
    method: str
    path: str
    description: str
    request_body: dict[str, Any] | list | None = None
    response_body: dict[str, Any] | list | None = None


@dataclass
class ArchitectureArtifact:
    """架构设计 Agent 的输出产物"""
    tech_stack: dict[str, str]
    system_components: list[str]
    api_endpoints: list[APIEndpoint]
    data_models: dict[str, Any]
    directory_structure: str
    raw_text: str = ""


@dataclass
class UIComponent:
    name: str
    page: str
    description: str
    interactions: list[str]


@dataclass
class UIUXArtifact:
    """UI/UX 设计 Agent 的输出产物"""
    pages: list[dict[str, str]]
    components: list[UIComponent]
    user_flows: list[str]
    design_tokens: dict[str, str]
    raw_text: str = ""


@dataclass
class CodeFile:
    path: str
    content: str
    language: str
    description: str = ""


@dataclass
class CodingArtifact:
    """编码 Agent 的输出产物"""
    files: list[CodeFile]
    dependencies: dict[str, list[str]]
    setup_instructions: list[str]
    raw_text: str = ""


@dataclass
class TestCase:
    id: str
    name: str
    test_type: Literal["unit", "integration", "e2e"]
    file_path: str
    content: str


@dataclass
class TestResult:
    passed: bool
    total: int
    failed: int
    output: str
    errors: list[str] = field(default_factory=list)


@dataclass
class TestingArtifact:
    """测试 Agent 的输出产物"""
    test_cases: list[TestCase]
    test_results: TestResult | None
    coverage_report: str | None
    raw_text: str = ""


@dataclass
class DevOpsArtifact:
    """DevOps Agent 的输出产物"""
    dockerfile: str
    docker_compose: str
    ci_config: str
    env_example: str
    deployment_notes: str
    raw_text: str = ""


# ---------------------------------------------------------------------------
# 阶段常量
# ---------------------------------------------------------------------------

class FactoryStage:
    INIT = "init"
    CLARIFYING = "clarifying"
    REQUIREMENTS = "requirements"
    ARCHITECTURE = "architecture"
    UI_UX = "ui_ux"
    CODING = "coding"
    TESTING = "testing"
    DEVOPS = "devops"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# 主 State 定义（TypedDict，兼容 LangGraph StateGraph）
# ---------------------------------------------------------------------------

class FactoryState(TypedDict):
    """AI 软件工厂的全局状态"""

    # 会话标识
    session_id: str
    project_id: str

    # 消息历史（内置 add_messages reducer，支持增量追加）
    messages: Annotated[list[BaseMessage], add_messages]

    # 当前阶段
    current_stage: str
    stage_history: Annotated[list[str], operator.add]

    # 用户原始需求
    user_input: str
    clarification_rounds: int

    # 各阶段产物
    requirements: RequirementsArtifact | None
    architecture: ArchitectureArtifact | None
    ui_ux: UIUXArtifact | None
    coding: CodingArtifact | None
    testing: TestingArtifact | None
    devops: DevOpsArtifact | None

    # 错误与重试控制
    error: str | None
    retry_count: int
    max_retries: int

    # 反思修复上下文：测试失败时由 TestingAgent 填入，CodingAgent 据此做针对性修复
    # 结构：{"error_output": str, "failed_files": [{"path": str, "content": str}]}
    fix_context: dict | None

    # 输出目录
    output_dir: str

    # 进度事件（SSE 推送，追加语义）
    progress_events: Annotated[list[dict], operator.add]
