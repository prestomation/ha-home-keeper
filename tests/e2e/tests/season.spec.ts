import { test, expect } from '@playwright/test';
import { createTask, deleteTask, listTasks, openPanel, trackPanelErrors } from './helpers';

/**
 * Active-season windows in a real browser.
 *
 * The unit tests cover the schema and the payload; what only a browser can answer is
 * whether a stored season comes *back* into the form. Issue #242's reporter created a
 * task with two windows, reopened it, and found the second one switched on with no
 * pickers under it — the round trip, not the maths. Nothing failed at the time because
 * no test opened a seasonal task for editing.
 */
test.describe('Home Keeper panel — active season', () => {
  let created: string[] = [];

  test.afterEach(async () => {
    // The e2e container's task store IS the committed seed fixture, so anything left
    // behind is a permanent addition to it.
    await Promise.all(created.map(deleteTask));
    created = [];
  });

  test('a stored two-window season reopens with both windows filled in', async ({ page }) => {
    const errors = trackPanelErrors(page);
    const taskId = await createTask({
      name: 'Fertilize the yard',
      recurrence_type: 'floating',
      interval: 2,
      unit: 'months',
      active_season: [
        { start: '04-01', end: '05-31' },
        { start: '09-01', end: '10-31' },
      ],
    });
    created.push(taskId);

    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    // Both windows are on screen, each with its own pickers — the reported bug was a
    // second window that came back switched on and uneditable.
    await expect(panel.locator('#hk-task-form-season-1')).toBeVisible();
    await expect(panel.locator('#hk-task-form-season-2')).toBeVisible();
    for (const window of ['#hk-task-form-season-1', '#hk-task-form-season-2']) {
      await expect(panel.locator(`${window} ha-select`)).toHaveCount(2);
      await expect(panel.locator(`${window} ha-selector-number`)).toHaveCount(2);
    }
    // Both windows are the same control repeated, so they carry the same labels.
    await expect(panel.locator('#hk-task-form-season-2')).toContainText('Start month');
    await expect(panel.locator('#hk-task-form-season-2')).toContainText('End month');

    // Saving an untouched form leaves the season exactly as it was found.
    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);
    const saved = (await listTasks()).find((t) => t.id === taskId);
    expect(saved?.active_season).toEqual([
      { start: '04-01', end: '05-31' },
      { start: '09-01', end: '10-31' },
    ]);
    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('a window can be added and removed, and the task is saved with what is on screen', async ({
    page,
  }) => {
    const taskId = await createTask({
      name: 'Season edit probe',
      recurrence_type: 'floating',
      interval: 1,
      unit: 'months',
      active_season: [{ start: '04-01', end: '09-30' }],
    });
    created.push(taskId);

    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-task-form-season-1')).toBeVisible();
    // One window, so there is nothing to remove yet.
    await expect(panel.locator('#hk-season-remove-1')).toHaveCount(0);

    await panel.locator('#hk-season-add').click();
    await expect(panel.locator('#hk-task-form-season-2')).toBeVisible();
    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);
    expect((await listTasks()).find((t) => t.id === taskId)?.active_season).toHaveLength(2);

    // Remove the *first* window: the survivor shifts up rather than the last one
    // being dropped, so what is saved is what the form was showing.
    await panel.locator('.d-edit').click();
    await expect(panel.locator('#hk-task-form-season-2')).toBeVisible();
    await panel.locator('#hk-season-remove-1').click();
    await expect(panel.locator('#hk-task-form-season-2')).toHaveCount(0);
    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);
    expect((await listTasks()).find((t) => t.id === taskId)?.active_season).toEqual([
      { start: '04-01', end: '09-30' },
    ]);
  });

  test('switching the season off clears it, and the due date leaves the window', async ({
    page,
  }) => {
    const taskId = await createTask({
      name: 'Season clear probe',
      recurrence_type: 'floating',
      interval: 1,
      unit: 'months',
      active_season: [{ start: '04-01', end: '04-30' }],
    });
    created.push(taskId);
    const seasonal = (await listTasks()).find((t) => t.id === taskId);
    expect(seasonal?.next_due?.slice(5, 7)).toBe('04');

    await page.goto(`/home-keeper/tasks/${taskId}`, { waitUntil: 'domcontentloaded' });
    const panel = page.locator('home-keeper-panel').first();
    await panel.waitFor({ state: 'attached', timeout: 45_000 });
    await panel.locator('.d-edit').click();
    const seasonSwitch = panel
      .locator('#hk-task-form-cadence ha-selector-boolean ha-switch')
      .first();
    await seasonSwitch.click();
    await expect(panel.locator('#hk-task-form-season-1')).toHaveCount(0);
    await panel.locator('#f-save').click();
    await expect(panel.locator('#hk-task-form')).toHaveCount(0);

    const cleared = (await listTasks()).find((t) => t.id === taskId);
    expect(cleared?.active_season).toBeNull();
    // Nothing is holding the date back any more: a monthly task is due within a month.
    const due = new Date(cleared?.next_due as string).getTime();
    expect(due).toBeLessThan(Date.now() + 32 * 24 * 60 * 60 * 1000);
  });
});
