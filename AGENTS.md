# AGENTS.md

> Canonical guide for AI coding agents working on the **AI Helix** codebase.

---

## Project Overview

AI Helix is a general-purpose AI Agent system, comprising four services:

| Service | Stack | Port (dev) | Entry Point |
|---|---|---|---|
| **Frontend** | React 18 + TypeScript, Vite 5, Tailwind CSS | 5174 | `ui/www/src/main.tsx` |
| **Backend** | Python 3.12, FastAPI, LangChain, SQLAlchemy/asyncpg | 8000 | `backend/app/main.py` |
| **Sandbox** | Python 3.10, FastAPI, Xvfb/Chrome/VNC | 8080 (API), 5900 (VNC) | `sandbox/app/main.py` |
| **Mockserver** | Python, FastAPI | 8090 | `mockserver/main.py` |

Infrastructure: **Postgres 16**, **Redis 7.0**, **Docker** (sandbox orchestration).

---

## Directory Structure

```
ai-helix/
├── ui/www/            # React 18 SPA (Vite, TypeScript, Tailwind)
├── backend/           # FastAPI backend (DDD layout)
│   └── app/
│       ├── domain/           # Models, services, tools, agents, repositories
│       ├── application/      # Application services (auth, agent, file, token, email)
│       ├── infrastructure/   # External integrations (search, browser, sandbox, DB, cache)
│       ├── interfaces/       # API routes, schemas, error handlers, dependencies
│       ├── core/             # Config (config.py)
│       └── main.py
├── sandbox/           # Sandbox service (shell, file, supervisor APIs)
├── mockserver/        # Mock LLM server for dev/testing
├── docs/              # Docsify documentation site
├── .cursor/skills/    # Cursor agent skills
├── dev.sh             # Shortcut: docker compose -f docker-compose-development.yml ...
├── run.sh             # Shortcut: docker compose -f docker-compose.yml ...
├── build.sh           # docker buildx bake
├── .env.example       # Environment variable template
├── docker-compose.yml                # Production compose
└── docker-compose-development.yml    # Development compose (hot-reload)
```

---

## Development Environment Setup

### Prerequisites

- **Docker 20.10+** and **Docker Compose**
- **uv** (Python package manager) — for running backend/sandbox outside Docker
- **Node.js / npm** — for running frontend outside Docker
- **Python 3.12+** (backend), **Python 3.10+** (sandbox)

### Quick Start (Docker Compose — Recommended)

```bash
cp .env.example .env
# Edit .env — at minimum set API_KEY to any non-empty string
./dev.sh up -d
```

This starts: frontend (5174), backend (8000), sandbox (8080), mockserver (8090), Postgres (5432), Redis.

### Key `.env` Values for Development

| Variable | Recommended Value | Purpose |
|---|---|---|
| `AUTH_PROVIDER` | `none` | Skip authentication entirely |
| `LLM_API_KEY` | `sk-ant-...` | Anthropic API key (required unless a gateway injects auth) |
| `AGENT_LLM_BASE_URL` | *(empty)* | Override only for a private Anthropic gateway; empty hits the default upstream |
| `LLM_PROXY_ADDRESS` | *(empty)* | Optional outbound HTTP proxy `host:port` |
| `MODEL_NAME` | `claude-sonnet-4-5` | Anthropic model name |
| `SEARCH_PROVIDER` | `bing_web` | No API key needed |
| `SANDBOX_ADDRESS` | `sandbox` | Use single dev sandbox container |
| `LOG_LEVEL` | `DEBUG` | Verbose logging |

### Running Services Individually (Without Docker)

**Backend:**
```bash
cd backend
uv sync
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Requires running Postgres and Redis. Requires `API_KEY` env var (or `.env` in `backend/`).

**Frontend:**
```bash
cd ui/www
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```
The Vite config creates a proxy for `/api` when `BACKEND_URL` is set.

**Sandbox:** Typically Docker-only (requires Xvfb, Chrome, VNC, supervisord).

**Mockserver:**
```bash
cd mockserver
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090 --reload
```

---

## Testing

### Backend Tests (pytest — integration-style)

Tests live in `backend/tests/` and hit a **running** backend at `http://localhost:8000`.

```bash
# Ensure backend + Postgres + Redis are running
./dev.sh up -d postgres redis backend

cd backend
uv run pytest                               # all tests
uv run pytest tests/test_auth_routes.py     # specific file
uv run pytest -m file_api                   # by marker
```

