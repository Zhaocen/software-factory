from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import AIMessage
from pydantic import BaseModel as PydanticModel, Field

from software_factory.agents.base import BaseAgent
from software_factory.state.factory_state import (
    CodeFile,
    CodingArtifact,
    FactoryStage,
)
from software_factory.tools.filesystem import write_file

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一名专业的全栈开发工程师。根据需求文档、架构设计和 UI/UX 规范，生成高质量的代码。

代码要求：
1. 代码结构清晰，有必要的注释
2. 遵循所选技术栈的最佳实践
3. 包含基本的错误处理
4. 每次只生成指定模块的代码
5. 对于简单的 Python 脚本项目，直接生成可运行的 .py 文件，不要引入不必要的框架

输出 JSON 格式，包含文件路径和代码内容。"""


class CodeFileOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    path: str = Field(description="相对于项目根目录的文件路径")
    content: str = Field(description="完整的文件内容")
    language: str = Field(default="text", description="编程语言，如 python、javascript、html")
    description: str = Field(default="", description="文件功能描述")


class ModuleOutput(PydanticModel):
    model_config = {"extra": "ignore"}
    files: list[CodeFileOutput] = Field(default_factory=list)
    module_description: str = ""


MODULES = [
    ("项目配置和依赖文件", "生成 requirements.txt/package.json、README.md、.env.example 等配置文件"),
    ("后端核心代码", "生成后端主要业务逻辑和核心 Python/JS 代码，对于 Python CLI 项目直接生成 main.py 和相关模块"),
    ("前端代码", "生成前端页面和交互代码，如果是纯命令行项目则跳过（返回空 files 列表）"),
]


class CodingAgent(BaseAgent):
    agent_name = "coding"
    skill_categories = ["development"]

    async def execute(self, state: dict) -> dict[str, Any]:
        requirements = state["requirements"]
        architecture = state["architecture"]
        ui_ux = state["ui_ux"]
        output_dir = state["output_dir"]

        # 加载相关 Skills
        skills_text, skill_names = await self._load_relevant_skills()

        # 构建完整上下文
        full_context = self._build_context(requirements, architecture, ui_ux)

        all_files: list[CodeFile] = []
        progress_events: list[dict] = []

        # 记录 skills 已应用
        if skill_names:
            progress_events.append({
                "type": "skills_applied",
                "stage": "coding",
                "skills": skill_names,
                "message": f"应用技能参考：{', '.join(skill_names)}",
            })

        from software_factory.tools.json_chain import create_json_chain

        # 分模块生成代码（每个模块最多重试 3 次）
        for module_name, module_desc in MODULES:
            logger.info("Generating module: %s", module_name)
            result = None
            last_error = ""
            raw = None
            for attempt in range(3):
                try:
                    already_paths = [f.path for f in all_files]
                    chain = create_json_chain(self.llm, SYSTEM_PROMPT + skills_text, ModuleOutput)
                    user_msg = (
                        f"项目上下文：\n{full_context}\n\n"
                        f"已生成的文件：{json.dumps(already_paths, ensure_ascii=False)}\n\n"
                        f"当前任务：{module_name}\n"
                        f"任务说明：{module_desc}\n\n"
                        "请生成该模块的所有必要文件。"
                    )
                    raw = await chain.ainvoke({"input": user_msg})
                    # 容错：模型直接返回 files 数组
                    if isinstance(raw, list):
                        raw = {"files": raw}
                    # 容错：模型返回了嵌套包裹 {"output": {...}}
                    if isinstance(raw, dict) and "output" in raw and isinstance(raw["output"], dict):
                        raw = raw["output"]
                    result = ModuleOutput.model_validate(raw)
                    break
                except Exception as e:
                    last_error = str(e)
                    is_retriable = (
                        "connection" in last_error.lower()
                        or "timeout" in last_error.lower()
                        or "429" in last_error
                    )
                    if is_retriable and attempt < 2:
                        import asyncio as _aio
                        wait = 2 ** (attempt + 1)
                        logger.warning(
                            "Module [%s] retriable error, retry in %ds: %s",
                            module_name, wait, last_error[:60],
                        )
                        await _aio.sleep(wait)
                        continue
                    if "validation error" in last_error.lower():
                        logger.warning(
                            "Module [%s] validation failed: %s | raw type=%s raw_keys=%s",
                            module_name, last_error[:200],
                            type(raw).__name__,
                            list(raw.keys()) if isinstance(raw, dict) else "N/A",
                        )
                    else:
                        logger.warning(
                            "Module [%s] generation failed (attempt %d): %s",
                            module_name, attempt + 1, last_error[:200],
                        )
                    break

            if result is None:
                progress_events.append({
                    "type": "module_failed",
                    "stage": "coding",
                    "module": module_name,
                    "message": f"模块生成失败: {module_name} — {last_error[:100]}",
                })
                logger.error("Module [%s] FAILED after retries: %s", module_name, last_error[:300])
                continue

            module_file_count = 0
            for f in result.files:
                code_file = CodeFile(
                    path=f.path,
                    content=f.content,
                    language=f.language,
                    description=f.description,
                )
                all_files.append(code_file)
                await write_file(output_dir, f.path, f.content)
                module_file_count += 1
                logger.info("  Written: %s (%s)", f.path, f.language)
                progress_events.append({
                    "type": "file_created",
                    "stage": "coding",
                    "path": f.path,
                    "language": f.language,
                    "message": f"生成文件: {f.path}",
                })

            progress_events.append({
                "type": "module_complete",
                "stage": "coding",
                "module": module_name,
                "file_count": module_file_count,
                "message": f"模块完成: {module_name}（{module_file_count} 个文件）",
            })
            logger.info("Module [%s] done: %d files", module_name, module_file_count)

        # 依赖信息
        tech_stack = architecture.tech_stack
        deps: dict[str, list[str]] = {}
        if any(kw in str(tech_stack).lower() for kw in ["python", "fastapi", "flask"]):
            deps["python"] = []
        if any(kw in str(tech_stack).lower() for kw in ["node", "react", "vue"]):
            deps["npm"] = []

        artifact = CodingArtifact(
            files=all_files,
            dependencies=deps,
            setup_instructions=[
                f"项目已生成到 {output_dir}",
                "请查看各文件中的注释了解启动方式",
            ],
        )

        progress_events.append({
            "type": "coding_summary",
            "stage": "coding",
            "total_files": len(all_files),
            "message": f"代码生成完成，共 {len(all_files)} 个文件",
        })

        return {
            "current_stage": FactoryStage.TESTING,
            "coding": artifact,
            "stage_history": [FactoryStage.CODING],
            "progress_events": progress_events,
            "messages": [AIMessage(content=f"代码生成完成。共生成 {len(all_files)} 个文件。")],
        }

    def _build_context(self, requirements, architecture, ui_ux) -> str:
        return f"""
项目名称：{requirements.project_name}
项目描述：{requirements.project_description}

功能需求：
{chr(10).join(f'- {r}' for r in requirements.functional_requirements)}

技术栈：{json.dumps(architecture.tech_stack, ensure_ascii=False)}

API 接口：
{chr(10).join(f'- {ep.method} {ep.path}: {ep.description}' for ep in architecture.api_endpoints[:10])}

目录结构：
{architecture.directory_structure}

页面列表：
{chr(10).join(f'- {p.get("name", "")}: {p.get("description", "")}' for p in (ui_ux.pages if ui_ux else [])[:5])}
"""
