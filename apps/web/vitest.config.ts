import { defineConfig } from 'vitest/config'
import path from 'path'

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    // Exclude Playwright E2E specs from Vitest — they use @playwright/test imports
    // which vitest cannot resolve. E2E tests run via: pnpm test:e2e
    exclude: ['**/e2e/**', '**/node_modules/**'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
})
