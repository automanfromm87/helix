"""Filesystem-backed `Skill` registry.

Scans a single root directory for `*/SKILL.md` files at startup and keeps
the parsed skills in memory. Hot-reload is intentionally NOT implemented in
this iteration — restart the backend to pick up new skills.

Layout:

    backend/skills/
      react-testing/
        SKILL.md
      fastapi-patterns/
        SKILL.md
      ...

Skills with parse errors are logged and skipped, never raise — a single
broken skill mustn't stall backend startup.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.domain.models.skill import Skill, SkillParseError, parse_skill_file

logger = logging.getLogger(__name__)


# Backend repo root → backend/skills/. The path resolves relative to this
# file's location so it works regardless of cwd.
_DEFAULT_SKILLS_ROOT = Path(__file__).resolve().parents[3] / "skills"


class FileSkillRepository:
    """In-memory snapshot of all skills found under the skills root."""

    def __init__(self, root: Optional[Path] = None) -> None:
        self._root = (root or _DEFAULT_SKILLS_ROOT).resolve()
        self._skills: Dict[str, Skill] = {}
        self._load()

    def _load(self) -> None:
        if not self._root.is_dir():
            logger.info("No skills directory at %s; running with zero skills", self._root)
            return
        for skill_dir in sorted(self._root.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
                skill = parse_skill_file(text, source_path=str(skill_file))
            except (SkillParseError, OSError) as e:
                logger.warning("Skipping invalid skill at %s: %s", skill_file, e)
                continue
            if skill.name in self._skills:
                logger.warning(
                    "Duplicate skill name %r at %s — keeping first",
                    skill.name, skill_file,
                )
                continue
            self._skills[skill.name] = skill
        logger.info(
            "Loaded %d skill(s) from %s: %s",
            len(self._skills), self._root, sorted(self._skills),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def names(self) -> List[str]:
        return sorted(self._skills)
