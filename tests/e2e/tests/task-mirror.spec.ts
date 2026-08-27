import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  familyChoresCard,
  listTasks,
  openDashboard,
  openPanel,
} from './helpers';

/**
 * Task mirrors, from the household's side.
 *
 * The integration suite proves the loop over the service API. What only a browser
 * shows is the payoff: the chore appearing as an ordinary line on the family's own
 * to-do list card — with the due date that makes it actionable — and a tick on that
 * card's checkbox landing back in Home Keeper's completion history. A captured
 * surface with nothing asserting on it is how #221 hid in plain sight for months,
 * so this spec reads the card's *contents*, not its count.
 *
 * `todo.family_chores` is a seeded `local_todo` list (see
 * `tests/integration/ha_config/.storage/core.config_entries`) standing in for the
 * Todoist project or kitchen-tablet list a real household already checks. It reports
 * its completed items rather than dropping them, so the mirror below runs with
 * `vanish_as_completed` off — what the README tells a `local_todo` user to do, and
 * what keeps a swept line from reading as somebody ticking a chore off.
 */

const FAMILY_LIST = 'todo.family_chores';
const CHORE = 'E2E mirror chore';
const MIRROR_ID = 'e2e_task_mirror';

/** The items on the household list, optionally filtered by status. */
async function familyItems(status?: string[]): Promise<any[]> {
  const data: Record<string, unknown> = { entity_id: FAMILY_LIST };
  if (status) data.status = status;
  const resp = await callService('todo', 'get_items', data, true);
  return resp[FAMILY_LIST]?.items ?? [];
}

async function familySummaries(status?: string[]): Promise<string[]> {
  return (await familyItems(status)).map((i) => i.summary);
}

/** Retry a Home Keeper service call through the entry-reload window a save opens. */
async function callWhenReady(service: string, data: Record<string, unknown>): Promise<void> {
  await expect
    .poll(
      async () => {
        try {
          await callService('home_keeper', service, data);
          return true;
        } catch {
          return false;
        }
      },
      { timeout: 40_000 },
    )
    .toBe(true);
}

/**
 * Point one mirror at the household list.
 *
 * No profile, so it gets the default filter: every enabled, scheduled task that is
 * due now. Passing `[]` turns it off again, which is what clears the lines it wrote.
 */
async function setMirror(on: boolean): Promise<void> {
  await callWhenReady('set_options', {
    task_mirrors: on
      ? [
          {
            id: MIRROR_ID,
            entity_id: FAMILY_LIST,
            profile_id: null,
            two_way: true,
            vanish_as_completed: false,
          },
        ]
      : [],
  });
}

test.describe('Home Keeper — tasks mirrored onto a household to-do list', () => {
  let taskId: string | undefined;

  test.beforeEach(async () => {
    await setMirror(true);
  });

  test.afterEach(async () => {
    // The container's store and the seeded list are shared state, so this spec has
    // to leave nothing behind — mirror, task, and both the open and ticked-off
    // lines. Switching the mirror off is what clears the open ones, so it goes
    // first, and the sweep waits for that pass to land: removing a line the mirror
    // still believes it owns is exactly the "the household deleted it" input it is
    // built to react to. The sweep takes the whole list because a default-filter
    // mirror puts every seeded overdue chore on it too, and nothing else here writes
    // to that list.
    await setMirror(false);
    await expect
      .poll(async () => (await familySummaries(['needs_action'])).length, { timeout: 30_000 })
      .toBe(0);
    await deleteTask(taskId);
    taskId = undefined;
    const leftovers = (await familyItems()).map((i) => i.uid);
    if (leftovers.length) {
      await callService('todo', 'remove_item', { entity_id: FAMILY_LIST, item: leftovers });
    }
  });

  test('an overdue chore lands on the household list, carrying its due date', async ({
    page,
  }) => {
    // Before: the family's list has no line for this chore.
    expect(await familySummaries()).not.toContain(CHORE);

    // A floating task with no "last done" is due immediately, so the default
    // filter wants it the moment it exists.
    taskId = await createTask({
      name: CHORE,
      recurrence_type: 'floating',
      interval: 1,
      unit: 'days',
    });

    await expect
      .poll(async () => await familySummaries(['needs_action']), { timeout: 40_000 })
      .toContain(CHORE);

    // The payoff, in the browser: the chore is a line on the family's own card.
    await openDashboard(page);
    const card = familyChoresCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    await expect(card).toContainText(CHORE);

    // And it is not just a summary — the line carries the task's due date, which is
    // what makes it actionable on somebody's phone. `next_due` is stored in Home
    // Assistant's own timezone, so its leading `YYYY-MM-DD` is the day a to-do list
    // works in (and dropping the time is what stops the line drifting a day either
    // way for whoever reads it).
    const task = (await listTasks()).find((t) => t.id === taskId);
    const item = (await familyItems(['needs_action'])).find((i) => i.summary === CHORE);
    expect(item.due, 'the mirrored line should carry a due date').toBeTruthy();
    expect(item.due).toBe(String(task!.next_due).slice(0, 10));
  });

  test('Settings names the configured sync by the list it keeps in step', async ({ page }) => {
    // The surface `docs/images/47-panel-settings-task-mirrors.png` documents. A
    // capture is not coverage: without this, the card could render every row as
    // "Not configured" and the only thing that would notice is a reader of the
    // README.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#tab-settings').click();
    const mirrors = panel.locator('#hk-task-mirrors');
    await expect(mirrors).toBeVisible();
    const row = mirrors.locator('.hk-item-header').first();
    await expect(row.locator('.hk-item-name')).toHaveText('Family chores');

    // Rows start collapsed; opening one reveals the sync's own form.
    await row.click();
    await expect(mirrors.locator('.hk-item-body ha-form').first()).toBeVisible();
  });

  test('ticking the line off on the card completes the task in Home Keeper', async ({
    page,
  }) => {
    taskId = await createTask({
      name: CHORE,
      recurrence_type: 'floating',
      interval: 1,
      unit: 'days',
    });
    await expect
      .poll(async () => await familySummaries(['needs_action']), { timeout: 40_000 })
      .toContain(CHORE);

    // Tick it off in the browser, the way the household would — the card's own
    // checkbox, not a service call.
    await openDashboard(page);
    const card = familyChoresCard(page);
    await expect(card).toBeVisible({ timeout: 30_000 });
    const row = card
      .locator('ha-check-list-item, ha-md-list-item')
      .filter({ hasText: CHORE })
      .first();
    await row.locator('ha-checkbox, input[type="checkbox"]').first().click();

    // Home Keeper records it as a completion like any other Done.
    await expect
      .poll(
        async () => (await listTasks()).find((t) => t.id === taskId)?.completions?.length,
        { timeout: 60_000 },
      )
      .toBe(1);

    // The line they ticked is theirs — it stays on the list as their record rather
    // than vanishing out from under them.
    expect(await familySummaries(['completed'])).toContain(CHORE);

    // …and the panel agrees: the task's detail page lists the completion.
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator(`.detail-open[data-detail-id="${taskId}"]`).click();
    await expect(panel.locator('.hk-hist-list li')).toHaveCount(1);
  });
});
