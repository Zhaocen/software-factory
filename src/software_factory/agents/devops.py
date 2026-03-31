from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    DevOpsArtifact,
    FactoryStage,
)
from software_factory.tools.filesystem import write_file

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一名 DevOps 工程师。根据项目信息，生成容器化和 CI/CD 配置文件。

生成内容：
1. Dockerfile（多阶段构建，优化镜像大小）
2. docker-compose.yml（本地开发环境）
3. GitHub Actions CI 配置（.github/workflows/ci.yml）
4. .env.example（环境变量示例）

输出 JSON 格式。"""


class DevOpsOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    dockerfile: str = Field(default="", description="Dockerfile 内容")
    docker_compose: str = Field(default="", description="docker-compose.yml 内容")
    ci_config: str = Field(default="", description="GitHub Actions CI 配置内容")
    env_example: str = Field(default="", description=".env.example 内容")
    deployment_notes: str = Field(default="", description="部署说明")


class DevOpsAgent(BaseAgent):
    agent_name = "devops"
    skill_categories = ["devops"]

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]
        output_dir = state["output_dir"]

        progress_events: list[dict] = []

        # ── 第一阶段：工具调用 — 获取 Docker 模板 ────────────────────────────────
        tools = self._get_skill_tools()
        tool_call_logs, tool_context = await self._run_with_tools(
            system_prompt=(
                "你是一名 DevOps 工程师，你有一组辅助工具可以使用，"
                "请根据项目情况自行判断是否需要调用工具及调用哪些工具，按需使用即可。"
            ),
            user_msg=(
                f"项目名：{requirements.project_name}\n"
                f"技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}"
            ),
            tools=tools,
            max_rounds=2,
        )

        if tool_call_logs:
            tool_names = list({inv["tool"] for inv in tool_call_logs})
            progress_events.append({
                "type": "skills_applied",
                "stage": "devops",
                "skills": tool_names,
                "message": f"调用 DevOps 规范工具：{', '.join(tool_names)}",
                "tool_calls": tool_call_logs,
            })

        # 加载 Skill 文本（兼容文本注入）
        skills_text, skill_names = await self._load_relevant_skills()
        if skill_names and not tool_call_logs:
            progress_events.append({
                "type": "skills_applied",
                "stage": "devops",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        # ── 第二阶段：LLM 生成 DevOps 配置 ──────────────────────────────────────
        from software_factory.tools.json_chain import create_json_chain

        chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, DevOpsOutput)
        user_msg = (
            f"项目名：{requirements.project_name}\n"
            f"技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}\n"
            f"系统组件：{json.dumps(architecture.system_components[:5], ensure_ascii=False)}"
            + tool_context
            + "\n\n请生成 DevOps 配置文件。"
        )
        raw = await chain.ainvoke({"input": user_msg})
        result = DevOpsOutput.model_validate(raw)

        # 写入 DevOps 文件并记录事件
        devops_files = [
            ("Dockerfile", result.dockerfile),
            ("docker-compose.yml", result.docker_compose),
            (".github/workflows/ci.yml", result.ci_config),
            (".env.example", result.env_example),
            ("DEPLOYMENT.md", result.deployment_notes),
        ]
        for fname, content in devops_files:
            if content:
                await write_file(output_dir, fname, content)
                logger.info("DevOps file written: %s", fname)
                progress_events.append({
                    "type": "file_created",
                    "stage": "devops",
                    "path": fname,
                    "message": f"生成文件: {fname}",
                })

        # ── 第三阶段：@tool 执行 Git 初始化和提交 ────────────────────────────────
        await self._run_git_init(requirements, output_dir, progress_events)

        artifact = DevOpsArtifact(
            dockerfile=result.dockerfile,
            docker_compose=result.docker_compose,
            ci_config=result.ci_config,
            env_example=result.env_example,
            deployment_notes=result.deployment_notes,
        )

        return {
            "current_stage": FactoryStage.COMPLETED,
            "devops": artifact,
            "stage_history": [FactoryStage.DEVOPS],
            "progress_events": progress_events,
            "messages": [AIMessage(content=f"DevOps 配置完成！项目已生成到 {output_dir}")],
        }

    async def _run_git_init(
        self,
        requirements,
        output_dir: str,
        progress_events: list[dict],
    ) -> None:
        """使用 run_git_operation @tool 执行 Git 初始化和提交"""
        try:
            from software_factory.db.config_service import RuntimeConfig
            rc = RuntimeConfig.get()
            git_init = rc.output_config.get("git_init", True)
        except Exception:
            git_init = True

        if not git_init:
            progress_events.append({
                "type": "git_skipped",
                "stage": "devops",
                "message": "Git 初始化已禁用（git_init=false）",
            })
            return

        from software_factory.tools.skill_tools import run_git_operation

        commit_msg = f"feat: initial generated code for {requirements.project_name}"

        # git init
        init_result = run_git_operation.invoke({
            "project_dir": output_dir,
            "operation": "init",
        })
        logger.info("[DevOpsAgent] git init: %s", init_result[:100])
        progress_events.append({
            "type": "git_commit",
            "stage": "devops",
            "tool": "run_git_operation",
            "message": f"git init: {init_result[:80]}",
        })

        # git add -A
        add_result = run_git_operation.invoke({
            "project_dir": output_dir,
            "operation": "add_all",
        })
        logger.info("[DevOpsAgent] git add: %s", add_result[:100])

        # git commit
        commit_result = run_git_operation.invoke({
            "project_dir": output_dir,
            "operation": "commit",
            "commit_message": commit_msg,
        })
        logger.info("[DevOpsAgent] git commit: %s", commit_result[:100])
        progress_events.append({
            "type": "git_commit",
            "stage": "devops",
            "tool": "run_git_operation",
            "message": f"Git 提交完成：{commit_msg}",
        })
