import { test, expect, type Page } from '@playwright/test';
import { auditOutlines } from '../outline-audit';
import { ASSET, PART, TASK } from '../fixture-ids';
import { openListFilters, setTaskLayout } from './helpers';

/**
 * Every outline is whole (#554).
 *
 * A border, a ring or an outline of a control must show all of it, on every view, at
 * the desktop and the phone width. `outline-audit.ts` finds a control that an ancestor
 * clips, and a border with a gap. Each view below is opened by a URL and a few clicks,
 * then audited. A view that fails names the control and the box that cuts it.
 *
 * Add the view to `VIEWS` when you add a surface that has bordered controls. A control
 * that is cut on purpose carries `data-hk-cut`.
 */
type View = {
  name: string;
  url: string;
  /** What shows that the view is ready. Defaults to the panel page. */
  ready?: (page: Page) => Promise<void>;
  /** Open a dialog, a menu or a state. */
  before?: (page: Page) => Promise<void>;
  /** Put back what `before` changed. */
  after?: (page: Page) => Promise<void>;
};

const panel = (page: Page) => page.locator('home-keeper-panel').first();
const card = (page: Page, n: number) => page.locator('home-keeper-card').nth(n);
const panelReady = async (page: Page): Promise<void> => {
  await expect(panel(page).locator('.hk-wrap')).toBeVisible();
};
const cardReady = async (page: Page): Promise<void> => {
  await expect(card(page, 0).locator('.hk-row').first()).toBeVisible();
};
const settingsReady = async (page: Page): Promise<void> => {
  await expect(panel(page).locator('.hk-settings-layout')).toBeVisible();
};
/** A dialog host reports hidden to Playwright, so wait on a button inside it. */
const dialogOpen = async (page: Page): Promise<void> => {
  await expect(
    page.locator('ha-dialog[open]').getByRole('button', { name: 'Cancel' }).first(),
  ).toBeVisible();
};
/** The layout is a stored setting of the user, so a view that changes it puts it back. */
const layout = (value: string): Pick<View, 'before' | 'after'> => ({
  before: async (page) => {
    await setTaskLayout(page, value);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await panelReady(page);
  },
  after: async (page) => {
    await setTaskLayout(page, 'rows');
  },
});

const WATER_HEATER = `/home-keeper/appliances/${ASSET.waterHeater}`;
const WATER_FILTER = `/home-keeper/tasks/${TASK.waterFilter}`;
const SETTINGS = [
  'general',
  'duetime',
  'cost',
  'shopping',
  'problem',
  'skipsnooze',
  'profiles',
  'notifications',
  'companions',
  'transfer',
];

