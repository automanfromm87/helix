"""Adapter implementing the domain `LLM` Protocol via the Anthropic SDK.

The actual streaming / one-shot logic lives in `claude_client` as
module-level functions (which is what the codebase has historically
called directly). This adapter just wraps them as instance methods so
domain services can take an injected `LLM` rather than reaching into
infrastructure.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional

from app.domain.external.llm import LLM
from app.infrastructure.external.llm import claude_client


class AnthropicLLM(LLM):
    """Default `LLM` adapter — delegates to `claude_client`."""

    async def complete_stream(
        self,
        *,
        messages: List[Dict[str, Any]],
        system: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Dict[str, Any]] = None,
        context_management: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        async for chunk in claude_client.complete_stream(
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            context_management=context_management,
            max_tokens=max_tokens,
            model=model,
        ):
            yield chunk

    async def complete_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        return await claude_client.complete_text(
            prompt,
            system=system,
            max_tokens=max_tokens,
            model=model,
        )
