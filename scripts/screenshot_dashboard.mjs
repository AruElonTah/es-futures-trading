/**
 * Playwright screenshot of /dashboard — waits for charts to render.
 * Run: node scripts/screenshot_dashboard.mjs
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'fs'

const URL = 'http://localhost:3000/dashboard'
const OUT = 'scripts/dashboard_screenshot.png'

const browser = await chromium.launch()
const page = await browser.newPage()
await page.setViewportSize({ width: 1440, height: 900 })

// Capture console messages for debugging
const logs = []
page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`))
page.on('pageerror', err => logs.push(`[ERROR] ${err.message}`))

console.log('Navigating to', URL)
await page.goto(URL, { waitUntil: 'domcontentloaded' })

// Wait for canvas elements — lightweight-charts renders to canvas
console.log('Waiting for canvas...')
try {
  await page.waitForSelector('canvas', { timeout: 15_000 })
  const count = await page.locator('canvas').count()
  console.log('Canvas elements found:', count)
} catch {
  console.warn('No canvas found within 15s')
}

// Allow charts to fully paint after data fetch
await page.waitForTimeout(4000)

const canvasCount = await page.locator('canvas').count()
const canvasSizes = await page.evaluate(() =>
  [...document.querySelectorAll('canvas')].map(c => ({ w: c.width, h: c.height }))
)
console.log('Canvases at capture:', JSON.stringify(canvasSizes))

await page.screenshot({ path: OUT })
console.log('Screenshot saved to', OUT)

// Write console log summary
writeFileSync('scripts/dashboard_console.txt', logs.join('\n'))
console.log('Console log saved to scripts/dashboard_console.txt')

await browser.close()
