from __future__ import annotations

import shutil
import subprocess
import sys
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from software_factory.db.config_service import (
    get_full_config,
    get_section,
    load_runtime_config,
    set_full_config,
    set_section,
)
from software_factory.db.database import db_session

router = APIRouter(prefix="/api/config", tags=["config"])


class LLMProviderConfig(BaseModel):
    id: str = ""
    name: str = ""
    provider: str = "openai_compatible"   # anthropic / openai / openai_compatible
    base_url: str = ""
    api_key: str = ""
    models: list[str] = []


class AgentConfig(BaseModel):
    provider_id: str = ""
    model: str = ""
    temperature: float = 0.2
    max_tokens: int = 16384
    # 向下兼容旧格式字段
    provider: str = ""
    base_url: str = ""
    api_key: str = ""


class DockerConfig(BaseModel):
    mem_limit: str = "512m"
    cpu_quota: int = 50000
    timeout_seconds: int = 120
    network_disabled: bool = True


class RetryConfig(BaseModel):
    max_retries: int = 3
    retry_delay: float = 2.0


class OutputConfig(BaseModel):
    base_dir: str = "projects"
    git_init: bool = True


class GitConfig(BaseModel):
    enabled: bool = False
    remote_url: str = ""
    default_branch: str = "main"
    auto_push: bool = False


# ─── 全量配置 ─────────────────────────────────────────────────────────────────

@router.get("/", response_model=dict[str, Any])
async def get_config(session: AsyncSession = Depends(db_session)):
    """获取完整配置"""
    return await get_full_config(session)


