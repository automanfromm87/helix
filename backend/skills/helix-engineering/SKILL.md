---
name: helix-engineering
description: |
  **MANDATORY default stack for any new web app, frontend, API, or backend
  the user asks for** — Vite + React 19 + TypeScript (strict) + Tailwind v4
  on the frontend; uv + Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2
  async + Alembic on the backend. Pick this stack by default whenever the
  request is "build a website / web app / UI / API / backend / service",
  unless the user explicitly opts out (e.g. "use vanilla HTML/JS only",
  "use Flask", "use Next.js"). Vanilla-HTML and `requirements.txt`-style
  setups are not acceptable for greenfield work — even tiny demos.

  Load this skill the moment a user asks for a new project. Read it once
  per task, then drive the work with `helix_scaffold` (init + page +
  endpoint + migration) — do NOT hand-roll the configs this skill used
  to teach. Do NOT load this skill for read-only Q&A or for tests-only
  changes (see `react-testing`).
---
# Helix engineering — the deterministic stack

Use the `helix_scaffold` tool for every greenfield action that maps to one
of its four verbs. Stack decisions are frozen — don't rederive them. This
skill is the post-scaffold reference: what to do once `init` has run.

## 0. First action on any greenfield request

```
helix_scaffold(action="init", args=[])
```

**Always pass `args=[]` (or only flags) — NEVER a project name.** The
helix sandbox runs everything in `/home/ubuntu/project/`. supervisord's
dev-runner watches that exact path for `package.json` / `pyproject.toml`
and starts Vite + uvicorn the moment they appear. Passing a name like
`["my-app"]` makes helixcli create a subdirectory `project/my-app/` that
the dev-runner can't see — preview stays blank forever and you'll waste
the rest of the session debugging it.

Wrong:
```
helix_scaffold(action="init", args=["instagram-clone"])      # ❌ subdir
helix_scaffold(action="init", args=["todo-app", "--db", "sqlite"])  # ❌
```

Right:
```
helix_scaffold(action="init", args=[])                       # ✓
helix_scaffold(action="init", args=["--frontend-only"])      # ✓
helix_scaffold(action="init", args=["--db", "sqlite"])       # ✓
```

That single call writes the entire monorepo into the cwd:
`apps/web/` (Vite + React 19 + TS strict + Tailwind v4 + Vitest +
ESLint flat config), `apps/api/` (uv + FastAPI + Pydantic v2 + SQLAlchemy 2
async + Alembic + pytest), root `package.json` (npm workspace), and
`.helix/manifest.json`. It auto-commits. **Do not write `package.json`,
`pyproject.toml`, `tsconfig.json`, `vite.config.ts`, `eslint.config.js`,
or `alembic.ini` by hand** — `init` already shipped a known-good copy.

Flags:
- `--frontend-only` / `--backend-only` for split tasks. **Use
  `--frontend-only` whenever the user describes only a UI/SPA with
  no API requirement** (anything that fits in localStorage / the
  browser) — full-stack init drags in uv + alembic + a postgres dep
  the project will never use.
- `--db postgres` (default) / `--db sqlite` for tiny demos.
- `--force` only when re-initialising — it'll be rejected otherwise.

After `init` — seven generators, all via `helix_scaffold`:

Frontend:
- `helix_scaffold(action="page", args=["Login"])` — routed page
  (`apps/web/src/pages/Login.tsx` + test + best-effort `<Route>`
  wiring in `App.tsx`). Use for top-level routes.
- `helix_scaffold(action="component", args=["PostCard"])` —
  presentational component (`apps/web/src/components/PostCard.tsx`
  + test). Use for reusable UI not tied to a route.
- `helix_scaffold(action="hook", args=["Posts"])` — custom hook
  (`apps/web/src/hooks/usePosts.ts` + test). Pass the noun,
  generator prepends `use`.

Backend:
- `helix_scaffold(action="model", args=["Post"])` — SQLAlchemy ORM
  model (`apps/api/app/models/post.py`). Auto-registered in
  `models/__init__.py` so Alembic sees it. File is `snake_case`,
  table is plural `snake_case`.
- `helix_scaffold(action="endpoint", args=["POST", "/api/v1/posts",
  "--auth", "public"])` — FastAPI handler + Pydantic schemas + httpx
  pytest. Repeated calls to the same resource path append to the
  same router file and merge schema imports automatically.
- `helix_scaffold(action="migration", args=["add_posts"])` — wraps
  `alembic revision --autogenerate`. Call AFTER `model` changes.

**Always prefer these over `file_write`** — they keep
`.helix/manifest.json` in sync, produce one git commit per
generator, and ship known-good skeletons (typed Props, `Mapped[]`
columns, Pydantic v2 schemas) so the agent doesn't reproduce the
same boilerplate every turn. Hand-write only when the structure
genuinely doesn't match a generator (utility functions, lib/ files,
adhoc fix-ups).

