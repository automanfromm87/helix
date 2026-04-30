from pydantic import BaseModel, Field
from typing import Any, Union, Literal, Dict, Optional, List, Self, Type
from datetime import datetime
from dataclasses import dataclass

from app.domain.models.plan import PlanStatus, TaskStatus
from app.interfaces.schemas.file import FileInfoResponse
from app.domain.models.event import ToolStatus, ToolContent, BrowserToolContent
from app.domain.models.event import (
    AgentEvent,
    ErrorEvent,
    PlanEvent,
    TaskEvent,
    MessageEvent,
    TitleEvent,
    ToolEvent,
)


class BaseEventData(BaseModel):
    event_id: Optional[str]
    timestamp: datetime = Field(default_factory=lambda: datetime.now())

    class Config:
        json_encoders = {
            datetime: lambda v: int(v.timestamp())
        }

    @classmethod
    def base_event_data(cls, event: AgentEvent) -> dict:
        return {
            "event_id": event.id,
            "timestamp": int(event.timestamp.timestamp()),
        }

    @classmethod
    def from_event(cls, event: AgentEvent) -> Self:
        return cls(
            **cls.base_event_data(event),
            **event.model_dump(exclude={"type", "id", "timestamp"}),
        )


class CommonEventData(BaseEventData):
    class Config:
        json_encoders = {
            datetime: lambda v: int(v.timestamp())
        }
        extra = "allow"


class BaseSSEEvent(BaseModel):
    event: str
    data: BaseEventData

    @classmethod
    def from_event(cls, event: AgentEvent) -> Self:
        data_class: Type[BaseEventData] = cls.__annotations__.get('data', BaseEventData)
        return cls(
            event=event.type,
            data=data_class.from_event(event),
        )


class MessageEventData(BaseEventData):
    role: Literal["user", "assistant"]
    content: str
    attachments: Optional[List[FileInfoResponse]] = None
    # Streaming: shared by partial+final emissions of the same logical
    # assistant turn. FE replaces an existing bubble with the same id.
    message_id: Optional[str] = None
    partial: bool = False


class MessageSSEEvent(BaseSSEEvent):
    event: Literal["message"] = "message"
    data: MessageEventData

    @classmethod
    async def from_event_async(cls, event: MessageEvent) -> Self:
        return cls(
            data=MessageEventData(
                **BaseEventData.base_event_data(event),
                role=event.role,
                content=event.message,
                attachments=[await FileInfoResponse.from_file_info(attachment) for attachment in event.attachments] if event.attachments else None,
                message_id=event.message_id,
                partial=event.partial,
            )
        )


class ToolEventData(BaseEventData):
    tool_call_id: str
    name: str
    status: ToolStatus
    function: str
    args: Dict[str, Any]
    content: Optional[ToolContent] = None


class ToolSSEEvent(BaseSSEEvent):
    event: Literal["tool"] = "tool"
    data: ToolEventData

    @classmethod
    async def from_event_async(cls, event: ToolEvent) -> Self:
        content = event.tool_content
        if isinstance(content, BrowserToolContent):
            from app.interfaces.dependencies import get_file_service
            file_service = get_file_service()
            content = BrowserToolContent(
                screenshot=await file_service.create_signed_url(
                    content.screenshot,
                    expire_minutes=file_service.EMBEDDED_SIGNED_URL_MINUTES,
                    internal=True,
                )
            )
        return cls(
            data=ToolEventData(
                **BaseEventData.base_event_data(event),
                tool_call_id=event.tool_call_id,
                name=event.tool_name,
                status=event.status,
                function=event.function_name,
                args=event.function_args,
                content=content,
            )
        )


class DoneSSEEvent(BaseSSEEvent):
    event: Literal["done"] = "done"


class WaitSSEEvent(BaseSSEEvent):
    event: Literal["wait"] = "wait"


class ErrorEventData(BaseEventData):
    error: str


class ErrorSSEEvent(BaseSSEEvent):
    event: Literal["error"] = "error"
    data: ErrorEventData


class TaskEventData(BaseEventData):
    task_id: str
    plan_id: str
    position: int
    title: str
    details: Optional[str] = None
    status: TaskStatus
    result: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0


