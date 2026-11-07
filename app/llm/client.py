"""OpenAI 兼容异步客户端：模型调用的唯一耦合点。"""
import asyncio
import json
import re
import time

import httpx

from app.core import config
from app.core.db import SessionLocal
from app.models import AiUsageLog

_TIMEOUT = 30.0
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


class LlmDisabled(Exception):
    """模型调用开关未开启。"""


class LlmBadJson(Exception):
    """返回内容无法解析为 JSON 对象。"""


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def _log_usage(
    task_id: int | None,
    purpose: str,
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    latency_ms: int | None,
    status: str,
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                AiUsageLog(
                    task_id=task_id,
                    purpose=purpose,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    status=status,
                )
            )
            await session.commit()
    except Exception:
        pass  # 用量记录失败不影响主流程


async def chat(
    messages: list[dict],
    *,
    purpose: str,
    model: str | None = None,
    task_id: int | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.3,
) -> str:
    if not config.LLM_ENABLED:
        raise LlmDisabled("模型调用未开启")
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    resolved_model = model or config.LLM_MODEL
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    body = {
        "model": resolved_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    started = time.monotonic()
    last_error: Exception = RuntimeError("上游调用失败")
    for attempt in range(3):  # 429/5xx 退避重试两次，间隔 1s/2s
        if attempt:
            await asyncio.sleep(1.0 * 2 ** (attempt - 1))
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            await _log_usage(task_id, purpose, resolved_model, None, None, _elapsed_ms(started), "error")
            raise RuntimeError(f"上游网络异常: {exc}") from exc
        if resp.status_code == 200:
            try:
                data = resp.json()
                content = data["choices"][0]["message"]["content"] or ""
                usage = data.get("usage") or {}
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                await _log_usage(task_id, purpose, resolved_model, None, None, _elapsed_ms(started), "error")
                raise RuntimeError(f"上游响应结构异常: {exc}") from exc
            await _log_usage(
                task_id,
                purpose,
                resolved_model,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                _elapsed_ms(started),
                "ok",
            )
            return content
        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = RuntimeError(f"上游返回 HTTP {resp.status_code}")
            continue
        await _log_usage(task_id, purpose, resolved_model, None, None, _elapsed_ms(started), "error")
        raise RuntimeError(f"上游返回 HTTP {resp.status_code}: {resp.text[:200]}")
    await _log_usage(task_id, purpose, resolved_model, None, None, _elapsed_ms(started), "error")
    raise last_error


async def chat_json(messages: list[dict], *, purpose: str, **kwargs) -> dict:
    content = (await chat(messages, purpose=purpose, **kwargs)).strip()
    fenced = _FENCE.search(content)
    if fenced:
        content = fenced.group(1).strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # 容错：截取首尾大括号之间的部分再解析一次
        head, tail = content.find("{"), content.rfind("}")
        if head < 0 or tail <= head:
            raise LlmBadJson(f"内容不是 JSON: {content[:80]}") from None
        try:
            data = json.loads(content[head : tail + 1])
        except json.JSONDecodeError as exc:
            raise LlmBadJson(str(exc)) from exc
    if not isinstance(data, dict):
        raise LlmBadJson("JSON 顶层不是对象")
    return data
