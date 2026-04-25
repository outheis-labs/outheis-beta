"""
LLM client abstraction.

Supports multiple providers per config:
- Anthropic (Claude)
- Ollama local (ollama.local — OpenAI-compatible, localhost)
- Ollama cloud (ollama.cloud — OpenAI-compatible, https://ollama.com/v1)
- OpenAI

All providers expose the same Anthropic-style response interface to callers.
OpenAI/Ollama responses are wrapped in compatible dataclasses so that agent
code never needs to branch on provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from outheis.core.config import LLMConfig, ModelConfig

# =============================================================================
# EXCEPTIONS
# =============================================================================

class BillingError(Exception):
    """Raised when the cloud provider rejects a call due to billing / auth issues.

    Signals the dispatcher to enter local-fallback mode if configured.
    """
    pass


# =============================================================================
# GLOBAL STATE (set once at startup)
# =============================================================================

_config: LLMConfig | None = None
_clients: dict[str, Any] = {}  # provider_name -> client


def init_llm(config: LLMConfig) -> None:
    """Initialize LLM with config. Called once at dispatcher startup."""
    global _config, _clients
    _config = config
    _clients = {}


def _raise_if_billing(exc: Exception) -> None:
    """Re-raise exc as BillingError if it indicates a billing or auth failure."""
    msg = str(exc).lower()
    # Anthropic: HTTP 402 credit exhausted, 401 invalid key
    status = getattr(exc, "status_code", None)
    if status in (401, 402):
        raise BillingError(str(exc)) from exc
    # Anthropic SDK error types
    type_name = type(exc).__name__
    if type_name in ("AuthenticationError", "PermissionDeniedError"):
        raise BillingError(str(exc)) from exc
    # Message-based detection as fallback
    billing_phrases = ("credit balance", "insufficient credits", "billing", "quota exceeded",
                       "invalid api key", "authentication", "permission denied")
    if any(p in msg for p in billing_phrases):
        raise BillingError(str(exc)) from exc


def get_llm_config() -> LLMConfig:
    """Get LLM config. Loads from file if not yet initialized."""
    global _config
    if _config is None:
        from outheis.core.config import load_config
        _config = load_config().llm
    return _config


def get_client(provider_name: str) -> Any:
    """Get LLM client for a provider. Creates on first use, then reuses."""
    global _clients

    if provider_name in _clients:
        return _clients[provider_name]

    config = get_llm_config()
    provider = config.get_provider(provider_name)

    if provider_name == "anthropic":
        import anthropic
        kwargs: dict[str, Any] = {}
        if provider.api_key:
            kwargs["api_key"] = provider.api_key
        if provider.base_url:
            kwargs["base_url"] = provider.base_url
        _clients[provider_name] = anthropic.Anthropic(**kwargs)

    elif provider_name == "openai" or provider_name.startswith("ollama"):
        try:
            import openai
        except ImportError:
            raise ImportError("openai package not installed — run: pip install openai")  # noqa: B904
        kwargs = {}
        if provider_name.startswith("ollama"):
            api_key = provider.api_key or "ollama-local"
            base_url = (provider.base_url or "http://localhost:11434").rstrip("/")
            if not base_url.endswith("/v1"):
                base_url += "/v1"
            kwargs["base_url"] = base_url
            kwargs["api_key"] = api_key
            kwargs["timeout"] = 120.0
            if provider_name == "ollama.local":
                import os
                if provider.env_vars:
                    for k, v in provider.env_vars.items():
                        os.environ.setdefault(k, str(v))
                os.environ["OLLAMA_API_KEY"] = api_key
        else:  # openai
            if provider.api_key:
                kwargs["api_key"] = provider.api_key
            if provider.base_url:
                kwargs["base_url"] = provider.base_url
        _clients[provider_name] = openai.OpenAI(**kwargs)

    else:
        raise ValueError(f"Unknown provider: {provider_name}")

    return _clients[provider_name]


# =============================================================================
# ANTHROPIC-COMPATIBLE RESPONSE WRAPPERS FOR OPENAI/OLLAMA
# =============================================================================

@dataclass
class _FakeUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass
class _FakeToolUseBlock:
    id: str
    name: str
    input: dict
    type: str = "tool_use"


@dataclass
class _FakeResponse:
    content: list
    stop_reason: str
    usage: _FakeUsage


def _to_openai_messages(messages: list[dict], system: str | None) -> list[dict]:
    """Convert Anthropic-format messages list to OpenAI chat format."""
    result: list[dict] = []

    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "user":
            if isinstance(content, str):
                result.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Tool results → one "tool" message per result
                tool_results = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_result"]
                if tool_results:
                    for tr in tool_results:
                        body = tr.get("content", "")
                        result.append({
                            "role": "tool",
                            "tool_call_id": tr.get("tool_use_id", ""),
                            "content": body if isinstance(body, str) else json.dumps(body),
                        })
                else:
                    # Plain text content list
                    text = " ".join(
                        c.get("text", "") if isinstance(c, dict) else (c.text if hasattr(c, "text") else "")
                        for c in content
                    )
                    result.append({"role": "user", "content": text})

        elif role == "assistant":
            if isinstance(content, str):
                result.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text = ""
                tool_calls = []
                for block in content:
                    btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", "")
                    if btype == "text":
                        text = block.get("text", "") if isinstance(block, dict) else block.text
                    elif btype == "tool_use":
                        bid   = block.get("id", "")    if isinstance(block, dict) else block.id
                        bname = block.get("name", "")  if isinstance(block, dict) else block.name
                        binp  = block.get("input", {}) if isinstance(block, dict) else block.input
                        tool_calls.append({
                            "id": bid,
                            "type": "function",
                            "function": {"name": bname, "arguments": json.dumps(binp)},
                        })
                oai_msg: dict[str, Any] = {"role": "assistant", "content": text or None}
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                result.append(oai_msg)

    return result


def _to_openai_tools(tools: list[dict] | None) -> list[dict] | None:
    """Convert Anthropic tool definitions to OpenAI function format."""
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _wrap_openai_response(response: Any) -> _FakeResponse:
    """Wrap an OpenAI chat completion in Anthropic-compatible dataclasses."""
    choice = response.choices[0]
    message = choice.message
    finish_reason = choice.finish_reason or "stop"

    stop_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"

    content: list[Any] = []

    if message.content:
        content.append(_FakeTextBlock(text=message.content))

    for tc in (getattr(message, "tool_calls", None) or []):
        try:
            arguments = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, AttributeError):
            arguments = {}
        content.append(_FakeToolUseBlock(
            id=tc.id,
            name=tc.function.name,
            input=arguments,
        ))

    usage = _FakeUsage(
        input_tokens=getattr(response.usage, "prompt_tokens", 0),
        output_tokens=getattr(response.usage, "completion_tokens", 0),
    )

    return _FakeResponse(content=content, stop_reason=stop_reason, usage=usage)


# =============================================================================
# PUBLIC API
# =============================================================================

def resolve_model(alias: str, skip_providers: set[str] | None = None) -> ModelConfig:
    """Resolve model alias to a complete ModelConfig.

    Uses provider_aliases + fallback_order when configured, otherwise falls back
    to the flat models dict + local_fallback (legacy).
    Raises ModelResolutionError if no usable provider is found.
    Logs a warning when a fallback is used.
    """
    import logging
    llm_config = get_llm_config()
    model_config, warning = llm_config.resolve_model(alias, skip_providers=skip_providers)
    if warning:
        logging.getLogger(__name__).warning(warning)
    return model_config


def _do_call(
    model_config: ModelConfig,
    messages: list[dict[str, Any]],
    system: str | None,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    timeout: float,
) -> Any:
    """Execute a single LLM call. Raises BillingError on billing/auth failure."""
    client = get_client(model_config.provider)

    if model_config.provider == "anthropic":
        kwargs: dict[str, Any] = {
            "model": model_config.name,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        try:
            return client.messages.create(timeout=timeout, **kwargs)
        except Exception as e:
            _raise_if_billing(e)
            raise

    else:  # openai or ollama
        oai_messages = _to_openai_messages(messages, system)
        oai_tools = _to_openai_tools(tools)
        kwargs = {
            "model": model_config.name,
            "max_tokens": max_tokens,
            "messages": oai_messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools
        if model_config.provider == "ollama.local":
            kwargs["extra_body"] = {"keep_alive": -1}
        try:
            raw = client.chat.completions.create(**kwargs)
        except Exception as e:
            _raise_if_billing(e)
            raise
        return _wrap_openai_response(raw)


def call_llm(
    model: str,
    messages: list[dict[str, Any]],
    system: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    agent: str = "unknown",
    timeout: float = 90.0,
) -> Any:
    """
    Call LLM with messages.

    Messages and tools are always passed in Anthropic format.
    For OpenAI/Ollama providers the conversion happens transparently here;
    callers always receive an Anthropic-compatible response object.

    When provider_aliases + fallback_order are configured, automatically retries
    on the next provider in fallback_order if the current provider raises a
    BillingError. Only propagates BillingError when all providers are exhausted.
    """
    import logging
    log = logging.getLogger(__name__)

    llm_config = get_llm_config()
    use_provider_fallback = bool(llm_config.model_fallbacks)

    failed_providers: set[str] = set()
    last_billing_error: BillingError | None = None

    while True:
        from outheis.core.config import ModelResolutionError
        try:
            skip = failed_providers if use_provider_fallback else None
            model_config = resolve_model(model, skip_providers=skip)
        except ModelResolutionError:
            if last_billing_error:
                raise last_billing_error
            raise

        try:
            response = _do_call(model_config, messages, system, tools, max_tokens, timeout)
        except BillingError as e:
            if not use_provider_fallback:
                raise
            log.warning(
                "[llm] BillingError on provider '%s' for alias '%s' — trying next provider",
                model_config.provider, model,
            )
            failed_providers.add(model_config.provider)
            last_billing_error = e
            continue

        try:
            from outheis.core.tokens import record_usage
            if hasattr(response, "usage") and response.usage:
                record_usage(
                    agent=agent,
                    model=model_config.name,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                )
        except Exception:
            pass

        return response
