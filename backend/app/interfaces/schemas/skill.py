"""Wire schemas for the skill CRUD API."""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.domain.models.skill import Skill


# Where the served skill came from in the resolved layer stack. Lets the FE
# disable edits on read-only file-based skills and badge global overrides.
SkillSource = Literal["file", "global", "project"]


class SkillItem(BaseModel):
    name: str
    description: str
    body: str
    source: SkillSource

    @classmethod
    def from_skill(cls, skill: Skill, *, source: SkillSource) -> "SkillItem":
        return cls(
            name=skill.name,
            description=skill.description,
            body=skill.body,
            source=source,
        )


class ListSkillsResponse(BaseModel):
    skills: List[SkillItem]


class UpsertSkillRequest(BaseModel):
    description: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)


class UpsertSkillResponse(BaseModel):
    skill: SkillItem


class GetSkillResponse(BaseModel):
    skill: Optional[SkillItem] = None
