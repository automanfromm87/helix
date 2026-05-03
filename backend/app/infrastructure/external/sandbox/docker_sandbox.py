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
            # Info-level: sandbox-down is a normal degraded state, not a bug.
            # No traceback in the log — the type + message is enough.
            logger.info(
                "sandbox transport error sandbox=%s err=%s: %s",
                self._sandbox_id, type(exc).__name__, exc,
            )
            raise SandboxUnavailableError(
                f"sandbox '{self._sandbox_id}' is not reachable ({type(exc).__name__})"
            ) from exc


# Container-side port the dev server is expected to bind to. Vite's
# default; matches what the agent runs (`npm run dev -- --host 0.0.0.0`).
# We map this to an ephemeral host port at container-create time.
DEV_SERVER_CONTAINER_PORT: int = 5173


class DockerSandbox(Sandbox):
    def __init__(
        self,
        ip: str = None,
        container_name: str = None,
        preview_host_port: int | None = None,
    ):
        """Initialize Docker sandbox and API interaction client.

        `preview_host_port` is the host TCP port docker mapped to the
        sandbox's dev-server port (5173). When set, `preview_url` returns
        `http://localhost:<port>` so the FE can iframe the running app
        directly without going through VNC. None for legacy sandboxes
        that didn't request the mapping.
        """
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
        """Sandbox ID"""
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
        """`http://localhost:<host_port>` for the sandbox's dev server.

        Returns None until the container has a port mapping AND the user's
        agent has actually started a server bound to 0.0.0.0:5173. Note
        the port is reserved at container-create time but nothing is
        listening until the agent runs `npm run dev -- --host 0.0.0.0`.
        """
        if self._preview_host_port is None:
            return None
        return f"http://localhost:{self._preview_host_port}"

    @property
    def preview_internal_url(self) -> Optional[str]:
        """Backend-side URL for liveness probing — uses the sandbox
        container's internal IP + container port (5173).

        The host-facing `preview_url` is `localhost:<host_port>`; that
        resolves correctly from a browser running on the docker host
        but NOT from another container (where `localhost` is itself,
        not the host). Probing from inside the backend container
        therefore needs the sandbox's docker-network IP directly.
        """
        if not self.ip:
            return None
        return f"http://{self.ip}:5173"

    @property
    def shell_stream_url(self) -> str:
        # Same port as the rest of the sandbox HTTP API — FastAPI handles
        # both HTTP and WS upgrades on 8080. Cols/rows/cwd are passed as
        # query params from the proxy when known.
        return f"ws://{self.ip}:8080/api/v1/shell/stream"

    @staticmethod
    def _extract_dev_server_port(container) -> Optional[int]:
        """Read the host port docker assigned to the container's
        DEV_SERVER_CONTAINER_PORT/tcp mapping. Returns None if the
        mapping isn't present (e.g. sandbox started without `ports=`).

        docker SDK structure: `container.ports` (or `attrs['NetworkSettings']
        ['Ports']`) is `{ '5173/tcp': [{ 'HostIp': '0.0.0.0', 'HostPort': '54321' }, ...] }`.
        We pick the first IPv4 binding. `None` for a mapping with the key
        present but value-list empty (race window during start).
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
        """Get container IP address from network settings
        
        Args:
            container: Docker container instance
            
        Returns:
            Container IP address
        """
        # Get container network settings
        network_settings = container.attrs['NetworkSettings']

        # Use .get() to avoid KeyError on newer Docker versions (e.g. Debian 13)
        # where the top-level IPAddress field may be absent when the container
        # is attached to a user-defined network instead of the default bridge.
        ip_address = network_settings.get('IPAddress', '')

        # Fall back to per-network IP when the top-level field is empty
        if not ip_address:
            networks = network_settings.get('Networks', {})
            for network_config in networks.values():
                candidate = network_config.get('IPAddress', '')
                if candidate:
                    ip_address = candidate
                    break

        return ip_address

    @staticmethod
    def _create_task(session_id: Optional[str] = None) -> 'DockerSandbox':
        """Create a new Docker sandbox (static method).

        When `session_id` is supplied, the container's `/home/ubuntu/project`
        is bind-mounted from `<sandbox_data_host_root>/<session_id>/project`
        on the host. This means project files survive container removal
        (TTL shutdown, manual stop, janitor reap) — the next sandbox for
        the same session remounts the same host directory and picks up
        where the previous one left off. Without `session_id` (legacy
        callers / standalone use) the project dir is ephemeral.
        """
        # Use configured default values
        settings = get_settings()

        image = settings.sandbox_image
        name_prefix = settings.sandbox_name_prefix
        container_name = f"{name_prefix}-{str(uuid.uuid4())[:8]}"

        try:
            # Create Docker client
            docker_client = docker.from_env()

            # Prepare container configuration. Only forward env vars that
            # are actually set — passing `None` becomes the literal string
            # "None" inside the container, which then breaks the sandbox's
            # pydantic settings parser (e.g. SERVICE_TIMEOUT_MINUTES).
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

            # Per-session host bind mount. Path lives on the docker host
            # (NOT inside this backend container) — the daemon resolves it.
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
                    # Marker so the orphan reaper can find Helix-managed
                    # containers without false-positives on the host.
                    "helix.managed": "true",
                    "helix.role": "sandbox",
                    # Track which session a sandbox belongs to so we can
                    # find / replace it without consulting the DB.
                    **({"helix.session": session_id} if session_id else {}),
                },
                "environment": sandbox_env,
                # Map the sandbox's dev-server port (Vite default 5173) to
                # an ephemeral host port. Lets the FE iframe the running
                # app via http://localhost:<port> without going through
                # VNC. Nothing listens on 5173 until the agent starts the
                # dev server, but the mapping is reserved up front so the
                # iframe URL is stable for the sandbox's whole life.
                "ports": {f"{DEV_SERVER_CONTAINER_PORT}/tcp": None},
            }
            if volumes:
                container_config["volumes"] = volumes

            # Add network to container config if configured
            if settings.sandbox_network:
                container_config["network"] = settings.sandbox_network
            
            # Create container
            container = docker_client.containers.run(**container_config)
            
            # Get container IP address
            container.reload()  # Refresh container info
            ip_address = DockerSandbox._get_container_ip(container)
            preview_port = DockerSandbox._extract_dev_server_port(container)

            # Create and return DockerSandbox instance
            return DockerSandbox(
                ip=ip_address,
                container_name=container_name,
                preview_host_port=preview_port,
            )
            
        except Exception as e:
            # Preserve the original docker SDK exception type + traceback.
            # `raise from e` keeps the cause chain so operators can see the
            # actual culprit (ImagePullError, PortAllocation, NotFound, …)
            # instead of a flat "Failed to create Docker sandbox" message.
            raise SandboxUnavailableError(
                f"Failed to create Docker sandbox: {type(e).__name__}: {e}"
            ) from e

    async def ensure_sandbox(self) -> None:
        """Ensure sandbox is ready by checking that all services are RUNNING"""
        max_retries = 30  # Maximum number of retries
        retry_interval = 2  # Seconds between retries
        
        for attempt in range(max_retries):
            try:
                response = await self.client.get(f"{self.base_url}/api/v1/supervisor/status")
                response.raise_for_status()
                
                # Parse response as ToolResult
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
                
                # Check if all services are RUNNING. One-shot bootstrap
                # programs (e.g. `prep_volumes` that chowns the bind-mount
                # target then exits) finish in EXITED state with exit code 0
                # — that's their healthy terminal state, not an error.
                # Without this carve-out, ensure_sandbox would wait until
                # the 60-second cap then surface a misleading "failed to
                # start" log even though the long-running services are up.
                all_running = True
                non_running_services = []

                for service in services:
                    service_name = service.get("name", "unknown")
                    state_name = service.get("statename", "")
                    exit_status = service.get("exitstatus", 0)

                    if state_name == "RUNNING":
                        continue
                    if state_name == "EXITED" and exit_status == 0:
                        # One-shot program that completed successfully.
                        continue
                    all_running = False
                    non_running_services.append(f"{service_name}({state_name})")
                
                if all_running:
                    logger.info(f"All {len(services)} services are RUNNING - sandbox is ready")
                    return  # Success - all services are running
                else:
                    logger.info(f"Waiting for services to start... Non-running: {', '.join(non_running_services)} (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_interval)
                    
            except Exception as e:
                logger.warning(f"Failed to check supervisor status (attempt {attempt + 1}/{max_retries}): {str(e)}")
                await asyncio.sleep(retry_interval)
        
        # All retries exhausted — surface as SandboxUnavailableError so the
        # agent loop's existing handling (skip tool render, log INFO,
        # propagate ToolResult with TOOL_RESULT_SANDBOX_UNAVAILABLE) takes
        # over. Silently returning made callers think the sandbox was
        # ready and the next operation always failed with confusing
        # secondary errors.
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
        """Write content to file
        
        Args:
            file: File path
            content: Content to write
            append: Whether to append content
            leading_newline: Whether to add newline before content
            trailing_newline: Whether to add newline after content
            sudo: Whether to use sudo privileges
            
        Returns:
            Result of write operation
        """
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
        """Read file content
        
        Args:
            file: File path
            start_line: Start line number
            end_line: End line number
            sudo: Whether to use sudo privileges
            
        Returns:
            File content
        """
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
        """List one directory level. Used by the FE explorer tree.

        Args:
            path: Absolute directory path inside the sandbox.
            show_hidden: Include dotfiles + noisy generated dirs.
        """
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/list",
            json={"path": path, "show_hidden": show_hidden},
        )
        return ToolResult(**response.json())

    async def file_exists(self, path: str) -> ToolResult:
        """Check if file exists
        
        Args:
            path: File path
            
        Returns:
            Whether file exists
        """
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/exists",
            json={"path": path}
        )
        return ToolResult(**response.json())
        
    async def file_delete(self, path: str) -> ToolResult:
        """Delete file
        
        Args:
            path: File path
            
        Returns:
            Result of delete operation
        """
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/delete",
            json={"path": path}
        )
        return ToolResult(**response.json())
        
    async def file_replace(self, file: str, old_str: str, new_str: str, sudo: bool = False) -> ToolResult:
        """Replace string in file
        
        Args:
            file: File path
            old_str: String to replace
            new_str: String to replace with
            sudo: Whether to use sudo privileges
            
        Returns:
            Result of replace operation
        """
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
        """Search in file content
        
        Args:
            file: File path
            regex: Regular expression
            sudo: Whether to use sudo privileges
            
        Returns:
            Search results
        """
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
        """Find files by name pattern
        
        Args:
            path: Search directory path
            glob_pattern: Glob match pattern
            
        Returns:
            List of found files
        """
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/find",
            json={
                "path": path,
                "glob": glob_pattern
            }
        )
        return ToolResult(**response.json())

    async def file_upload(self, file_data: BinaryIO, path: str, filename: str = None) -> ToolResult:
        """Upload file to sandbox
        
        Args:
            file_data: File content as binary stream
            path: Target file path in sandbox
            filename: Original filename (optional)
            
        Returns:
            Upload operation result
        """
        # Prepare form data for upload
        files = {"file": (filename or "upload", file_data, "application/octet-stream")}
        data = {"path": path}
        
        response = await self.client.post(
            f"{self.base_url}/api/v1/file/upload",
            files=files,
            data=data
        )
        return ToolResult(**response.json())

    async def file_download(self, path: str) -> BinaryIO:
        """Download file from sandbox
        
        Args:
            path: File path in sandbox
            
        Returns:
            File content as binary stream
        """
        response = await self.client.get(
            f"{self.base_url}/api/v1/file/download",
            params={"path": path}
        )
        response.raise_for_status()
        
        # Return the response content as a BinaryIO stream
        # TODO: change to real stream
        return io.BytesIO(response.content)
    
    @staticmethod
    @alru_cache(maxsize=128, typed=True)
    async def _resolve_hostname_to_ip(hostname: str) -> str:
        """Resolve hostname to IP address
        
        Args:
            hostname: Hostname to resolve
            
        Returns:
            Resolved IP address, or None if resolution fails
            
        Note:
            This method is cached using LRU cache with a maximum size of 128 entries.
            The cache helps reduce repeated DNS lookups for the same hostname.
        """
        try:
            # First check if hostname is already in IP address format
            try:
                socket.inet_pton(socket.AF_INET, hostname)
                # If successfully parsed, it's an IPv4 address format, return directly
                return hostname
            except OSError:
                # Not a valid IP address format, proceed with DNS resolution
                pass
                
            # Use socket.getaddrinfo for DNS resolution
            addr_info = socket.getaddrinfo(hostname, None, family=socket.AF_INET)
            # Return the first IPv4 address found
            if addr_info and len(addr_info) > 0:
                return addr_info[0][4][0]  # Return sockaddr[0] from (family, type, proto, canonname, sockaddr), which is the IP address
            return None
        except Exception as e:
            # Log error and return None on failure
            logger.error(f"Failed to resolve hostname {hostname}: {str(e)}")
            return None
    
    async def destroy(self) -> bool:
        """Destroy Docker sandbox"""
        try:
            if self.client:
                await self.client.aclose()
            if self._container_name:
                docker_client = docker.from_env()
                docker_client.containers.get(self._container_name).remove(force=True)
            return True
        except Exception as e:
            logger.error(f"Failed to destroy Docker sandbox: {str(e)}")
            return False
    
    async def get_browser(self) -> Browser:
        """Return a CDPBrowser bound to the sandbox's chrome.

        Single engine — `CDPBrowser` (pure CDP via Playwright). The previous
        browser_use / legacy-playwright engines were dropped after the
        browser_use WebSocket-disconnect 30-min hang incident; CDPBrowser
        wraps every CDP send in a hard timeout and avoids the silent
        reconnect loops that caused that wedge."""
        return CDPBrowser(self.cdp_url)

    @classmethod
    async def create(cls, session_id: Optional[str] = None) -> Sandbox:
        """Create a new sandbox instance.

        When `session_id` is provided, the new container's project dir is
        bind-mounted from a stable host path keyed by that session — so
        project state persists across container lifecycles (this is the
        whole point of `sandbox_data_host_root`). Falls back to ephemeral
        when omitted (legacy callers).
        """
        settings = get_settings()

        if settings.sandbox_address:
            # Chrome CDP needs IP address
            ip = await cls._resolve_hostname_to_ip(settings.sandbox_address)
            return DockerSandbox(ip=ip)

        return await asyncio.to_thread(DockerSandbox._create_task, session_id)
    
    @staticmethod
    def reap_orphans(active_container_names: set[str]) -> int:
        """Remove containers labeled `helix.managed=true` whose names aren't
        referenced by any active session.

        Called during backend startup to clean up sandboxes left behind by a
        crashed previous run. No-op when not running in Docker mode (i.e.
        SANDBOX_ADDRESS is set), because no containers will carry the label.

        Containers younger than _REAP_GRACE_SECONDS are skipped — this
        protects against a dev-mode race where uvicorn `--reload` restarts
        the backend while a sandbox was just spawned: the new process's
        active-sandbox list may briefly miss the freshly-saved row, and
        without a grace period the reaper would kill a healthy in-flight
        sandbox mid-task (caller would see `ConnectError: All connection
        attempts failed`).
        """
        from datetime import datetime, timezone

        _REAP_GRACE_SECONDS = 90

        try:
            docker_client = docker.from_env()
        except Exception as e:
            logger.debug("reap_orphans: no Docker daemon available: %s", e)
            return 0

        try:
            containers = docker_client.containers.list(
                all=True,
                filters={"label": "helix.managed=true"},
            )
        except Exception as e:
            logger.warning("reap_orphans: failed to list containers: %s", e)
            return 0

        now = datetime.now(timezone.utc)
        reaped = 0
        for c in containers:
            if c.name in active_container_names:
                continue
            # Docker `Created` is ISO8601 in UTC. Parse defensively — older
            # docker SDKs return microsecond precision that fromisoformat
            # only handles up to 6 digits, so trim trailing nanos.
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
        """Live-read a sandbox by ID — always hits the docker daemon
        (~5ms inspect call). Raises `SandboxUnavailableError` (→ 503 to
        FE) when the container is gone.

        Pre-registry this method was `@alru_cache`'d, which silently
        handed back Sandbox objects whose IPs pointed at long-dead
        containers; now caching is the registry's job and this method
        guarantees freshness. Sync docker SDK calls go through a thread
        so the event loop isn't blocked on the (rare) slow inspect.
        """
        settings = get_settings()
        if settings.sandbox_address:
            ip = await cls._resolve_hostname_to_ip(settings.sandbox_address)
            return DockerSandbox(ip=ip, container_name=id)

        def _inspect():
            client = docker.from_env()
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
            logger.warning("docker API error getting sandbox %s: %s", id, exc)
            raise SandboxUnavailableError(
                f"docker API error reaching sandbox '{id}': {exc}"
            ) from exc

        ip_address = cls._get_container_ip(container)
        preview_port = cls._extract_dev_server_port(container)
        return DockerSandbox(
            ip=ip_address,
            container_name=id,
            preview_host_port=preview_port,
        )
