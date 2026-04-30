# 🚀 Quick Start

## Environment Requirements

This project mainly relies on Docker for development and deployment, requiring a newer version of Docker:

 * Docker 20.10+
 * Docker Compose

Model capabilities required:

 * Supports LangChain chat models (default provider is `openai`)
 * Supports Function Call
 * Supports JSON Format output

Recommended models: Deepseek and ChatGPT.

## Docker Installation

### Windows & Mac Systems

Install Docker Desktop according to official requirements: https://docs.docker.com/desktop/

### Linux Systems

Install Docker Engine according to official requirements: https://docs.docker.com/engine/

## Deployment

Deploy using Docker Compose. Set `LLM_API_KEY` to your Anthropic API key; override `AGENT_LLM_BASE_URL` / `LLM_PROXY_ADDRESS` only if you front Anthropic with a private gateway / outbound proxy:

<!-- docker-compose-example.yml -->
```yaml
services:
  frontend:
    image: simpleyyt/helix-frontend
    ports:
      - "5173:80"
    depends_on:
      - backend
    restart: unless-stopped
    networks:
      - helix-network
    environment:
      - BACKEND_URL=http://backend:8000

  backend:
    image: simpleyyt/helix-backend
    depends_on:
      - sandbox
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      #- ./mcp.json:/etc/mcp.json # Mount MCP servers directory
    networks:
      - helix-network
    environment:
      # Anthropic API key (required unless AGENT_LLM_BASE_URL points at a
      # gateway that injects auth upstream)
      - LLM_API_KEY=
      # Optional overrides — leave empty for direct upstream access:
      #- AGENT_LLM_BASE_URL=
      #- LLM_PROXY_ADDRESS=
      # LLM model name
      - MODEL_NAME=claude-opus-4-7
      # LLM temperature parameter, controls randomness
      #- TEMPERATURE=0.7
      # Maximum tokens for LLM response
      #- MAX_TOKENS=4096
      # More configuration options: https://docs.ai-helix.com/#/configuration

  sandbox:
    image: simpleyyt/helix-sandbox
    command: /bin/sh -c "exit 0"  # prevent sandbox from starting, ensure image is pulled
    restart: "no"
    networks:
      - helix-network

  postgres:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=helix
      - POSTGRES_PASSWORD=helix
      - POSTGRES_DB=helix
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped
    networks:
      - helix-network

volumes:
  postgres_data:
    name: helix-postgres-data

networks:
  helix-network:
    name: helix-network
    driver: bridge
```
<!-- /docker-compose-example.yml -->

Save as `docker-compose.yml` file.

### Managing Configuration with `.env` File

The example above only includes the essential AI model configuration. For additional settings (search engine, authentication, sandbox, etc.), it is recommended to use `env_file` to load a `.env` file, keeping your `docker-compose.yml` clean.

**Step 1**: Create a `.env` file based on [`.env.example`](https://github.com/simpleyyt/ai-helix/blob/main/.env.example):

<!-- .env.example -->
```ini
# Anthropic Claude API configuration.
# Leave AGENT_LLM_BASE_URL empty to hit the default upstream
# (https://api.anthropic.com); override only if you front the API with a
# private gateway. LLM_PROXY_ADDRESS is an optional `host:port` if your
# network requires an outbound HTTP proxy.
#AGENT_LLM_BASE_URL=
#LLM_PROXY_ADDRESS=
LLM_API_KEY=
#LLM_REQUEST_TIMEOUT=300

# Model configuration
MODEL_NAME=claude-opus-4-7
TEMPERATURE=0.7
MAX_TOKENS=4096

# Postgres configuration (uses asyncpg driver)
#POSTGRES_DSN=postgresql+asyncpg://helix:helix@postgres:5432/helix

# Sandbox configuration
#SANDBOX_ADDRESS=
SANDBOX_IMAGE=simpleyyt/helix-sandbox
SANDBOX_NAME_PREFIX=sandbox
SANDBOX_TTL_MINUTES=30
SANDBOX_NETWORK=helix-network
#SANDBOX_CHROME_ARGS=
#SANDBOX_HTTPS_PROXY=
#SANDBOX_HTTP_PROXY=
#SANDBOX_NO_PROXY=

# Browser engine configuration
# Options: playwright, browser_use (default)
# - playwright:   uses Playwright directly via CDP (stable, well-tested)
# - browser_use:  uses the browser_use library's BrowserSession via CDP
#                 (richer DOM state extraction via AI-friendly selector map)
#BROWSER_ENGINE=browser_use

# Search engine configuration
# Options: baidu, baidu_web, google, bing, bing_web, tavily
# baidu: uses the Baidu Qianfan AI Search API (requires BAIDU_SEARCH_API_KEY)
# baidu_web: scrapes Baidu search results with browser impersonation (no API key needed)
# bing: uses the official Bing Web Search API (requires BING_SEARCH_API_KEY)
# bing_web: scrapes Bing search results directly (no API key needed)
SEARCH_PROVIDER=bing_web

# Baidu search configuration, only used when SEARCH_PROVIDER=baidu
# Get your API key from https://console.bce.baidu.com/qianfan/ais/console/onlineService
#BAIDU_SEARCH_API_KEY=

# Bing search configuration, only used when SEARCH_PROVIDER=bing
# Get your API key from https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
#BING_SEARCH_API_KEY=

# Google search configuration, only used when SEARCH_PROVIDER=google
#GOOGLE_SEARCH_API_KEY=
#GOOGLE_SEARCH_ENGINE_ID=

# Tavily search configuration, only used when SEARCH_PROVIDER=tavily
#TAVILY_API_KEY=

# Google Analytics configuration
# Set your Google Analytics Measurement ID (e.g. G-XXXXXXXXXX)
#GOOGLE_ANALYTICS_ID=

# Auth configuration
# Options: password, none, local
AUTH_PROVIDER=password

# Password auth configuration, only used when AUTH_PROVIDER=password
PASSWORD_SALT=
PASSWORD_HASH_ROUNDS=10

# Local auth configuration, only used when AUTH_PROVIDER=local
#LOCAL_AUTH_EMAIL=admin@example.com
#LOCAL_AUTH_PASSWORD=admin

# JWT configuration
JWT_SECRET_KEY=your-secret-key-here
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# Email configuration
# Only used when AUTH_PROVIDER=password
#EMAIL_HOST=smtp.gmail.com
#EMAIL_PORT=587
#EMAIL_USERNAME=your-email@gmail.com
#EMAIL_PASSWORD=your-password
#EMAIL_FROM=your-email@gmail.com

# Extra headers for LLM API requests (JSON format)
#EXTRA_HEADERS={"X-Custom-Header": "value"}

# MCP configuration
#MCP_CONFIG_PATH=/etc/mcp.json

# Log configuration
LOG_LEVEL=INFO
```
<!-- /.env.example -->

**Step 2**: In `docker-compose.yml`, replace the `environment` section of the `backend` service with `env_file`:

```yaml
  backend:
    image: simpleyyt/helix-backend
    # ...
    env_file:
      - .env
```

> **Tip**: `env_file` and `environment` can be used together — values in `environment` override those from `env_file`. See [Configuration](configuration.md) for a full list of available options.

### Start Services

```bash
docker compose up -d
```

> Note: If you see `sandbox-1 exited with code 0`, this is normal — it ensures the sandbox image is successfully pulled locally.

Open your browser and visit <http://localhost:5173> to access Helix.
