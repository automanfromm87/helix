---
name: uv-fastapi-python
description: |
  **MANDATORY default stack for ANY new Python backend / API / web service /
  microservice** — uv + Python 3.12+ + FastAPI + Pydantic v2 + SQLAlchemy 2
  (async) + Alembic + ruff + pytest. Pick this stack by default whenever the
  request is "build an API", "build a backend", "build a web service",
  "build a Python service", etc., unless the user explicitly opts out
  (e.g. "use Flask", "use Django", "use plain stdlib only"). The
  `requirements.txt` + `pip` + setup.py approach is NOT acceptable for
  new projects under this skill — even for tiny demos. Also use when
  scaffolding the build/dependency setup or picking framework/tooling
  for an existing Python project. Do NOT use when fixing application
  bugs in an already-configured app, writing tests for existing code,
  or doing data-science / Jupyter work — this skill is the green-field
  service setup, not day-to-day development.
---
# uv + Python 3.12 + FastAPI — Greenfield Backend Setup

Use this skill the moment a user asks for a new Python backend / API /
service. The output is a working, opinionated setup the user can `uv run
fastapi dev` immediately. Do NOT scaffold extra features the user didn't
ask for (auth, queues, observability) — pick those when needed.

## 1. Why this stack (and what to refuse)

Default stack: **uv + Python 3.12+ + FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic + ruff + pytest**.

- **Refuse `requirements.txt` + raw pip** — uv replaces both, with a real
  lockfile, deterministic resolution, and 10-100× faster installs.
- **Refuse `setup.py` / `setup.cfg`** — `pyproject.toml` is the only
  modern source of truth. Setup scripts are PEP-517 legacy.
- **Refuse Poetry / pipenv / pdm / hatch as default** — they're fine
  tools but not the choice here. uv subsumes their ergonomics with
  much faster resolution and a better lockfile format. Don't argue if
  the user already picked one.
- **Refuse Pydantic v1** — `BaseModel.dict()` and `parse_obj` are dead.
  Use `model_dump()` and `model_validate()`.
- **Refuse SQLAlchemy 1.x style** — no `Query.filter_by`, no
  `declarative_base()`. Use 2.0-style `select()` + `Mapped[]` typed
  columns.
- **Refuse Flask / Django for greenfield APIs** — FastAPI gives you
  async + Pydantic-validated request/response + OpenAPI for free. Use
  Flask only for tiny scripts the user explicitly asked for; use
  Django only when the user explicitly wants the ORM + admin.

## 2. Scaffold command

Always use uv to bootstrap. uv generates a clean `pyproject.toml`,
manages the venv, and pins Python automatically.

**2a. Initialize the project**

```bash
# In an empty (or empty-ish) directory:
cd /home/ubuntu/project
uv init --app --python 3.12
```

`--app` (not `--lib`) means we're building a service, not a library —
no `src/` layout overhead, no `__init__.py` in the root. Python 3.12
is the floor; 3.13 is also fine.

**2b. Install runtime + dev dependencies**

```bash
uv add fastapi 'uvicorn[standard]' pydantic pydantic-settings \
       sqlalchemy 'asyncpg' alembic httpx

uv add --dev pytest pytest-asyncio pytest-cov ruff mypy
```

Skip `asyncpg` if the user is using SQLite (use `aiosqlite` instead).
Skip `pydantic-settings` if there's no config-from-env need.

**2c. Replace the boilerplate `hello.py`** with a proper FastAPI entry
in `app/main.py` (see §4) and delete the stub. Update `pyproject.toml`'s
`[project.scripts]` if you want a CLI entry; otherwise the user runs
`uv run fastapi dev app/main.py`.

**2d. Run `uv sync` yourself, then verify uvicorn — DO NOT start uvicorn yourself**

The sandbox runs uvicorn as a supervisord-managed service
(`/usr/local/bin/helix-dev-runner.sh`). It **passively waits** for
`.venv/` to appear, then exec's
`uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.
`--reload` keeps the running process in sync with your file edits.
**`uv sync` is your job:** run it yourself, ONCE, after writing
`pyproject.toml`. The runner does NOT sync deps for you (an
earlier auto-sync racing the agent's own sync corrupted state).

After `uv sync` completes, uvicorn auto-starts within ~2s. Verify:

```bash
for i in {1..15}; do
  curl -fsS http://localhost:8000/docs -o /dev/null && { echo OK; break; }
  sleep 2
