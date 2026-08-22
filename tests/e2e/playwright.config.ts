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
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          // Chrome's Local Network Access checks classify a response synthesized by
          // `route.fulfill` as coming from a *public* address space, which then blocks
          // the page's own `ws://localhost:8123/api/websocket` as a local-network
          // request (`net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS`). Any spec that
          // rewrites a document — `card-registration.spec.ts` does, to simulate a stale
          // app shell — loses the websocket entirely and fails for a reason that has
          // nothing to do with Home Keeper. Every test here is localhost talking to
          // localhost, so the check can only ever produce false failures.
          // It bites only on newer Chromium: the headless shell CI installs enforces it,
          // the full Chromium behind CHROMIUM_EXEC did not, which is why this passed
          // locally and failed on CI.
          args: ['--disable-features=LocalNetworkAccessChecks'],
          ...(process.env.CHROMIUM_EXEC
            ? { executablePath: process.env.CHROMIUM_EXEC }
            : {}),
        },
      },
    },
  ],
});
