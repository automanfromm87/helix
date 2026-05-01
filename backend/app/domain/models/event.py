from pydantic import BaseModel, Field
from typing import Dict, Any, Literal, Optional, Union, List
from datetime import datetime
from enum import Enum
import uuid

from app.domain.models.plan import Plan, PlanStatus, Task, TaskStatus
from app.domain.models.file import FileInfo
from app.domain.models.search import SearchResultItem


class ToolStatus(str, Enum):
    """Tool status enum"""
    CALLING = "calling"
    CALLED = "called"


class BaseEvent(BaseModel):
    """Base class for agent events"""
    type: Literal[""] = ""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.now)


class ErrorEvent(BaseEvent):
    type: Literal["error"] = "error"
    error: str
    # Optional machine-readable tag so the flow can route errors that need
    # special handling (e.g. "budget_exhausted" should skip retry+replan and
    # fail the plan immediately — replanning won't help when the framework
    # itself ran out of room). Free-form string; absence = "generic error".
    code: Optional[str] = None


class PlanEvent(BaseEvent):
    """Plan lifecycle event — emitted at create/finalize transitions.

    Carries the full Plan (including tasks) so the frontend can re-render its
    sidebar plan panel from a single event without follow-up fetches.
    """
    type: Literal["plan"] = "plan"
    plan: Plan
    status: PlanStatus


class TaskEvent(BaseEvent):
    """Per-task transition event. The frontend uses these to update individual
    rows in the plan panel without rerendering the whole plan."""
    type: Literal["task"] = "task"
    task: Task
    status: TaskStatus


class BrowserToolContent(BaseModel):
    screenshot: str


class SearchToolContent(BaseModel):
    results: List[SearchResultItem]


class ShellToolContent(BaseModel):
    console: Any


class FileToolContent(BaseModel):
    content: str


class McpToolContent(BaseModel):
    result: Any


ToolContent = Union[
    BrowserToolContent,
    SearchToolContent,
    ShellToolContent,
    FileToolContent,
    McpToolContent,
]


class ToolEvent(BaseEvent):
    type: Literal["tool"] = "tool"
    tool_call_id: str
    tool_name: str
    tool_content: Optional[ToolContent] = None
    function_name: str
    function_args: Dict[str, Any]
    status: ToolStatus
    function_result: Optional[Any] = None


class TitleEvent(BaseEvent):
    type: Literal["title"] = "title"
    title: str


class MessageEvent(BaseEvent):
    type: Literal["message"] = "message"
    role: Literal["user", "assistant"] = "assistant"
    message: str
    attachments: Optional[List[FileInfo]] = None
    # Streaming: when the same logical assistant turn is emitted as multiple
    # MessageEvents (incremental text deltas), they share `message_id`. The
    # frontend replaces an existing bubble with the same id instead of
    # appending. The last emit for a turn carries `partial=False` so the FE
    # can lock in the final text.
    message_id: Optional[str] = None
    partial: bool = False


class DoneEvent(BaseEvent):
    type: Literal["done"] = "done"


class WaitEvent(BaseEvent):
    type: Literal["wait"] = "wait"


AgentEvent = Union[
    ErrorEvent,
    PlanEvent,
    TaskEvent,
    ToolEvent,
    MessageEvent,
    DoneEvent,
    TitleEvent,
    WaitEvent,
]
