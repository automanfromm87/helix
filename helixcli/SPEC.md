# helixcli — Spec (v0.1 draft)

The deterministic baseline the agent calls before writing code. Replaces
LLM-driven framework scaffolding with a CLI that produces byte-stable
output. Pulls the canonical decisions from the existing
`react-vite-typescript` and `uv-fastapi-python` skills so they don't
have to be re-decided every turn.

Status: **draft for review**, not implemented yet.

---

## 0. Premises

- **One stack only.** A second stack means a second CLI. Don't bake
  `--frontend=svelte` flags in.
- **Generators auto-commit.** Each `helixcli` call → one git commit.
  Plan-versioning's diff view shows only the agent's edits on top of a
  known baseline.
- **Manifest is authoritative.** `.helix/manifest.json` is the source
  of truth for "what's in this project". Generators read it before
  emitting and write it after.
- **Generators never destroy user code.** If a target path exists,
  abort with a clear message; require `--force` to overwrite.

---

## 1. Stack (FROZEN)

| Layer | Choice | Skill source |
|---|---|---|
| Frontend framework | Vite + React 19 + TypeScript 5 (strict) | `react-vite-typescript` |
| Frontend styling | Tailwind v4 (`@tailwindcss/vite`, no `tailwind.config.js`) | `react-vite-typescript` §2c |
| Frontend lint | ESLint 9 flat config | `react-vite-typescript` §5 |
| Frontend test | Vitest + Testing Library | `react-testing` |
| Frontend pkgmgr | pnpm (REQUIRED — no npm fallback, fail fast if missing) | `react-vite-typescript` §1 + decision §8.5 |
| Backend framework | FastAPI + Pydantic v2 | `uv-fastapi-python` |
| Backend pkgmgr | uv (Python 3.12+) | `uv-fastapi-python` |
| Backend ORM | SQLAlchemy 2.0 async + Alembic | `uv-fastapi-python` §6 |
| Backend lint | ruff | `uv-fastapi-python` §3 |
| Backend type | mypy strict + pydantic.mypy | `uv-fastapi-python` §3 |
| Backend test | pytest + pytest-asyncio + httpx | `uv-fastapi-python` |
| Default DB | Postgres (asyncpg) — SQLite (aiosqlite) for tiny demos | `uv-fastapi-python` §2b |

**Refused.** Any of: Create React App, Babel for new apps, requirements.txt,
setup.py, Pydantic v1, SQLAlchemy 1.x, Flask/Django for greenfield
APIs, jQuery for new UIs. The skills already enumerate this; the CLI
inherits the same refuse-list.

---

## 2. Project layout (FROZEN)

Two-app monorepo at `/home/ubuntu/project` (the existing sandbox path).

```
project/
├── .helix/
│   ├── manifest.json     # generator state — see §3
│   └── README.md         # human overview, regenerated on every helixcli call
├── apps/
│   ├── web/              # frontend (Vite + React + TS)
│   │   ├── src/
│   │   │   ├── main.tsx
│   │   │   ├── App.tsx
│   │   │   ├── index.css
│   │   │   ├── pages/
│   │   │   ├── components/
│   │   │   ├── hooks/
│   │   │   ├── lib/
│   │   │   └── types/
│   │   ├── eslint.config.js
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   └── package.json
│   └── api/              # backend (uv + FastAPI)
│       ├── app/
│       │   ├── main.py
│       │   ├── api/      # routers
│       │   ├── core/     # config + db
│       │   ├── models/   # SQLAlchemy ORM
│       │   ├── schemas/  # Pydantic
│       │   └── services/ # business logic
│       ├── tests/
│       ├── migrations/   # alembic
│       ├── alembic.ini
│       ├── pyproject.toml
│       └── uv.lock
├── packages/             # only created when both apps exist
│   └── api-types/        # apps/web/src/api-types.ts — derived from
│                         # apps/api's /openapi.json by openapi-typescript.
│                         # `pnpm gen:types` (npm script in apps/web) is
│                         # the only entry point. helixcli itself never
│                         # touches these — FastAPI already serves the
│                         # OpenAPI schema, and openapi-typescript already
│                         # knows how to consume it.
├── README.md
├── .gitignore
└── pnpm-workspace.yaml   # only when frontend exists
```

`apps/web/src/` mirrors what the React skill §6 prescribes.
`apps/api/app/` mirrors what the FastAPI skill §7 prescribes.

`--frontend-only` / `--backend-only` flags omit the unused tree.

---

## 3. Manifest (.helix/manifest.json)

The single artifact every generator touches. Plain JSON so `jq` /
`Read` / Pydantic can all consume it directly.

