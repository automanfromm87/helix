---
name: react-vite-typescript
description: |
  **MANDATORY default stack for ANY new frontend / web app / UI / SPA the
  user asks for** — Vite + React 19 + TypeScript (strict) + Tailwind v4.
  Pick this stack by default whenever the request is "build a website",
  "build a web app", "build a UI", "build a todo app", etc., unless the
  user explicitly opts out (e.g. "use vanilla HTML/JS only", "use jQuery",
  "use Next.js"). The vanilla-HTML-CSS-JS approach is NOT acceptable for
  new projects under this skill — even for tiny demos. Also use when
  scaffolding the build setup or picking framework/tooling for an
  existing project. Do NOT use when fixing styling bugs, writing tests
  (see `react-testing`), or working inside an already-configured app —
  this skill is the green-field setup, not day-to-day development.
---
# React + Vite + TypeScript — Greenfield Setup

Use this skill the moment a user asks for a new frontend project. The output
is a working, opinionated setup the user can `npm run dev` immediately. Do
NOT scaffold extra features the user didn't ask for (auth, i18n, state
management) — pick those when needed.

## 1. Why this stack (and what to refuse)

Default stack: **Vite + React 19 + TypeScript 5.x + ESLint 9 (flat) + Vitest**.

- **Refuse Create React App (CRA)** — Meta deprecated it in 2025. CRA projects
  still in the wild should be migrated to Vite. CRA is slow, unmaintained,
  and ships old Webpack 4 internals.
- **Refuse Babel for new apps** — Vite uses esbuild + Rollup; SWC is the
  fastest plugin (`@vitejs/plugin-react-swc`).
- **Refuse `npx create-react-app`, `react-scripts`, `craco`**, anything CRA-
  adjacent. Don't generate `react-scripts`-based `package.json`.
- **Default to `pnpm`** when the user has no preference (faster, deterministic
  hoisting). Fall back to `npm` if the environment lacks pnpm. Don't argue
  about it if the user already picked one.

## 2. Scaffold command

Always use the official Vite scaffolder — pinning template versions
manually drifts. The `react-swc-ts` template gives React + TypeScript +
SWC out of the box. Tailwind v4 ships as a default add-on (see step
2c) — explicitly drop it only when the user opts out (CSS Modules,
existing design system, etc.).

**2a. Scaffold the app**

```bash
# pnpm (preferred)
pnpm create vite@latest my-app -- --template react-swc-ts
cd my-app && pnpm install

# npm fallback
npm create vite@latest my-app -- --template react-swc-ts
cd my-app && npm install
```

In the helix sandbox, the project lives at `/home/ubuntu/project`. To
scaffold INTO that path (when it already exists and may be empty):

```bash
cd /home/ubuntu/project
pnpm create vite@latest . -- --template react-swc-ts
pnpm install
```

**2b. Tighten tsconfig + vite.config** — see §3 and §4.

**2c. Wire Tailwind v4 (default)**

```bash
pnpm add -D tailwindcss @tailwindcss/vite
```

```ts
// vite.config.ts — add tailwindcss() to plugins
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: { host: '0.0.0.0', port: 5173, strictPort: true },
  build: { target: 'es2022', sourcemap: true },
})
```

```css
/* src/index.css — replace any pre-existing content */
@import "tailwindcss";
```

That's it. **Tailwind v4 has NO `tailwind.config.js`** — the old three-
liner (`@tailwind base/components/utilities`) is v3 syntax and will
not work. Customizations live in CSS via `@theme` blocks:

```css
@import "tailwindcss";

@theme {
  --color-brand: oklch(0.65 0.2 250);
  --font-display: "Inter Variable", sans-serif;
}
```

Verify it works by adding `<h1 className="text-3xl font-bold underline">`
to `App.tsx` — if the styling lands, you're done. If not, the most
common miss is forgetting the `@import` in `index.css` or skipping the
plugin in `vite.config.ts`.

**2d. Boot the dev server**

```bash
pnpm dev   # binds to 0.0.0.0:5173
```

Don't proceed until you've seen the server bind to a port AND verified
a Tailwind class actually styles something — that confirms 2c worked.

## 3. tsconfig — make strict mode actually strict

Vite's default `tsconfig.json` is OK but loose. Tighten it:

```jsonc
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",

    // Type-safety: turn ALL of these on for greenfield. They're cheap to
    // satisfy from day one and impossible to retrofit later without pain.
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noImplicitOverride": true,
    "noFallthroughCasesInSwitch": true,
    "exactOptionalPropertyTypes": true,

    // Vite/SWC-specific — preserve module shape, never emit:
    "isolatedModules": true,
    "verbatimModuleSyntax": true,
    "noEmit": true,
    "useDefineForClassFields": true,
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,

    // Lint hooks (TS does the analysis, ESLint surfaces it):
    "noUnusedLocals": true,
    "noUnusedParameters": true,

    // Skip lib check ONLY for speed; keep it on if you hit a lib bug.
    "skipLibCheck": true,

    "baseUrl": ".",
    "paths": { "@/*": ["src/*"] }
  },
  "include": ["src"]
}
```

The `@/*` path alias is the single most-asked-for ergonomic feature. Wire
it in `vite.config.ts` too (next section).

## 4. vite.config.ts notes

The file template is in §2c (with the Tailwind plugin already wired).
Beyond what's there:

