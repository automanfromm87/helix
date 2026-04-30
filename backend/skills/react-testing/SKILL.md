---
name: react-testing
description: |
  React Testing Library best practices and common patterns. Use when adding
  tests for React components, fixing flaky tests, debugging "act()" or
  selector errors, or migrating from Enzyme.
---
# React Testing Library — Best Practices

Use this skill when writing component tests for a React app that already
has `@testing-library/react` and `@testing-library/user-event` installed.
Output should be ready-to-run test files; don't generate scaffolding the
caller hasn't asked for.

## 1. Query priority (top → bottom)

Always prefer the highest-priority query that still uniquely identifies
the element. This makes tests resilient to refactors.

1. `getByRole(name)` — the way assistive tech finds elements. Use ARIA
   roles like `button`, `textbox`, `link`, `heading`. The `name` option
   matches accessible name (label text, aria-label, etc.).
2. `getByLabelText` — for form fields with `<label>`.
3. `getByPlaceholderText` — fallback for inputs without labels.
4. `getByText` — for non-interactive text.
5. `getByDisplayValue` — for filled-in form fields.
6. `getByAltText`, `getByTitle` — for images / icons.
7. `getByTestId` — last resort. Add `data-testid` only when no semantic
   query works.

```tsx
// good
screen.getByRole('button', { name: /submit/i })

// avoid
screen.getByTestId('submit-button')
container.querySelector('.submit-btn')
```

## 2. User interactions: `userEvent` over `fireEvent`

`userEvent` simulates real user behavior (focus, key events, debouncing).
`fireEvent` fires a single synthetic DOM event and skips most of that.

```tsx
import { userEvent } from '@testing-library/user-event'

const user = userEvent.setup()
await user.click(screen.getByRole('button', { name: /save/i }))
await user.type(screen.getByLabelText(/email/i), 'a@b.com')
```

`userEvent.setup()` MUST be called once per test (not module-level) so
internal state (clipboard, pointer position) is fresh.

## 3. Async assertions: `findBy*` and `waitFor`

`getBy*` throws synchronously. `findBy*` returns a Promise that resolves
when the element appears (default 1000ms). For state changes that don't
add/remove DOM, use `waitFor`.

```tsx
// good — wait for the loaded state
const row = await screen.findByText(/widget #42/i)

// also good — wait for a derived assertion
await waitFor(() => {
  expect(mockApi).toHaveBeenCalledTimes(1)
})

// avoid — sleeping
await new Promise(r => setTimeout(r, 500))
```

## 4. `act()` warnings — what they mean

```
Warning: An update to <Component> inside a test was not wrapped in act(...)
```

You see this when state updates happen AFTER your assertions / between
test renders. Fix:

- If the update is a direct response to your interaction → use
  `await user.click(...)` instead of `fireEvent.click(...)`.
- If it's an async effect (timer, fetch) → `await waitFor(...)` for
  the final state, or use `findBy*` instead of `getBy*`.
- Almost never wrap your code in `act(...)` manually — RTL already does
  that inside `render`, `userEvent`, and `waitFor`.

## 5. Mocking

### `fetch` / API clients

Prefer `msw` (Mock Service Worker) over jest mocks of `fetch`. It runs
real network plumbing and lets you express expectations in HTTP terms.

```tsx
import { setupServer } from 'msw/node'
import { http, HttpResponse } from 'msw'

const server = setupServer(
  http.get('/api/widgets', () => HttpResponse.json([{ id: 42 }]))
)
beforeAll(() => server.listen())
afterEach(() => server.resetHandlers())
afterAll(() => server.close())
```

### Modules

```tsx
jest.mock('@/lib/featureFlags', () => ({
  useFeatureFlag: jest.fn().mockReturnValue(true),
}))
```

Reset between tests:

```tsx
afterEach(() => jest.clearAllMocks())
```

## 6. Snapshot tests

Use sparingly — they encode "any change is a failure" rather than the
intent. Prefer `toMatchInlineSnapshot()` for tiny pieces of output.
Never snapshot a whole component tree just to "have a test".

## 7. `toBeInTheDocument()` and friends — `@testing-library/jest-dom`

```tsx
import '@testing-library/jest-dom'
expect(screen.getByRole('alert')).toBeInTheDocument()
expect(button).toBeDisabled()
expect(input).toHaveValue('hello')
```

Set up the import in `jest.setup.ts` so every test file gets it.

## 8. Common pitfalls

- **Querying inside the act of unmounting**: don't call `screen.getBy*`
  inside `useEffect` cleanup.
- **Using `container.querySelector`**: bypasses RTL's accessibility
  guarantees. Avoid unless testing a third-party component with no
  accessible markup.
- **Asserting on implementation detail** (state names, internal CSS
  classes): tests rot the moment the component is refactored.

## 9. CRA-specific

Create-React-App ships RTL out of the box. Tests live next to components
as `*.test.tsx`. Run with `npm test`. Use `--watchAll=false` in CI.

```json
"scripts": {
  "test:ci": "react-scripts test --watchAll=false --ci"
}
```

## 10. Where to look further

- React Testing Library docs: https://testing-library.com/docs/react-testing-library/intro/
- Common mistakes: https://kentcdodds.com/blog/common-mistakes-with-react-testing-library
- MSW: https://mswjs.io/docs/
