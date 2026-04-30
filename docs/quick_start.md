# 🚀 快速上手

## 环境准备

本项目主要依赖Docker进行开发与部署，需要安装较新版本的Docker：

 * Docker 20.10+
 * Docker Compose

模型能力要求：

 * 支持 LangChain Chat Model（默认 `openai` 提供商）
 * 支持 FunctionCall
 * 支持 Json Format 输出

推荐使用 Deepseek 与 ChatGPT 模型。


## Docker 安装

### Windows & Mac 系统

按照官方要求安装 Docker Desktop ：https://docs.docker.com/desktop/

### Linux 系统

按照官方要求安装 Docker Engine：https://docs.docker.com/engine/

## 部署

使用 Docker Compose 进行部署。把你的 Anthropic API key 写到 `LLM_API_KEY`,如需走私有网关再覆盖 `AGENT_LLM_BASE_URL` / `LLM_PROXY_ADDRESS`:

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
      # Anthropic API key(若 AGENT_LLM_BASE_URL 指向自带鉴权的网关则可留空)
      - LLM_API_KEY=
      # 可选:私有网关 / 出站代理,默认直连上游
      #- AGENT_LLM_BASE_URL=
      #- LLM_PROXY_ADDRESS=
      # LLM 模型名
      - MODEL_NAME=claude-opus-4-7
      # LLM 温度，控制随机性
      #- TEMPERATURE=0.7
      # 最大输出 tokens
      #- MAX_TOKENS=4096
      # 更多配置：https://docs.ai-helix.com/#/configuration

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

保存成 `docker-compose.yml` 文件。

### 使用 `.env` 文件管理配置

上述示例仅包含最基本的 AI 模型配置。如需自定义更多配置（搜索引擎、认证方式、沙箱等），推荐使用 `env_file` 方式加载 `.env` 文件，避免在 `docker-compose.yml` 中堆积大量环境变量。

**步骤 1**：基于 [`.env.example`](https://github.com/simpleyyt/ai-helix/blob/main/.env.example) 创建 `.env` 文件：

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

**步骤 2**：在 `docker-compose.yml` 的 `backend` 服务中，将 `environment` 替换为 `env_file`：

```yaml
  backend:
    image: simpleyyt/helix-backend
    # ...
    env_file:
      - .env
```

> **提示**：`env_file` 和 `environment` 可以同时使用，`environment` 中的值会覆盖 `env_file` 中的同名变量。完整的配置项说明请参阅[配置说明](configuration.md)。

### 启动服务

```bash
docker compose up -d
```

> 注意：如果提示 `sandbox-1 exited with code 0`，这是正常的，这是为了让 sandbox 镜像成功拉取到本地。

打开浏览器访问 <http://localhost:5173> 即可访问 Helix。
