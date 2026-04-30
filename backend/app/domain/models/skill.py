"""Skill — a chunk of domain expertise the agent can pull on demand.

Modeled after Claude Code's "skill" feature: each skill is a markdown file
with YAML frontmatter, the body holds the actual knowledge, and the agent
loads the body lazily by calling a `load_skill` tool. Only the index
(name + short description) lives in the system prompt; the heavy body
enters context only when the model decides it's relevant.

File format:

    ---
    name: react-testing
    description: |
      React Testing Library best practices.
      Use when writing or fixing React component tests.
    ---
    # React Testing Library

    ## Query priority
    ...

The `description` is what the model sees in the index — it's effectively
the trigger condition. The body should be self-contained reference text;
agent loops will treat its tool_result as a normal message turn.
"""

from __future__ import annotations

from typing import Tuple

from pydantic import BaseModel, Field


class Skill(BaseModel):
    """One unit of domain knowledge."""

    name: str
    description: str
    body: str
    # Where the file came from. Used for logging + future hot-reload.
    source_path: str = Field(default="")


class SkillParseError(ValueError):
    """Raised when a `SKILL.md` file is missing/malformed frontmatter."""


def parse_skill_file(text: str, *, source_path: str = "") -> Skill:
    """Parse `---` YAML frontmatter + markdown body into a `Skill`.

    Frontmatter MUST contain `name` and `description`. Body is everything
    after the closing `---` line; whitespace at the top is trimmed.
    """
    meta, body = _split_frontmatter(text)
    name = (meta.get("name") or "").strip()
    description = (meta.get("description") or "").strip()
    if not name:
        raise SkillParseError(f"skill at {source_path or '?'} has no `name`")
    if not description:
        raise SkillParseError(f"skill {name} has no `description`")
    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        source_path=source_path,
    )


_DELIM = "---"


def _split_frontmatter(text: str) -> Tuple[dict, str]:
    """Hand-rolled YAML-subset parser for frontmatter — supports the two
    forms we actually use: scalar `key: value` and block-scalar `key: |`
    followed by indented lines. Avoids a pyyaml dependency."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != _DELIM:
        raise SkillParseError("missing leading `---` frontmatter delimiter")
    end_idx = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == _DELIM:
            end_idx = i
            break
    if end_idx < 0:
        raise SkillParseError("missing closing `---` frontmatter delimiter")
    body = "\n".join(lines[end_idx + 1:])
    meta = _parse_simple_yaml(lines[1:end_idx])
    return meta, body


def _parse_simple_yaml(lines: list[str]) -> dict:
    """Parse `key: value` mappings with optional `key: |` block scalars.
    Anything fancier (anchors, lists, nested maps) is rejected loudly."""
    out: dict = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if ":" not in line:
            raise SkillParseError(f"unparseable frontmatter line: {line!r}")
        key, _, rest = line.partition(":")
        key = key.strip()
        rest = rest.strip()
        if not key:
            raise SkillParseError(f"empty key in line: {line!r}")
        if rest in ("|", ">"):
            # Block scalar: collect indented continuation lines.
            i += 1
            indent: int | None = None
            block_lines: list[str] = []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    block_lines.append("")
                    i += 1
                    continue
                lead = len(nxt) - len(nxt.lstrip())
                if indent is None:
                    indent = lead if lead > 0 else 1
                if lead < indent:
                    break
                block_lines.append(nxt[indent:])
                i += 1
            sep = "\n" if rest == "|" else " "
            out[key] = sep.join(block_lines).rstrip()
            continue
        # Strip surrounding quotes if any.
        if (rest.startswith('"') and rest.endswith('"')) or (
            rest.startswith("'") and rest.endswith("'")
        ):
            rest = rest[1:-1]
        out[key] = rest
        i += 1
    return out