```jsonc
{
  "version": 1,
  "stack": {
    "frontend": "vite-react-ts" /* or null */,
    "backend": "uv-fastapi"     /* or null */,
    "database": "postgres"      /* or "sqlite" or null */
  },
  "routes": [
    { "path": "/login", "component": "apps/web/src/pages/Login.tsx",
      "test": "apps/web/src/pages/Login.test.tsx" }
  ],
  "endpoints": [
    { "method": "POST", "path": "/api/v1/auth/login",
      "handler": "apps/api/app/api/auth.py:login",
      "schema": "apps/api/app/schemas/auth.py:LoginRequest",
      "test": "apps/api/tests/test_auth.py" }
  ],
  "models": [
    { "name": "User", "table": "users",
      "file": "apps/api/app/models/user.py" }
  ],
  "created_at": "2026-05-03T...",
  "helixcli_version": "0.1.0"
}
```

Helix backend can read this (via the `file` tool) and seed the next
plan-act turn's `workspace_summary` — the planner gets a structured map
of the project instead of having to grep.

---

## 4. Generators (initial surface)

Four commands. **Do not pre-build more.** Add a generator only when
real usage shows the agent producing inconsistent output for that
operation.

### `helixcli init [name] [flags]`

Flags: `--frontend-only`, `--backend-only`, `--db postgres|sqlite`,
`--force`.

What it does:
1. Refuse if `.helix/manifest.json` already exists (unless `--force`).
   Don't bother checking for unrelated stray files — by design the
   sandbox is agent-only and the agent should call `init` first.
2. Refuse if `pnpm` isn't on `$PATH` (frontend path). No silent fallback
   to npm — keeps lockfiles deterministic across runs.
3. `git init` if no `.git` exists.
4. Run the frontend scaffold (`pnpm create vite . --template react-swc-ts` →
   tighten tsconfig per skill §3 → wire Tailwind v4 → drop in
   `helix-inspector.ts` per skill §2e → install ESLint config) into
   `apps/web/`.
5. Run the backend scaffold (`uv init --app --python 3.12` → install
   the FastAPI dep set per skill §2b → drop in the `app/main.py` from
   skill §4 → init Alembic) into `apps/api/`.
6. If both apps exist: add `apps/web/package.json` script
   `"gen:types": "openapi-typescript http://localhost:8000/openapi.json -o src/api-types.ts"`,
   install `openapi-typescript` as a dev dep. The agent runs it on
   demand; helixcli doesn't auto-call it.
7. Write `.helix/manifest.json` reflecting the chosen stack.
8. Write `.helix/README.md` (human overview).
9. `git add . && git commit -m "helixcli init"`.

Exit codes: `0` ok, `64` already initialised, `65` pnpm missing,
`70` internal failure. Output: JSON to stdout —
`{"created": [...paths], "manifest": {...}}` — so the tool wrapper can
parse it without grepping.

### `helixcli page <Name>`

Emits:
- `apps/web/src/pages/<Name>.tsx` — component skeleton (typed props,
  default export, Tailwind starter classes)
- `apps/web/src/pages/<Name>.test.tsx` — Vitest test that mounts the
  component and asserts the heading via `getByRole('heading')`
- Updates the router (`apps/web/src/App.tsx` or
  `apps/web/src/router.tsx`, whichever is present) with a new
  `<Route path="/<name-slug>" element={<Name />}>`. If no router
  exists yet, install `react-router` and create one.

Updates `manifest.routes`. Commit message: `helixcli page <Name>`.

### `helixcli endpoint <METHOD> <path> [--auth required|public]`

`<path>` like `/api/v1/auth/login`. `<METHOD>` is GET/POST/PATCH/DELETE.

Emits:
- `apps/api/app/api/<resource>.py` — adds the handler to an existing
  router file or creates one (resource = the first non-versioned path
  segment, e.g. `auth`)
- `apps/api/app/schemas/<resource>.py` — request + response Pydantic
  models (skipped for GETs with no body)
- `apps/api/tests/test_<resource>.py` — pytest httpx-AsyncClient test
  asserting 200/422/401 as appropriate

Updates `manifest.endpoints`. Commit message: `helixcli endpoint METHOD path`.

### `helixcli migration <name>`

Wrapper. Runs `cd apps/api && uv run alembic revision --autogenerate
-m "<name>"`. Records the new revision file in `manifest.migrations`
(implicit list — alembic owns the truth, but the manifest entry helps
the agent reason about pending work).

Why a wrapper instead of letting the agent run alembic directly:
predictable cwd, predictable env, no "where is alembic.ini?" thinking
on the agent side.

---

