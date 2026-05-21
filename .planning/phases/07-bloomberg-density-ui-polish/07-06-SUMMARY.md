---
plan: "07-06"
phase: "07"
status: complete
date: "2026-05-21"
key-files:
  modified:
    - .planning/phases/07-bloomberg-density-ui-polish/07-HUMAN-UAT.md
    - apps/web/hooks/useStream.ts
    - apps/web/app/dashboard/page.tsx
    - apps/web/e2e/playwright.config.ts
---

# Plan 07-06 Summary: Human UAT — All 8 Tests Passed

Executed the 8 human UAT tests that were bypassed during Plan 07-04 due to `workflow.auto_advance=true`. All 8 tests passed. Three inline bugs were discovered and fixed during testing; all changes committed as `5e49e3e`.

## Tests Completed

| # | Test | Result |
|---|------|--------|
| 1 | Four panes visible at /dashboard (1440px+) | passed |
| 2 | Drag-resize handles — vertical and horizontal | passed |
| 3 | localStorage layout persistence across hard reload | passed (fix applied) |
| 4 | /dashboard/blotter redirects to /dashboard (308) | passed |
| 5 | WS ConnectionStatus: green→red→green on uvicorn kill/restart | passed (fix applied) |
| 6 | Strategy controls — "Params saved — engine reloading" transient text | passed |
| 7 | Run Backtest button disables (Running…) and re-enables on completion | passed |
| 8 | Playwright E2E ws-reconnect.spec.ts — 1 passed (13.4s) | passed (fix applied) |

## Inline Fixes Applied

**useStream.ts** — React StrictMode double-invocation guard
- `ws.onclose` and `ws.onerror` callbacks were firing twice in dev mode due to React StrictMode's deliberate double-mount. The second callback ran on a closed socket and clobbered `connected=true` set by the first reconnect.
- Fix: added `if (stopped) return` guard at the top of both handlers.

**page.tsx** — Replaced manual localStorage with `react-resizable-panels` autoSaveId
- Manual `localStorage` read/write + SSR guard (`typeof window === 'undefined'`) produced a React hydration mismatch warning: server-rendered default sizes differed from client-restored sizes on first paint.
- Fix: removed manual persistence; passed `autoSaveId="es-terminal"` to `PanelGroup`, which handles hydration-safe persistence natively via the library's own mechanism.

**playwright.config.ts** — Corrected testDir
- `testDir: './e2e'` was wrong because the config file itself lives inside `e2e/`. Playwright resolved it to `e2e/e2e/`, finding no tests.
- Fix: changed to `testDir: '.'` so Playwright finds `ws-reconnect.spec.ts` in the same directory as the config.

## Verification

- `07-HUMAN-UAT.md`: `status: complete`, `passed: 8`, `pending: 0`
- Commit `5e49e3e`: 4 files changed — `07-HUMAN-UAT.md`, `useStream.ts`, `page.tsx`, `playwright.config.ts`
- Playwright output: `1 passed (13.4s)`

## Self-Check: PASSED
