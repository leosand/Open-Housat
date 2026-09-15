import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  webServer: {
    command: 'npm run dev -- --port 5174 --strictPort',
    port: 5174,
    reuseExistingServer: !process.env.CI,
  },
  use: { baseURL: 'http://localhost:5174' },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
})