done
```

If curl never returns OK: `supervisorctl status dev_server` and tail
the dev_server log to see why (usually an import error or syntax
problem at module top level — fix the code; supervisord will pick up
the next reload cycle on its own).

**Never** run `nohup uv run uvicorn …` or `shell_kill_process` on
uvicorn. The dev server is not your process. If you absolutely need a
clean restart (rare — `--reload` handles edits), use
`sudo supervisorctl restart dev_server`.

Don't proceed until curl returns OK AND `GET /` (or the first endpoint)
returns 200.

## 3. pyproject.toml — the only source of truth

uv writes most of this. Verify these knobs are set:

```toml
[project]
name = "your-service"
version = "0.1.0"
description = "Short one-liner."
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",
    "pydantic-settings>=2.5",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.30",
    "alembic>=1.14",
    "httpx>=0.28",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "pytest-cov>=5",
    "ruff>=0.7",
    "mypy>=1.13",
]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
# Enable a sane default set. The full list is intentional — fewer surprises
# than `extend-select = ["ALL"]`.
select = ["E", "F", "I", "B", "UP", "ASYNC", "S", "SIM", "RUF"]
ignore = ["S101"]  # assert is fine in tests

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S"]   # security checks don't apply to tests

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
addopts = "-ra --strict-markers --strict-config"
testpaths = ["tests"]
```

## 4. FastAPI entry point — minimum viable

```python
# app/main.py
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api import api_router
from app.core.config import get_settings
from app.core.db import close_engine, init_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    await init_engine(settings.database_url)
    try:
        yield
    finally:
        await close_engine()


