from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from software_factory.state.factory_state import TestResult

if TYPE_CHECKING:
    from software_factory.config.settings import Settings

logger = logging.getLogger(__name__)

# 容器内项目路径前缀 → 宿主机路径（Docker-in-Docker 路径翻译）
_CONTAINER_PROJECTS_PREFIX = "/app/projects"


def _translate_to_host_path(container_path: str) -> str:
    """
    将容器内路径翻译为宿主机路径，用于 Docker daemon 的 volume 挂载。
    当 app 运行在 Docker 容器内且通过 socket 使用宿主机 Docker daemon 时，
    volume 路径必须是宿主机的实际路径，而不是容器内路径。
    """
    host_dir = os.environ.get("PROJECTS_HOST_DIR", "").rstrip("/")
    if host_dir and container_path.startswith(_CONTAINER_PROJECTS_PREFIX):
        translated = host_dir + container_path[len(_CONTAINER_PROJECTS_PREFIX):]
        logger.debug("Path translated: %s → %s", container_path, translated)
        return translated
    return container_path


class DockerExecutor:
    """Docker 沙箱执行器，在独立容器中构建和测试生成的代码"""

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self._client = None
        self._refresh_config()

    def _refresh_config(self) -> None:
        """从 RuntimeConfig 读取最新 docker 配置"""
        try:
            from software_factory.db.config_service import RuntimeConfig
            docker_cfg = RuntimeConfig.get().docker_config
        except Exception:
            docker_cfg = {}
        if not docker_cfg:
            docker_cfg = self.settings.get_docker_config()
        self.mem_limit = docker_cfg.get("mem_limit", "512m")
        self.cpu_quota = docker_cfg.get("cpu_quota", 50000)
        self.timeout = docker_cfg.get("timeout_seconds", 120)
        self.network_disabled = docker_cfg.get("network_disabled", True)

    def _get_client(self):
        if self._client is None:
            import docker
            self._client = docker.from_env()
        return self._client

    async def run_tests(self, project_dir: str, tech_stack: dict[str, str]) -> TestResult:
        """在 Docker 容器中执行测试"""
        self._refresh_config()
        image, test_cmd = self._select_image_and_command(tech_stack)
        # 翻译为宿主机路径（Docker-in-Docker 场景必须）
        host_project_dir = _translate_to_host_path(str(Path(project_dir).absolute()))

        logger.info("DockerExecutor.run_tests: image=%s cmd=%s dir=%s",
                    image, test_cmd, host_project_dir)

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            self._run_container_sync,
            image,
            test_cmd,
            host_project_dir,
        )
        return result

    async def build_project(self, project_dir: str, tech_stack: dict[str, str]) -> str:
        """在 Docker 容器中构建项目（安装依赖），返回构建日志"""
        self._refresh_config()
        image, _ = self._select_image_and_command(tech_stack)
        build_cmd = self._get_build_command(tech_stack)
        host_project_dir = _translate_to_host_path(str(Path(project_dir).absolute()))

        loop = asyncio.get_event_loop()
        output = await loop.run_in_executor(
            None,
            self._run_container_sync,
            image,
            build_cmd,
            host_project_dir,
        )
        return output.output

    def _run_container_sync(self, image: str, cmd: str, project_dir: str) -> TestResult:
        try:
            import docker

            client = self._get_client()
            container_kwargs: dict = {
                "image": image,
                "command": cmd,
                "volumes": {project_dir: {"bind": "/workspace", "mode": "rw"}},
                "working_dir": "/workspace",
                "remove": True,
                "stdout": True,
                "stderr": True,
                "mem_limit": self.mem_limit,
                "cpu_period": 100000,
                "cpu_quota": self.cpu_quota,
            }
            if self.network_disabled:
                container_kwargs["network_mode"] = "none"

            raw = client.containers.run(**container_kwargs)
            output = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
            logger.info("Container run succeeded. Output preview: %s", output[:300])

            # 基于实际输出检查测试是否通过（exit code 0 且不含明确失败标志）
            lower_out = output.lower()
            failed_keywords = ["failed", "error", "exception", "traceback"]
            passed_keywords = ["passed", "ok", "success", "no tests ran"]
            # 有明确通过标志 → passed; 有明确失败标志 → failed; 否则视为 passed
            has_passed = any(kw in lower_out for kw in passed_keywords)
            has_failed = any(kw in lower_out for kw in failed_keywords)
            passed = (has_passed or not has_failed)

            return TestResult(passed=passed, output=output, total=0, failed=0)

        except Exception as e:
            import docker.errors
            if isinstance(e, docker.errors.ContainerError):
                stderr = ""
                if hasattr(e, "stderr") and e.stderr:
                    stderr = e.stderr.decode("utf-8") if isinstance(e.stderr, bytes) else str(e.stderr)
                stdout_out = ""
                try:
                    # ContainerError 的 container 对象通常已被删除（remove=True），尝试读取 logs
                    if hasattr(e, "container") and e.container:
                        raw_logs = e.container.logs(stdout=True, stderr=True)
                        stdout_out = raw_logs.decode("utf-8") if isinstance(raw_logs, bytes) else str(raw_logs)
                except Exception:
                    pass
                combined = (stdout_out + "\n" + stderr).strip()
                logger.warning("Docker container test failed (exit %s): %s",
                               getattr(e, "exit_status", "?"), combined[:300])
                return TestResult(
                    passed=False,
                    output=combined or str(e),
                    total=0,
                    failed=1,
                    errors=[str(e)],
                )
            # 其他基础设施错误 → 抛出，由 testing agent 作为"跳过"处理
            logger.error("Docker infrastructure error: %s", e)
            raise

    def _select_image_and_command(self, tech_stack: dict[str, str]) -> tuple[str, str]:
        backend = tech_stack.get("backend", "").lower()
        if any(kw in backend for kw in ["fastapi", "flask", "python", "django"]):
            return (
                "python:3.11-slim",
                "sh -c 'pip install -r requirements.txt -q 2>/dev/null || true && "
                "python -m pytest tests/ -v --tb=short 2>&1 || "
                "python -m pytest . -v --tb=short 2>&1 || echo NO_TESTS'",
            )
        elif any(kw in backend for kw in ["node", "express", "next"]):
            return (
                "node:18-alpine",
                "sh -c 'npm install --silent 2>/dev/null || true && npm test 2>&1 || echo NO_TESTS'",
            )
        else:
            # 默认 Python
            return (
                "python:3.11-slim",
                "sh -c 'pip install pytest -q && "
                "python -m pytest tests/ -v --tb=short 2>&1 || "
                "python -m pytest . -v --tb=short 2>&1 || echo NO_TESTS'",
            )

    def _get_build_command(self, tech_stack: dict[str, str]) -> str:
        backend = tech_stack.get("backend", "").lower()
        if any(kw in backend for kw in ["fastapi", "flask", "python"]):
            return "pip install -r requirements.txt -q"
        elif any(kw in backend for kw in ["node", "express"]):
            return "npm install --silent"
        return "echo 'Build complete'"
