"""Internal message + content-block types matching Anthropic's wire format.

These are the only message types the rest of the agent layer should know
about. They serialize directly to what `messages.create(messages=[...])`
expects, so we never have to translate between an "internal" and "API" shape.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


CacheControl = Dict[str, Any]  # e.g. {"type": "ephemeral"}


class _BlockBase(BaseModel):
    cache_control: Optional[CacheControl] = None

    def to_api(self) -> Dict[str, Any]:
        return self.model_dump(exclude_none=True)


class TextBlock(_BlockBase):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(_BlockBase):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: Dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(_BlockBase):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str = ""
    is_error: bool = False


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


class ConvMessage(BaseModel):
    """A single Anthropic-shape conversation turn."""

    role: Literal["user", "assistant"]
    content: List[ContentBlock] = Field(default_factory=list)

    @classmethod
    def user_text(cls, text: str) -> "ConvMessage":
        return cls(role="user", content=[TextBlock(text=text)])

    def text(self) -> str:
        """Concatenate all text blocks; ignores tool_use/tool_result."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))

    def tool_uses(self) -> List[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def to_api(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": [b.to_api() for b in self.content],
        }


def message_from_api(payload: Dict[str, Any]) -> ConvMessage:
    """Hydrate an Anthropic API response into a ConvMessage. Unknown block
    types (e.g. server_tool_use, thinking) are dropped — we keep only the
    blocks our own loop and history care about.
    """
    blocks: List[ContentBlock] = []
    for raw in payload.get("content", []) or []:
        btype = raw.get("type")
        if btype == "text":
            blocks.append(TextBlock(text=raw.get("text", "")))
        elif btype == "tool_use":
            blocks.append(
                ToolUseBlock(
                    id=raw["id"],
                    name=raw["name"],
                    input=raw.get("input") or {},
                )
            )
        elif btype == "tool_result":
            content = raw.get("content")
            if isinstance(content, list):
                # Multi-part tool_result; flatten text blocks.
                content = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
                )
            blocks.append(
                ToolResultBlock(
                    tool_use_id=raw["tool_use_id"],
                    content=content or "",
                    is_error=bool(raw.get("is_error", False)),
                )
            )
    return ConvMessage(role=payload.get("role", "assistant"), content=blocks)
