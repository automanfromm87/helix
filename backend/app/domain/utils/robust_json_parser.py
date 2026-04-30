"""Best-effort JSON extraction for free-text LLM output.

Strategy (in order):
  1. Strip markdown code fences and try `json.loads`.
  2. Locate the largest balanced `{...}` substring and try `json.loads`.
  3. As a last resort, try `json.loads` on the raw text.

Returns a dict on success; raises `ToolCallParseError` on failure.

Anthropic's tool_use blocks are already structured, so this parser is only
used for planner/executor JSON-text outputs (not for tool call args).
"""

from __future__ import annotations

import json
import re
from typing import Optional


class ToolCallParseError(Exception):
    """Raised when robust JSON parsing fails."""


_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def _strip_fences(text: str) -> str:
    match = _FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _largest_balanced_object(text: str) -> Optional[str]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end < 0:
        return None
    return text[start : end + 1]


def parse_robust_json(text: str) -> dict:
    """Pull a JSON object out of a possibly-fenced, possibly-prefixed string."""
    if not isinstance(text, str) or not text.strip():
        raise ToolCallParseError("Empty input")

    candidates: list[str] = []
    candidates.append(_strip_fences(text))
    balanced = _largest_balanced_object(text)
    if balanced and balanced not in candidates:
        candidates.append(balanced)
    if text not in candidates:
        candidates.append(text)

    last_error: Optional[Exception] = None
    for cand in candidates:
        try:
            value = json.loads(cand)
            if isinstance(value, dict):
                return value
            last_error = ValueError(f"Parsed value is not a JSON object: {type(value).__name__}")
        except Exception as e:
            last_error = e
            continue
    raise ToolCallParseError(f"Could not parse JSON object: {last_error}")
