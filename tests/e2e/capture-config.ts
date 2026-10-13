import type { PlaywrightTestConfig } from '@playwright/test';
import baseConfig, { DESKTOP_PROJECT } from './playwright.config';

/**
 * The config a capture harness runs under.
 *
 * The eight harnesses were eight near-identical copies of `{...baseConfig, testDir,
 * testMatch}`, which was fine while the base config had one project. It now has
 * three, and a spread picks all of them up: every capture would run at desktop,
 * phone and tablet width, each writing the *same* committed PNG path, and whichever
 * finished last would be the one committed. Pinning the desktop project here rather
 * than in eight places is what stops the next harness forgetting to.
 *
 * A capture that wants a different width sets it in the harness with
 * `page.setViewportSize()`, the way `screenshots.capture.ts` shoots the phone
 * Settings pair — the shot's framing then sits next to the shot.
 */
export function captureConfig(
  testMatch: string,
  extra: Partial<PlaywrightTestConfig> = {},
): PlaywrightTestConfig {
  return {
    ...baseConfig,
    testDir: '.',
    testMatch,
    projects: [{ name: DESKTOP_PROJECT.name, use: DESKTOP_PROJECT.use }],
    ...extra,
    // Merged, not replaced: an `extra.use` that overrode the whole object would drop
    // baseURL, storageState and the trace/screenshot settings with it.
    //
    // Block service workers. On `localhost`, the Home Assistant frontend registers one
    // in each new browser context, and it calls `location.reload()` when that worker
    // takes control of the page. That occurs some seconds after the first load, at a
    // time that changes from run to run. The reload closed open forms and dialogs in
    // the middle of a capture, and a shot then showed the loading screen.
    use: { ...baseConfig.use, serviceWorkers: 'block', ...extra.use },
  };
}