**Scaffolded files are starting points — own them after the
generator runs.** Each generator emits placeholder code AND a
placeholder test. The placeholder test is sized to assert the
PLACEHOLDER, not your real logic. The moment you customise the
implementation (rewrite the hook's return shape, change the
component's markup, swap the model's columns), **rewrite the
matching test in the same edit pass**. The test files are marked
`(placeholder)` in their `describe` block so this is greppable.

Treating placeholder tests as ground truth and trying to make your
custom implementation pass the placeholder's assertions is a known
trap — it produces 20+ iteration loops debugging tests against
contradictory shapes, then exhausts the iteration budget. Don't.

Each generator updates `.helix/manifest.json` and produces a single
git commit. The manifest is the authoritative project map — read it
when you need to know what already exists.

## 1. What to refuse

The CLI inherits this refuse-list; if you find yourself wanting to
emit any of the below, stop and use `helix_scaffold` instead.

Frontend:
- Create React App, `react-scripts`, `craco`, `npx create-react-app`.
- Babel (we use SWC via `@vitejs/plugin-react`).
- Tailwind v3 syntax (`@tailwind base/components/utilities`,
  `tailwind.config.js`). v4 is CSS-first: `@import "tailwindcss"`,
  customisations in `@theme {}` blocks.
- pnpm. Frontend uses npm in workspace mode at the project root.
- jQuery, Bootstrap CSS, MUI / Ant Design unless the user explicitly
  asked for them.
- Next.js / Remix unless SSR is genuinely needed (rare).

Backend:
- `requirements.txt`, `setup.py`, `setup.cfg`. We use `pyproject.toml`
  + `uv.lock` only.
- Poetry, pipenv, pdm, hatch.
- Pydantic v1 (`BaseModel.dict()`, `parse_obj`). Use `model_dump()` /
  `model_validate()`.
- SQLAlchemy 1.x (`Query.filter_by`, `declarative_base()`). Use 2.0
  `select()` + `Mapped[]` typed columns.
- Flask / Django for greenfield APIs.

## 2. Frontend reflexes (post-scaffold)

> **BEFORE you `file_write` a `.tsx` / `.ts` file, decide which generator
> seeds it.** Hand-writing is the fallback, not the default.
>
> | What you're adding | Generator |
> |---|---|
> | A routed page (`/login`, `/dashboard`, …) | `helix_scaffold(action="page", args=["Login"])` |
> | A reusable React component | `helix_scaffold(action="component", args=["PostCard"])` |
> | A custom hook | `helix_scaffold(action="hook", args=["Posts"])` |
> | Anything else (lib helper, util, types file) | `file_write` is fine |
>
> The two-step pattern is: `helix_scaffold` to seed the file pair (impl
> + placeholder test), then edit BOTH to your real shape. Do not skip
> straight to `file_write` "because it's faster" — every component you
> hand-roll loses the path-conventions / test setup / git commit /
> manifest entry the generator would have produced.

The scaffolded app already has:
- `@/` path alias → `src/*`.
- Tailwind v4 wired (`@import "tailwindcss"` in `src/index.css`).
- ESLint 9 flat config + `react-hooks` + `react-refresh`.
- Vitest + Testing Library (see `react-testing` skill).
- `helix-inspector.ts` for the host's preview-tab inspect button.

Patterns:
- **Type props directly**, no `React.FC`:
  ```tsx
  type Props = { name: string }
  export function Greet({ name }: Props) { return <h1>Hi {name}</h1> }
  ```
- **No barrel files** (`index.ts` re-exports). Import from real paths.
- **No JS files** — `.ts`/`.tsx` only.
- **Server state → TanStack Query v5**, not `useEffect+fetch`. Add it
  with `npm install @tanstack/react-query --workspace apps/web` only
  when you actually fetch.
- **Client state → Zustand 5** for shared UI state. Context is fine
  for static values; Redux is overkill.
- **Forms → React Hook Form + Zod**. Formik is in maintenance.
- **Strip dev tools from prod builds** with `if (import.meta.env.DEV)`
  guards around devtools imports.

Tailwind v4 specifics that bite:
- The CSS file holds the `@import` AND any `@theme {}` overrides. There
  is no `tailwind.config.js`. If you find yourself reaching for it,
  you're applying v3 muscle memory.
- Customise tokens via CSS variables in `@theme`:
  ```css
  @theme {
    --color-brand: oklch(0.65 0.2 250);
    --font-display: "Inter Variable", sans-serif;
  }
  ```

