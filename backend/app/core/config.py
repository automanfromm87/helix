import os
import json
import logging
from pydantic_settings import BaseSettings
from functools import lru_cache

logger = logging.getLogger(__name__)


def _parse_extra_headers() -> dict | None:
    raw = os.environ.get("EXTRA_HEADERS")
    if not raw:
        return None
    try:
        headers = json.loads(raw)
        if isinstance(headers, dict):
            return headers
        logger.warning("EXTRA_HEADERS is not a JSON object, ignoring")
    except json.JSONDecodeError:
        logger.warning("EXTRA_HEADERS is not valid JSON, ignoring")
    return None


class Settings(BaseSettings):

    # Anthropic Claude API configuration. Override `agent_llm_base_url` to
    # point at a private gateway / proxy (corporate firewall, on-prem
    # routing, etc.); leave it empty to hit the default upstream.
    agent_llm_base_url: str = ""
    # Optional HTTP proxy (host:port) the SDK routes through. Empty =
    # direct connection.
    llm_proxy_address: str = ""
    llm_api_key: str = ""
    llm_request_timeout: float = 300.0  # seconds
    # Streaming idle-timeout: max seconds to wait between two consecutive
    # SSE chunks before declaring the stream stalled. httpx's per-read
    # timeout doesn't catch this — a server that keeps the TCP connection
    # alive without sending data appears healthy. Idle timeouts surface
    # the silent-hang case so retry/resume can take over.
    llm_stream_idle_timeout: float = 60.0  # seconds
    # Maximum seconds to wait for the stream context to open (request
    # accepted + first byte of response back). Tighter than the chunk-idle
    # timeout because nothing useful is happening yet — if the SDK can't
    # establish the stream in this window, retry rather than wait.
    llm_stream_first_byte_timeout: float = 30.0  # seconds
    # Hard wall-clock cap on a single streaming LLM call. Distinct from the
    # idle timeout: chunk-idle only fires when the stream produces no events
    # for N seconds, but observed pathology — CLOSE_WAIT socket where the SDK
    # consumes EOF as low-level events without yielding a StopAsyncIteration —
    # keeps the idle clock from ever firing. This bound guarantees that no
    # single call can wedge a session indefinitely. Set well above worst
    # observed legitimate latency (long generation on a freshly-cached
    # huge prompt) so it never fires on a healthy call.
    llm_stream_total_timeout: float = 300.0  # seconds
    # Process-wide cap on concurrent LLM calls (one-shots + streaming).
    # Coordinates burst behaviour across sessions so a fork-many run
    # doesn't blow past the per-account RPM/TPM. Set near the per-account
    # concurrency cap of the upstream model service. 8 is a conservative
    # default; bump for higher-tier accounts.
    llm_max_concurrency: int = 8

    # Model configuration
    model_name: str = "claude-opus-4-7"
    temperature: float = 0.7
    max_tokens: int = 16384
    
    # Postgres configuration. The DSN must use the `postgresql+asyncpg://` scheme.
    postgres_dsn: str = "postgresql+asyncpg://helix:helix@postgres:5432/helix"

    # Sandbox configuration
    # Container runtime backend. "podman" (default) talks to podman's
    # docker-compatible REST socket (rootful: /run/podman/podman.sock,
    # rootless: /run/user/$UID/podman/podman.sock); "docker" talks to
    # the Docker daemon. Selection happens once at startup via
    # `infrastructure.external.sandbox.factory.get_sandbox_cls()`.
    sandbox_vendor: str = "podman"
    # Optional explicit URL for the podman socket (e.g.
    # "unix:///run/podman/podman.sock"). Only consulted when
    # `sandbox_vendor == "podman"`. When empty, PodmanSandbox falls back
    # to `docker.from_env()` — which honors `DOCKER_HOST` and otherwise
    # uses `/var/run/docker.sock`. The simplest deployment is to
    # bind-mount the podman socket at `/var/run/docker.sock` inside the
    # backend container and leave this unset.
    sandbox_podman_socket: str | None = None
    sandbox_address: str | None = None
    sandbox_image: str | None = None
    sandbox_name_prefix: str | None = None
    # `None` = sandbox never self-shuts-down. Default for local dev: a
    # sandbox is just a docker container, there's no multi-tenant
    # eviction pressure to satisfy. Cloud / shared deployments override
    # this via env to e.g. 30 to keep idle sandboxes from accumulating.
    sandbox_ttl_minutes: int | None = None
    # Host filesystem path (NOT a backend-container path) under which
    # per-session project directories live. Each session gets its own
    # `<root>/<session_id>/project/` bind-mounted into the sandbox at
    # `/home/ubuntu/project`. The host directory survives sandbox
    # container removal — replacing the auto-shutdown-then-lose-data
    # cycle from the previous TTL design.
    #
    # Resolution model: this is what the docker daemon sees. It may not
    # exist inside the backend container's mount namespace; that's fine,
    # the daemon (running on the host) creates and accesses the path.
    # Override with `SANDBOX_DATA_HOST_ROOT` env in production.
    sandbox_data_host_root: str = "/tmp/helix-sandboxes"
    sandbox_network: str | None = None  # Docker network bridge name
    sandbox_chrome_args: str | None = ""
    sandbox_https_proxy: str | None = None
    sandbox_http_proxy: str | None = None
    sandbox_no_proxy: str | None = None
    # Janitor that periodically reaps sandbox containers whose owning session
    # is no longer active. Set to 0 to disable.
    sandbox_janitor_interval_seconds: int = 300

    # Search engine configuration
    search_provider: str | None = "bing_web"  # "baidu", "baidu_web", "google", "bing", "bing_web", "tavily"
    baidu_search_api_key: str | None = None
    bing_search_api_key: str | None = None
    google_search_api_key: str | None = None
    google_search_engine_id: str | None = None
    tavily_api_key: str | None = None
    
    # Google Analytics configuration
    google_analytics_id: str | None = None

    # Auth configuration
    auth_provider: str = "password"  # "password", "none", "local"
    show_github_button: bool = True
    github_repository_url: str = "https://github.com/simpleyyt/ai-helix"
    password_salt: str | None = None
    password_hash_rounds: int = 10
    password_hash_algorithm: str = "pbkdf2_sha256"
    local_auth_email: str = "admin@example.com"
    local_auth_password: str = "admin"
    
    # Email configuration
    email_host: str | None = None  # "smtp.gmail.com"
    email_port: int | None = None  # 587
    email_username: str | None = None
    email_password: str | None = None
    email_from: str | None = None
    
    # JWT configuration
    jwt_secret_key: str = "your-secret-key-here"  # Should be set in production
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    
    # Extra headers for LLM requests (parsed from EXTRA_HEADERS env var, JSON)
    extra_headers: dict | None = None
    
    # MCP configuration
    mcp_config_path: str = "/etc/mcp.json"
    
    # Logging configuration
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """Get application settings"""
    settings = Settings()
    settings.extra_headers = _parse_extra_headers()
    return settings
