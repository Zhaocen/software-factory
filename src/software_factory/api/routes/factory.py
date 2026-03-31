from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from software_factory.api.schemas import ClarifyRequest, StartRequest, StartResponse
from software_factory.api.sse import sse_manager
from software_factory.config.settings import get_settings
from software_factory.db.config_service import RuntimeConfig
from software_factory.db.database import get_session
from software_factory.db.models import Project, ProjectLog
from software_factory.orchestrator.graph import build_factory_graph
from software_factory.state.factory_state import FactoryStage, FactoryState
from software_factory.tools.filesystem import ensure_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/factory", tags=["factory"])

_graph = None
# session_id -> {config, project_id, workspace_path}
_session_configs: dict[str, dict] = {}

# 阶段顺序与显示名
STAGE_NAMES = {
    "requirements_agent": "需求分析",
    "architecture_agent": "架构设计",
    "uiux_agent": "UI/UX 设计",
    "coding_agent": "代码生成",
    "testing_agent": "自动测试",
    "devops_agent": "DevOps 配置",
}
STAGE_ORDER = [
    "requirements_agent", "architecture_agent", "uiux_agent",
    "coding_agent", "testing_agent", "devops_agent",
]
INITIAL_STAGES = {
    s: {"status": "pending", "name": STAGE_NAMES[s]} for s in STAGE_ORDER
}


def _get_graph():
    global _graph
    if _graph is None:
        _graph = build_factory_graph(get_settings())
    return _graph


# ---- DB 工具函数 ----

async def _db_save_project(project: Project) -> None:
    async with get_session() as session:
        merged = await session.merge(project)
        await session.flush()


async def _db_update_project(project_id: str, **kwargs) -> None:
    async with get_session() as session:
        p = await session.get(Project, project_id)
        if p:
            for k, v in kwargs.items():
                if k == "stages":
                    p.stages = v
                else:
                    setattr(p, k, v)
            p.updated_at = datetime.now()


async def _db_update_stage(project_id: str, stage_key: str, stage_data: dict) -> None:
    async with get_session() as session:
        p = await session.get(Project, project_id)
        if p:
            stages = p.stages
            stages[stage_key] = {**stages.get(stage_key, {}), **stage_data}
            p.stages = stages
            p.updated_at = datetime.now()


async def _db_append_log(project_id: str, log_type: str, message: str, extra: dict | None = None) -> None:
    async with get_session() as session:
        log = ProjectLog(
            project_id=project_id,
            log_type=log_type,
            message=message,
            ts=datetime.now(),
            extra_json=json.dumps(extra, ensure_ascii=False) if extra else None,
        )
        session.add(log)


# ---- API 路由 ----