- Bind `server.host: '0.0.0.0'` so the helix sandbox port-forward
  reaches the dev server.
- `strictPort: true` makes Vite fail loudly on port conflicts instead
  of silently picking a different port the proxy doesn't know about.
- Don't add `define`, `optimizeDeps`, or PWA plugins until something
  breaks without them. Premature config makes future debugging harder.

## 5. ESLint 9 (flat config)

ESLint 9 dropped legacy `.eslintrc` — use `eslint.config.js`. Vite's
template gives you a working baseline; verify it has these:

```js
// eslint.config.js
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules'] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        project: ['./tsconfig.json', './tsconfig.node.json'],
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
      // Surface obvious bugs without nagging on every `any`:
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': 'error',
    },
  },
)
```

Commands: `pnpm lint`, `pnpm lint --fix`. Add to `package.json`:

```json
"scripts": {
  "lint": "eslint .",
  "typecheck": "tsc --noEmit",
  "test": "vitest"
}
```

## 6. Project structure (start small)

Don't over-organize before there's code to organize. Begin flat under `src/`:

```
src/
├── main.tsx          # bootstrap
├── App.tsx           # root component
├── index.css         # global styles + tailwind imports
├── components/       # reusable presentational components
├── pages/ or routes/ # if using a router
├── hooks/            # custom hooks
├── lib/              # framework-agnostic helpers (api client, utils)
└── types/            # shared TS types (if any)
```

Add `features/` (vertical-slice folders) only once the same domain has
component + hook + types + tests living together. Don't preemptively
create `services/`, `stores/`, `utils/`, `helpers/` — they collect
random code.

## 7. Recommended additions (only when asked)

Tailwind is in §2c (default). Everything else here is opt-in — pick on
demand, don't preinstall.

| Need | Pick | Why not the alternative |
|---|---|---|
| Routing | `react-router` v7 (library mode) for SPAs; **TanStack Router** for type-safe routes | Don't reach for Next.js if SSR isn't required — adds complexity |
| Server state | **TanStack Query v5** | Don't roll your own `useEffect+fetch`; don't put server data in Redux |
| Client state | **Zustand 5** for shared UI state | Redux is overkill; Context for non-trivial state hits perf cliffs |
| Forms | **React Hook Form + Zod** | Formik is in maintenance |
| Tests | **Vitest + Testing Library** (see `react-testing` skill) | Jest works but Vitest shares Vite's transform — faster + zero config drift |
| Date | **`date-fns`** or `Temporal` polyfill | Moment is deprecated |

If the user explicitly opts OUT of Tailwind (CSS Modules, an existing
design system, vanilla CSS), skip §2c and remove `@tailwindcss/vite`
from `vite.config.ts`. Don't argue about it.

## 8. Common pitfalls

- **Don't import from `react-dom`'s deep paths** (`react-dom/client` is the
  exception — `createRoot` lives there). Internal paths break across
  major versions.
- **`useEffect` for data fetching** in React 19 — usually the wrong tool.
  Use TanStack Query, or a Suspense-aware fetcher. Server components
  aren't relevant in a Vite SPA, but `use()` for promises is.
- **No `barrel` files** (`index.ts` re-exports). They defeat tree-shaking
  in many bundler/tsconfig combos and slow IDE indexing. Import direct
  paths.
- **No JS files mixed in** — keep `.ts`/`.tsx` only. The `allowJs` flag
  in tsconfig is a one-way ratchet to nowhere.
- **`React.FC` is unnecessary** — type props directly:
  ```tsx
  type Props = { name: string }
  export function Greet({ name }: Props) { return <h1>Hi {name}</h1> }
  ```
- **Don't ship dev tools to prod** — make sure `vite build` doesn't pull
  in TanStack Query Devtools / Zustand devtools. Tree-shake them by
  conditional import:
  ```ts
  if (import.meta.env.DEV) {
    const { ReactQueryDevtools } = await import('@tanstack/react-query-devtools')
    // …
  }
  ```

## 9. Verification checklist before declaring "done"

After scaffolding, run these in order — each must pass:

1. `pnpm install` — clean exit, no peer-dependency errors
2. `pnpm typecheck` (i.e. `tsc --noEmit`) — zero errors
3. `pnpm lint` — zero errors (warnings OK to start)
4. `pnpm dev` — server binds to a port, hot reload works on a trivial edit
5. **A Tailwind class actually styles something** (default: add
   `className="text-3xl font-bold underline"` to the root heading and
   confirm in the browser). Skip this step ONLY if the user opted out
   of Tailwind in §2c.
6. `pnpm build` — succeeds, `dist/` is reasonable size
7. `pnpm preview` — built site loads in a browser

If you can't satisfy all of them, the setup is not actually done — say
so explicitly rather than declaring success.

## 10. Migration from CRA / outdated stacks

If the user hands you a CRA project:

1. Confirm before migrating — it's a non-trivial change.
2. Move `src/` over largely as-is; CRA's source layout is compatible.
3. Replace `react-scripts` deps with Vite + plugin-react-swc (above).
4. Convert `process.env.REACT_APP_*` → `import.meta.env.VITE_*`. Vite
   exposes only env vars prefixed with `VITE_` to the client.
5. Convert `public/index.html` from CRA's `%PUBLIC_URL%` template to
   Vite's `<script type="module" src="/src/main.tsx">` entry.
6. Test the production build — that's where CRA-vs-Vite differences
   bite (asset paths, env vars).
