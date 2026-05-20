---
phase: 7
slug: bloomberg-density-ui-polish
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-20
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Frontend unit framework** | Vitest 4.1.6 (jsdom environment) |
| **Frontend E2E framework** | Playwright 1.60.0 (Chromium) |
| **Python test framework** | pytest 8.4.2 + pytest-asyncio 0.24.x |
| **Vitest config** | `apps/web/vitest.config.ts` (exists) |
| **Playwright config** | `apps/web/e2e/playwright.config.ts` (Wave 0 gap — create) |
| **Quick run (frontend unit)** | `pnpm --filter web test -- --run` |
| **Quick run (Python)** | `uv run pytest packages/ -x -q` |
| **E2E run** | `pnpm --filter web test:e2e` |
| **Full suite** | `uv run pytest packages/ && pnpm --filter web test -- --run` |
| **Estimated runtime** | ~45 seconds (unit) / ~120 seconds (E2E) |

---

## Sampling Rate

- **After every task commit:** Run `pnpm --filter web test -- --run` + `uv run pytest packages/ -x -q`
- **After every plan wave:** Full suite + manual browser verification of layout rendering
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 45 seconds (unit) / 120 seconds (E2E)

---

## Per-Task Verification Map

| Task ID | Req | Threat Ref | Test Type | Automated Command | File Exists | Status |
|---------|-----|------------|-----------|-------------------|-------------|--------|
| WS seq numbers (server) | SP-06 | — | pytest | `uv run pytest packages/api/tests/test_stream.py -x` | ❌ W0 | ⬜ pending |
| useStream backoff + gap detect | UI-02, SP-06 | — | E2E | `pnpm --filter web test:e2e` | ❌ W0 | ⬜ pending |
| 4-pane layout renders | UI-03 | — | E2E | `pnpm --filter web test:e2e` | ❌ W0 | ⬜ pending |
| localStorage save/restore | UI-03 | T-layout-poison | Vitest unit | `pnpm --filter web test -- --run` | ❌ W0 | ⬜ pending |
| TradeHistoryPane renders | UI-06 | — | Vitest unit | `pnpm --filter web test -- --run` | ❌ W0 | ⬜ pending |
| DD histogram below equity | UI-06 | — | Vitest unit | `pnpm --filter web test -- --run` | ❌ W0 | ⬜ pending |
| GET /strategies | UI-07 | — | pytest | `uv run pytest packages/api/tests/test_strategies.py -x` | ❌ W0 | ⬜ pending |
| PUT /strategies/{id}/params 200 | UI-07 | T-path-traversal, T-yaml-inject | pytest | `uv run pytest packages/api/tests/test_strategies.py -x` | ❌ W0 | ⬜ pending |
| PUT /strategies/{id}/params 422 | UI-07 | T-input-validation | pytest | `uv run pytest packages/api/tests/test_strategies.py -x` | ❌ W0 | ⬜ pending |
| POST /strategies/{id}/toggle | UI-07 | — | pytest | `uv run pytest packages/api/tests/test_strategies.py -x` | ❌ W0 | ⬜ pending |
| POST /backtests/run + polling | UI-07 | — | pytest | `uv run pytest packages/api/tests/test_backtests.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `apps/web/e2e/playwright.config.ts` — Playwright config pointing to `http://localhost:3000`
- [ ] `apps/web/e2e/ws-reconnect.spec.ts` — WS disconnect/reconnect/gap-detect E2E test stub (covers UI-02, SP-06)
- [ ] `apps/web/__tests__/TradeHistoryPane.test.ts` — stub: renders trade rows + DD histogram series (covers UI-06)
- [ ] `packages/api/tests/test_strategies.py` — stubs for GET /strategies, PUT /strategies/orb/params 200 + 422, POST .../toggle (covers UI-07, SP-06 server side)
- [ ] `apps/web/package.json` — add `"test:e2e": "playwright test"` + `@playwright/test` devDep

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Drag/resize panes visually | UI-03 | Pixel-level drag interaction hard to automate reliably | Open `localhost:3000/dashboard`, drag resize handle, verify layout shifts and persists after reload |
| Strategy hot-reload visible in engine | UI-07 | Requires live uvicorn + EventBus | Edit ORB param via UI, verify engine log shows `TOPIC_STRATEGY_RELOAD` received |
| WS gap-detect Playwright (full flow) | UI-02 | Requires mock WS server pause | Run `pnpm test:e2e` — spec simulates 30s network drop via Playwright `page.route` intercept |
| Hotkey collision detection at startup | SP-06 | Runtime throw at hook init | Start dev server, open console, confirm no collision errors; add deliberate duplicate and confirm throw |

---

## Threat Model

| Pattern | STRIDE | Mitigation | Plan Task |
|---------|--------|------------|-----------|
| Path traversal via `strategy_id` in YAML write | Tampering | Validate `strategy_id` matches `^[a-z0-9_-]+$`; use `Path.resolve()` + `relative_to()` guard | strategies.py task |
| YAML injection via params values | Tampering | Pydantic model validates before `yaml.dump()`; only write typed values | strategies.py task |
| CORS expansion for PUT method | Spoofing | Add `PUT` to `allow_methods` (localhost-scoped); no `*` widening | app.py CORS task |
| localStorage layout poisoning | Tampering | `JSON.parse` in `try/catch` with silent fallback (D-06) | TerminalLayout task |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 45s (unit) / 120s (E2E)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
