"""Podman-backed Sandbox implementation.

Copy of `docker_sandbox.py` adapted to talk to podman's Docker-compatible
REST API. We keep using the official `docker` Python SDK because podman
implements the Docker API faithfully — only the socket URL changes. This
avoids adding `podman-py` as a new dependency.

Differences vs DockerSandbox:
  - All client construction goes through `_get_podman_client()` instead
    of `docker.from_env()`. When `settings.sandbox_podman_socket` is set,
    we use it explicitly; otherwise we fall through to `docker.from_env()`,
    which honors `DOCKER_HOST` and defaults to `/var/run/docker.sock`.
    The simplest deployment is to bind-mount the podman socket at
    `/var/run/docker.sock` inside the backend container and leave the
    setting empty.
  - Container labels carry `helix.runtime: "podman"` so a docker-and-
    podman side-by-side environment doesn't reap each other's orphans.
  - Reap orphan filter narrows on `helix.runtime=podman` to match.

Everything else is line-for-line identical to DockerSandbox.
"""

from typing import Dict, Any, Optional, List, BinaryIO, Awaitable, Callable
import uuid
import httpx
import docker
import socket
import logging
import asyncio
import io
from async_lru import alru_cache  # only used for DNS resolution caching
from app.core.config import get_settings
from app.application.errors.exceptions import SandboxUnavailableError
from app.domain.models.tool_result import ToolResult
from app.domain.external.sandbox import Sandbox
from app.infrastructure.external.browser.cdp_browser import CDPBrowser
from app.domain.external.browser import Browser

logger = logging.getLogger(__name__)


# httpx exceptions that mean "we never got bytes on the wire" — DNS failure,
# refused connection, connect timeout. These are deterministic indicators
# that the sandbox container is stopped or networking is broken; they
# should NOT be retried inside the agent loop and SHOULD surface to the FE
# as 503. ReadTimeout / WriteTimeout are excluded because those mean the
# sandbox accepted the request but is slow — different failure mode.
_TRANSPORT_DOWN_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
)


def _get_podman_client() -> docker.DockerClient:
    """Return a `docker.DockerClient` pointed at the podman REST socket.

    When `settings.sandbox_podman_socket` is set, we honor it verbatim
    (e.g. `unix:///run/podman/podman.sock` or `tcp://host:port`).
    Otherwise we fall back to `docker.from_env()`, which respects the
    `DOCKER_HOST` env var and ultimately defaults to
    `unix:///var/run/docker.sock`. Bind-mounting podman's socket to that
    path is the lowest-config deployment.
    """
    socket_url = get_settings().sandbox_podman_socket
    if socket_url:
        return docker.DockerClient(base_url=socket_url)
    return docker.from_env()


class _SafeSandboxClient:
    """Thin wrapper around `httpx.AsyncClient` that translates transport-
    layer failures into `SandboxUnavailableError`. Callers see the same
    `post` / `get` / `aclose` surface; everything else (timeouts, HTTP 5xx
    bodies, JSON decode errors) bubbles up unchanged."""

    def __init__(self, client: httpx.AsyncClient, sandbox_id: str) -> None:
        self._client = client
        self._sandbox_id = sandbox_id

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._guard(self._client.post, *args, **kwargs)

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._guard(self._client.get, *args, **kwargs)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _guard(
        self,
        fn: Callable[..., Awaitable[httpx.Response]],
        *args: Any,
        **kwargs: Any,
    ) -> httpx.Response:
        try:
            return await fn(*args, **kwargs)
        except _TRANSPORT_DOWN_EXCEPTIONS as exc:
            logger.info(
                "sandbox transport error sandbox=%s err=%s: %s",
                self._sandbox_id, type(exc).__name__, exc,
            )
            raise SandboxUnavailableError(
                f"sandbox '{self._sandbox_id}' is not reachable ({type(exc).__name__})"
            ) from exc


# Container-side port the dev server is expected to bind to. Vite's
# default; matches what the agent runs (`npm run dev -- --host 0.0.0.0`).
DEV_SERVER_CONTAINER_PORT: int = 5173


