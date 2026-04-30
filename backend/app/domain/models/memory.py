from typing import List, Optional

from pydantic import BaseModel

from app.domain.models.conv_message import (
    ConvMessage,
    ToolResultBlock,
    ToolUseBlock,
)


class Memory(BaseModel):
    """Per-agent conversation memory, in Anthropic's native message shape."""

    messages: List[ConvMessage] = []

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_message(self, message: ConvMessage) -> None:
        self.messages.append(message)

    def get_messages(self) -> List[ConvMessage]:
        return self.messages

    def get_last_message(self) -> Optional[ConvMessage]:
        return self.messages[-1] if self.messages else None

    def roll_back(self) -> None:
        if self.messages:
            self.messages = self.messages[:-1]

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------

    def close_dangling_tool_uses(self, message: str) -> int:
        """Append synthetic is_error tool_results for any tool_use in the
        last assistant turn that doesn't yet have a matching tool_result.

        Returns the number of tool_uses closed. Used by the startup reaper
        when a session's process died mid-tool-call: without this, the next
        Anthropic API call rejects the conversation as malformed.
        """
        last = self.get_last_message()
        if not last or last.role != "assistant":
            return 0
        pending = [b for b in last.content if isinstance(b, ToolUseBlock)]
        if not pending:
            return 0
        # If the very next message already supplies tool_results, we're fine.
        # That's not actually possible here (last_message IS the assistant
        # turn), but keep the guard for clarity.
        results = [
            ToolResultBlock(tool_use_id=b.id, content=message, is_error=True)
            for b in pending
        ]
        self.messages.append(ConvMessage(role="user", content=list(results)))
        return len(results)