@router.put("/")
async def update_config(body: dict[str, Any], session: AsyncSession = Depends(db_session)):
    """全量更新配置"""
    try:
        await set_full_config(session, body)
        await load_runtime_config(session)
        _invalidate_graph_cache()
        return {"status": "ok", "message": "配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Agents ──────────────────────────────────────────────────────────────────

@router.get("/agents", response_model=dict[str, Any])
async def get_agents_config(session: AsyncSession = Depends(db_session)):
    return await get_section(session, "agents")


@router.put("/agents/{agent_name}")
async def update_agent_config(
    agent_name: str,
    body: AgentConfig,
    session: AsyncSession = Depends(db_session),
):
    valid_agents = ["requirements", "architecture", "ui_ux", "coding", "testing", "devops"]
    if agent_name not in valid_agents:
        raise HTTPException(status_code=400, detail=f"无效 Agent 名称，可选：{valid_agents}")
    agents: dict = await get_section(session, "agents") or {}
    agents[agent_name] = body.model_dump()
    await set_section(session, "agents", agents)
    await load_runtime_config(session)
    _invalidate_graph_cache()
    return {"status": "ok", "agent": agent_name}


# ─── Docker ──────────────────────────────────────────────────────────────────

@router.get("/docker", response_model=DockerConfig)
async def get_docker_config(session: AsyncSession = Depends(db_session)):
    data = await get_section(session, "docker") or {}
    return DockerConfig(**data)


@router.put("/docker")
async def update_docker_config(body: DockerConfig, session: AsyncSession = Depends(db_session)):
    await set_section(session, "docker", body.model_dump())
    return {"status": "ok"}


# ─── Git ─────────────────────────────────────────────────────────────────────

@router.get("/git", response_model=GitConfig)
async def get_git_config(session: AsyncSession = Depends(db_session)):
    data = await get_section(session, "git") or {}
    return GitConfig(**data)


@router.put("/git")
async def update_git_config(body: GitConfig, session: AsyncSession = Depends(db_session)):
    await set_section(session, "git", body.model_dump())
    return {"status": "ok"}


# ─── LLM Providers ───────────────────────────────────────────────────────────

@router.get("/llm-providers", response_model=list[dict])
async def list_llm_providers(session: AsyncSession = Depends(db_session)):
    return await get_section(session, "llm_providers") or []


@router.post("/llm-providers", response_model=dict, status_code=201)
async def create_llm_provider(body: LLMProviderConfig, session: AsyncSession = Depends(db_session)):
    providers: list[dict] = await get_section(session, "llm_providers") or []
    new_id = body.id or str(uuid.uuid4())[:8]
    if any(p.get("id") == new_id for p in providers):
        raise HTTPException(status_code=400, detail=f"供应商 ID '{new_id}' 已存在")
    entry = body.model_dump()
    entry["id"] = new_id
    providers.append(entry)
    await set_section(session, "llm_providers", providers)
    await load_runtime_config(session)
    _invalidate_graph_cache()
    return entry


@router.put("/llm-providers/{provider_id}", response_model=dict)
async def update_llm_provider(
    provider_id: str,
    body: LLMProviderConfig,
    session: AsyncSession = Depends(db_session),
):
    providers: list[dict] = await get_section(session, "llm_providers") or []
    for i, p in enumerate(providers):
        if p.get("id") == provider_id:
            entry = body.model_dump()
            entry["id"] = provider_id
            providers[i] = entry
            await set_section(session, "llm_providers", providers)
            await load_runtime_config(session)
            _invalidate_graph_cache()
            return entry
    raise HTTPException(status_code=404, detail="供应商不存在")


@router.delete("/llm-providers/{provider_id}", status_code=204)
async def delete_llm_provider(provider_id: str, session: AsyncSession = Depends(db_session)):
    providers: list[dict] = await get_section(session, "llm_providers") or []
    new_providers = [p for p in providers if p.get("id") != provider_id]
    if len(new_providers) == len(providers):
        raise HTTPException(status_code=404, detail="供应商不存在")
    await set_section(session, "llm_providers", new_providers)
    await load_runtime_config(session)
    _invalidate_graph_cache()


# ─── 连通性测试 & 模型列表获取 ──────────────────────────────────────────────────

class ProviderTestRequest(BaseModel):
    provider: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@router.post("/llm-providers/fetch-models")
async def fetch_provider_models(body: ProviderTestRequest):
    """调用供应商 API 获取可用模型列表"""
    import httpx

    try:
        if body.provider in ("openai", "openai_compatible"):
            base = (body.base_url.rstrip("/") if body.base_url else "https://api.openai.com/v1")
            headers = {"Authorization": f"Bearer {body.api_key or 'EMPTY'}"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(f"{base}/models", headers=headers)
            if resp.status_code != 200:
                return {"ok": False, "models": [], "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            models = sorted(
                [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")],
            )
            return {"ok": True, "models": models}

        elif body.provider == "anthropic":
            headers = {
                "x-api-key": body.api_key or "",
                "anthropic-version": "2023-06-01",
            }
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://api.anthropic.com/v1/models", headers=headers)
            if resp.status_code != 200:
                return {"ok": False, "models": [], "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            return {"ok": True, "models": models}

        else:
            return {"ok": False, "models": [], "error": f"不支持自动获取该供应商类型的模型列表"}

    except Exception as e:
        return {"ok": False, "models": [], "error": str(e)[:200]}


@router.post("/llm-providers/test")
async def test_llm_provider(body: ProviderTestRequest):
    """用当前填写的配置发送一条最小请求，测试供应商连通性"""
    if not body.model:
        raise HTTPException(status_code=400, detail="请填写模型名称")

    t0 = time.time()
    try:
        if body.provider == "anthropic":
            from langchain_anthropic import ChatAnthropic
            llm = ChatAnthropic(
                model=body.model, max_tokens=16,
                api_key=body.api_key or "",
            )
        elif body.provider == "openai":
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=body.model, max_tokens=16,
                api_key=body.api_key or "",
            )
        elif body.provider == "openai_compatible":
            if not body.base_url:
                raise HTTPException(status_code=400, detail="OpenAI 兼容类型需要填写 Base URL")
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI(
                model=body.model, max_tokens=16,
                base_url=body.base_url,
                api_key=body.api_key or "EMPTY",
            )
        else:
            raise HTTPException(status_code=400, detail=f"未知供应商类型: {body.provider}")

        from langchain_core.messages import HumanMessage
        resp = await llm.ainvoke([HumanMessage(content="Say 'ok'")])
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": True,
            "elapsed_ms": elapsed,
            "reply": (resp.content or "")[:80],
        }
    except HTTPException:
        raise
    except Exception as e:
        elapsed = round((time.time() - t0) * 1000)
        return {
            "ok": False,
            "elapsed_ms": elapsed,
            "error": str(e)[:200],
        }


# ─── 辅助端点 ─────────────────────────────────────────────────────────────────

@router.get("/projects-host-dir")
async def get_projects_host_dir():
    """返回宿主机项目目录路径（从环境变量 PROJECTS_HOST_DIR 读取）"""
    import os
    host_dir = os.environ.get("PROJECTS_HOST_DIR", "./projects")
    return {"host_dir": host_dir}


@router.get("/pick-folder")
async def pick_folder():
    """唤起系统原生文件夹选择框，返回所选路径（仅 macOS 本地运行时有效）"""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        raise HTTPException(
            status_code=400,
            detail="仅支持 macOS 本地运行，Docker 模式请手动输入路径",
        )
    try:
        result = subprocess.run(
            ["osascript", "-e", 'POSIX path of (choose folder with prompt "选择项目空间路径")'],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail="用户已取消")
        return {"path": result.stdout.strip()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="选择超时")


# ─── 内部工具 ─────────────────────────────────────────────────────────────────

def _invalidate_graph_cache() -> None:
    """让 factory 重建 graph，下次请求时使用最新配置"""
    try:
        import software_factory.api.routes.factory as _f
        _f._graph = None
    except Exception:
        pass
