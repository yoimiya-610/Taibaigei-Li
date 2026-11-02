from dataclasses import dataclass
from typing import Any

import httpx
from nonebot.matcher import current_event, current_matcher

from mybot.common.config import get_deepseek_api_key
from mybot.common.logger import get_plugin_logger
from mybot.common.usage_policy import AI_REQUEST_QUOTA, QuotaDecision, consume_quota


API_URL = "https://api.deepseek.com/chat/completions"
CHAT_MODEL = "deepseek-chat"
PRO_MODEL = "deepseek-v4-pro"
logger = get_plugin_logger(__name__)


class AIClientError(RuntimeError):
    """Raised when the shared AI client cannot return a usable response."""


class MissingAPIKeyError(AIClientError):
    """Raised when DEEPSEEK_API_KEY is not configured."""


class AIUsageQuotaError(AIClientError):
    def __init__(self, decision: QuotaDecision):
        super().__init__("ai_usage_quota_exceeded")
        self.decision = decision


@dataclass(frozen=True)
class AIToolCall:
    id: str
    name: str
    arguments: str

    def to_api_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass(frozen=True)
class AIChatMessage:
    content: str | None
    tool_calls: tuple[AIToolCall, ...] = ()
    reasoning_content: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": self.content,
        }
        if self.reasoning_content is not None:
            message["reasoning_content"] = self.reasoning_content
        if self.tool_calls:
            message["tool_calls"] = [call.to_api_dict() for call in self.tool_calls]
        return message


def is_configured() -> bool:
    return bool(get_deepseek_api_key())


def _consume_current_ai_quota() -> QuotaDecision | None:
    try:
        event = current_event.get()
        matcher = current_matcher.get()
    except LookupError:
        return None
    try:
        user_id = event.get_user_id()
    except Exception:
        return None
    module_name = str(getattr(matcher, "module_name", "") or "")
    feature_key = module_name.rsplit(".", 1)[-1] or "ai"
    group_id = getattr(event, "group_id", None)
    return consume_quota(
        feature_key,
        str(user_id),
        str(group_id) if group_id is not None else None,
        AI_REQUEST_QUOTA,
    )


def _parse_chat_message(result: Any) -> AIChatMessage:
    try:
        raw_message = result["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AIClientError("AI response has no usable message") from exc
    if not isinstance(raw_message, dict):
        raise AIClientError("AI response message is invalid")

    raw_content = raw_message.get("content")
    if raw_content is not None and not isinstance(raw_content, str):
        raise AIClientError("AI response content is invalid")
    content = raw_content.strip() if isinstance(raw_content, str) and raw_content.strip() else None

    raw_reasoning = raw_message.get("reasoning_content")
    reasoning_content = raw_reasoning if isinstance(raw_reasoning, str) else None
    raw_tool_calls = raw_message.get("tool_calls")
    if raw_tool_calls is None:
        raw_tool_calls = []
    elif not isinstance(raw_tool_calls, list):
        raise AIClientError("AI response tool calls are invalid")

    tool_calls = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict) or raw_call.get("type") != "function":
            raise AIClientError("AI response tool call is invalid")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise AIClientError("AI response tool function is invalid")
        call_id = raw_call.get("id")
        name = function.get("name")
        arguments = function.get("arguments")
        if not (
            isinstance(call_id, str)
            and bool(call_id)
            and isinstance(name, str)
            and bool(name)
            and isinstance(arguments, str)
        ):
            raise AIClientError("AI response tool call fields are invalid")
        tool_calls.append(AIToolCall(id=call_id, name=name, arguments=arguments))

    if content is None and not tool_calls:
        raise AIClientError("AI response has no usable content or tool calls")
    return AIChatMessage(
        content=content,
        tool_calls=tuple(tool_calls),
        reasoning_content=reasoning_content,
    )


async def chat_completion_message(
    messages: list[dict[str, Any]],
    *,
    model: str = CHAT_MODEL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 30,
    raise_errors: bool = False,
    usage_checked: bool = False,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
) -> AIChatMessage | None:
    api_key = get_deepseek_api_key()
    if not api_key:
        error = MissingAPIKeyError("DEEPSEEK_API_KEY is not configured")
        if raise_errors:
            raise error
        logger.warning(str(error))
        return None

    if not usage_checked:
        decision = _consume_current_ai_quota()
        if decision is not None and not decision.allowed:
            error = AIUsageQuotaError(decision)
            if raise_errors:
                raise error
            logger.info(
                "AI request held by shared quota feature_scope=%s wait_seconds=%s",
                decision.blocked_scope,
                decision.wait_seconds,
            )
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
        "tools": tools,
        "tool_choice": tool_choice,
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
            return _parse_chat_message(response.json())
    except Exception as exc:
        if raise_errors:
            raise
        logger.exception(f"AI request failed: {exc}")
        return None


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    model: str = CHAT_MODEL,
    max_tokens: int | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    thinking: dict[str, Any] | None = None,
    reasoning_effort: str | None = None,
    timeout: float = 30,
    raise_errors: bool = False,
    usage_checked: bool = False,
) -> str | None:
    message = await chat_completion_message(
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        timeout=timeout,
        raise_errors=raise_errors,
        usage_checked=usage_checked,
    )
    if message is None:
        return None
    if message.content is None:
        error = AIClientError("AI response has no usable content")
        if raise_errors:
            raise error
        logger.warning(str(error))
        return None
    return message.content


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
    usage_checked: bool = False,
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
        usage_checked=usage_checked,
    )
