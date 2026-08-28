/**
 * Shared screenshot helpers for the capture harnesses.
 *
 * The panel's edit drawer scrolls its own content inside a `100vh` sticky column,
 * which breaks the obvious `page.screenshot({ fullPage: true })` in two ways at once
 * (see `shotWithDrawer`). Both capture files hit it, so the handling lives here
 * rather than being written twice and drifting.
 */
import { expect, Locator, Page } from '@playwright/test';

/** Scroll *el* to the middle of whatever scrolls it, rather than just barely into view. */
export async function centre(el: Locator): Promise<void> {
  await el.evaluate((node: Element) => node.scrollIntoView({ block: 'center' }));
}

/**
 * Screenshot a surface with the edit drawer open, full-page where that works and
 * viewport-only where it doesn't.
 *
 * Two things make a naive `fullPage: true` wrong here. The drawer is
 * `position: sticky`, so it renders at the *page's* scroll offset — anywhere
 * `scrollIntoViewIfNeeded` last left it — with blank paper above. And the drawer's
 * scroll container is capped at `100vh`, which a full-page capture expands to the
 * whole document: the container stops being scrollable, so a drawer scrolled down to
 * a field re-lays-out from the top and the shot shows the wrong part of the form,
 * mid-reflow.
 *
 * So: put the page back at the top, and if the drawer is scrolled, photograph the
 * viewport — which is what a person looking at that field would see anyway.
 */
export async function shotWithDrawer(page: Page, path: string): Promise<void> {
  await page.evaluate(() => {
    document.scrollingElement?.scrollTo({ top: 0 });
  });
  await page.waitForTimeout(250);
  const drawerScrolled = await page
    .locator('home-keeper-panel')
    .evaluate(
      (el) =>
        ((el.shadowRoot?.querySelector('.hk-drawer-sticky') as HTMLElement)?.scrollTop ?? 0) > 4,
    );
  await page.screenshot({ path, fullPage: !drawerScrolled });
}

/**
 * Wait for Home Assistant's toasts to expire.
 *
 * A toast the capture deliberately provoked (the blocked-Done message) outlives the
 * step that raised it and lands on the next few shots, over whatever they are meant
 * to be documenting — two of them stacked, when the same action ran twice. HA removes
 * the `ha-toast` element when it expires, so wait for it to be gone rather than
 * guessing at a duration.
 */
export async function settleToasts(page: Page): Promise<void> {
  await expect
    .poll(
      () =>
        page.evaluate(() => {
          const find = (root: ParentNode): Element | null => {
            const hit = root.querySelector('ha-toast');
            if (hit) return hit;
            for (const el of root.querySelectorAll('*')) {
              const sr = (el as HTMLElement).shadowRoot;
              if (sr) {
                const deep = find(sr);
                if (deep) return deep;
              }
            }
            return null;
          };
          return find(document) !== null;
        }),
      { timeout: 15_000 },
    )
    .toBe(false);
}

/**
 * Screenshot the part of *el* that is actually on screen.
 *
 * A plain element screenshot captures the element's whole box, and any of it clipped
 * by a scrollable ancestor comes out blank. That is what the edit drawer is: it
 * scrolls its own content, so a part card taller than the drawer photographed as a
 * band of content between two empty margins. Clipping to the intersection of the
 * element and the viewport captures what a person would actually see.
 */
export async function shotVisible(page: Page, el: Locator, path: string): Promise<void> {
  await el.scrollIntoViewIfNeeded();
  const box = await el.boundingBox();
  if (!box) throw new Error(`no bounding box for ${path}`);
  const view = page.viewportSize();
  if (!view) throw new Error('no viewport size');
  const x = Math.max(0, box.x);
  const y = Math.max(0, box.y);
  const width = Math.min(box.x + box.width, view.width) - x;
  const height = Math.min(box.y + box.height, view.height) - y;
  await page.screenshot({ path, clip: { x, y, width, height } });
}

/**
 * Expand a collapsed `<details>` group, leaving an already-open one alone.
 *
 * Toggling a `<details>` is not idempotent, and several capture steps reach into the
 * same group: a blind `summary.click()` in a later step closes what an earlier one
 * opened, and the shot silently captures a collapsed group.
 *
 * Read-then-click also races a re-render: the panel rebuilds its whole shadow tree on
 * any refresh, so a group read as closed can be re-rendered open before the click
 * lands, and the click then closes it. The failure surfaces much later, as a row that
 * is present but not visible. Poll until it is actually open instead.
 */
export async function expandGroup(group: Locator): Promise<void> {
  await expect
    .poll(
      async () => {
        if (!(await group.evaluate((el: HTMLDetailsElement) => el.open))) {
          await group.locator('summary').click();
        }
        return group.evaluate((el: HTMLDetailsElement) => el.open);
      },
      { timeout: 10_000 },
    )
    .toBe(true);
}

/**
 * Click a row open, retrying until the panel has actually navigated.
 *
 * Same race as `expandGroup`: a click can land on a row that is being replaced and go
 * nowhere. Poll on the URL the click is supposed to produce, not on the click
 * resolving.
 *
 * Takes the whole selector rather than the id, so the seeded id stays written out at
 * the call site — `tests/unit/test_integration_fixture_clean.py` greps these harnesses
 * for the detail-id attribute to prove every record a tour opens is still in the
 * fixture, and an id assembled from a variable would slip past it.
 */
export async function openRow(page: Page, panel: Locator, rowSelector: string): Promise<void> {
  const before = page.url();
  const row = panel.locator(rowSelector);
  await expect
    .poll(
      async () => {
        if (await row.isVisible().catch(() => false)) {
          await row.click().catch(() => undefined);
        }
        return page.url() !== before;
      },
      { timeout: 15_000 },
    )
    .toBe(true);
}
