---
name: product-spec
description: |
  ⚠️ **PLANNER-ONLY skill.** This skill is for YOU (the planner) to read
  BEFORE you call `submit_plan`. It is NOT a task to delegate to the
  executor. Do NOT add a task like "Draft a spec per the product-spec
  skill" — that defeats the whole point. Load it, internalize it, and
  apply it to YOUR plan output.

  **Trigger:** the user's request is a feature / app / tool to build,
  AND the user said less than ~3 sentences about what they want. Examples:
  - "build me a todo app" → load
  - "make a habit tracker" → load
  - "I want a tool that does X" → load
  - "create a website for Y" → load

  **What this skill does for you:** it gives you a PRD-extraction
  protocol. You call `load_skill(name="product-spec")`, read the body,
  then render a structured spec (intent / scenarios / must-have /
  nice-to-have / assumptions / non-goals / acceptance) in your
  `submit_plan(message=...)` field. The user reads the spec in chat;
  if they push back, the next user turn corrects it. Then the rest of
  your `tasks` array is derived from the must-haves.

  **Do NOT load this skill when:**
  - The user is fixing a specific bug ("make this button green",
    "fix the lint error in foo.ts")
  - The user is making a focused code change in an existing project
    ("add a logout button", "rename this function")
  - The user explicitly wrote a detailed spec already (>200 chars of
    requirements)

  **How to know you've used it correctly:** your `submit_plan(message=)`
  contains the seven labeled sections (Intent / Core scenarios /
  Must-haves / Nice-to-haves / Assumptions / Out of scope / Acceptance),
  and the first task is NOT "draft a spec" — it's the first concrete
  must-have.
---

# Product spec extraction

You are the planner. Before drafting any tasks, you MUST produce a
compact product spec. The user did not write one — your job is to infer
the reasonable defaults and surface them so the user can correct any
that don't match their intent.

## Why this exists

Without a spec, the planner ends up making silent decisions like
"persist to localStorage", "add dark mode", "include filtering" that
the user never asked for — or worse, MISSING things the user assumed
were obvious ("of course it has a calendar", "of course it syncs").
Either failure mode wastes a task budget on the wrong thing.

The spec is fast (one LLM round, no tools) and produces structured
state that the rest of the plan inherits.

## The spec, structured

Render this as the planner's `message` field (shown to the user
*before* tasks start running). Use the user's language. Keep it under
~250 words total.

```
**Intent.** One-line restatement of what you're building, in your own
words. Names the artifact ("a single-page todo app", "a CLI for renaming
files"), not the steps to build it.

**Core scenarios.** 2-4 bullets, each a concrete usage moment.
- "User adds a todo with a deadline → sees it appear in the list"
- "User checks an item → it moves to the completed section"
- (Skip generic "user signs up" unless the user actually mentioned auth.)

**Must-haves (will build).** The features without which the artifact
fails its core scenarios. 3-6 bullets, atomic. Each one becomes a task.

**Nice-to-haves (will skip unless asked).** Things you noticed are
adjacent but didn't make the cut. List 2-4 to make the trade-off
visible. Examples: "user accounts", "drag-to-reorder", "PWA install",
"server sync".

**Assumptions you're making.** The implicit decisions you'd otherwise
make silently. List 3-5. Examples:
- Stack: Vite + React + TypeScript + Tailwind (per the
  `react-vite-typescript` skill — load it next)
- Persistence: localStorage (no backend)
- Theme: light + dark, system-preference default
- Routing: single page, no router needed
- Deployment: dev server only

**Out of scope.** Things the user might assume but you're explicitly
NOT doing. 2-4 items. These become `explicit_non_goals` on the
relevant tasks. Examples: "user accounts / login", "calendar/iCal
integration", "mobile-app packaging", "Stripe / payments".

**Acceptance check.** One sentence describing how a human would tell
the build is done. "Open the app, add a todo, refresh — todo is still
there; toggle dark mode — colors flip; click delete — item removed."
```

## Use the spec to drive the plan

After producing the spec:

1. **Each Must-have becomes one task.** Atomic — no bundling.
2. **Each Out-of-scope item is added as `explicit_non_goals`** on tasks
   where it could plausibly tempt the executor. (E.g. if "user accounts"
   is out-of-scope, list it on every task that touches state, so the
   executor doesn't add an `auth.ts` "while it's in there".)
3. **The Acceptance check becomes the final task** — a single
   verification task that's *optional* (the recovery planner may SKIP
   it if the dev server can't be brought up). Title it explicitly:
   "Verify acceptance criteria via browser_navigate (optional)".
4. **Reference the assumptions in the relevant task descriptions** so
   the executor follows them without re-deciding (e.g. "Persist to
   localStorage as agreed in the spec").

## When the user pushes back

If the user replies "actually I want X" after seeing your spec, treat
it as a hard correction:
- Update the relevant section of the spec
- Re-derive the affected tasks
- Don't try to "blend" both — pick the user's choice cleanly

## Examples (short)

### Example 1 — bare ask

User: "Build me a todo app."

Spec excerpt:

> **Intent.** A single-page todo app where I can capture tasks, mark
> them done, and have them survive a reload.
>
> **Core scenarios.**
> - Add a todo with text and an optional deadline
> - Mark a todo done / undone
> - Delete a todo
> - Refresh the page → my todos are still there
>
> **Must-haves (will build).**
> - Add / list / toggle / delete CRUD on todos
> - localStorage persistence
> - Visual differentiation of pending vs done vs expired
>
> **Nice-to-haves (skipping).** Drag-reorder, tags, calendar export,
> notifications, accounts.
>
> **Assumptions.** Vite + React + TS + Tailwind; light/dark; no
> backend; SPA, no router.
>
> **Out of scope.** Login / accounts; multi-device sync; mobile app;
> calendar integration.
>
> **Acceptance.** Open localhost:5173, add 3 todos including one with a
> past deadline, mark one done, delete one, refresh — surviving todos
> render correctly with expired item visually distinct.

### Example 2 — vague tooling ask

User: "I need something to keep track of my expenses."

Spec excerpt:

> **Intent.** A personal expense tracker that runs locally and lets me
> log, categorize, and total my spending over a chosen period.
> ... (etc)

## Output

Render the spec inside the `message` field of `submit_plan`. Then
populate `tasks` with one task per Must-have plus the optional
acceptance verification task at the end. Set `explicit_non_goals` on
each task using items from the Out-of-scope section.

Do NOT write the spec to a file. The user reads it in the chat.
