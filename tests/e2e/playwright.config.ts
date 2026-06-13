import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for the Home Keeper browser smoke tests.
 *
 * Drives a real Chromium against the Home Assistant `stable` Docker container
 * (the same one used by tests/integration). global-setup completes HA onboarding
 * and writes an authenticated storage state so specs start logged in.
 */
const HA_URL = process.env.HA_URL || 'http://localhost:8123';

export default defineConfig({
  testDir: './tests',
  globalSetup: require.resolve('./global-setup'),
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: HA_URL,
    storageState: './.auth/state.json',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
