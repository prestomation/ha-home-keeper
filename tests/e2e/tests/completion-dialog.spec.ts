import { test, expect } from '@playwright/test';
import { openPanel, trackPanelErrors } from './helpers';
import { TASK } from '../fixture-ids';

test.describe('Home Keeper panel — completion dialog', { tag: '@responsive' }, () => {
  test('the completion-details dialog renders its action buttons and can be submitted', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // "Replace fridge filter" is seeded with completion_detail: "optional", which
    // opens the completion-details dialog on Done instead of completing in one tap.
    await panel.locator(`.done-btn[data-id="${TASK.fridgeFilter}"]`).click();

    // ha-dialog portals its surface, so wait on an inner field rather than the host.
    const dialog = panel.locator('ha-dialog[open]');
    const noteField = dialog.locator('ha-selector-text textarea, ha-selector-text input').first();
    await noteField.waitFor({ state: 'visible', timeout: 15_000 });

    // Regression guard for #144: HA's ha-dialog only exposes a "footer" slot, so
    // the dialog's action buttons must be wrapped in <ha-dialog-footer slot="footer">
    // — buttons slotted straight onto <ha-dialog> silently don't render at all.
    // Assert the structure, not just visibility, so a future revert back to
    // slotting directly on <ha-dialog> fails here even before it's visibly broken.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="secondaryAction"]')).toHaveCount(2);

    await expect(dialog.getByRole('button', { name: 'Mark done' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Skip details' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();

    await noteField.fill('E2E completion dialog regression check');
    await dialog.getByRole('button', { name: 'Mark done' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('the move-date dialog renders its action buttons and can be cancelled', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    await panel.locator(`.detail-open[data-detail-id="${TASK.fridgeFilter}"]`).click();
    await expect(panel.locator('.hk-hist-list li').first()).toBeVisible();
    await panel.locator('.hk-hist-move').first().click();

    const dialog = panel.locator('ha-dialog[open]');
    const dateField = dialog.locator('ha-selector-datetime').first();
    await dateField.waitFor({ state: 'visible', timeout: 15_000 });

    // Same regression guard as the completion dialog (#144/#147): the move-date
    // dialog is built by hand alongside it and must wrap its buttons the same way.
    const footer = dialog.locator('ha-dialog-footer[slot="footer"]');
    await expect(footer).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="primaryAction"]')).toHaveCount(1);
    await expect(footer.locator('ha-button[slot="secondaryAction"]')).toHaveCount(1);

    await expect(dialog.getByRole('button', { name: 'Save' })).toBeVisible();
    await expect(dialog.getByRole('button', { name: 'Cancel' })).toBeVisible();

    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('editing a meter reading in history re-anchors the usage task (#235)', async ({
    page,
  }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();

    // The seeded nozzle task meters printer hours (a constant 780 h) against a 300 h
    // target, anchored at 660 — so its one completion reads "at 660 h" and the bar
    // shows 120 of 300 used. That equality is the whole invariant: a usage task's
    // baseline *is* the reading on its latest completion.
    const monitored = panel.locator('details.hk-group[data-group-key="status:monitored"]');
    if (!(await monitored.evaluate((el: HTMLDetailsElement) => el.open))) {
      await monitored.locator('summary').click();
    }
    await panel.locator(`.detail-open[data-detail-id="${TASK.nozzleUsage}"]`).click();
    const row = panel.locator('.hk-hist-list li').first();
    await expect(row.locator('.hk-hist-chips')).toContainText('at 660 h');
    await expect(panel.locator('.hk-meter-note').first()).toHaveText('180 h to go');

    await row.locator('.hk-hist-edit').click();
    const dialog = panel.locator('ha-dialog[open]');
    // Two number fields — cost, plus the meter reading this task gets for being bound
    // to a numeric sensor. The reading must arrive *seeded*: update_completion treats
    // an omitted key as "clear it", so a blank box here would mean editing a note
    // silently destroyed a value the user never typed and doesn't know is there.
    const numbers = dialog.locator('ha-selector-number input');
    await expect(numbers).toHaveCount(2);
    await expect(numbers.last()).toHaveValue('660');

    // Correct it downwards: the last service really happened 40 h earlier than logged.
    await numbers.last().fill('620');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });

    // The log now says 620 — and so does the meter, which is the point. Left alone,
    // the bar would still be counting from 660 and contradicting the history above it.
    await expect(row.locator('.hk-hist-chips')).toContainText('at 620 h', {
      timeout: 10_000,
    });
    await expect(panel.locator('.hk-meter-note').first()).toHaveText('140 h to go');

    // Put it back. The seeded store is bind-mounted, so a spec that edits it has to
    // undo itself or the next run starts from a state its own preconditions deny —
    // and the screenshot harness photographs this very row.
    await row.locator('.hk-hist-edit').click();
    await dialog.locator('ha-selector-number input').last().fill('660');
    await dialog.getByRole('button', { name: 'Save' }).click();
    await expect(panel.locator('ha-dialog[open]')).toHaveCount(0, { timeout: 10_000 });
    await expect(row.locator('.hk-hist-chips')).toContainText('at 660 h', {
      timeout: 10_000,
    });

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
