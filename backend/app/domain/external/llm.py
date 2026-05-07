"""Port for the language-model client used by the agent runtime.

The previous version of this Protocol had a single `ask()` method that
no domain code ever called — agents called the streaming + one-shot
helpers in `infrastructure.external.llm.claude_client` directly. This
revision aligns the Protocol with actual usage so the runtime can hold
an injected `LLM` instead of reverse-importing the concrete module.
"""

from typing import Any, AsyncGenerator, Dict, List, Optional, Protocol


class LLM(Protocol):
    """Streaming + one-shot text completion gateway."""

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
        """Streaming Messages-style turn.

        Yields a sequence of dicts shaped like:
          * `{"type": "text_delta", "text": <chunk>, "accumulated": <so far>}`
          * `{"type": "final", "payload": <full message dict>}`

        The final dict's `payload` is the assembled assistant message
        including any tool-use blocks. Telemetry recording is the
        adapter's concern; the Protocol only specifies the wire format.
        """
        ...

    async def complete_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """One-shot text completion. No tools, no streaming, no caching.
        Used by ancillary callers (workspace surveyor, browser content
        extraction) that just need a text -> text turn."""
        ...
