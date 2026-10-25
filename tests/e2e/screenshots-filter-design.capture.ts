import { test, expect, Page } from '@playwright/test';
import { openDashboard, openPanel } from './tests/helpers';

/**
 * DESIGN PROTOTYPE ONLY (scratch branch). Captures the card editor and the profile
 * editor for each filter option. The option is chosen with localStorage `hk-proto`.
 */
const OUT = process.env.SHOT_DIR || '/tmp/claude-0/shots';
const VARIANT = process.env.VARIANT || 'today';
const PROTO: Record<string, [string, string]> = {
  today: ['', ''],
  C: ['C', ''],
  D: ['D', ''],
  Dor: ['D', '1'],
  A: ['', ''],
  B: ['B', ''],
  Bnone: ['B', ''],
};

async function seed(page: Page): Promise<void> {
  await page.evaluate(async () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any).hass;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const labels: any[] = await hass.callWS({ type: 'config/label_registry/list' });
    for (const name of ['tasks', 'P1 task', 'P2 task']) {
      if (!labels.some((l) => l.name === name)) {
        await hass.callWS({ type: 'config/label_registry/create', name });
      }
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const areas: any[] = await hass.callWS({ type: 'config/area_registry/list' });
    if (!areas.some((a) => a.area_id === 'garage')) {
      await hass.callWS({ type: 'config/area_registry/create', name: 'Garage' });
    }
  });
}

async function setProfiles(page: Page, groups: boolean): Promise<void> {
  await page.evaluate(async (groups) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any).hass;
    const flat = (f: Record<string, unknown>) => {
      if (!groups) return f;
      const { status, ...rest } = f;
      return { status, groups: [{ name: '', labels_match: 'any', ...rest }] };
    };
    await hass.callService('home_keeper', 'set_options', {
      profiles: [
        { id: 'demo_all', name: 'Everything', filter: flat({ status: 'all' }) },
        {
          id: 'demo_kids',
          name: 'Kids chores',
          filter: flat({ status: 'due_soon', labels: ['tasks'], exclude_areas: ['garage'] }),
        },
      ],
    });
  }, groups);
}

async function shotEditor(page: Page, name: string, width: number): Promise<void> {
  // Open Settings at desktop width first: it makes HA load the label and area pickers.
  await page.setViewportSize({ width: 1280, height: 2400 });
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  await panel.locator('#tab-settings').click();
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  await panel.locator('#hk-profiles .hk-item-card .hk-item-header').first().click();
  await page.waitForTimeout(1000);
  // The #304 build hangs at phone width, so its 390px shot is drawn in a desktop page.
  if (!['A', 'B'].includes(VARIANT)) {
    await page.setViewportSize({ width: width > 500 ? 1280 : width, height: width > 500 ? 2400 : 3800 });
  } else {
    await page.setViewportSize({ width: 1280, height: 3800 });
  }
  // Load the card module on the panel page, where HA has the label and area pickers.
  await page.evaluate(async () => {
    if (!customElements.get('home-keeper-card-editor')) {
      const src = [...document.querySelectorAll('script')]
        .map((s) => s.src)
        .find((s) => s.includes('home-keeper-card'));
      await import(src ?? '/home_keeper_panel/home-keeper-card.js');
    }
  }).catch(() => undefined);
  await page.waitForTimeout(1500);
  await page.evaluate(
    async ({ width, variant }) => {
      await customElements.whenDefined('home-keeper-card-editor');
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const hass = (document.querySelector('home-assistant') as any).hass;
      const host = document.createElement('div');
      host.id = 'proto-host';
      host.style.cssText =
        `position:absolute;top:0;left:0;width:${width}px;box-sizing:border-box;padding:16px;` +
        'z-index:99999;background:var(--card-background-color,#fff);color:var(--primary-text-color)';
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const ed = document.createElement('home-keeper-card-editor') as any;
      ed.hass = hass;
      const config: Record<string, unknown> = {
        type: 'custom:home-keeper-card',
        title: 'P1 tasks',
        profile: variant === 'Bnone' ? '' : 'demo_all',
        filter: 'all',
      };
      if (variant === 'A' || variant === 'B' || variant === 'Bnone') {
        config.groups = [{ labels: ['p1_task'] }];
      } else {
        config.labels = ['p1_task'];
        config.label_match = 'any';
      }
      ed.setConfig(config);
      host.appendChild(ed);
      // Inside the panel, so HA's pickers get the registry context from <home-assistant>.
      const findPanel = (root: Document | ShadowRoot): Element | null => {
        const hit = root.querySelector('home-keeper-panel');
        if (hit) return hit;
        for (const el of root.querySelectorAll('*')) {
          if (el.shadowRoot) {
            const found = findPanel(el.shadowRoot);
            if (found) return found;
          }
        }
        return null;
      };
      const panelEl = findPanel(document);
      host.style.position = 'fixed';
      host.style.maxHeight = 'none';
      (panelEl?.shadowRoot ?? document.body).appendChild(host);
    },
    { width: width > 500 ? 600 : ['A', 'B'].includes(VARIANT) ? 430 : width, variant: VARIANT },
  );
  await page.waitForTimeout(2500);
  await page.locator('#proto-host').screenshot({ path: `${OUT}/${VARIANT}-card-editor${name}.png` });
}

async function shotProfile(page: Page, name: string, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  if (size.width < 500) {
    await panel.locator('#mtab-settings').click();
    await panel.locator('.hk-index-row[data-section="profiles"]').click();
  } else {
    await panel.locator('#tab-settings').click();
  }
  await expect(panel.locator('#hk-profiles')).toBeVisible();
  const row = panel.locator('#hk-profiles .hk-item-card').filter({ hasText: 'Kids chores' }).first();
  await row.locator('.hk-item-header').first().click();
  await expect(row.locator('.hk-item-body ha-form').first()).toBeVisible();
  await page.waitForTimeout(1200);
  await row.screenshot({ path: `${OUT}/${VARIANT}-profile${name}.png` });
}

test('filter design shots', async ({ page }) => {
  test.setTimeout(300_000);
  await openDashboard(page);
  const [p, or] = PROTO[VARIANT];
  await page.evaluate(
    ([p, or]) => {
      localStorage.setItem('hk-proto', p);
      localStorage.setItem('hk-proto-or', or);
    },
    [p, or],
  );
  await seed(page);
  await setProfiles(page, VARIANT === 'A' || VARIANT === 'B' || VARIANT === 'Bnone');
  if (!process.env.PHONE_ONLY) await shotEditor(page, '', 1280);
  await shotEditor(page, '-mobile', 390);
  if (!['A', 'B', 'Bnone'].includes(VARIANT)) {
    await shotProfile(page, '', { width: 1280, height: 2000 });
    await shotProfile(page, '-mobile', { width: 390, height: 2000 });
  }
});
