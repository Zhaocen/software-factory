from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from software_factory.config.settings import Settings


def create_llm_for_agent(
    agent_name: str,
    settings: "Settings | None" = None,
    *,
    agents_config: dict[str, Any] | None = None,
    llm_providers: list[dict[str, Any]] | None = None,
    openai_compatible_api_key: str = "",
    anthropic_api_key: str = "",
    openai_api_key: str = "",
):
    """为指定 Agent 创建 LLM 实例。

    优先使用直接传入的 agents_config / llm_providers（来自数据库）；
    如果未传入则回退到 settings 对象（兼容旧调用方式）。
    """
    if agents_config is None and settings is not None:
        agents_config = {agent_name: settings.get_agent_model_config(agent_name)}
    if llm_providers is None:
        llm_providers = []

    config = (agents_config or {}).get(agent_name, {})
    if not config:
        config = {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "temperature": 0.2,
            "max_tokens": 4096,
        }

    model = config.get("model", "")
    temperature = config.get("temperature", 0.2)
    max_tokens = config.get("max_tokens", 4096)

    # API keys 优先级：直接传参 > settings 对象
    _anthropic_key = anthropic_api_key or (settings.anthropic_api_key if settings else "")
    _openai_key = openai_api_key or (settings.openai_api_key if settings else "")
    _compat_key = openai_compatible_api_key or (settings.openai_compatible_api_key if settings else "")

    # ---- 解析供应商信息 ----
    provider_id = config.get("provider_id")
    if provider_id:
        # 新格式：从 llm_providers 列表查找
        provider_cfg: dict = {}
        for p in llm_providers:
            if p.get("id") == provider_id:
                provider_cfg = p
                break
        # fallback: 尝试从 RuntimeConfig 查找（防止 llm_providers 未传入）
        if not provider_cfg:
            try:
                from software_factory.db.config_service import RuntimeConfig
                provider_cfg = RuntimeConfig.get().get_llm_provider(provider_id)
            except Exception:
                pass
        if not provider_cfg and settings is not None:
            provider_cfg = settings.get_llm_provider(provider_id)
        if not provider_cfg:
            raise ValueError(
                f"Agent '{agent_name}' 引用了未知的供应商 ID '{provider_id}'，"
                "请在配置页面中添加该供应商。"
            )
        provider = provider_cfg.get("provider", "openai_compatible")
        base_url = provider_cfg.get("base_url", "")
        api_key = provider_cfg.get("api_key") or _compat_key or "EMPTY"
    else:
        # 旧格式：agent 配置中内联供应商信息
        provider = config.get("provider", "anthropic")
        base_url = config.get("base_url", "")
        api_key = config.get("api_key") or _compat_key or "EMPTY"

    if not model:
        raise ValueError(
            f"Agent '{agent_name}' 未配置模型名称（model），请在配置页面中选择模型。"
        )

    # ---- 构建 LLM 实例 ----
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=_anthropic_key,
        )

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=_openai_key,
        )

    if provider == "openai_compatible":
        if not base_url:
            raise ValueError(
                f"Agent '{agent_name}' 使用 openai_compatible 供应商，"
                "但未配置 base_url，请在配置页面补充。"
            )
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            api_key=api_key,
        )

    raise ValueError(
        f"未知的 LLM provider 类型: '{provider}'。"
        "支持的值：anthropic / openai / openai_compatible"
    )
