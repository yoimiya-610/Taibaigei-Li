from typing import Any

import httpx

from mybot.common.config import get_deepseek_api_key
from mybot.common.logger import get_plugin_logger


API_URL = "https://api.deepseek.com/chat/completions"
CHAT_MODEL = "deepseek-chat"
PRO_MODEL = "deepseek-v4-pro"
logger = get_plugin_logger(__name__)


class AIClientError(RuntimeError):
    """Raised when the shared AI client cannot return a usable response."""


class MissingAPIKeyError(AIClientError):
    """Raised when DEEPSEEK_API_KEY is not configured."""


def is_configured() -> bool:
    return bool(get_deepseek_api_key())


async def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: str = CHAT_MODEL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 30,
    raise_errors: bool = False,
) -> str | None:
    api_key = get_deepseek_api_key()
    if not api_key:
        error = MissingAPIKeyError("DEEPSEEK_API_KEY is not configured")
        if raise_errors:
            raise error
        logger.warning(str(error))
        return None

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    optional_fields = {
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
    }
    payload.update({key: value for key, value in optional_fields.items() if value is not None})

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                API_URL,
                headers={
                    "Authorization": "Bearer " + api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise AIClientError("AI response has no usable content")
            return content.strip()
    except Exception as exc:
        if raise_errors:
            raise
        logger.exception(f"AI request failed: {exc}")
        return None


async def prompt_completion(
    prompt: str,
    *,
    system: str | None = None,
    model: str = CHAT_MODEL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 30,
    raise_errors: bool = False,
) -> str | None:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    return await chat_completion(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        timeout=timeout,
        raise_errors=raise_errors,
    )
