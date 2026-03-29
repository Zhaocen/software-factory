#!/usr/bin/env python3
"""端到端测试脚本：创建一个简单的 Todo List 应用"""

import asyncio
import json
import sys
import httpx

BASE_URL = "http://localhost:8000"
TEST_DESCRIPTION = """
创建一个简单的 Todo List Web 应用，需求如下：
1. 用户可以添加任务（输入文本后按回车或点击按钮）
2. 任务列表显示所有未完成的任务
3. 可以标记任务为已完成
4. 可以删除任务
5. 使用 Python FastAPI 作为后端，纯 HTML/CSS/JS 作为前端
6. 数据存储在内存中（不需要数据库）
"""


async def test_factory():
    print("=" * 60)
    print("AI 软件工厂 - 端到端测试")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. 健康检查
        try:
            resp = await client.get(f"{BASE_URL}/api/projects/")
            print(f"✓ 服务运行正常 (状态码: {resp.status_code})")
        except Exception as e:
            print(f"✗ 服务连接失败: {e}")
            print("  请先启动服务: bash scripts/start.sh")
            sys.exit(1)

        # 2. 启动工厂
        print("\n📤 提交需求...")
        resp = await client.post(
            f"{BASE_URL}/api/factory/start",
            json={"description": TEST_DESCRIPTION},
        )
        if resp.status_code != 200:
            print(f"✗ 启动失败: {resp.text}")
            sys.exit(1)

        data = resp.json()
        session_id = data["session_id"]
        project_id = data["project_id"]
        print(f"✓ 工厂已启动")
        print(f"  Session ID: {session_id}")
        print(f"  Project ID: {project_id}")

        # 3. 订阅 SSE 进度流
        print("\n📡 订阅实时进度流...")
        print("-" * 40)

        current_stage = None
        done = False

        async with client.stream("GET", f"{BASE_URL}/api/factory/stream/{session_id}") as stream:
            async for line in stream.aiter_lines():
                if not line:
                    continue

                if line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    try:
                        event_data = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue

                    if event_type == "heartbeat":
                        print(".", end="", flush=True)
                        continue

                    stage = event_data.get("stage", "")
                    message = event_data.get("message", "")

                    if event_type == "stage_start":
                        print(f"\n▶ [{stage}] {message}")
                        current_stage = stage

                    elif event_type == "stage_complete":
                        print(f"✓ [{stage}] 完成")

                    elif event_type == "stage_error":
                        print(f"✗ [{stage}] 错误: {message}")

                    elif event_type == "clarify_needed":
                        print(f"\n💬 需要澄清: {message}")
                        # 自动回答（测试模式）
                        answer = "请按照最简单的方式实现即可，不需要用户认证"
                        print(f"   自动回答: {answer}")
                        await client.post(
                            f"{BASE_URL}/api/factory/clarify/{session_id}",
                            json={"answer": answer},
                        )

                    elif event_type == "llm_stream":
                        print(event_data.get("content", ""), end="", flush=True)

                    elif event_type == "done":
                        print(f"\n\n✅ {message}")
                        done = True
                        break

                    elif event_type == "error":
                        print(f"\n\n✗ 错误: {message}")
                        sys.exit(1)

        # 4. 查看生成文件
        print("\n" + "-" * 40)
        print("📁 查看生成的文件...")
        resp = await client.get(f"{BASE_URL}/api/projects/{project_id}/files")
        if resp.status_code == 200:
            files_data = resp.json()
            files = files_data.get("files", [])
            print(f"✓ 共生成 {len(files)} 个文件:")
            for f in sorted(files)[:20]:
                print(f"  - {f}")
            if len(files) > 20:
                print(f"  ... 以及其他 {len(files) - 20} 个文件")
        else:
            print(f"  无法获取文件列表 (状态码: {resp.status_code})")

    print("\n" + "=" * 60)
    print(f"🎉 测试完成！项目目录：projects/{project_id}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_factory())
