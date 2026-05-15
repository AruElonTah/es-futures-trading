# apps/web — ES Futures Trading System UI

Phase 1 scaffold (Next.js 16.2 + React 19 + TypeScript 5). Real chart and panel work lands in Phase 3.

## Tailwind v3 pin

This app uses **Tailwind v3**, not v4 (which is the create-next-app default in 2026). The rationale is
documented in `.planning/phases/01-foundation-data-in/01-RESEARCH.md` Open Question O-1: v4 is still
maturing; v3 is more stable in 2026, and the dense Bloomberg-style styling work begins in Phase 7,
by which point v4 should have matured. Revisit during Phase 7 polish.

## Dev commands

All commands run from the repo root (the `pnpm --filter web` selector targets this workspace member):

```bash
# 1. Install workspace dependencies (run once after clone)
pnpm install

# 2. Start the Next.js dev server (Turbopack; HMR enabled) on http://localhost:3000
pnpm --filter web dev

# 3. Production build (verifies the App Router compiles + Tailwind v3 PostCSS works)
pnpm --filter web build

# 4. Type-check without emitting JS (CI gate; must exit 0)
pnpm --filter web exec tsc --noEmit
```

On Windows the production build typically takes 30–60 seconds — do NOT Ctrl-C it mid-run.

## Phase roadmap

Phase 1 (this stub): placeholder page that proves the toolchain builds cleanly end-to-end.

Phase 3 will replace `app/page.tsx` with the real `/dashboard` page powered by TradingView
**Lightweight Charts** (v5.2.0, vanilla — mounted inside a `useEffect` ref per the project's
NOT-a-wrapper rule from `.planning/PROJECT.md`). The chart panel renders ES/SPY candles, the ORB
box overlay, and entry/stop/target markers driven off WebSocket bars from the FastAPI backend.