class TaskSSEEvent(BaseSSEEvent):
    event: Literal["task"] = "task"
    data: TaskEventData

    @classmethod
    def from_event(cls, event: TaskEvent) -> Self:
        return cls(
            data=TaskEventData(
                **BaseEventData.base_event_data(event),
                task_id=event.task.id,
                plan_id=event.task.plan_id,
                position=event.task.position,
                title=event.task.title,
                details=event.task.details,
                status=event.status,
                result=event.task.result,
                error=event.task.error,
                retries=event.task.retries,
            )
        )


class TitleEventData(BaseEventData):
    title: str


class TitleSSEEvent(BaseSSEEvent):
    event: Literal["title"] = "title"
    data: TitleEventData


class PlanEventData(BaseEventData):
    plan_id: str
    title: str
    goal: str
    status: PlanStatus
    error: Optional[str] = None
    tasks: List[TaskEventData]


class PlanSSEEvent(BaseSSEEvent):
    event: Literal["plan"] = "plan"
    data: PlanEventData

    @classmethod
    def from_event(cls, event: PlanEvent) -> Self:
        return cls(
            data=PlanEventData(
                **BaseEventData.base_event_data(event),
                plan_id=event.plan.id,
                title=event.plan.title,
                goal=event.plan.goal,
                status=event.status,
                error=event.plan.error,
                tasks=[
                    TaskEventData(
                        **BaseEventData.base_event_data(event),
                        task_id=t.id,
                        plan_id=t.plan_id,
                        position=t.position,
                        title=t.title,
                        details=t.details,
                        status=t.status,
                        result=t.result,
                        error=t.error,
                        retries=t.retries,
                    )
                    for t in sorted(event.plan.tasks, key=lambda t: t.position)
                ],
            )
        )


class CommonSSEEvent(BaseSSEEvent):
    event: str
    data: CommonEventData


AgentSSEEvent = Union[
    CommonEventData,
    PlanSSEEvent,
    TaskSSEEvent,
    MessageSSEEvent,
    TitleSSEEvent,
    ToolSSEEvent,
    DoneSSEEvent,
    ErrorSSEEvent,
    WaitSSEEvent,
]


@dataclass
class EventMapping:
    sse_event_class: Type[BaseEventData]
    data_class: Type[BaseEventData]
    event_type: str


class EventMapper:
    """Map AgentEvent to SSEEvent"""

    _cached_mapping: Optional[Dict[str, EventMapping]] = None

    @staticmethod
    def _get_event_type_mapping() -> Dict[str, EventMapping]:
        if EventMapper._cached_mapping is not None:
            return EventMapper._cached_mapping

        from typing import get_args

        sse_event_classes = get_args(AgentSSEEvent)
        mapping = {}
        for sse_event_class in sse_event_classes:
            if sse_event_class == BaseSSEEvent:
                continue
            if hasattr(sse_event_class, '__annotations__') and 'event' in sse_event_class.__annotations__:
                event_field = sse_event_class.__annotations__['event']
                if hasattr(event_field, '__args__') and len(event_field.__args__) > 0:
                    event_type = event_field.__args__[0]
                    data_class = None
                    if hasattr(sse_event_class, '__annotations__') and 'data' in sse_event_class.__annotations__:
                        data_class = sse_event_class.__annotations__['data']
                    mapping[event_type] = EventMapping(
                        sse_event_class=sse_event_class,
                        data_class=data_class,
                        event_type=event_type,
                    )
        EventMapper._cached_mapping = mapping
        return mapping

    @staticmethod
    async def event_to_sse_event(event: AgentEvent) -> AgentSSEEvent:
        event_type_mapping = EventMapper._get_event_type_mapping()
        event_mapping = event_type_mapping.get(event.type)
        if event_mapping:
            sse_event_class = event_mapping.sse_event_class
            if hasattr(sse_event_class, 'from_event_async'):
                return await sse_event_class.from_event_async(event)
            return sse_event_class.from_event(event)
        return CommonEventData.from_event(event)

    @staticmethod
    async def events_to_sse_events(events: List[AgentEvent]) -> List[AgentSSEEvent]:
        return list(filter(lambda x: x is not None, [
            await EventMapper.event_to_sse_event(event) for event in events if event
        ]))
