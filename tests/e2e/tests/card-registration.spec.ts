import { test, expect } from '@playwright/test';
import { DASHBOARD } from './helpers';

/**
 * Regression test for #228 — "Custom element doesn't exist: home-keeper-card".
 *
 * `frontend.add_extra_js_url` reaches a browser exactly one way: Home Assistant's
 * `IndexView` renders an inline `import("<url>")` for every extra module into the
 * app-shell HTML. That response carries no `Cache-Control` and no ETag, and HA's own
 * service worker serves navigations `StaleWhileRevalidate` from a 24h `file-cache` —
 * so a shell cached before Home Keeper was installed has no such import, and the card
 * element was never defined.
 *
 * Since #368 a storage-mode install does not put the card into the shell at all: the
 * Lovelace resource list, which the frontend fetches over the websocket on every
 * dashboard load, is the only path. So every load of this dashboard is now the
 * #228 case, with no need to strip anything. The card must render, and the bundle
 * must cross the wire, which proves the resource delivered it.
 * `tests/integration/test_card_resource.py` pins that the shell has no import.
 */

// A service worker answers navigations before Playwright sees them, and a shell it
// cached earlier in the run is not the one this test means to load.
test.use({ serviceWorkers: 'block' });

const CARD_BUNDLE = 'home-keeper-card.js';

test.describe('Home Keeper card — delivery (#228)', () => {
  test('renders from the Lovelace resource alone', async ({ page }) => {
    // The card can only load once the websocket is up and the resource list has been
    // fetched.
    test.setTimeout(120_000);

    // Diagnosing this test from a CI log is otherwise guesswork.
    const problems: string[] = [];
    const bundleTraffic: string[] = [];
    let shell: string | null = null;
    page.on('console', (m) => {
      if (m.type() === 'error') problems.push(`console: ${m.text().slice(0, 300)}`);
    });
    page.on('pageerror', (e) => problems.push(`pageerror: ${String(e).slice(0, 300)}`));
    page.on('request', (r) => {
      if (r.url().includes(CARD_BUNDLE)) bundleTraffic.push(`request ${r.url()}`);
    });
    page.on('response', async (r) => {
      if (r.url().includes(CARD_BUNDLE)) bundleTraffic.push(`response ${r.status()}`);
      if (r.request().resourceType() === 'document' && new URL(r.url()).pathname === DASHBOARD) {
        shell = await r.text().catch(() => null);
      }
    });
    page.on('requestfailed', (r) => {
      if (r.url().includes(CARD_BUNDLE))
        problems.push(`bundle request failed: ${r.failure()?.errorText}`);
    });

    await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });

    // Deliberately not `helpers.openCardDashboard`: its 3x reload retry exists to
    // absorb exactly this class of failure and would mask the regression.
    const card = page.locator('home-keeper-card').first();
    try {
      await card.waitFor({ state: 'attached', timeout: 60_000 });
    } catch (err) {
      throw new Error(
        'the card never loaded from the Lovelace resource — issue #228.\n' +
          `bundle traffic: ${
            bundleTraffic.length ? bundleTraffic.join(', ') : '(the bundle was never requested)'
          }\nbrowser problems:\n${problems.join('\n') || '(none)'}`,
        { cause: err },
      );
    }
    await expect(card.locator('.hk-row, .hk-empty').first()).toBeVisible({ timeout: 30_000 });
    await expect(card.locator('.hk-title').first()).toContainText('Home maintenance');

    // Guard the guard. If the shell imports the bundle again, this test no longer
    // proves that the resource alone is enough.
    expect(shell, 'the dashboard document was never seen').not.toBeNull();
    expect(shell!, 'the app shell imports the card bundle again — see #368').not.toContain(
      CARD_BUNDLE,
    );
    expect(
      bundleTraffic.filter((t) => t.startsWith('response')),
      `the card upgraded without the bundle being fetched: ${bundleTraffic.join(', ')}`,
    ).not.toHaveLength(0);

    // What the reporter saw: HA substitutes an error card for an undefined custom
    // element, one per card instance. The seeded dashboard's other cards are native,
    // so a single one of these is the bug.
    await expect(page.locator('hui-error-card')).toHaveCount(0);
  });
});