app = FastAPI(
    title="Your Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

Don't put business logic in `main.py`. It's a wiring file — config,
lifespan, routers, middleware. Anything beyond that goes in `app/api/`.

## 5. Pydantic v2 — the right reflexes

```python
from pydantic import BaseModel, Field, ConfigDict

class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None

class TodoOut(BaseModel):
    # `from_attributes=True` lets `model_validate()` consume an ORM row.
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    done: bool
    created_at: datetime
```

Rules:
- **No `BaseModel.dict()`, no `parse_obj`** — those are v1. Use
  `model_dump()` / `model_validate()`.
- **No `Optional[X]`** — write `X | None`. PEP 604 is mandatory on
  3.10+, and we're on 3.12.
- **No `Field(default_factory=lambda: ...)` for mutable defaults at
  module level** — Pydantic handles defaults correctly without it.
- **Settings via `pydantic-settings`**, never `os.environ.get(...)`
  scattered across the codebase:

    ```python
    from pydantic_settings import BaseSettings, SettingsConfigDict
    from functools import lru_cache

    class Settings(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
        database_url: str
        jwt_secret: str
        debug: bool = False

    @lru_cache
    def get_settings() -> Settings:
        return Settings()  # type: ignore[call-arg]
    ```

## 6. SQLAlchemy 2.0 async + Alembic

```python
# app/core/db.py
from sqlalchemy.ext.asyncio import (
    AsyncSession, async_sessionmaker, create_async_engine,
)

_engine = None
_session_factory = None

async def init_engine(url: str) -> None:
    global _engine, _session_factory
    _engine = create_async_engine(url, pool_pre_ping=True)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

async def close_engine() -> None:
    if _engine is not None:
        await _engine.dispose()

def session_factory() -> async_sessionmaker[AsyncSession]:
    assert _session_factory is not None, "init_engine() not called"
    return _session_factory
```

Models use the 2.0-style `Mapped[]` columns:

```python
# app/models/todo.py
from datetime import datetime
from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class Base(DeclarativeBase): pass

class Todo(Base):
    __tablename__ = "todos"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

Queries are 2.0-style `select()`:

```python
from sqlalchemy import select

async def list_todos(db: AsyncSession) -> list[Todo]:
    result = await db.scalars(select(Todo).order_by(Todo.created_at.desc()))
    return list(result.all())
```

Initialize Alembic:

```bash
uv run alembic init -t async migrations
```

Edit `migrations/env.py` to import your `Base.metadata`, then:

```bash
uv run alembic revision --autogenerate -m "init"
uv run alembic upgrade head
```

Don't run `Base.metadata.create_all()` in production — that's for tests
and tiny demos only. Alembic is the source of truth for schema changes.

## 7. Project structure (start small)

Don't over-organize before there's code to organize. Begin:

```
project/
├── pyproject.toml
├── uv.lock                # checked in
├── .env.example           # checked in
├── .env                   # gitignored
├── alembic.ini
├── migrations/
│   ├── env.py
│   └── versions/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI entrypoint, lifespan, router wiring
│   ├── api/
│   │   ├── __init__.py    # api_router = APIRouter()
│   │   └── todos.py       # @router.get("/todos") etc.
│   ├── core/
│   │   ├── config.py      # Settings (pydantic-settings)
│   │   └── db.py          # engine + session factory
│   ├── models/            # SQLAlchemy ORM
│   ├── schemas/           # Pydantic request/response
│   └── services/          # business logic, takes a session_factory
└── tests/
    ├── conftest.py
    └── test_todos.py
```

Add `app/repositories/` only when business logic shouldn't see SQL
directly — for tiny CRUD apps, `services/` accessing the session
directly is fine. Don't preemptively split into `routes/handlers/use_cases/`
— that's over-engineering for a service starting at zero endpoints.

## 8. Common pitfalls

- **Synchronous I/O in an async handler**: never `requests.get(...)`,
  always `httpx.AsyncClient`. Never `time.sleep()`, always
  `asyncio.sleep()`. Block-tight CPU work goes through
  `asyncio.to_thread`.
- **Engine per request**: create the engine ONCE at startup (`lifespan`)
  and dispose it on shutdown. Each request gets a fresh `AsyncSession`,
  not a fresh engine.
- **Forgetting `expire_on_commit=False`** on `async_sessionmaker`: with
  the default, accessing attributes after `commit()` triggers a fresh
  query that fails because the session is no longer bound. Always set
  it false for async.
- **Mutable defaults**: `def f(items: list = []):` rebinds the same
  list across calls. Use `items: list | None = None` and `items =
  items or []` inside.
- **`@app.middleware("http")` for everything**: middleware runs on
  every request, including `/health`. Prefer FastAPI dependencies
  (`Depends(...)`) for per-route concerns; reserve middleware for
  truly global stuff (CORS, request-id propagation, auth).
- **`Optional[T]` in FastAPI handlers**: write `T | None`. The OpenAPI
  schema is identical and the codebase stays consistent.
- **`BaseSettings(...)` without `model_config`**: pydantic-settings v2
  won't autoload `.env` without `SettingsConfigDict(env_file=".env")`.

## 9. Verification checklist before declaring "done"

After scaffolding, run these in order — each must pass:

1. `uv sync` — clean exit, no resolution errors.
2. `uv run ruff check .` — zero errors (warnings OK to start).
3. `uv run ruff format --check .` — zero diffs.
4. `uv run mypy app` — zero errors.
5. `uv run pytest` — passes (even if it's just one health-check test).
6. `uv run alembic upgrade head` — applies cleanly to a fresh DB.
7. `uv run fastapi dev app/main.py --host 0.0.0.0 --port 8000` — server
   binds, `GET /health` returns 200, OpenAPI schema is reachable at
   `/docs`.

If any of these fail, the setup is not actually done — say so explicitly
rather than declaring success.

## 10. Migration from pip / Poetry / pipenv

If the user hands you an existing pip/Poetry project:

1. Confirm before migrating — it's a non-trivial change.
2. `uv init` in the same directory will refuse if `pyproject.toml`
   already exists. Use `uv lock --upgrade-package=...` to convert
   step-by-step, or:

    ```bash
    # From requirements.txt:
    uv add $(cat requirements.txt | grep -v '^#' | tr '\n' ' ')

    # From poetry: uv reads `[tool.poetry.dependencies]` partially but
    # safer is to re-add explicitly with uv add.
    ```

3. Replace `pip install -e .` workflows with `uv sync`. The venv lives
   at `.venv/` automatically — uv manages it.
4. Replace `python script.py` with `uv run script.py` in scripts and
   CI to skip activation dance.
5. Pin Python with a `.python-version` file (uv reads it). Commit this.
