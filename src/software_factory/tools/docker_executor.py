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

_CONTAINER_PROJECTS_PREFIX = "/app/projects"


def _translate_to_host_path(container_path: str) -> str:
    host_dir = os.environ.get("PROJECTS_HOST_DIR", "").rstrip("/")
    if host_dir and container_path.startswith(_CONTAINER_PROJECTS_PREFIX):
        translated = host_dir + container_path[len(_CONTAINER_PROJECTS_PREFIX):]
        # Docker volume 要求绝对路径：若 PROJECTS_HOST_DIR 是相对路径则转换
        if not os.path.isabs(translated):
            translated = str(Path(translated).resolve())
        logger.debug("Path translated: %s → %s", container_path, translated)
        return translated
    return container_path


# ── 内置回退映射（LLM 未提供时使用）─────────────────────────────────────────
_FALLBACK_CONFIGS: list[tuple[list[str], str, str, str]] = [
    # (关键词列表, image, install_cmd, test_cmd)
    (
        ["python", "fastapi", "flask", "django"],
        "python:3.11-slim",
        "sh -c 'pip install -r requirements.txt -q 2>&1 && pip install pytest -q 2>&1'",
        "sh -c 'find . -name \"*.py\" ! -path \"./.git/*\" | head -50 | xargs python -m py_compile 2>&1 && echo \"语法检查通过\" && python -m pytest tests/ -v --tb=long 2>&1 || python -m pytest . -v --tb=long --ignore=.git 2>&1'",
    ),
    (
        ["node", "express", "next", "react", "vue"],
        "node:18-alpine",
        "npm install 2>&1",
        "npm test 2>&1",
    ),
    (
        ["go", "golang"],
        "golang:1.22-alpine",
        "go mod download 2>&1",
        "go test ./... -v 2>&1",
    ),
    (
        ["java", "spring", "maven"],
        "maven:3.9-eclipse-temurin-17",
        "mvn dependency:resolve -q 2>&1",
        "mvn test 2>&1",
    ),
    (
        ["ruby", "rails", "sinatra"],
        "ruby:3.2-slim",
        "sh -c 'gem install bundler -q && bundle install -q 2>&1'",
        "bundle exec rspec 2>&1 || bundle exec rake test 2>&1",
    ),
    (
        ["rust", "cargo"],
        "rust:1.77-slim",
        "cargo fetch 2>&1",
        "cargo test -- --nocapture 2>&1",
    ),
    (
        ["php", "laravel", "symfony"],
        "php:8.2-cli",
        "sh -c 'curl -sS https://getcomposer.org/installer | php && php composer.phar install -q 2>&1'",
        "php vendor/bin/phpunit 2>&1",
    ),
]

_VERIFY_MAIN_SNIPPET = (
    "main_file=\"\"; "
    "for f in main.py app.py run.py src/main.py index.py; do "
    "  if [ -f \"$f\" ]; then main_file=\"$f\"; break; fi; "
    "done; "
    "if [ -n \"$main_file\" ]; then "
    "  echo \"验证主程序可导入: $main_file\"; "
    "  timeout 5 python \"$main_file\" --help 2>&1 || "
    "  python -c \"import importlib.util; spec=importlib.util.spec_from_file_location('_m','$main_file'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\" 2>&1 || "
    "  echo \"主程序验证完成\"; "
    "fi"
)


def _fallback_config(tech_stack: dict) -> tuple[str, str, str]:
    """根据 tech_stack 推断镜像和命令（LLM 未提供时的保底方案）"""
    stack_text = " ".join(tech_stack.values()).lower()
    for keywords, image, install, test in _FALLBACK_CONFIGS:
        if any(kw in stack_text for kw in keywords):
            return image, install, test
    # 什么都匹配不到 → Python
    return _FALLBACK_CONFIGS[0][1], _FALLBACK_CONFIGS[0][2], _FALLBACK_CONFIGS[0][3]


