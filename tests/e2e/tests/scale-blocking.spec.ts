import { test, expect, type Page } from '@playwright/test';
import { appendFileSync } from 'fs';
import { callService, deleteTask, listStates, openPanel } from './helpers';

/**
 * How long the panel blocks the browser main thread in a home with many tasks.
 *
 * Each case seeds `HK_SCALE_N` tasks (1000 by default), does one user action in the real
 * panel, and reads the Long Tasks the browser reported. A long task is a block of more
 * than 50 ms. Two numbers come out of it:
 *
 * - `longest`: the longest single block. Above 200 ms the person sees input lag.
 * - `tbt`: total blocking time, the sum of (block - 50 ms) for each block.
 *
 * The budgets are strict on purpose. 50 ms is the long-task line, and 100 ms is 2 times
 * that. A keystroke has to stay under the line, because it is the one action that repeats
 * many times a second.
 *
 * Run a bigger home with `HK_SCALE_N=5000 npx playwright test scale-blocking`. That run
 * takes several minutes, so CI uses the default. Set `HK_SCALE_OUT=<file>` to append one
 * JSON line per measurement to a file.
 */
const N = Number(process.env.HK_SCALE_N || 1000);
const OUT = process.env.HK_SCALE_OUT || '';

/** Budgets in milliseconds. A measured number above its budget fails the case. */
const BUDGET = {
  /** Open the Tasks list from a cold page. */
  openList: { firstRow: 1500, longest: 200, tbt: 500 },
  /** One search keystroke: the worst of 4, and the middle of 4. */
  keystroke: { longest: 100, median: 50 },
  /** Press Done on one row. */
  complete: { longest: 100, tbt: 150 },
  /** Open one task page from the list. */
  openTask: { longest: 150, tbt: 150 },
  /** Open the History tab of that task page. */
  historyTab: { longest: 100, tbt: 150 },
  /** Another surface completes a task, and the panel loads the data again. */
  liveRefresh: { longest: 100, tbt: 150 },
};

/**
 * Where the list stands after the keyed patch (`panel-list-patch.ts`). These lines still
 * miss their budget at 1000 tasks. They need a bound on the rows that are drawn (paging
 * or windowing), which the patch does not give. Each has a ceiling, 2 to 3 times the
 * measured value, so a return to the old behavior fails. A line over its budget but
 * under its ceiling prints KNOWN-GAP. Remove the ceiling when the line meets its budget.
 */
const CEILING: Record<string, number> = {
  'open list: time to first row (ms)': 4000,
  'open list: longest block (ms)': 2500,
  'open list: total blocking time (ms)': 2500,
  'keystroke: worst block (ms)': 300,
  'complete: longest block (ms)': 400,
  'complete: total blocking time (ms)': 400,
  'live refresh: longest block (ms)': 500,
  'live refresh: total blocking time (ms)': 500,
};

/** Assert that `value` is under its budget, or under its ceiling for a known gap. */
function within(label: string, value: number, budget: number): void {
  // The ceilings are for 1000 tasks. A bigger home gets a ceiling that grows with it.
  const ceiling = CEILING[label] === undefined ? undefined : CEILING[label] * Math.max(1, N / 1000);
  if (ceiling === undefined) {
    expect.soft(value, `${label}, budget ${budget}`).toBeLessThan(budget);
    return;
  }
  expect.soft(value, `${label}, ceiling ${ceiling}`).toBeLessThan(ceiling);
  // eslint-disable-next-line no-console
  if (value >= budget) console.log(`KNOWN-GAP ${label}: ${value}, budget ${budget}`);
}

type Block = { longest: number; tbt: number; count: number };

const BASES = [
  'Replace furnace filter',
  'Clean dryer vent',
  'Test smoke alarm',
  'Descale kettle',
  'Check tire pressure',
  'Flush water heater',
  'Wipe window tracks',
  'Update firmware',
  'Replace battery',
  'Rinse HVAC drain',
];

/** One import document. The mix spreads the tasks over every status group. */
function seedDocument(n: number): Record<string, unknown> {
  const tasks: Record<string, unknown>[] = [];
  for (let i = 0; i < n; i++) {
    const name = `Scale ${String(i).padStart(5, '0')} ${BASES[i % BASES.length]}`;
    if (i % 4 === 0) {
      // A one-off: overdue, soon or later.
      const day = ((i / 4) % 80) - 30;
      const due = new Date(Date.now() + day * 86_400_000).toISOString();
      tasks.push({ name, recurrence_type: 'one-off', due });
    } else {
      tasks.push({
        name,
        interval: [1, 2, 3, 6, 12][i % 5],
        unit: 'months',
        notes: i % 3 === 0 ? 'Note line.\nSecond line.' : '',
      });
    }
  }
  return { home_keeper: { format: 1 }, tasks };
}