@router.post("/start", response_model=StartResponse)
async def start_factory(request: StartRequest, background: BackgroundTasks):
    """启动 AI 软件工厂流程"""
    session_id = str(uuid.uuid4())
    project_id = f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:6]}"
    settings = get_settings()

    # 解析 workspace_path
    rc = RuntimeConfig.get()
    output_base_dir = rc.output_base_dir or settings.output_base_dir
    if request.workspace_path:
        workspace = os.path.abspath(request.workspace_path)
    else:
        workspace = os.path.abspath(
            os.path.join(output_base_dir, project_id)
        )

    await ensure_dir(workspace)

    # 创建项目记录
    project = Project(
        id=project_id,
        name=project_id,
        description=request.description,
        status="building",
        progress=0,
        current_stage="init",
        workspace_path=workspace,
        session_id=session_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    project.stages = dict(INITIAL_STAGES)
    await _db_save_project(project)
    await _db_append_log(project_id, "system", "工厂已启动", {"description": request.description[:200]})

    initial_state: FactoryState = {
        "session_id": session_id,
        "project_id": project_id,
        "messages": [HumanMessage(content=request.description)],
        "current_stage": FactoryStage.INIT,
        "stage_history": [],
        "user_input": request.description,
        "clarification_rounds": 0,
        "requirements": None,
        "architecture": None,
        "ui_ux": None,
        "coding": None,
        "testing": None,
        "devops": None,
        "error": None,
        "retry_count": 0,
        "max_retries": rc.max_retries,
        "fix_context": None,
        "output_dir": workspace,
        "progress_events": [],
    }

    config = {"configurable": {"thread_id": session_id}}
    _session_configs[session_id] = {
        "config": config,
        "project_id": project_id,
        "workspace_path": workspace,
    }

    background.add_task(_run_graph, session_id, initial_state, config, project_id, workspace)
    logger.info("Factory started: session=%s project=%s workspace=%s", session_id, project_id, workspace)

    return StartResponse(
        session_id=session_id,
        project_id=project_id,
        workspace_path=workspace,
    )


@router.get("/stream/{session_id}")
async def stream_progress(session_id: str):
    """SSE 实时进度流"""
    return StreamingResponse(
        sse_manager.subscribe(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.post("/clarify/{session_id}")
async def provide_clarification(
    session_id: str,
    body: ClarifyRequest,
    background: BackgroundTasks,
):
    """用户提供澄清回答，继续工厂流程"""
    graph = _get_graph()
    info = _session_configs.get(session_id)
    if not info:
        raise HTTPException(status_code=404, detail="Session not found")

    config = info["config"]
    project_id = info["project_id"]

    try:
        await graph.aupdate_state(
            config=config,
            values={"messages": [HumanMessage(content=body.answer)]},
        )
        await _db_append_log(project_id, "clarify", "用户提交澄清回答", {"answer": body.answer[:500]})
        background.add_task(_resume_graph, session_id, config, project_id, info["workspace_path"])
        return {"status": "resumed", "session_id": session_id}
    except Exception as e:
        logger.error("Clarification failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ---- 后台执行 ----

async def _run_graph(
    session_id: str,
    initial_state: FactoryState,
    config: dict,
    project_id: str,
    workspace_path: str,
):
    graph = _get_graph()
    try:
        await sse_manager.publish(session_id, {
            "type": "started",
            "stage": "init",
            "message": "AI 软件工厂已启动，开始分析需求...",
        })

        async for event in graph.astream_events(initial_state, config=config, version="v2"):
            await _handle_graph_event(session_id, event, project_id)

        state = await graph.aget_state(config)
        if state.next and "human_clarify" in state.next:
            logger.info("Graph interrupted for clarification: session=%s", session_id)
        else:
            await _finalize_project(session_id, project_id, state)

    except Exception as e:
        logger.exception("Graph execution error: %s", e)
        await _db_update_project(project_id, status="failed")
        await _db_append_log(project_id, "error", str(e))
        await sse_manager.publish(session_id, {"type": "error", "message": str(e)})


async def _resume_graph(session_id: str, config: dict, project_id: str, workspace_path: str):
    graph = _get_graph()
    try:
        async for event in graph.astream_events(None, config=config, version="v2"):
            await _handle_graph_event(session_id, event, project_id)

        state = await graph.aget_state(config)
        # 与 _run_graph 保持一致：如果图再次被澄清打断，不 finalize，等待用户下一轮回答
        if state.next and "human_clarify" in state.next:
            logger.info("Graph interrupted again for clarification: session=%s", session_id)
        else:
            await _finalize_project(session_id, project_id, state)
    except Exception as e:
        logger.exception("Graph resume error: %s", e)
        await _db_update_project(project_id, status="failed")
        await _db_append_log(project_id, "error", str(e))
        await sse_manager.publish(session_id, {"type": "error", "message": str(e)})


async def _finalize_project(session_id: str, project_id: str, state) -> None:
    """流程完成后，提取项目名并更新 DB"""
    extra_updates = {"status": "completed", "progress": 100, "current_stage": "completed"}
    try:
        vals = state.values if hasattr(state, "values") else {}
        req = vals.get("requirements")
        if req:
            pname = req.get("project_name") if isinstance(req, dict) else getattr(req, "project_name", None)
            if pname:
                extra_updates["name"] = pname
    except Exception:
        pass
    await _db_update_project(project_id, **extra_updates)
    await _db_append_log(project_id, "system", "工厂流程完成")
    await sse_manager.publish(session_id, {"type": "done", "stage": "completed", "message": "软件工厂流程完成！"})


async def _handle_graph_event(session_id: str, event: dict, project_id: str):
    """处理 LangGraph 事件 → SSE + DB"""
    event_name = event.get("event", "")
    event_data = event.get("data", {})

    if event_name == "on_chain_start":
        node_name = event.get("name", "")
        if node_name.endswith("_agent") or node_name == "human_clarify":
            display = STAGE_NAMES.get(node_name, node_name)
            await sse_manager.publish(session_id, {
                "type": "stage_start",
                "stage": node_name,
                "message": f"开始执行：{display}",
            })
            if node_name in STAGE_ORDER:
                idx = STAGE_ORDER.index(node_name)
                progress = int(idx / len(STAGE_ORDER) * 100)
                await _db_update_project(project_id, current_stage=node_name, progress=progress)
                await _db_update_stage(project_id, node_name, {"status": "running"})
                await _db_append_log(project_id, "stage_start", f"开始：{display}")

    elif event_name == "on_chain_end":
        node_name = event.get("name", "")
        if node_name.endswith("_agent"):
            output = event_data.get("output", {})

            # 转发所有 progress_events 到 SSE，并将关键事件写入 DB 日志
            for pe in output.get("progress_events", []):
                await sse_manager.publish(session_id, pe)
                pe_type = pe.get("type", "")
                pe_msg = pe.get("message", "")
                if pe_type in ("file_created", "skills_applied", "test_result",
                               "test_running", "module_complete", "module_failed",
                               "git_commit", "coding_summary"):
                    await _db_append_log(project_id, pe_type, pe_msg, pe)

            has_error = bool(output.get("error"))
            stage_update: dict = {"status": "failed" if has_error else "completed"}

            # 提取 artifact 摘要
            artifact_key = node_name.replace("_agent", "")
            artifact = output.get(artifact_key) or output.get(artifact_key.replace("uiux", "ui_ux"))
            if artifact:
                stage_update["artifact_summary"] = _summarize_artifact(artifact_key, artifact)

            await _db_update_stage(project_id, node_name, stage_update)

            # 发送阶段完成 / 失败的 SSE 事件（前端据此更新节点状态）
            display = STAGE_NAMES.get(node_name, node_name)
            if has_error:
                await sse_manager.publish(session_id, {
                    "type": "stage_error",
                    "stage": node_name,
                    "message": output.get("error", f"阶段失败：{display}"),
                })
            else:
                await sse_manager.publish(session_id, {
                    "type": "stage_complete",
                    "stage": node_name,
                    "message": f"完成：{display}",
                })

            # 需求阶段完成后，更新项目名
            if node_name == "requirements_agent" and not has_error:
                req = output.get("requirements")
                if req:
                    pname = req.get("project_name") if isinstance(req, dict) else getattr(req, "project_name", None)
                    if pname:
                        await _db_update_project(project_id, name=pname)

            await _db_append_log(project_id, "stage_end", f"{'失败' if has_error else '完成'}：{node_name}",
                                  {"error": output.get("error")} if has_error else None)

    elif event_name == "on_chat_model_stream":
        chunk = event_data.get("chunk")
        if chunk and hasattr(chunk, "content") and chunk.content:
            content = chunk.content
            await sse_manager.publish(session_id, {"type": "llm_stream", "content": content})


def _summarize_artifact(stage: str, artifact) -> dict:
    if isinstance(artifact, dict):
        d = artifact
    else:
        try:
            d = artifact.model_dump() if hasattr(artifact, "model_dump") else {}
        except Exception:
            return {}

    if stage == "requirements":
        return {
            "project_name": d.get("project_name", ""),
            "user_stories_count": len(d.get("user_stories", [])),
            "functional_requirements_count": len(d.get("functional_requirements", [])),
        }
    elif stage == "architecture":
        return {
            "tech_stack": d.get("tech_stack", {}),
            "components_count": len(d.get("components", [])),
            "api_endpoints_count": len(d.get("api_endpoints", [])),
        }
    elif stage in ("ui_ux", "uiux"):
        return {
            "pages_count": len(d.get("pages", [])),
            "components_count": len(d.get("components", [])),
        }
    elif stage == "coding":
        return {
            "files_count": len(d.get("files", [])),
            "dependencies": d.get("dependencies", [])[:5],
        }
    elif stage == "testing":
        return {
            "test_cases_count": len(d.get("test_cases", [])),
            "passed": d.get("passed", False),
        }
    elif stage == "devops":
        return {
            "has_dockerfile": bool(d.get("dockerfile")),
            "has_compose": bool(d.get("docker_compose")),
            "has_ci": bool(d.get("ci_config")),
        }
    return {}
