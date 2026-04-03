# Frontend

React 19 single-page application with TypeScript, Vite, and TanStack Query (GraphQL data fetching).

## Tech Stack

- **Framework:** React 19, TanStack Router, TypeScript 5.9
- **Build:** Vite 8, pnpm
- **Styling:** Tailwind CSS 4, Radix UI primitives, class-variance-authority
- **GraphQL:** TanStack Query 5, graphql-codegen (auto-generated hooks in `src/generated/`)
- **Forms:** React Hook Form 7, Zod 4
- **Testing:** Vitest, React Testing Library, jsdom

## File Structure

```text
frontend/
├── src/
│   ├── components/       # Shared components
│   │   └── ui/           # Radix-based UI primitives (Badge, Button, Dialog, etc.)
│   ├── pages/            # Route-level page components
│   │   ├── deployments/  # Deploy form, deployment detail
│   │   ├── drivers/      # Driver list, detail, add
│   │   ├── environments/ # Environment list, detail, create dialog
│   │   └── settings/     # Settings, cluster detail, create cluster dialog
│   ├── routes/           # TanStack Router route definitions (code-based)
│   ├── routeTree.ts      # Assembled route tree (all routes as children of root)
│   ├── router.ts         # Router instance + type registration (declare module)
│   ├── hooks/            # Custom React hooks (useAutoRefresh)
│   ├── lib/              # Utility functions (cn)
│   ├── graphql/          # .graphql operation files
│   ├── generated/        # Auto-generated GraphQL types (do not edit)
│   └── test/             # Test infrastructure (setup, utilities)
├── vitest.config.ts      # Test runner configuration
├── vite.config.ts        # Build configuration
├── eslint.config.js      # Linting configuration
└── package.json          # Dependencies and scripts
```

## Commands

```bash
pnpm install              # Install dependencies
pnpm dev                  # Start dev server
pnpm build                # Type-check and build
pnpm lint                 # ESLint + Prettier check
pnpm format               # Format with Prettier
pnpm test                 # Run tests once
pnpm test:watch           # Run tests in watch mode
pnpm codegen              # Regenerate GraphQL types
```

## Testing

### Running Tests

```bash
pnpm test                 # Run all tests once (CI mode)
pnpm test:watch           # Run in watch mode (development)
```

### Writing Tests

- **Co-locate** test files next to source files: `Component.test.tsx` alongside `Component.tsx`
- **Naming:** `*.test.ts` for utilities/hooks, `*.test.tsx` for components
- **Import test utilities** from `@/test/utils` (provides custom `render` with router context)

### What to Test

| Component Type | What to Test |
|----------------|-------------|
| Utility functions | Input/output, edge cases (empty, null, conflict resolution) |
| Custom hooks | State changes, side effects (timers), cleanup on unmount |
| Presentational components | Correct text/elements render for each prop variant |
| Interactive components | User interactions (clicks, toggles), callback invocations |
| Layout components | Navigation links render, toggle behavior |

### Test Patterns

**Component test:**

```tsx
import { render, screen } from "@/test/utils";
import { MyComponent } from "./MyComponent";

it("renders the title", async () => {
  await render(<MyComponent title="Hello" />);
  expect(screen.getByText("Hello")).toBeInTheDocument();
});
```

**Hook test:**

```ts
import { renderHook, act } from "@testing-library/react";
import { useMyHook } from "./useMyHook";

it("updates state", () => {
  const { result } = renderHook(() => useMyHook());
  act(() => { result.current.doSomething(); });
  expect(result.current.value).toBe(expected);
});
```

**User interaction test:**

```tsx
import { render, screen, userEvent } from "@/test/utils";

it("calls handler on click", async () => {
  const user = userEvent.setup();
  const onClick = vi.fn();
  await render(<Button onClick={onClick}>Click</Button>);
  await user.click(screen.getByRole("button", { name: "Click" }));
  expect(onClick).toHaveBeenCalledOnce();
});
```

### Mocking

- **localStorage:** Use `vi.stubGlobal("localStorage", mockStorage)` — jsdom does not fully implement Storage
- **Timers:** Use `vi.useFakeTimers()` / `vi.advanceTimersByTime()` for interval-based hooks
- **GraphQL:** The custom `render` in `@/test/utils` provides both TanStack Router and TanStack Query wrappers with retries disabled
