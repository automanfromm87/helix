"""Pre-plan workspace surveyor.

Builds a short markdown brief of `/home/ubuntu/project/` so the planner can
reason about real file structure instead of guessing. Two steps:

1. **Collect raw context** via one `exec_command` call (heredoc shell
   script): directory tree + known manifests + README + top-level entry
   files. Cheap, deterministic, no LLM.
2. **Compress to markdown** with a single non-cached `complete_text` call.
   The prompt forces a compact form (top-level layout + one-line per
   directory + tech stack) so the result fits cleanly into the planner
   system prompt.

If the project dir is missing or empty, the surveyor short-circuits and
returns an empty string — the planner prompt then omits the workspace
section entirely instead of showing `(empty)`.

Failures are logged and swallowed: a survey error must never block
planning. The planner just falls back to the no-context behavior.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.domain.constants import SANDBOX_PROJECT_DIR
from app.domain.external.llm import LLM
from app.domain.external.sandbox import Sandbox

logger = logging.getLogger(__name__)


SURVEYOR_SHELL_ID = "_workspace_surveyor"

# Cap raw collection so a giant repo doesn't blow up the LLM call.
_MAX_RAW_CHARS = 12_000

_COLLECT_SCRIPT = r"""
set -u
PROJ="{project}"
if [ ! -d "$PROJ" ] || [ -z "$(ls -A "$PROJ" 2>/dev/null)" ]; then
  exit 0
fi

echo "=== TREE ==="
# Depth-limited listing, excluding the usual noise. find is portable;
# `tree` may not be installed in the sandbox base image.
find "$PROJ" -maxdepth 3 \
  \( -name node_modules -o -name .git -o -name __pycache__ \
     -o -name dist -o -name build -o -name .next -o -name .venv \
     -o -name venv -o -name target -o -name .pytest_cache \) -prune -o \
  -print 2>/dev/null | head -200

echo ""
echo "=== MANIFESTS ==="
for f in package.json pyproject.toml requirements.txt Cargo.toml go.mod \
         tsconfig.json setup.py setup.cfg Pipfile poetry.lock \
         pnpm-workspace.yaml turbo.json vite.config.ts vite.config.js; do
  if [ -f "$PROJ/$f" ]; then
    echo "--- $f ---"
    head -c 3000 "$PROJ/$f"
    echo ""
  fi
done

echo ""
echo "=== README ==="
for f in README.md README.MD readme.md README.rst README.txt README; do
  if [ -f "$PROJ/$f" ]; then
    echo "--- $f ---"
    head -n 80 "$PROJ/$f"
    break
  fi
done

echo ""
echo "=== ENTRY FILES ==="
for f in $(find "$PROJ" -maxdepth 3 \
            \( -name node_modules -o -name .git -o -name __pycache__ \
               -o -name dist -o -name build -o -name .next \
               -o -name .venv -o -name venv \) -prune -o \
            \( -name 'index.ts' -o -name 'index.tsx' -o -name 'index.js' \
               -o -name 'App.tsx' -o -name 'App.jsx' -o -name 'main.py' \
               -o -name 'main.ts' -o -name '__init__.py' -o -name 'app.py' \
               -o -name 'server.py' \) -print 2>/dev/null | head -10); do
  echo "--- $f ---"
  head -n 30 "$f"
  echo ""
done
""".strip()


_SUMMARIZE_SYSTEM = (
    "You are a senior engineer briefing a teammate on an unfamiliar repo. "
    "Output is read by a planner LLM that hasn't seen any code yet."
)


_SUMMARIZE_PROMPT_TEMPLATE = """Read the raw collected context below and produce a TIGHT markdown
workspace brief for a planning agent. The brief must:

- Start with one line: the project's apparent purpose (inferred from
  README/manifests).
- List the tech stack: language(s), framework(s), key libraries, build
  tool. One line.
- Show the top-level layout as a simple `dir/ — responsibility` list
  (max ~12 entries, only meaningful directories — skip caches/build).
- Mention any test framework + test directory if present.
- Stay under 350 words. No fluff, no preamble. Markdown only.

If the raw context is clearly NOT a code project (e.g. just docs, just
data), say so in one line and stop.

Raw context:
```
{raw}
```
"""


class WorkspaceSurveyor:
    """Builds the `<workspace_summary>` block injected into planner prompts."""

    def __init__(self, llm: LLM, *, model: Optional[str] = None) -> None:
        # Smaller/faster model is fine here — the brief is stylistic, not
        # reasoning-heavy. None = adapter's default model.
        self._llm = llm
        self._model = model

    async def summarize(self, sandbox: Sandbox) -> str:
        raw = await self._collect_raw(sandbox)
        if not raw.strip():
            return ""
        if len(raw) > _MAX_RAW_CHARS:
            raw = raw[:_MAX_RAW_CHARS] + "\n... (truncated)"
        try:
            brief = await self._llm.complete_text(
                _SUMMARIZE_PROMPT_TEMPLATE.format(raw=raw),
                system=_SUMMARIZE_SYSTEM,
                max_tokens=800,
                model=self._model,
            )
        except Exception:
            logger.exception("Workspace summarizer LLM call failed")
            return ""
        return brief.strip()

    async def _collect_raw(self, sandbox: Sandbox) -> str:
        try:
            result = await sandbox.exec_command(
                SURVEYOR_SHELL_ID,
                "/home/ubuntu",
                _COLLECT_SCRIPT.format(project=SANDBOX_PROJECT_DIR),
            )
        except Exception:
            logger.exception("Workspace surveyor exec_command failed")
            return ""
        if not result or not result.success or not result.data:
            return ""
        output = result.data.get("output") or ""
        return output if isinstance(output, str) else str(output)