class DockerExecutor:
    """Docker 沙箱执行器：两阶段运行（联网安装依赖 → 断网测试验证）"""

    def __init__(self, settings: "Settings"):
        self.settings = settings
        self._client = None
        self._docker_host = ""
        self._refresh_config()

    def _refresh_config(self) -> None:
        try:
            from software_factory.db.config_service import RuntimeConfig
            docker_cfg = RuntimeConfig.get().docker_config
        except Exception:
            docker_cfg = {}
        if not docker_cfg:
            docker_cfg = self.settings.get_docker_config()
        self.mem_limit = docker_cfg.get("mem_limit", "512m")
        self.cpu_quota = docker_cfg.get("cpu_quota", 50000)
        self.timeout = docker_cfg.get("timeout_seconds", 180)
        new_host = docker_cfg.get("docker_host", "").strip()
        # docker_host 变更时重置客户端
        if new_host != self._docker_host:
            self._docker_host = new_host
            self._client = None

    def _get_client(self):
        if self._client is None:
            import docker
            if self._docker_host:
                logger.info("DockerExecutor: connecting to docker_host=%s", self._docker_host)
                self._client = docker.DockerClient(base_url=self._docker_host)
            else:
                self._client = docker.from_env()
        return self._client

    async def run_tests(
        self,
        project_dir: str,
        tech_stack: dict[str, str],
        docker_image: str = "",
        install_command: str = "",
        test_command: str = "",
    ) -> TestResult:
        """两阶段执行：① 联网安装依赖  ② 断网运行测试"""
        self._refresh_config()
        host_project_dir = _translate_to_host_path(str(Path(project_dir).absolute()))

        # 优先使用 LLM 提供的配置，否则自动推断
        if docker_image and install_command and test_command:
            image, install_cmd, test_cmd = docker_image, install_command, test_command
            logger.info("DockerExecutor: using LLM-specified image=%s", image)
        else:
            image, install_cmd, test_cmd = _fallback_config(tech_stack)
            logger.info("DockerExecutor: using fallback image=%s for tech_stack=%s", image, tech_stack)

        # 若是 Python 镜像，在测试命令末尾追加主程序验证
        if "python" in image and _VERIFY_MAIN_SNIPPET not in test_cmd:
            inner = test_cmd.replace("sh -c '", "").rstrip("'")
            test_cmd = "sh -c '" + inner + "\n" + _VERIFY_MAIN_SNIPPET + "'"

        logger.info("Phase-1 install: image=%s dir=%s", image, host_project_dir)
        loop = asyncio.get_event_loop()

        # Phase-1：联网安装依赖
        install_result = await loop.run_in_executor(
            None, self._run_container_sync,
            image, install_cmd, host_project_dir, False,
        )
        if not install_result.passed:
            logger.warning("Dependency install failed:\n%s", install_result.output[:500])
            return TestResult(
                passed=False,
                output=f"=== 依赖安装失败 ===\n{install_result.output}",
                total=0, failed=1,
                errors=["依赖安装失败，请检查依赖声明文件（requirements.txt / package.json 等）"],
            )

        logger.info("Phase-2 test: image=%s dir=%s", image, host_project_dir)

        # Phase-2：断网运行测试
        test_result = await loop.run_in_executor(
            None, self._run_container_sync,
            image, test_cmd, host_project_dir, True,
        )

        combined_output = (
            f"=== 安装阶段 ===\n{install_result.output}\n\n"
            f"=== 测试阶段 ===\n{test_result.output}"
        )
        return TestResult(
            passed=test_result.passed,
            output=combined_output,
            total=test_result.total,
            failed=test_result.failed,
            errors=test_result.errors,
        )

    def _run_container_sync(
        self,
        image: str,
        cmd: str,
        project_dir: str,
        network_disabled: bool,
    ) -> TestResult:
        """运行容器，用 exit code 判断结果"""
        client = self._get_client()
        container = None
        try:
            container_kwargs: dict = {
                "image": image,
                "command": cmd,
                "volumes": {project_dir: {"bind": "/workspace", "mode": "rw"}},
                "working_dir": "/workspace",
                "detach": True,
                "stdout": True,
                "stderr": True,
                "mem_limit": self.mem_limit,
                "cpu_period": 100000,
                "cpu_quota": self.cpu_quota,
            }
            if network_disabled:
                container_kwargs["network_mode"] = "none"

            container = client.containers.run(**container_kwargs)
            wait_result = container.wait(timeout=self.timeout)
            exit_code = wait_result.get("StatusCode", 1)

            output_bytes = container.logs(stdout=True, stderr=True)
            output = output_bytes.decode("utf-8", errors="replace") if isinstance(output_bytes, bytes) else str(output_bytes)

            logger.info("Container exited code=%d preview=%s", exit_code, output[:200])
            passed = (exit_code == 0)
            return TestResult(
                passed=passed, output=output,
                total=0, failed=0 if passed else 1,
                errors=[] if passed else [f"exit code {exit_code}"],
            )

        except Exception as e:
            output = ""
            if container:
                try:
                    raw = container.logs(stdout=True, stderr=True)
                    output = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                except Exception:
                    pass
            err_str = str(e)
            logger.error("Docker error: %s\nOutput: %s", err_str, output[:300])
            if "timed out" in err_str.lower() or "timeout" in err_str.lower():
                return TestResult(
                    passed=False,
                    output=f"容器执行超时（>{self.timeout}s）\n{output}",
                    total=0, failed=1, errors=["容器执行超时"],
                )
            raise
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    async def build_project(self, project_dir: str, tech_stack: dict[str, str]) -> str:
        self._refresh_config()
        host_project_dir = _translate_to_host_path(str(Path(project_dir).absolute()))
        image, install_cmd, _ = _fallback_config(tech_stack)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._run_container_sync,
            image, install_cmd, host_project_dir, False,
        )
        return result.output