const VIEWS: View[] = [
  // Tasks
  {
    name: 'Tasks, filters open',
    url: '/home-keeper',
    before: async (page) => {
      await openListFilters(panel(page));
      await expect(panel(page).locator('.hk-card-row').first()).toBeVisible();
    },
  },
  { name: 'Tasks, tiles', url: '/home-keeper', ...layout('tiles') },
  { name: 'Tasks, board', url: '/home-keeper', ...layout('board') },
  {
    name: 'Task page',
    url: WATER_FILTER,
    before: async (page) => {
      await expect(panel(page).locator('.hk-detail-actions .hk-split-caret')).toBeVisible();
    },
  },
  {
    name: 'Task page, Done menu',
    url: WATER_FILTER,
    before: async (page) => {
      await panel(page).locator('.hk-detail-actions .hk-split-caret').click();
      await expect(panel(page).locator('.hk-defer-menu')).toBeVisible();
    },
  },
  {
    name: 'Task page, Snooze dialog',
    url: WATER_FILTER,
    before: async (page) => {
      await panel(page).locator('.hk-split-caret').click();
      await panel(page).locator('.hk-defer-snooze').click();
      await dialogOpen(page);
    },
  },
  {
    name: 'Task page, History',
    url: `/home-keeper/tasks/${TASK.fridgeFilter}/history`,
    before: async (page) => {
      await expect(panel(page).locator('.hk-subtab[data-tab="history"].active')).toBeVisible();
    },
  },
  {
    name: 'Task page, History, delete confirmation',
    url: `/home-keeper/tasks/${TASK.fridgeFilter}/history`,
    before: async (page) => {
      await panel(page).locator('.hk-hist-del').first().click();
      await expect(page.locator('.hk-confirm-scrim')).toBeVisible();
    },
    after: async (page) => {
      await page.keyboard.press('Escape');
      await expect(page.locator('.hk-confirm-scrim')).toHaveCount(0);
    },
  },
  {
    name: 'Add task form',
    url: '/home-keeper',
    before: async (page) => {
      await panel(page).locator('#add-btn, #add-fab').locator('visible=true').first().click();
      await expect(panel(page).locator('#hk-task-form')).toBeVisible();
    },
  },
  {
    name: 'Edit task form',
    url: `/home-keeper/tasks/${TASK.fridgeFilter}`,
    before: async (page) => {
      await panel(page).locator('.d-edit').click();
      await expect(panel(page).locator('#hk-form')).toBeVisible();
    },
  },
  // Appliances and parts
  { name: 'Appliances', url: '/home-keeper/appliances' },
  {
    name: 'Appliances, tree',
    url: '/home-keeper/appliances',
    before: async (page) => {
      const filters = panel(page).locator('#hk-filters-btn');
      if (await filters.isVisible()) await filters.click();
      await panel(page).locator('[data-seg="assetView"] [data-seg-val="tree"]').click();
      await expect(panel(page).locator('.hk-tree-group').first()).toBeVisible();
    },
    after: async (page) => {
      await panel(page).locator('[data-seg="assetView"] [data-seg-val="flat"]').click();
    },
  },
  {
    name: 'Parts',
    url: '/home-keeper/appliances/parts',
    before: async (page) => {
      await expect(panel(page).locator('.hk-pt-row').first()).toBeVisible();
    },
  },
  ...['parts', 'tasks', 'documents', 'details', 'related', 'history'].map(
    (tab): View => ({
      name: `Appliance page, ${tab}`,
      url: `${WATER_HEATER}/${tab}`,
      before: async (page) => {
        await expect(panel(page).locator(`.hk-subtab[data-tab="${tab}"].active`)).toBeVisible();
      },
    }),
  ),
  {
    name: 'Part page',
    url: `${WATER_HEATER}/parts/${PART.anode}`,
    before: async (page) => {
      await expect(panel(page).locator('.hk-detail-card').first()).toBeVisible();
    },
  },
  {
    name: 'Appliance edit form',
    url: WATER_HEATER,
    before: async (page) => {
      await panel(page).locator('.d-edit').click();
      await expect(panel(page).locator('.hk-drawer[data-open] .hk-drawer-sticky')).toBeVisible();
    },
  },
  // Settings
  { name: 'Settings', url: '/home-keeper/settings', ready: settingsReady },
  ...SETTINGS.map(
    (section): View => ({
      name: `Settings, ${section}`,
      url: `/home-keeper/settings/${section}`,
      ready: settingsReady,
    }),
  ),
  // The dashboard card
  { name: 'Card', url: '/home-keeper-e2e/card', ready: cardReady },
  {
    name: 'Card, grouped',
    url: '/home-keeper-e2e/card',
    ready: cardReady,
    before: async (page) => {
      await expect(card(page, 1).locator('details.hk-group').first()).toBeVisible();
    },
  },
  {
    name: 'Card, labels',
    url: '/home-keeper-e2e/card',
    ready: cardReady,
    before: async (page) => {
      await expect(card(page, 2).locator('ha-assist-chip.hk-label').first()).toBeVisible();
    },
  },
  {
    name: 'Card, new task form',
    url: '/home-keeper-e2e/card',
    ready: cardReady,
    before: async (page) => {
      await card(page, 0).locator('#hk-add').click();
      await expect(card(page, 0).locator('.hk-form ha-form').first()).toBeVisible();
    },
  },
  {
    name: 'Card, Snooze dialog',
    url: '/home-keeper-e2e/card',
    ready: cardReady,
    before: async (page) => {
      await card(page, 0).locator('.hk-defer-snooze').first().click();
      await expect(page.locator('ha-dialog[open] .hk-snooze-hint').first()).toBeVisible();
    },
  },
  {
    name: 'Card editor',
    url: '/home-keeper-e2e/card',
    ready: cardReady,
    before: async (page) => {
      await page.evaluate(() => {
        const hass = (document.querySelector('home-assistant') as unknown as { hass: unknown }).hass;
        const ed = document.createElement('home-keeper-card-editor') as HTMLElement & {
          setConfig: (c: unknown) => void;
          hass: unknown;
        };
        ed.id = 'hk-audit-editor';
        ed.style.cssText =
          'position:fixed;left:0;top:0;width:100%;max-width:520px;height:100vh;overflow:auto;z-index:99999;background:var(--card-background-color,#fff)';
        document.body.appendChild(ed);
        ed.setConfig({ type: 'custom:home-keeper-card', title: 'Audit' });
        ed.hass = hass;
      });
      await expect(page.locator('#hk-audit-editor ha-form').first()).toBeVisible();
    },
  },
];

test.describe('Home Keeper — outlines are whole (#554)', () => {
  for (const view of VIEWS) {
    test(`${view.name} @responsive`, async ({ page }) => {
      await page.goto(view.url, { waitUntil: 'domcontentloaded' });
      await (view.ready ?? panelReady)(page);
      try {
        if (view.before) await view.before(page);
        expect(await auditOutlines(page), 'controls with a cut or open outline').toEqual([]);
      } finally {
        if (view.after) await view.after(page);
      }
    });
  }
});
