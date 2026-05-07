"""Port for the project's version-control system — the layer that
records "this is what the project looked like at the end of plan X".

The plan_act flow needs to commit a snapshot of the sandbox project
directory whenever a plan completes (so the FE can show "v3 · abc123"
+ diff/restore). It used to import `commit_plan` directly from
`infrastructure.external.git.plan_versioning`, breaking the layer
direction. Now it depends on this Protocol; the actual git invocation
lives in the matching adapter.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol


@dataclass(frozen=True)
class CommitInfo:
    """Result of a successful `commit_plan` call.

    Mirrors the shape used by the existing git adapter; kept in domain
    so callers don't reach into infrastructure for a result type.
    """

    sha: str
    short_sha: str
    files_changed: int


class VersionControl(Protocol):
    """Snapshot a project directory after a plan finishes."""

    async def commit_plan(
        self,
        project_path: Path,
        plan_id: str,
        plan_title: str,
    ) -> Optional[CommitInfo]:
        """Stage every change under `project_path`, commit + tag if
        anything changed, otherwise return None.

        The tag name convention is the adapter's choice (the existing
        git adapter uses `helix/plan/<short_plan_id>`). Caller updates
        the Plan row's `commit_sha` from the return value.
        """
        ...