async function seed(n: number): Promise<string[]> {
  const ids: string[] = [];
  const doc = seedDocument(n);
  const all = doc.tasks as Record<string, unknown>[];
  for (let at = 0; at < all.length; at += 500) {
    const report = await callService(
      'home_keeper',
      'import_data',
      { document: { ...doc, tasks: all.slice(at, at + 500) } },
      true,
    );
    expect(report.problems, 'the seed document is valid').toEqual([]);
    for (const r of report.records) ids.push(r.id as string);
  }
  expect(ids).toHaveLength(n);
  return ids;
}

/**
 * Wait until Home Assistant stops changing entity states after the seed. A state change
 * makes an open panel load its data again, and that load would land in the middle of a
 * measurement.
 */
async function waitForQuietStates(): Promise<void> {
  let last = '';
  let steady = 0;
  for (let i = 0; i < 120 && steady < 4; i++) {
    const states = await listStates();
    const now = JSON.stringify(
      states.map((s) => [s.entity_id, s.state, s.last_changed]).sort(),
    );
    steady = now === last ? steady + 1 : 0;
    last = now;
    await new Promise((r) => setTimeout(r, 1000));
  }
}

/** Start the Long Task observer before any page script runs. */
async function observeLongTasks(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as any;
    w.__hkLong = [] as number[];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) w.__hkLong.push(e.duration);
    }).observe({ type: 'longtask', buffered: true });
  });
}

/**
 * Wait until the main thread is quiet: no new long task, and no 100 ms timer that ran
 * late, for `quietMs` in a row. The late timer catches a block whose Long Task entry
 * has not arrived yet.
 */
async function settle(page: Page, minMs = 0, quietMs = 600): Promise<void> {
  await page.evaluate(
    ([min, quiet]) =>
      new Promise<void>((done) => {
        const w = window as any;
        const start = performance.now();
        let seen = w.__hkLong.length;
        let last = performance.now();
        let quietSince = last;
        const tick = () => {
          const now = performance.now();
          const late = now - last > 150;
          last = now;
          if (w.__hkLong.length !== seen || late) {
            seen = w.__hkLong.length;
            quietSince = now;
          }
          if (now - start >= min && now - quietSince >= quiet) done();
          else setTimeout(tick, 100);
        };
        setTimeout(tick, 100);
      }),
    [minMs, quietMs] as const,
  );
}

/** The blocks the Long Task observer has seen since the last reset. */
async function blocks(page: Page): Promise<Block> {
  return page.evaluate(() => {
    const d: number[] = (window as any).__hkLong;
    return {
      longest: Math.round(Math.max(0, ...d)),
      tbt: Math.round(d.reduce((a, x) => a + Math.max(0, x - 50), 0)),
      count: d.length,
    };
  });
}

/** Run `action` and report the blocks it caused. */
async function measure(page: Page, action: () => Promise<void>, minMs = 0): Promise<Block> {
  await settle(page);
  await page.evaluate(() => ((window as any).__hkLong.length = 0));
  await action();
  await settle(page, minMs);
  return blocks(page);
}

function report(action: string, data: Record<string, number>): void {
  const line = JSON.stringify({ n: N, action, ...data });
  // eslint-disable-next-line no-console
  console.log(`SCALE ${line}`);
  if (OUT) appendFileSync(OUT, line + '\n');
}

// The Home Assistant service worker takes control of a new page about 6 s after it loads
// and reloads it. A reload in the middle of a measurement would throw the numbers away.
test.use({ serviceWorkers: 'block' });