class PodmanSandbox(Sandbox):
    def __init__(
        self,
        ip: str = None,
        container_name: str = None,
        preview_host_port: int | None = None,
    ):
        self.ip = ip
        self.base_url = f"http://{self.ip}:8080"
        self._vnc_url = f"ws://{self.ip}:5901"
        self._cdp_url = f"http://{self.ip}:9222"
        self._container_name = container_name
        self._preview_host_port = preview_host_port
        self.client = _SafeSandboxClient(
            httpx.AsyncClient(timeout=600),
            sandbox_id=container_name or self.ip or "dev-sandbox",
        )

    @property
    def id(self) -> str:
        if not self._container_name:
            return "dev-sandbox"
        return self._container_name

    @property
    def cdp_url(self) -> str:
        return self._cdp_url

    @property
    def vnc_url(self) -> str:
        return self._vnc_url

    @property
    def preview_url(self) -> Optional[str]:
        if self._preview_host_port is None:
            return None
        return f"http://localhost:{self._preview_host_port}"

    @property
    def preview_internal_url(self) -> Optional[str]:
        if not self.ip:
            return None
        return f"http://{self.ip}:5173"

    @property
    def shell_stream_url(self) -> str:
        return f"ws://{self.ip}:8080/api/v1/shell/stream"

    @staticmethod
    def _extract_dev_server_port(container) -> Optional[int]:
        """Read the host port the runtime assigned to the container's
        DEV_SERVER_CONTAINER_PORT/tcp mapping. Returns None if the
        mapping isn't present (e.g. sandbox started without `ports=`).

        Podman exposes the same `NetworkSettings.Ports` structure as
        docker via the REST API.
        """
        key = f"{DEV_SERVER_CONTAINER_PORT}/tcp"
        ports = (
            (container.attrs.get("NetworkSettings") or {}).get("Ports") or {}
        )
        bindings = ports.get(key) or []
        for b in bindings:
            host_port = b.get("HostPort")
            if host_port:
                try:
                    return int(host_port)
                except (TypeError, ValueError):
                    continue
        return None

    @staticmethod
    def _get_container_ip(container) -> str:
        """Get container IP from network settings.

        Podman's REST response shape mirrors docker's. Same defensive
        fallback to per-network IPs when the top-level `IPAddress` is
        empty (typical when the container is attached to a user-defined
        network).
        """
        network_settings = container.attrs['NetworkSettings']
        ip_address = network_settings.get('IPAddress', '')

        if not ip_address:
            networks = network_settings.get('Networks', {})
            for network_config in networks.values():
                candidate = network_config.get('IPAddress', '')
                if candidate:
                    ip_address = candidate
                    break

        return ip_address

    @staticmethod
    def _create_task(session_id: Optional[str] = None) -> 'PodmanSandbox':
        settings = get_settings()

        image = settings.sandbox_image
        name_prefix = settings.sandbox_name_prefix
        container_name = f"{name_prefix}-{str(uuid.uuid4())[:8]}"

        try:
            podman_client = _get_podman_client()

            sandbox_env: dict[str, str] = {}
            if settings.sandbox_ttl_minutes is not None:
                sandbox_env["SERVICE_TIMEOUT_MINUTES"] = str(settings.sandbox_ttl_minutes)
            if settings.sandbox_chrome_args:
                sandbox_env["CHROME_ARGS"] = settings.sandbox_chrome_args
            if settings.sandbox_https_proxy:
                sandbox_env["HTTPS_PROXY"] = settings.sandbox_https_proxy
            if settings.sandbox_http_proxy:
                sandbox_env["HTTP_PROXY"] = settings.sandbox_http_proxy
            if settings.sandbox_no_proxy:
                sandbox_env["NO_PROXY"] = settings.sandbox_no_proxy

            volumes: dict[str, dict[str, str]] = {}
            if session_id:
                host_project = (
                    f"{settings.sandbox_data_host_root.rstrip('/')}/{session_id}/project"
                )
                volumes[host_project] = {
                    "bind": "/home/ubuntu/project",
                    "mode": "rw",
                }
                sandbox_env["SANDBOX_OWN_PROJECT_DIR"] = "/home/ubuntu/project"

            container_config = {
                "image": image,
                "name": container_name,
                "detach": True,
                "remove": True,
                "labels": {
                    "helix.managed": "true",
                    "helix.role": "sandbox",
                    # Tag the runtime so the orphan reaper for one runtime
                    # never touches containers spawned by the other.
                    "helix.runtime": "podman",
                    **({"helix.session": session_id} if session_id else {}),
                },
                "environment": sandbox_env,
                "ports": {f"{DEV_SERVER_CONTAINER_PORT}/tcp": None},
                # On podman+SELinux hosts the bind-mounted project dir
                # carries host labels the container_t domain can't
                # chown. Disabling labelling for this single container
                # lets prep_volumes' `chown -R ubuntu:ubuntu` succeed
                # without weakening the rest of the system. No-op on
                # docker.
                "security_opt": ["label=disable"],
            }
            if volumes:
                container_config["volumes"] = volumes

            if settings.sandbox_network:
                container_config["network"] = settings.sandbox_network

            container = podman_client.containers.run(**container_config)

            container.reload()
            ip_address = PodmanSandbox._get_container_ip(container)
            preview_port = PodmanSandbox._extract_dev_server_port(container)

            return PodmanSandbox(
                ip=ip_address,
                container_name=container_name,
                preview_host_port=preview_port,
            )

        except Exception as e:
            raise SandboxUnavailableError(
                f"Failed to create Podman sandbox: {type(e).__name__}: {e}"
            ) from e

    async def ensure_sandbox(self) -> None:
        """Ensure sandbox is ready by checking that all services are RUNNING"""
        max_retries = 30
        retry_interval = 2

        for attempt in range(max_retries):
            try:
                response = await self.client.get(f"{self.base_url}/api/v1/supervisor/status")
                response.raise_for_status()

                tool_result = ToolResult(**response.json())

                if not tool_result.success:
                    logger.warning(f"Supervisor status check failed: {tool_result.message}")
                    await asyncio.sleep(retry_interval)
                    continue

                services = tool_result.data or []
                if not services:
                    logger.warning("No services found in supervisor status")
                    await asyncio.sleep(retry_interval)
                    continue

                all_running = True
                non_running_services = []

                for service in services:
                    service_name = service.get("name", "unknown")
                    state_name = service.get("statename", "")
                    exit_status = service.get("exitstatus", 0)

                    if state_name == "RUNNING":
                        continue
                    if state_name == "EXITED" and exit_status == 0:
                        continue
                    all_running = False
                    non_running_services.append(f"{service_name}({state_name})")

                if all_running:
                    logger.info(f"All {len(services)} services are RUNNING - sandbox is ready")
                    return
                else:
                    logger.info(f"Waiting for services to start... Non-running: {', '.join(non_running_services)} (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_interval)

            except Exception as e:
                logger.warning(f"Failed to check supervisor status (attempt {attempt + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(retry_interval)

        error_message = (
            f"Sandbox services failed to start after {max_retries} attempts "
            f"({max_retries * retry_interval} seconds)"
        )
        logger.error(error_message)
        raise SandboxUnavailableError(error_message)

    async def exec_command(self, session_id: str, exec_dir: str, command: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/exec",
            json={
                "id": session_id,
                "exec_dir": exec_dir,
                "command": command
            }
        )
        return ToolResult(**response.json())

    async def view_shell(self, session_id: str, console: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/view",
            json={
                "id": session_id,
                "console": console
            }
        )
        return ToolResult(**response.json())

    async def wait_for_process(self, session_id: str, seconds: Optional[int] = None) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/wait",
            json={
                "id": session_id,
                "seconds": seconds
            }
        )
        return ToolResult(**response.json())

    async def write_to_process(self, session_id: str, input_text: str, press_enter: bool = True) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/write",
            json={
                "id": session_id,
                "input": input_text,
                "press_enter": press_enter
            }
        )
        return ToolResult(**response.json())

    async def kill_process(self, session_id: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/shell/kill",
            json={"id": session_id}
        )
        return ToolResult(**response.json())

    async def file_write(self, file: str, content: str, append: bool = False,
                        leading_newline: bool = False, trailing_newline: bool = False,
                        sudo: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/write",
            json={
                "file": file,
                "content": content,
                "append": append,
                "leading_newline": leading_newline,
                "trailing_newline": trailing_newline,
                "sudo": sudo
            }
        )
        return ToolResult(**response.json())

    async def file_read(self, file: str, start_line: int = None,
                        end_line: int = None, sudo: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/read",
            json={
                "file": file,
                "start_line": start_line,
                "end_line": end_line,
                "sudo": sudo
            }
        )
        return ToolResult(**response.json())

    async def file_list(self, path: str, show_hidden: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/list",
            json={"path": path, "show_hidden": show_hidden},
        )
        return ToolResult(**response.json())

    async def file_exists(self, path: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/exists",
            json={"path": path}
        )
        return ToolResult(**response.json())

    async def file_delete(self, path: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/delete",
            json={"path": path}
        )
        return ToolResult(**response.json())

    async def file_replace(self, file: str, old_str: str, new_str: str, sudo: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/replace",
            json={
                "file": file,
                "old_str": old_str,
                "new_str": new_str,
                "sudo": sudo
            }
        )
        return ToolResult(**response.json())

    async def file_search(self, file: str, regex: str, sudo: bool = False) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/search",
            json={
                "file": file,
                "regex": regex,
                "sudo": sudo
            }
        )
        return ToolResult(**response.json())

    async def file_find(self, path: str, glob_pattern: str) -> ToolResult:
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/find",
            json={
                "path": path,
                "glob": glob_pattern
            }
        )
        return ToolResult(**response.json())

    async def file_upload(self, file_data: BinaryIO, path: str, filename: str = None) -> ToolResult:
        files = {"file": (filename or "upload", file_data, "application/octet-stream")}
        data = {"path": path}

        response = await self.client.post(
            f"{self.base_url}/api/v1/file/upload",
            files=files,
            data=data
        )
        return ToolResult(**response.json())

    async def file_download(self, path: str) -> BinaryIO:
        response = await self.client.get(
            f"{self.base_url}/api/v1/file/download",
            params={"path": path}
        )
        response.raise_for_status()
        return io.BytesIO(response.content)

    @staticmethod
    @alru_cache(maxsize=128, typed=True)
    async def _resolve_hostname_to_ip(hostname: str) -> str:
        try:
            try:
                socket.inet_pton(socket.AF_INET, hostname)
                return hostname
            except OSError:
                pass

            addr_info = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
            if addr_info and len(addr_info) > 0:
                return addr_info[0][4][0]
            return None
        except Exception as e:
            logger.error(f"Failed to resolve hostname {hostname}: {str(e)}")
            return None

    async def destroy(self) -> bool:
        try:
            if self.client:
                await self.client.aclose()
            if self._container_name:
                podman_client = _get_podman_client()
                podman_client.containers.get(self._container_name).remove(force=True)
            return True
        except Exception as e:
            logger.error(f"Failed to destroy Podman sandbox: {str(e)}")
            return False

    async def get_browser(self) -> Browser:
        return CDPBrowser(self.cdp_url)

    @classmethod
    async def create(cls, session_id: Optional[str] = None) -> Sandbox:
        settings = get_settings()

        if settings.sandbox_address:
            ip = await cls._resolve_hostname_to_ip(settings.sandbox_address)
            return PodmanSandbox(ip=ip)

        return await asyncio.to_thread(PodmanSandbox._create_task, session_id)

    @staticmethod
    def reap_orphans(active_container_names: set[str]) -> int:
        """Remove containers labeled `helix.managed=true` AND
        `helix.runtime=podman` whose names aren't referenced by any
        active session.

        The runtime label narrows the scan so that, in a host running
        both docker and podman side by side (rare but possible during
        migration), each reaper only touches its own runtime's
        containers.
        """
        from datetime import datetime, timezone

        _REAP_GRACE_SECONDS = 3600

        try:
            podman_client = _get_podman_client()
        except Exception as e:
            logger.debug("reap_orphans: no Podman daemon available: %s", e)
            return 0

        try:
            containers = podman_client.containers.list(
                all=True,
                filters={"label": ["helix.managed=true", "helix.runtime=podman"]},
            )
        except Exception as e:
            logger.warning("reap_orphans: failed to list containers: %s", e)
            return 0

        now = datetime.now(timezone.utc)
        reaped = 0
        for c in containers:
            if c.name in active_container_names:
                continue
            created_raw = c.attrs.get("Created", "")
            try:
                created_clean = created_raw.split(".")[0] if created_raw else ""
                if created_clean.endswith("Z"):
                    created_clean = created_clean[:-1] + "+00:00"
                created_at = datetime.fromisoformat(created_clean) if created_clean else None
                if created_at and created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
            except Exception:
                created_at = None

            if created_at and (now - created_at).total_seconds() < _REAP_GRACE_SECONDS:
                logger.debug(
                    "reap_orphans: skipping young container %s (age %.1fs < %ds grace)",
                    c.name, (now - created_at).total_seconds(), _REAP_GRACE_SECONDS,
                )
                continue

            try:
                c.remove(force=True)
                reaped += 1
                logger.info("Reaped orphan sandbox container", extra={"container": c.name})
            except Exception as e:
                logger.warning("Failed to reap orphan sandbox %s: %s", c.name, e)
        return reaped

    @classmethod
    async def fetch(cls, id: str) -> Sandbox:
        settings = get_settings()
        if settings.sandbox_address:
            ip = await cls._resolve_hostname_to_ip(settings.sandbox_address)
            return PodmanSandbox(ip=ip, container_name=id)

        def _inspect():
            client = _get_podman_client()
            container = client.containers.get(id)
            container.reload()
            return container

        try:
            container = await asyncio.to_thread(_inspect)
        except docker.errors.NotFound as exc:
            logger.info("sandbox container not found id=%s", id)
            raise SandboxUnavailableError(
                f"sandbox '{id}' no longer exists"
            ) from exc
        except docker.errors.APIError as exc:
            logger.warning("podman API error getting sandbox %s: %s", id, exc)
            raise SandboxUnavailableError(
                f"podman API error reaching sandbox '{id}': {exc}"
            ) from exc

        ip_address = cls._get_container_ip(container)
        preview_port = cls._extract_dev_server_port(container)
        return PodmanSandbox(
            ip=ip_address,
            container_name=id,
            preview_host_port=preview_port,
        )
