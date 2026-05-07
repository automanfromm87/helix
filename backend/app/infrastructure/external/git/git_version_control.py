"""Adapter implementing the domain `VersionControl` Protocol via git.

Wraps the existing module-level functions in `plan_versioning` as a
class so the domain layer can hold an injected dependency instead of
importing the function directly. The functions themselves stay where
they are — they're also called from the application layer (project
fork / restore endpoints) which is allowed to depend on infrastructure.
"""

from pathlib import Path
from typing import Optional

from app.domain.external.version_control import CommitInfo, VersionControl
from app.infrastructure.external.git import plan_versioning as _pv


class GitVersionControl(VersionControl):
    """Default `VersionControl` adapter — shells out to git."""

    async def commit_plan(
        self,
        project_path: Path,
        plan_id: str,
        plan_title: str,
    ) -> Optional[CommitInfo]:
        result = await _pv.commit_plan(project_path, plan_id, plan_title)
        if result is None:
            return None
        # The infrastructure module ships its own CommitInfo dataclass
        # for legacy reasons; remap to the domain-side one so callers
        # that type-annotate against the Protocol don't have to know
        # about the infra type.
        return CommitInfo(
            sha=result.sha,
            short_sha=result.short_sha,
            files_changed=result.files_changed,
        )
