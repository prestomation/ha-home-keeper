import { test, expect } from '@playwright/test';
import { deleteTask, listTasks, openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

/**
 * Duplicating a task (#279).
 *
 * The reporter's case is ten "water the flowers" tasks, one per moisture sensor,
 * differing only in a name, a sensor and a device. Duplicate opens the *create* form
 * prefilled, so the copy is a couple of fields away from done.
 *
 * The sensor task is the one worth driving end to end: it is the issue's own shape,
 * and it carries the trap — a usage meter's `baseline` is the reading the original
 * was anchored at, and a copy that inherits it starts life most of the way through an
 * interval it never measured.
 *
 * Untagged: desktop layout, where the drawer is a column beside the page.
 */
test.describe('Home Keeper panel — duplicating a task', () => {
  test('seeds the create form from a sensor task, without its meter anchor', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // A dormant usage task lives in the collapsed Monitored group (it has no due
    // date to sort by), so open that before reaching for its row.
    const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
    if (!(await monitored.evaluate((el: HTMLDetailsElement) => el.open))) {
      await monitored.locator('summary').click();
    }
    await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.nozzleUsage}$`));

    await panel.locator('.d-dup').click();
    await expect(panel.locator('#hk-task-form')).toBeVisible();

    // It is a *creation*, not an edit of the original — the whole mechanism.
    await expect(panel.locator('#f-save')).toHaveText(/Create/);
    // The drawer opens beside the page, which stays put.
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.nozzleUsage}$`));
    await expect(panel.locator('#back-btn')).toBeVisible();

    // The name arrives already marked as a copy…
    await expect(panel.locator('#hk-task-form ha-selector-text input').first()).toHaveValue(
      /\(copy\)$/,
    );
    // …and the meter's starting reading arrives *blank*, so the copy anchors itself
    // against its own sensor rather than inheriting the original's 660 h. The number
    // fields run target, starting reading, then the backstop interval.
    const startingReading = panel.locator('#hk-task-form ha-selector-number input').nth(1);
    await expect(startingReading).toHaveValue('');
    // The live hint is the same claim in words: a seeded baseline makes it read
    // "Counting from 660 h…", so its absence is what proves the anchor did not ride
    // along. Asserting the sentence beats asserting an input index alone.
    await expect(panel.locator('#hk-sensor-hint')).toBeVisible();
    await expect(panel.locator('#hk-sensor-hint')).not.toContainText('Counting from');

    let copyId: string | undefined;
    try {
      await panel.locator('#f-save').click();
      await expect(panel.locator('#hk-form')).toHaveCount(0, { timeout: 10_000 });

      const tasks = await listTasks();
      const original = tasks.find((t) => t.id === TASK.nozzleUsage);
      const copy = tasks.find(
        (t) => t.id !== TASK.nozzleUsage && /\(copy\)$/.test(String(t.name)),
      );
      copyId = copy?.id;

      expect(copy, 'Create should have made a second task').toBeTruthy();
      // The rule came across…
      expect(copy!.recurrence_type).toBe('sensor');
      expect(copy!.sensor.entity_id).toBe(original!.sensor.entity_id);
      expect(copy!.sensor.target).toBe(original!.sensor.target);
      // …the record did not.
      expect(copy!.completions ?? []).toHaveLength(0);
      expect(copy!.last_completed ?? null).toBeNull();
      expect(copy!.tag_id ?? null).toBeNull();
      // The baseline is either unset or the copy's own live reading — never the
      // original's stored anchor carried over wholesale.
      if (copy!.sensor.baseline != null) {
        expect(copy!.sensor.baseline).not.toBe(original!.sensor.baseline);
      }
      // The original is untouched by having been copied.
      expect(original!.sensor.baseline).toBeDefined();
    } finally {
      // Every later spec and every screenshot reads this list.
      await deleteTask(copyId);
    }

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('refuses a task it does not own, and says why', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    const before = (await listTasks()).length;

    // A wear-part task: its appliance's reconciler owns it.
    await panel.locator(`.detail-open[data-detail-id="${TASK.anode}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.anode}$`));

    const blocked = panel.locator('.d-dup-blocked');
    await expect(blocked).toBeVisible();
    await expect(panel.locator('.d-dup')).toHaveCount(0);
    await expect(blocked.locator('ha-button')).toHaveAttribute('disabled', /.*/);

    // A dead button that says nothing is worse than no button; pressing it explains.
    await blocked.click();
    await expect(panel.locator('#hk-form')).toHaveCount(0);
    // Refusing is inert: it does not open a form, create anything, or move the page.
    // The span wraps a disabled button, and a stray navigation here would be invisible
    // in a screenshot but obvious to anyone actually pressing it.
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.anode}$`));
    await expect(panel.locator('.hk-detail-actions').first()).toBeVisible();
    expect((await listTasks()).length, 'refusing must not create anything').toBe(before);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('keeps Edit beside the greyed Duplicate on an integration-managed task', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // Managed, but not source-owned: still editable, only copying is refused. The
    // button has to land in the branch that keeps Edit rather than replace it.
    await panel.locator(`.detail-open[data-detail-id="${TASK.buddyMedicine}"]`).click();
    await expect(page).toHaveURL(new RegExp(`/home-keeper/tasks/${TASK.buddyMedicine}$`));

    await expect(panel.locator('.d-edit')).toBeVisible();
    await expect(panel.locator('.d-dup-blocked')).toBeVisible();
    await expect(panel.locator('.d-dup')).toHaveCount(0);

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
