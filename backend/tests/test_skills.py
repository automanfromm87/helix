"""Tests for the skill registry + load_skill tool path."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models.skill import Skill, SkillParseError, parse_skill_file
from app.domain.services.skills import LayeredSkillRepository
from app.domain.services.tools.skill import (
    LOAD_SKILL_TOOL,
    SkillToolkit,
    render_skill_index,
)
from app.infrastructure.skills.file_skill_repository import FileSkillRepository


# ---------------------------------------------------------------------------
# parse_skill_file
# ---------------------------------------------------------------------------


def test_parse_minimal_skill() -> None:
    text = (
        "---\n"
        "name: foo\n"
        "description: short\n"
        "---\n"
        "# Body heading\n"
        "Body line.\n"
    )
    skill = parse_skill_file(text, source_path="/tmp/foo/SKILL.md")
    assert skill.name == "foo"
    assert skill.description == "short"
    assert "# Body heading" in skill.body
    assert skill.source_path == "/tmp/foo/SKILL.md"


def test_parse_multiline_description() -> None:
    text = (
        "---\n"
        "name: bar\n"
        "description: |\n"
        "  Multi-line summary.\n"
        "  Second line.\n"
        "---\n"
        "Body.\n"
    )
    skill = parse_skill_file(text)
    assert "Multi-line summary." in skill.description
    assert "Second line." in skill.description


def test_parse_missing_frontmatter_raises() -> None:
    with pytest.raises(SkillParseError):
        parse_skill_file("# just a body\n")


def test_parse_unterminated_frontmatter_raises() -> None:
    with pytest.raises(SkillParseError):
        parse_skill_file("---\nname: x\n# body without closing delimiter\n")


def test_parse_missing_name_raises() -> None:
    text = "---\ndescription: x\n---\nBody.\n"
    with pytest.raises(SkillParseError):
        parse_skill_file(text)


def test_parse_missing_description_raises() -> None:
    text = "---\nname: x\n---\nBody.\n"
    with pytest.raises(SkillParseError):
        parse_skill_file(text)


# ---------------------------------------------------------------------------
# FileSkillRepository
# ---------------------------------------------------------------------------


def _write_skill(root: Path, name: str, description: str, body: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8",
    )


def test_repository_loads_all_valid_skills(tmp_path: Path) -> None:
    _write_skill(tmp_path, "alpha", "A skill", "alpha body")
    _write_skill(tmp_path, "beta", "Another skill", "beta body")
    repo = FileSkillRepository(root=tmp_path)
    assert sorted(repo.names()) == ["alpha", "beta"]
    assert repo.get("alpha").body == "alpha body"


def test_repository_skips_broken_skill(tmp_path: Path, caplog) -> None:
    _write_skill(tmp_path, "good", "ok", "body")
    bad = tmp_path / "broken"
    bad.mkdir()
    (bad / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")
    repo = FileSkillRepository(root=tmp_path)
    assert repo.names() == ["good"]


def test_repository_handles_missing_root(tmp_path: Path) -> None:
    """No skills/ directory at all → empty registry, no exception."""
    missing = tmp_path / "nope"
    repo = FileSkillRepository(root=missing)
    assert repo.list() == []


# ---------------------------------------------------------------------------
# SkillToolkit
# ---------------------------------------------------------------------------


class _StubRepo:
    def __init__(self, skills: dict[str, Skill]) -> None:
        self._skills = skills

    def list(self):
        return list(self._skills.values())

    def get(self, name):
        return self._skills.get(name)

    def names(self):
        return sorted(self._skills)


@pytest.mark.asyncio
async def test_load_skill_returns_body() -> None:
    skill = Skill(name="x", description="Use when…", body="full body content")
    toolkit = SkillToolkit(_StubRepo({"x": skill}))
    tool = toolkit.get_tool(LOAD_SKILL_TOOL)
    assert tool is not None
    result = await tool.ainvoke({"name": "x"})
    assert result.success is True
    assert result.data == "full body content"


@pytest.mark.asyncio
async def test_load_unknown_skill_lists_available() -> None:
    skill = Skill(name="x", description="d", body="body")
    toolkit = SkillToolkit(_StubRepo({"x": skill}))
    tool = toolkit.get_tool(LOAD_SKILL_TOOL)
    result = await tool.ainvoke({"name": "missing"})
    assert result.success is False
    assert "x" in (result.message or "")


# ---------------------------------------------------------------------------
# render_skill_index
# ---------------------------------------------------------------------------


def test_render_index_empty_registry() -> None:
    assert render_skill_index(_StubRepo({})) == ""


def test_render_index_one_line_per_skill() -> None:
    repo = _StubRepo(
        {
            "a": Skill(name="a", description="first line\nsecond line", body=""),
            "b": Skill(name="b", description="just one line", body=""),
        }
    )
    out = render_skill_index(repo)
    # Header + body + closer.
    assert "<available_skills>" in out
    assert "</available_skills>" in out
    # Each skill: only the first line of description is included.
    assert "**a** — first line" in out
    assert "second line" not in out
    assert "**b** — just one line" in out


# ---------------------------------------------------------------------------
# LayeredSkillRepository
# ---------------------------------------------------------------------------


def _skill(name: str, body: str = "body", description: str = "d") -> Skill:
    return Skill(name=name, description=description, body=body)


def test_layered_falls_back_to_base() -> None:
    base = _StubRepo({"a": _skill("a", "base body")})
    layered = LayeredSkillRepository(base=base)
    assert layered.get("a").body == "base body"
    assert layered.names() == ["a"]


def test_layered_global_override_shadows_base() -> None:
    base = _StubRepo({"a": _skill("a", "file body"), "b": _skill("b", "file b")})
    layered = LayeredSkillRepository(
        base=base,
        global_overrides=[_skill("a", "global body")],
    )
    assert layered.get("a").body == "global body"
    assert layered.get("b").body == "file b"


def test_layered_project_override_beats_global() -> None:
    base = _StubRepo({"a": _skill("a", "file body")})
    layered = LayeredSkillRepository(
        base=base,
        global_overrides=[_skill("a", "global body")],
        project_overrides=[_skill("a", "project body")],
    )
    assert layered.get("a").body == "project body"


def test_layered_unique_names_merged() -> None:
    base = _StubRepo({"a": _skill("a")})
    layered = LayeredSkillRepository(
        base=base,
        global_overrides=[_skill("b")],
        project_overrides=[_skill("c")],
    )
    assert layered.names() == ["a", "b", "c"]
    assert len(layered.list()) == 3


def test_layered_returns_sorted_list() -> None:
    base = _StubRepo({"z": _skill("z"), "a": _skill("a")})
    layered = LayeredSkillRepository(base=base)
    assert [s.name for s in layered.list()] == ["a", "z"]
