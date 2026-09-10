from openai import AsyncOpenAI
from config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL

client = AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)


async def stream_chat(prompt: str):
    """异步生成器，逐 chunk yield 文本片段。"""
    response = await client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        max_tokens=8192,
    )
    async for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
