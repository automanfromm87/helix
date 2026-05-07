"""Vendor dispatch for the sandbox container runtime.

`Sandbox` is a Protocol (`app.domain.external.sandbox`); concrete
implementations live alongside this module. The single entry point
`get_sandbox_cls()` reads `settings.sandbox_vendor` and returns the
class that satisfies the Protocol — the rest of the codebase
(`SandboxRegistry`, `AgentService`, the orphan reaper in `main.py`)
treats the result structurally and never imports a concrete class.

Imports of vendor modules are lazy so that selecting docker doesn't
pull in podman code paths and vice versa.
"""

from __future__ import annotations

from typing import Type

from app.core.config import get_settings
from app.domain.external.sandbox import Sandbox


def get_sandbox_cls() -> Type[Sandbox]:
    """Return the Sandbox implementation class selected by configuration.

    Raises ValueError on an unknown vendor — fail loud at the wiring
    layer rather than silently falling back to docker, which would
    surprise operators who set the env var expecting podman.
    """
    vendor = (get_settings().sandbox_vendor or "docker").strip().lower()
    if vendor == "docker":
        from app.infrastructure.external.sandbox.docker_sandbox import DockerSandbox
        return DockerSandbox
    if vendor == "podman":
        from app.infrastructure.external.sandbox.podman_sandbox import PodmanSandbox
        return PodmanSandbox
    raise ValueError(
        f"Unknown sandbox_vendor {vendor!r}; expected 'docker' or 'podman'"
    )
