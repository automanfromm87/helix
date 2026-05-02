from typing import List, Optional, Union
from app.domain.services.tools.base import BaseToolkit, tool
from app.domain.models.tool_result import ToolResult


# The single source of truth for the tool name that pauses the agent loop
# until the user replies. Imported by base.py + execution.py instead of
# stringly-typing the name in three places.
ASK_USER_TOOL = "message_ask_user"


class MessageToolkit(BaseToolkit):
    """Message tool class, providing message sending functions for user interaction"""

    name: str = "message"
    
    def __init__(self):
        """Initialize message tool class"""
        super().__init__()

    @tool
    async def message_notify_user(
        self,
        text: str
    ) -> ToolResult:
        """Send a message to user without requiring a response. Use for acknowledging receipt of messages, providing progress updates, reporting task completion, or explaining changes in approach.
        
        Args:
            text: Message text to display to user
        """
            
        # Return success result, actual UI display logic implemented by caller
        return ToolResult(success=True, message="OK")
    
    @tool
    async def message_ask_user(
        self,
        text: str,
        options: Optional[List[str]] = None,
        attachments: Optional[Union[str, List[str]]] = None,
        suggest_user_takeover: Optional[str] = None
    ) -> ToolResult:
        """Ask user a question and wait for response. Use for requesting clarification, asking for confirmation, or gathering additional information.

        STRONGLY PREFER providing `options` whenever the answer space is
        discrete (2-5 distinct choices). The UI renders one click-to-send
        button per option, removing the need for the user to retype your
        wording. Free-form replies remain valid even when options are
        present — the user can ignore the buttons and type whatever.

        Args:
            text: Question text to present to user. State the question
                clearly and let `options` carry the actual choices —
                don't repeat the option labels in `text`.
            options: (Optional) Discrete answer choices, 2-5 entries.
                Each entry is the literal label shown on a button AND
                the literal text submitted as the user's reply when
                clicked, so write them as direct first-person answers
                (e.g. "Honor the brief — remove search" rather than
                "Option 1: honor the brief").
            attachments: (Optional) List of question-related files or reference materials
            suggest_user_takeover: (Optional) Suggested operation for user takeover (enum: "none" or "browser")
        """

        # Return success result, actual UI interaction logic implemented by caller
        return ToolResult(success=True)