Project layout (the scaffold ships this; don't restructure):
```
apps/web/src/
├── main.tsx        # bootstrap (already wires helix-inspector in dev)
├── App.tsx         # root component
├── index.css       # @import "tailwindcss" lives here
├── pages/          # one .tsx per route, generated by helix_scaffold page
├── components/     # reusable presentational components
├── hooks/
├── lib/            # framework-agnostic helpers (api client, utils)
└── types/
```

Add `features/` (vertical slices) only when the same domain has
component + hook + types + tests living together. Don't preemptively
create `services/`, `stores/`, `utils/`, `helpers/`.

## 3. Backend reflexes (post-scaffold)

> **BEFORE you `file_write` a `.py` file under `apps/api/app/`, decide
> which generator seeds it.**
>
> | What you're adding | Generator |
> |---|---|
> | A SQLAlchemy ORM model | `helix_scaffold(action="model", args=["Post"])` |
> | A FastAPI endpoint | `helix_scaffold(action="endpoint", args=["POST", "/api/v1/posts"])` |
> | A schema migration | `helix_scaffold(action="migration", args=["add_posts"])` |
> | Anything else (services/, core/ helpers, business logic) | `file_write` is fine |
>
> Run `model` BEFORE `migration`; the generator updates
> `app/models/__init__.py` so Alembic's autogenerate picks the new
> table up. Skipping the generator and writing the model by hand
> means the import has to be added manually too.

The scaffolded service already has:
- `app/main.py` with `lifespan` and `/health`.
- `app/core/config.py` (Settings via `pydantic-settings`).
- `app/core/db.py` (async engine + session factory).
- `app/models/base.py` (DeclarativeBase).
- `app/api/health.py` (sample handler).
- `migrations/` (alembic init done).
- `tests/conftest.py` (httpx AsyncClient fixture).

Patterns:

```python
from pydantic import BaseModel, ConfigDict, Field

class TodoCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    notes: str | None = None  # X | None, never Optional[X]

class TodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # consume ORM rows
    id: int
    title: str
    done: bool
    created_at: datetime
```

Models — 2.0-style `Mapped[]`:

```python
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class Todo(Base):
    __tablename__ = "todos"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    done: Mapped[bool] = mapped_column(default=False)
```

Queries — 2.0-style `select()`:

```python
from sqlalchemy import select

async def list_todos(db: AsyncSession) -> list[Todo]:
    result = await db.scalars(select(Todo).order_by(Todo.created_at.desc()))
    return list(result.all())
```

Settings access goes through `get_settings()` from `app.core.config` —
never `os.environ.get(...)` scattered through the codebase.

Migrations: every schema change is a `helix_scaffold migration <name>`
call. Don't run `Base.metadata.create_all()` outside tests.

## 4. Common pitfalls

Frontend:
- **`useEffect` for data fetching** in React 19 is usually wrong. Use
  TanStack Query, or a Suspense-aware fetcher.
- **Importing from `react-dom` deep paths** other than `react-dom/client`.
- **Iframe sandbox preview** runs at `localhost:5173`. The dev runner
  is supervisord-managed — never `npm run dev` yourself.

Backend:
- **Sync I/O in an async handler** — never `requests.get()`,
  always `httpx.AsyncClient`. Never `time.sleep()`, always
  `asyncio.sleep()`. CPU work goes through `asyncio.to_thread`.
- **Engine per request** — the engine is created once at startup
  (`lifespan`) and disposed on shutdown. Each request gets a fresh
  `AsyncSession`, not a fresh engine.
- **`expire_on_commit=False`** on `async_sessionmaker` — without it,
  attribute access after `commit()` triggers a query against a
  detached session.
- **`@app.middleware("http")`** runs on every request including
  `/health`. Prefer `Depends(...)` for per-route concerns.
- **`Optional[T]`** in handler signatures — write `T | None`. Same
  OpenAPI output, consistent codebase.

Both:
- **Don't start dev servers yourself.** supervisord runs Vite
  (`apps/web`, port 5173) and uvicorn (`apps/api`, port 8000) the
  moment the scaffold appears. Verify with `curl`, restart with
  `sudo supervisorctl restart dev_server` only when reload doesn't
  cut it.

## 5. Verification before declaring done

Once you've added the user's actual feature on top of the scaffold,
all of these must pass:

```bash
# Backend
cd apps/api && uv run pytest
cd apps/api && uv run ruff check .

# Frontend
npm run typecheck --workspace apps/web
npm run lint --workspace apps/web
npm test --workspace apps/web -- --run

# Dev servers reachable
curl -fsS http://localhost:8000/health
curl -fsS http://localhost:5173/
```

If any step fails, the work is not done. Say so explicitly rather
than declaring success.

For type-safe API clients on the frontend, regenerate from the live
OpenAPI schema:

```bash
npm run gen:types --workspace apps/web
```

That writes `apps/web/src/api-types.ts` from `apps/api`'s `/openapi.json`.
Re-run after adding endpoints.

## 6. When the user asks for an existing project (not greenfield)

If `.helix/manifest.json` exists, the project was scaffolded by us —
keep using `helix_scaffold` for new pages/endpoints/migrations so the
manifest stays accurate.

If the project is foreign (CRA, requirements.txt, Poetry), don't
rewrite it under this stack without confirming. Migration is a
non-trivial change the user should opt into. Quick conversions:

- CRA → Vite: move `src/` over, replace `react-scripts` with Vite +
  `@vitejs/plugin-react`, swap `process.env.REACT_APP_*` → `import.meta.env.VITE_*`.
- pip / Poetry → uv: `uv init` in-place will refuse if `pyproject.toml`
  exists. Convert via `uv add $(grep -v '^#' requirements.txt | tr '\n' ' ')`
  and replace `pip install -e .` workflows with `uv sync`.
