import type { Page } from '@playwright/test';

/**
 * The widths the panel's layout actually changes at, in one place.
 *
 * A leaf module on purpose, like `fixture-ids.ts`: `playwright.config.ts` imports it
 * to build its projects, the specs import it as `../viewports`, and the capture
 * harnesses as `./viewports`. Putting it in `tests/helpers.ts` instead would drag
 * that file's REST/auth machinery into config evaluation.
 *
 * These sizes were each written out by hand in four different files before this
 * existed, so a breakpoint move meant finding all four.
 */
export type Viewport = { width: number; height: number };

/**
 * A phone. Below every breakpoint: the tabs move to the bottom of the screen, Add
 * becomes a floating button, the filter segment comes apart into chips that wrap,
 * and a task row stacks.
 */
export const PHONE: Viewport = { width: 390, height: 844 };

/**
 * A small tablet — the 700–1150px band, and the reason this file has three entries
 * rather than two.
 *
 * 820 is under the drawer's 1150px sheet threshold and under the 1000px at which the
 * appliance master pane and the Settings rail step aside, but *over* the 700px phone
 * chrome. So the top tabs are still there and Add is still inline while the drawer is
 * already a bottom sheet — the one combination no test exercised, and where the three
 * thresholds have to agree with each other.
 */
export const TABLET: Viewport = { width: 820, height: 1180 };

/** What `devices['Desktop Chrome']` gives the default project. */
export const DESKTOP: Viewport = { width: 1280, height: 720 };

/**
 * Comfortably past the 1150px sheet threshold, where the drawer is a side panel and
 * the list beside it stays live. Wider than `DESKTOP` so a test can cross the
 * threshold in both directions without leaving the band it means to be in.
 */
export const WIDE: Viewport = { width: 1400, height: 900 };

/**
 * Which layout band the page is in *right now*.
 *
 * Reads the live viewport rather than `test.info().project.name`, because the specs
 * that resize themselves mid-body — the ones proving the split is pure CSS — would
 * get the wrong answer from the project. The thresholds are the stylesheet's own, so
 * moving a breakpoint is a one-line change here rather than a hunt.
 */
export function band(page: Page): 'phone' | 'narrow' | 'wide' {
  const width = page.viewportSize()?.width ?? DESKTOP.width;
  if (width <= 700) return 'phone';
  return width <= 1150 ? 'narrow' : 'wide';
}
