from __future__ import annotations

from typing import Any, Type

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel


def create_json_chain(llm, system_prompt: str, output_schema: Type[BaseModel]):
    """
    创建一个提示词驱动的 JSON 输出链，不依赖 response_format API。
    兼容所有 OpenAI 兼容接口（包括不支持 JSON Schema 模式的模型）。

    原理：JsonOutputParser 将 Pydantic 模型的 schema 格式化为文字说明，
    注入到提示词末尾，让模型自行输出 JSON，再从响应文本中提取解析。
    """
    parser = JsonOutputParser(pydantic_object=output_schema)
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt + "\n\n{format_instructions}"),
        ("human", "{input}"),
    ]).partial(format_instructions=parser.get_format_instructions())
    return prompt | llm | parser
