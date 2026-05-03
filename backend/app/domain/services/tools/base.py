"""Tool & toolkit primitives — pure stdlib + pydantic, no langchain.

Usage:

    class MyToolkit(BaseToolkit):
        name = "my"

        @tool
        async def do_thing(self, query: str, limit: int = 10) -> ToolResult:
            \"\"\"Short description.

            Args:
                query: what to search for
                limit: how many results
            \"\"\"
            ...

The decorator just tags the method. `BaseToolkit.__init__` walks tagged
methods and builds the schema lazily so that subclasses receive the toolkit
instance bound into each Tool.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, get_type_hints

from pydantic import BaseModel, Field, create_model

from app.domain.models.tool_result import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def tool(
    fn: Optional[Callable[..., Awaitable[Any]]] = None,
    *,
    name: Optional[str] = None,
):
    """Mark an async method as an LLM-callable tool.

    The function name doubles as the tool name unless `name=` is given.
    The docstring's first paragraph becomes the description; Google-style
    `Args:` blocks supply per-parameter descriptions.
    """

    def wrap(f: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        f._is_tool = True  # type: ignore[attr-defined]
        f._tool_name = name or f.__name__  # type: ignore[attr-defined]
        desc, arg_docs = _split_docstring(f.__doc__ or "")
        f._tool_description = desc  # type: ignore[attr-defined]
        f._tool_arg_docs = arg_docs  # type: ignore[attr-defined]
        return f

    if fn is not None:
        return wrap(fn)
    return wrap


# ---------------------------------------------------------------------------
# Tool wrapper
# ---------------------------------------------------------------------------


class Tool:
    """A single callable tool, bound to a toolkit instance."""

    def __init__(
        self,
        *,
        toolkit: "BaseToolkit",
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        fn: Callable[..., Awaitable[Any]],
    ) -> None:
        self.toolkit = toolkit
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self._fn = fn

    def to_anthropic(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    async def ainvoke(self, args: Dict[str, Any]) -> ToolResult:
        # Defence in depth: `validate_tool_input` upstream already rejects
        # non-dict args, but if a future caller skips that gate, a non-dict
        # `args` would TypeError on `**args`. Coerce here to a kwargs-safe
        # value so the worst case is "tool runs with defaults" rather than
        # "agent loop crashes mid-flight".
        kwargs = args if isinstance(args, dict) else {}
        result = await self._fn(**kwargs)
        if isinstance(result, ToolResult):
            return result
        # Be permissive: wrap raw values so the loop can always serialize.
        return ToolResult(success=True, data=result)


# ---------------------------------------------------------------------------
# Toolkit base
# ---------------------------------------------------------------------------


class BaseToolkit:
    """Base toolset class.

    Subclasses set `name` and decorate methods with `@tool`. They MUST call
    `super().__init__()` so the registry is built.
    """

    name: str = ""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._register_decorated_tools()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tools(self) -> List[Tool]:
        return list(self._tools.values())

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        return self._tools.get(tool_name)

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_decorated_tools(self) -> None:
        # Walk the class hierarchy so subclass-defined tools are picked up.
        seen: set[str] = set()
        for cls in type(self).__mro__:
            for attr_name, raw in cls.__dict__.items():
                if attr_name in seen:
                    continue
                if not callable(raw):
                    continue
                if not getattr(raw, "_is_tool", False):
                    continue
                seen.add(attr_name)
                bound = getattr(self, attr_name)
                tname: str = raw._tool_name  # type: ignore[attr-defined]
                desc: str = raw._tool_description  # type: ignore[attr-defined]
                arg_docs: Dict[str, str] = raw._tool_arg_docs  # type: ignore[attr-defined]
                schema = _build_input_schema(raw, arg_docs)
                self._tools[tname] = Tool(
                    toolkit=self,
                    name=tname,
                    description=desc,
                    input_schema=schema,
                    fn=bound,
                )

    def _add_tool(self, tool_obj: Tool) -> None:
        """Hook for toolkits that build tools dynamically (e.g. MCP)."""
        self._tools[tool_obj.name] = tool_obj


# ---------------------------------------------------------------------------
# Schema generation
# ---------------------------------------------------------------------------


def _build_input_schema(fn: Callable[..., Any], arg_docs: Dict[str, str]) -> Dict[str, Any]:
    """Reflect a function's signature + docstring args into a JSON Schema."""
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:
        hints = {}

    fields: Dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        annotation = hints.get(pname, param.annotation if param.annotation is not inspect._empty else str)
        if annotation is inspect._empty:
            annotation = str
        if param.default is inspect.Parameter.empty:
            default = ...
        else:
            default = param.default
        description = arg_docs.get(pname, "")
        fields[pname] = (annotation, Field(default=default, description=description))

    if not fields:
        return {"type": "object", "properties": {}}

    Model = create_model(f"{fn.__name__}_Args", __base__=BaseModel, **fields)
    schema = Model.model_json_schema()
    schema = _strip_titles(schema)
    return schema


def _strip_titles(schema: Any) -> Any:
    """Remove pydantic's noisy `title` keys from the JSON Schema in place.

    `title` in JSON Schema is always a STRING label. Inside `properties`,
    the dict value of key `"title"` is the schema for a property named
    `title` — we must NOT strip that one. Filter on value type so we only
    drop the schema-metadata variant.
    """
    if isinstance(schema, dict):
        if isinstance(schema.get("title"), str):
            schema.pop("title")
        for v in schema.values():
            _strip_titles(v)
    elif isinstance(schema, list):
        for item in schema:
            _strip_titles(item)
    return schema


# ---------------------------------------------------------------------------
# Docstring parsing (Google style)
# ---------------------------------------------------------------------------


_ARGS_RE = re.compile(r"^\s*Args:\s*$", re.MULTILINE)
_PARAM_RE = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(?:\([^)]*\))?\s*:\s*(.*)$")


def _split_docstring(doc: str) -> tuple[str, Dict[str, str]]:
    """Return (description, {param_name: description}) from a Google-style docstring."""
    if not doc:
        return "", {}
    text = inspect.cleandoc(doc)
    args_match = _ARGS_RE.search(text)
    if not args_match:
        return text.strip(), {}

    description = text[: args_match.start()].rstrip()
    args_section = text[args_match.end():]

    arg_docs: Dict[str, str] = {}
    current_name: Optional[str] = None
    for line in args_section.splitlines():
        if not line.strip():
            current_name = None
            continue
        # Continuation lines (indented further than the param line) extend
        # the most recent param's description.
        m = _PARAM_RE.match(line)
        if m and not line.startswith("        "):
            current_name = m.group(1)
            arg_docs[current_name] = m.group(2).strip()
        elif current_name is not None:
            arg_docs[current_name] = (arg_docs[current_name] + " " + line.strip()).strip()
    return description, arg_docs
