"""Skill toolkit — exposes the lazy-load interface to the agent.

Surfaces a single tool, `load_skill(name)`, whose tool_result carries the
full markdown body of the requested skill. The body lands in memory on
the next turn and gets cached server-side via the existing 3-tier cache
breakpoints, so subsequent turns reading the same skill pay near-zero.
"""

from __future__ import annotations

from typing import List, Optional

from app.domain.models.skill import Skill
from app.domain.models.tool_result import ToolResult
from app.domain.repositories.skill_repository import SkillRepository
from app.domain.services.tools.base import BaseToolkit, tool


# Toolkit name reused by `agents/base.py` to bypass the per-tool_result
# truncation guard — a partial skill body is worse than no skill at all.
SKILL_TOOLKIT_NAME = "skill"
LOAD_SKILL_TOOL = "load_skill"


class SkillToolkit(BaseToolkit):
    """Lazy domain-knowledge loader."""

    name: str = SKILL_TOOLKIT_NAME

    def __init__(self, repository: SkillRepository) -> None:
        self._repository = repository
        super().__init__()

    @tool
    async def load_skill(self, name: str) -> ToolResult:
        """Load a skill's full body into the conversation. Use this when the
        current task falls into the skill's domain (see the skill index in
        the system prompt). Don't pre-load skills speculatively — only when
        you're about to act in that domain.

        Args:
            name: Exact skill name from the index (e.g. "react-testing").
        """
        skill = self._repository.get(name)
        if skill is None:
            available = ", ".join(self._repository.names()) or "(none)"
            return ToolResult(
                success=False,
                message=f"Unknown skill {name!r}. Available: {available}",
            )
        return ToolResult(success=True, data=skill.body)


def render_skill_index(repository: SkillRepository) -> str:
    """Build the `<available_skills>` block we splice into the system prompt.

    Returns an empty string when the registry is empty so callers can append
    unconditionally without worrying about a dangling header.
    """
    skills = repository.list()
    if not skills:
        return ""
    lines = [
        "<available_skills>",
        f"Domain knowledge libraries you can pull on demand via the "
        f"`{LOAD_SKILL_TOOL}` tool. The body becomes available on the next "
        "turn and stays in context for the rest of the task. Only load a "
        "skill when the work falls into its domain — don't load all of them.",
        "",
    ]
    for skill in skills:
        # One-line summary; keep total index small so it doesn't dominate
        # system_prompt token budget.
        first_line = skill.description.strip().splitlines()[0]
        lines.append(f"- **{skill.name}** — {first_line}")
    lines.append("</available_skills>")
    return "\n".join(lines)
