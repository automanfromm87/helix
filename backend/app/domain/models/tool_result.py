from pydantic import BaseModel
from typing import Any, Optional, TypeVar, Generic

T = TypeVar('T')


# Stable error codes set on `ToolResult.code` so callers can branch
# without substring-matching on `message`. Add new entries as needed.
TOOL_RESULT_SANDBOX_UNAVAILABLE = "sandbox_unavailable"


class ToolResult(BaseModel, Generic[T]):
    success: bool
    message: Optional[str] = None
    data: Optional[T] = None
    # Optional structured error code for failed results — lets the FE/agent
    # branch without parsing English error text. Free-form so toolkits can
    # introduce their own codes.
    code: Optional[str] = None
