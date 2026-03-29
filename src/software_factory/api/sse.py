from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class SSEManager:
    """为每个 session 维护独立的异步事件队列，驱动 SSE 推送"""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = defaultdict(lambda: asyncio.Queue(maxsize=200))

    async def publish(self, session_id: str, event: dict) -> None:
        """向指定 session 推送事件"""
        try:
            queue = self._queues[session_id]
            await asyncio.wait_for(queue.put(event), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("SSE queue full for session %s, dropping event", session_id)
        except Exception as e:
            logger.error("SSE publish error: %s", e)

    def publish_nowait(self, session_id: str, event: dict) -> None:
        """非阻塞推送（从同步上下文调用）"""
        try:
            self._queues[session_id].put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("SSE queue full for session %s", session_id)

    async def subscribe(self, session_id: str) -> AsyncGenerator[str, None]:
        """SSE 端点消费，生成 text/event-stream 格式字符串"""
        queue = self._queues[session_id]
        heartbeat_interval = 25.0  # 秒

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)

                event_type = event.get("type", "message")
                data = json.dumps(event, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"

                if event_type == "done" or event_type == "error":
                    break

            except asyncio.TimeoutError:
                # 心跳保持连接活跃
                yield "event: heartbeat\ndata: {}\n\n"

    def cleanup(self, session_id: str) -> None:
        """清理 session 队列"""
        self._queues.pop(session_id, None)


# 全局单例
sse_manager = SSEManager()
