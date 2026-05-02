"""Retrieve toolkit — keyword search over session-attached Markdown.

Why this exists. Context files attached via Session Settings get folded
into the agent's `extra_system_prompt` on every turn. That works while
the corpus is small, but a 2 MB spec drag becomes wasteful — every turn
re-pays for the same prompt cache, and the model has to skim past
irrelevant sections just to find what it needs.

The retrieve tool gives the agent a focused alternative: "find the
N chunks of my reference docs most relevant to this query". Returns
filename-attributed snippets so the model can cite back. Pure keyword
match (no embeddings) — Markdown specs are usually small enough that
TF over heading/paragraph chunks works fine, and we avoid the
embedding-API dependency for v1.
"""

from __future__ import annotations

import re
from typing import List

from app.domain.models.tool_result import ToolResult
from app.domain.repositories.session_repository import SessionRepository
from app.domain.services.tools.base import BaseToolkit, tool


# Per-chunk size cap. Markdown sections that exceed this get split on
# paragraphs. Chosen so a top-5 retrieval lands well under 8 KB total
# tool_result, keeping the agent's response cycle quick.
_CHUNK_CHAR_CAP = 1500


def _split_chunks(text: str) -> List[str]:
    """Split a Markdown doc into retrieval-sized chunks. Prefers
    sections (split on `#`/`##`/`###` headings) so each chunk is
    semantically coherent. Big sections fall back to paragraph splits;
    very long paragraphs are hard-truncated."""
    sections = re.split(r"(?m)^(?=#{1,3}\s)", text)
    chunks: List[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(section) <= _CHUNK_CHAR_CAP:
            chunks.append(section)
            continue
        for para in re.split(r"\n\s*\n", section):
            para = para.strip()
            if not para:
                continue
            chunks.append(para[:_CHUNK_CHAR_CAP])
    return chunks


def _terms(query: str) -> List[str]:
    """Tokenize the query: lowercase word chars, drop 1-letter noise."""
    return [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]


def _score(chunk: str, terms: List[str]) -> int:
    """Sum of (case-insensitive) occurrences of each term in `chunk`.

    Naive TF — no IDF, no stemming. Good enough when the corpus is
    one user's spec docs; if multiple files all use the same jargon
    they'll get equal weight, but that's acceptable since the agent
    sees filename attribution and can reason about source.
    """
    chunk_lower = chunk.lower()
    return sum(chunk_lower.count(t) for t in terms)


class RetrieveToolkit(BaseToolkit):
    """Lazy keyword retrieval over the session's attached context files.

    Files are looked up at *call* time (not construction) so newly-added
    docs become searchable mid-session without restarting the agent.
    """

    name: str = "retrieve"

    def __init__(
        self, session_id: str, session_repository: SessionRepository,
    ) -> None:
        self._session_id = session_id
        self._session_repository = session_repository
        super().__init__()

    @tool
    async def retrieve(self, query: str, top_k: int = 5) -> ToolResult:
        """Search the user's attached reference documents for the N most
        relevant Markdown chunks. Use when looking up a specific topic
        in attached specs/docs — cheaper than re-reading whole files,
        and the user explicitly attached these so they want them used.

        Each result is annotated with its source filename so you can
        cite back precisely (e.g. "per spec.md, the modal should …").

        Args:
            query: 3-7 keywords describing what you're looking for.
                Phrases work better than full sentences.
            top_k: Max chunks to return. Default 5; raise if you need
                broader coverage, lower if you're sure of a single hit.
        """
        terms = _terms(query)
        if not terms:
            return ToolResult(
                success=False,
                message="query must contain at least one word of length ≥ 2",
            )

        files = await self._session_repository.list_context_files(self._session_id)
        if not files:
            return ToolResult(
                success=True,
                data="No context files are attached to this session.",
            )

        scored: List[tuple[int, str, str]] = []
        for f in files:
            for chunk in _split_chunks(f.content):
                s = _score(chunk, terms)
                if s > 0:
                    scored.append((s, f.filename, chunk))
        scored.sort(key=lambda x: -x[0])

        top = scored[: max(1, min(top_k, 20))]
        if not top:
            return ToolResult(
                success=True,
                data=f"No matches for query: {query!r}",
            )

        formatted = "\n\n---\n\n".join(
            f"**[{filename}]** (score={score})\n\n{chunk}"
            for score, filename, chunk in top
        )
        return ToolResult(success=True, data=formatted)