Key test files:
- `tests/test_auth_routes.py` — auth endpoints
- `tests/test_api_file.py` — file upload/download
- `tests/test_sandbox_file.py` — sandbox file operations

Config: `backend/pytest.ini` (`asyncio_mode = auto`, markers: `file_api`).

### Sandbox Tests (pytest)

```bash
./dev.sh up -d sandbox
cd sandbox
uv run pytest
```

### Frontend (No Automated Test Runner)

```bash
cd ui/www
npm run type-check    # tsc -b --noEmit
npm run build         # production build (catches TS + JSX errors)
```

For manual UI testing: start full dev stack (`./dev.sh up -d`), open `http://localhost:5174`.

### Mockserver

No tests. Verify with:
```bash
curl -X POST http://localhost:8090/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"mock","messages":[{"role":"user","content":"hi"}]}'
```

### Full-Stack Integration Test

1. `./dev.sh up -d` — start all services
2. Open `http://localhost:5173`
3. Login (or bypass with `AUTH_PROVIDER=none`)
4. Create session, send message — mockserver returns canned tool calls
5. Check logs: `./dev.sh logs -f backend`
6. Check VNC at `localhost:5902` for sandbox desktop

---

## Code Conventions

### Backend (Python)

- **DDD architecture**: `domain/` → `application/` → `infrastructure/` → `interfaces/`
- **FastAPI** with **Pydantic v2** models and settings
- **SQLAlchemy 2.x async ORM** + **asyncpg** for Postgres (`infrastructure/models/sql.py`)
- **Redis** for caching and message queues
- Dependency management: **uv** + `pyproject.toml` (PEP 621)
- No enforced linter/formatter (no Ruff, Black, or Flake8 configured)
- Async-first: use `async def` for route handlers and service methods

### Frontend (TypeScript / React)

- **React 18** with function components + hooks
- **TypeScript** throughout
- **Tailwind CSS** for styling, **Radix UI** primitives, **lucide-react** icons
- Path alias: `@/` → `src/`
- **Zustand** for global state (replaces Vue's reactive composables)
- English only — i18n removed
- Dependency management: **npm** + `package.json`
- No ESLint or Prettier configured

### Sandbox (Python)

- **FastAPI** service exposing shell, file, and supervisor APIs
- Runs inside Docker with **supervisord** managing Chrome, Xvfb, VNC, and the API
- Dependency management: **uv** + `pyproject.toml`

---

## CI/CD

Single GitHub Actions workflow: `.github/workflows/docker-build-and-push.yml`

- **Triggers**: push/PR to `main` and `develop`; tags `v*`
- **Builds**: matrix of `frontend`, `backend`, `sandbox` Docker images for `linux/amd64` and `linux/arm64`
- **Pushes** to Docker Hub on non-PR events (requires `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets)
- **No** automated test or lint steps in CI

---

## Cursor Cloud Specific Instructions

### Environment Setup

When running in a Cloud Agent environment:

1. Docker may not be available. If Docker commands fail, focus on running individual services or testing code changes without the full stack.
2. For backend work, install dependencies with `cd backend && uv sync`.
3. For frontend work, install dependencies with `cd ui/www && npm install`.
4. Set `AUTH_PROVIDER=none` in `.env` to bypass auth. The internal Claude API needs no key.

### Testing Strategy by Change Type

| Change Type | Testing Approach |
|---|---|
| Backend Python logic | `cd backend && uv run pytest` (needs running backend + Postgres + Redis) |
| Backend API routes | `cd backend && uv run pytest` against running server |
| Frontend React/TS | `cd ui/www && npm run type-check && npm run build` |
| Frontend UI changes | Type-check + build + manual GUI testing via `computerUse` subagent |
| Sandbox changes | `cd sandbox && uv run pytest` |
| Config / env changes | Verify with `./dev.sh up -d` and check service logs |
| Documentation / README | No testing needed |

### Debugging the Backend

The dev compose starts the backend with **debugpy** on port `5678`. Attach a remote Python debugger for step-through debugging.

### Resetting State

- Postgres data persists in volume `helix-postgres-data`. Wipe with `./dev.sh down -v`.
- Mockserver tracks response index; restart to reset: `./dev.sh restart mockserver`.

---

## Skills

| Skill File | When to Use |
|---|---|
| `.cursor/skills/starter.md` | Setting up, running, or testing any part of the codebase. Contains detailed API reference, env var tables, and testing workflows. |
