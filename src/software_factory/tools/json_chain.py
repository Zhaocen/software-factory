from __future__ import annotations

import logging
from typing import Any, Type

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)


def create_json_chain(llm, system_prompt: str, output_schema: Type[BaseModel]):
    """
    创建一个提示词驱动的 JSON 输出链，不依赖 response_format API。
    兼容所有 OpenAI 兼容接口（包括不支持 JSON Schema 模式的模型）。

    返回一个可 ainvoke({"input": ...}) 的 Runnable，输出为 dict（已通过 Pydantic 校验）。
    如果模型输出不符合 schema，会自动将错误反馈给模型重新生成，最多重试 2 次。
    """
    parser = JsonOutputParser(pydantic_object=output_schema)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt + "\n\n{format_instructions}"),
            ("human", "{input}"),
        ]
    ).partial(format_instructions=parser.get_format_instructions())

    base_chain = prompt | llm | parser

    return _ValidatedChain(base_chain, output_schema, llm, system_prompt, parser)


class _ValidatedChain:
    """
    对 base_chain 的薄封装：调用后用 Pydantic 校验，失败时把错误告知 LLM 重新生成。
    """

    def __init__(self, base_chain, schema: Type[BaseModel], llm, system_prompt: str, parser):
        self._chain = base_chain
        self._schema = schema
        self._llm = llm
        self._system_prompt = system_prompt
        self._parser = parser

    async def ainvoke(self, inputs: dict[str, Any], **kwargs) -> dict:
        raw = await self._chain.ainvoke(inputs, **kwargs)
        last_error: str = ""

        # 第一次尝试校验
        try:
            self._schema.model_validate(raw)
            return raw
        except ValidationError as e:
            last_error = _format_validation_error(e)
            logger.warning(
                "JSON schema validation failed (attempt 1), retrying: %s", last_error[:200]
            )

        # 最多再重试 2 次，把错误反馈给 LLM
        for attempt in range(2):
            fix_prompt = (
                f"{self._system_prompt}\n\n{self._parser.get_format_instructions()}"
            )
            messages = [
                SystemMessage(content=fix_prompt),
                HumanMessage(content=inputs.get("input", "")),
                HumanMessage(
                    content=(
                        f"你上一次的输出存在格式错误，请修正后重新输出：\n\n{last_error}\n\n"
                        "请严格按照 JSON schema 要求输出，注意字段类型（列表字段必须是数组，"
                        "不能是字符串）。"
                    )
                ),
            ]
            try:
                response = await self._llm.ainvoke(messages)
                raw = self._parser.parse(response.content)
                self._schema.model_validate(raw)
                logger.info(
                    "JSON validation passed after retry %d", attempt + 2
                )
                return raw
            except ValidationError as e:
                last_error = _format_validation_error(e)
                logger.warning(
                    "JSON schema validation failed (attempt %d): %s",
                    attempt + 2, last_error[:200],
                )
            except Exception as e:
                logger.warning("Retry LLM call failed (attempt %d): %s", attempt + 2, e)
                break

        # 所有重试均失败，返回最后一次原始 dict（由调用方决定如何处理）
        logger.error(
            "JSON validation failed after all retries for schema %s, returning raw dict",
            self._schema.__name__,
        )
        return raw if isinstance(raw, dict) else {}


def _format_validation_error(e: ValidationError) -> str:
    """将 Pydantic ValidationError 格式化为简洁的错误描述"""
    lines = []
    for err in e.errors():
        loc = " -> ".join(str(x) for x in err["loc"])
        input_type = err.get("input", "?").__class__.__name__
        lines.append(f"字段 '{loc}': {err['msg']}（输入值类型为 {input_type}）")
    return "\n".join(lines)
