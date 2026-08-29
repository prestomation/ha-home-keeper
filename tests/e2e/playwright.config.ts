import { defineConfig, devices } from '@playwright/test';
import { PHONE, TABLET } from './viewports';

/**
 * Playwright config for the Home Keeper browser smoke tests.
 *
 * Drives a real Chromium against the Home Assistant `stable` Docker container
 * (the same one used by tests/integration). global-setup completes HA onboarding
 * and writes an authenticated storage state so specs start logged in.
 *
 * ## Three widths, one test body
 *
 * The panel's layout changes at 1150px (the edit drawer becomes a modal bottom
 * sheet), at 1000px (the Settings rail and the appliance master pane step aside)
 * and at 700px (the tabs move to the bottom, Add becomes a floating button, the
 * filter segment comes apart into chips). All of it is CSS, so the same spec can
 * assert the same behaviour at any of them — which is the point of running the
 * panel specs in three projects rather than writing a second suite.
 *
 * A spec opts in with a tag:
 *
 * | tag           | runs in                                        |
 * | ------------- | ---------------------------------------------- |
 * | *(none)*      | desktop only — the default, and most of the suite |
 * | `@responsive` | all three                                      |
 * | `@narrow`     | phone + tablet (the layout it asserts has no desktop form) |
 * | `@phone`      | phone only                                     |
 * | `@tablet`     | tablet only                                    |
 *
 * **Every tag starts with `@` deliberately.** Playwright matches `grep` against the
 * project name, the file name, the describe and test titles *and* the tags, all in
 * one string — so a project named `tablet` with a bare `/tablet/` would match every
 * test it contains.
 *
 * The projects do not replace `page.setViewportSize()`; the two coexist on purpose.
 * A test that crosses a breakpoint *within* one page — proving the split is CSS, or
 * exercising the one `matchMedia` listener in the panel — cannot be expressed as a
 * fixed viewport, so it resizes itself and stays untagged.
 */
const HA_URL = process.env.HA_URL || 'http://localhost:8123';

/**
 * The browser every project runs.
 *
 * Deliberately **not** a phone device descriptor for the narrow projects:
 * `devices['Pixel 5']` and friends also set `isMobile`, `hasTouch` and a
 * `deviceScaleFactor`, none of which `page.setViewportSize()` changes. Since specs
 * use both mechanisms, a device descriptor would make the two disagree — and a
 * capture taken under one would not match a screenshot taken under the other.
 * Overriding only the viewport keeps them identical.
 */
const chromium = {
  ...devices['Desktop Chrome'],
  ...(process.env.CHROMIUM_EXEC
    ? { launchOptions: { executablePath: process.env.CHROMIUM_EXEC } }
    : {}),
};

/**
 * The desktop project, exported so the capture harnesses can pin it.
 *
 * Each `*.config.ts` spreads this file's default export, so without an explicit
 * `projects` every capture would inherit all three and photograph every surface
 * three times over — three widths writing the same committed PNG path, last one
 * wins. `captureConfig()` in `capture-config.ts` applies the pin.
 */
export const DESKTOP_PROJECT = {
  name: 'desktop',
  use: chromium,
  grepInvert: /@narrow|@phone|@tablet/,
};

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
  // Declared desktop-first: with `workers: 1` the projects run in this order, so the
  // leg that matches what shipped before reports first.
  projects: [
    DESKTOP_PROJECT,
    {
      name: 'phone',
      grep: /@responsive|@narrow|@phone/,
      use: { ...chromium, viewport: PHONE },
    },
    {
      name: 'tablet',
      grep: /@responsive|@narrow|@tablet/,
      use: { ...chromium, viewport: TABLET },
    },
  ],
});
