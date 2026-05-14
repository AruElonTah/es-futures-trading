# apps/web — ES Futures Trading System UI

Phase 1 scaffold (Next.js 16.2 + React 19 + TypeScript 5). Real chart and panel work lands in Phase 3.

## Tailwind v3 pin

This app uses **Tailwind v3**, not v4 (which is the create-next-app default in 2026). The rationale is
documented in `.planning/phases/01-foundation-data-in/01-RESEARCH.md` Open Question O-1: the dense
Bloomberg-style styling work begins in Phase 7, by which point v4's evolving feature surface should be
stable; for a placeholder stub the ergonomic gains from v4 do not justify the version-churn risk.

Revisit during Phase 7 when serious styling work begins.

## Getting Started

```bash
pnpm install
pnpm --filter web dev
```

Open [http://localhost:3000](http://localhost:3000).