## 5. Sandbox + agent integration

- The CLI binary is built from this directory and `COPY`'d into the
  sandbox image at `/usr/local/bin/helixcli`.
- Helix backend exposes it as a tool named `helix_scaffold` (in the
  agent's toolkit, alongside `shell_exec` / `file_*`).
- Tool schema:
  ```jsonc
  {
    "name": "helix_scaffold",
    "input_schema": {
      "action": "init" | "page" | "endpoint" | "migration",
      "args": [...]   // positional args specific to the action
    }
  }
  ```
- Tool returns the CLI's stdout JSON verbatim — paths created + new
  manifest snapshot.
- The render in `_handle_tool_event` adds a new
  `_render_scaffold` branch that surfaces the diff in the side panel
  (paths added/modified, manifest delta).

The agent should be encouraged via system-prompt convention to call
`helix_scaffold init` as the **first action** on any greenfield project
request, before reaching for `file_write`. The skill registry can
dedupe this guidance — when `helixcli` is available, the
`react-vite-typescript` and `uv-fastapi-python` skills shrink to
"prefer `helix_scaffold` over manual scaffolding; this skill is for
existing projects only".

---

## 6. Determinism + auto-commit

- **Templates pinned.** `helixcli` is versioned; bumping the CLI bumps
  a version in manifest, and templates are read from a baked-in
  resource path so a re-run on the same CLI version produces byte-
  stable output.
- **One commit per call.** Generators stage and commit before
  returning. The plan-versioning system already auto-commits at
  plan boundaries; helixcli's commits give the diff view a clean base.
- **No partial state.** A generator either succeeds end-to-end (writes
  all files + updates manifest + commits) or fails atomically. On
  failure, the CLI runs `git reset --hard HEAD` to undo any half-
  applied changes.

---

## 7. What helixcli explicitly does NOT do

- **Run dev servers.** Supervisord owns those. The existing
  `helix-dev-runner.sh` picks up the `package.json` / `pyproject.toml`
  the moment they appear.
- **Pick or switch stacks.** Stack is hardcoded.
- **Replace the agent.** It's the deterministic layer the agent calls
  when scaffolding; freeform code edits still flow through `file_write`.
- **Generate models, components, hooks, queues, auth.** Initial set is
  four commands. More are added when observation justifies it.
- **Manage secrets.** `.env.example` is committed; `.env` is `.gitignore`d
  — same as the skill prescribes. No secret rotation, no vault wiring.

---

## 8. Decisions

(Was the open-question list. All five are answered; keeping the
numbering so any earlier reference still resolves.)

1. **Manifest is authoritative — no drift detection.** The agent is
   the only writer in the sandbox; we control its behaviour through
   the toolkit + skills. Make `helix_scaffold page` more attractive
   than `file_write` for adding routes (better tool description,
   surfaced in side panel, auto-commit) and the manifest stays
   accurate. If a future model goes off-script and edits routes by
   hand, that's a behavioural fix in the system prompt, not a CLI
   feature.
2. **No `helixcli sync-types`. Use FastAPI's existing OpenAPI.** When
   `init` creates both apps, it adds an `openapi-typescript` dev dep
   and a `pnpm gen:types` npm script in `apps/web`. The agent runs
   that when it wants fresh types — explicit, no chained side-effect.
   FastAPI already exposes `/openapi.json`; we don't need to re-do
   that work in the CLI.
3. **No sample tests on `init`.** The scaffolded stack is the
   authoritative reference; we don't need a smoke-test that just
   re-asserts the framework works. `pnpm test` and `pytest` start
   green-but-empty until the agent adds a real test.
4. **Non-empty target — refuse if `.helix/manifest.json` exists.
   Otherwise proceed.** The sandbox is agent-only and the agent calls
   `init` first by convention; we don't need to scan for unrelated
   stray files. The `--force` flag is for the manifest case (the rare
   "re-init from scratch") only.
5. **pnpm required, no npm fallback.** A silent fallback would let
   two runs on different machines produce different lockfiles, which
   contradicts the determinism premise (§0). Sandbox image must ship
   pnpm; `init` exits 65 if it's missing.

---

## 9. Out of scope for v0.1

The following are good ideas, but not for the first version:

- TUI / interactive prompts (`helixcli init --interactive`)
- Project templates beyond the default web+api
- A `helixcli doctor` that validates an existing project against the
  spec
- A `helixcli upgrade` that bumps stack versions
- Native skill-replacement (today the skills still teach the agent
  rules; helixcli only handles scaffolding output)
- Agent-side caching of CLI output (idempotent re-runs that skip work)

These get their own spec when the time comes.
