from typing import Any, Dict, List
from pydantic import BaseModel, Field

class Message(BaseModel):
    message: str = ""
    attachments: List[str] = []
    # Pre-built Anthropic image content blocks (base64 inline). Populated by
    # the runner from image-MIME attachments before the message reaches an
    # agent — keeps the agent layer free of file_storage dependency.
    image_blocks: List[Dict[str, Any]] = Field(default_factory=list)