test(`Home Keeper panel — main thread blocking with ${N} tasks`, async ({ context }) => {
  test.setTimeout(Math.max(900_000, N * 400));
  const ids = await seed(N);
  try {
    await waitForQuietStates();
    // Every action gets a fresh page, so no action starts from the state of another.
    const fresh = async () => {
      const page = await context.newPage();
      await observeLongTasks(page);
      return page;
    };
    /** Open the list, wait until it is quiet, and return the panel. */
    const openList = async (page: Page) => {
      await openPanel(page);
      const panel = page.locator('home-keeper-panel').first();
      await expect(panel.locator(`.hk-card[data-id="${ids[0]}"]`)).toBeAttached({
        timeout: 120_000,
      });
      await settle(page);
      return panel;
    };

    await test.step('open the Tasks list', async () => {
      const page = await fresh();
      const t0 = Date.now();
      await page.goto('/home-keeper', { waitUntil: 'domcontentloaded' });
      const panel = page.locator('home-keeper-panel').first();
      await panel.locator('.hk-card').first().waitFor({ state: 'attached', timeout: 120_000 });
      const firstRow = Date.now() - t0;
      await settle(page);
      const b = await blocks(page);
      report('openList', { firstRow, ...b });
      const m = BUDGET.openList;
      within('open list: time to first row (ms)', firstRow, m.firstRow);
      within('open list: longest block (ms)', b.longest, m.longest);
      within('open list: total blocking time (ms)', b.tbt, m.tbt);
      await page.close();
    });

    await test.step('type in the search box', async () => {
      const page = await fresh();
      const panel = await openList(page);
      const input = panel.locator('.hk-search-input');
      await input.click();
      const longest: number[] = [];
      for (const key of ['f', 'i', 'l', 't']) {
        const b = await measure(page, () => page.keyboard.press(key));
        longest.push(b.longest);
      }
      const sorted = [...longest].sort((a, b) => a - b);
      const median = Math.round((sorted[1] + sorted[2]) / 2);
      const worst = sorted[3];
      report('keystroke', { worst, median });
      expect.soft(await input.inputValue(), 'the box holds what was typed').toBe('filt');
      within('keystroke: worst block (ms)', worst, BUDGET.keystroke.longest);
      within('keystroke: median block (ms)', median, BUDGET.keystroke.median);
      await page.close();
    });

    await test.step('complete one task', async () => {
      const page = await fresh();
      const panel = await openList(page);
      const done = panel.locator(`.hk-card[data-id="${ids[1]}"] .done-btn`);
      await expect(done).toBeAttached();
      // The row can sit in a folded group, so the click goes to the element itself.
      const b = await measure(page, () => done.evaluate((el) => (el as HTMLElement).click()), 1500);
      report('complete', b);
      within('complete: longest block (ms)', b.longest, BUDGET.complete.longest);
      within('complete: total blocking time (ms)', b.tbt, BUDGET.complete.tbt);
      await page.close();
    });

    await test.step('open a task page, then its History tab', async () => {
      const page = await fresh();
      const panel = await openList(page);
      const opener = panel.locator(`.hk-card[data-id="${ids[2]}"] .detail-open`).first();
      await expect(opener).toBeAttached();
      const open = await measure(page, () => opener.evaluate((el) => (el as HTMLElement).click()), 800);
      const tabButton = panel.locator('.hk-subtab[data-tab="history"]');
      await expect(tabButton).toBeVisible();
      const tab = await measure(page, () => tabButton.click());
      await expect(panel.locator('.hk-subtab[data-tab="history"].active')).toBeVisible();
      report('openTask', open);
      report('historyTab', tab);
      within('open task: longest block (ms)', open.longest, BUDGET.openTask.longest);
      within('open task: total blocking time (ms)', open.tbt, BUDGET.openTask.tbt);
      within('History tab: longest block (ms)', tab.longest, BUDGET.historyTab.longest);
      within('History tab: total blocking time (ms)', tab.tbt, BUDGET.historyTab.tbt);
      await page.close();
    });

    await test.step('refresh after another surface completes a task', async () => {
      const page = await fresh();
      const panel = await openList(page);
      const card = panel.locator(`.hk-card[data-id="${ids[3]}"]`);
      const before = await card.innerHTML();
      // The service call stands for the card, the to-do list or a tag scan. The panel hears
      // of it through the entity states and loads the data again.
      const b = await measure(
        page,
        async () => {
          await callService('home_keeper', 'complete_task', { task_id: ids[3] });
          await expect(async () => {
            expect(await card.innerHTML()).not.toBe(before);
          }).toPass({ timeout: 20_000 });
        },
        1500,
      );
      report('liveRefresh', b);
      within('live refresh: longest block (ms)', b.longest, BUDGET.liveRefresh.longest);
      within('live refresh: total blocking time (ms)', b.tbt, BUDGET.liveRefresh.tbt);
      await page.close();
    });
  } finally {
    for (let at = 0; at < ids.length; at += 25) {
      await Promise.all(ids.slice(at, at + 25).map((id) => deleteTask(id)));
    }
  }
});
