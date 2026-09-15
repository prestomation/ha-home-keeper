import { expect, test } from '@playwright/test';
import { createTask, deleteTask, openCardDashboard } from './helpers';

/**
 * The dashboard card's note quick-view (#340): a task with a note gets a one-tap
 * chip that opens the full note as Markdown, without leaving the dashboard —
 * independent of whether the row already shows notes inline.
 */
test.describe('Home Keeper card — note quick-view', () => {
  // Tasks this spec creates, torn down after each test. The e2e container's task
  // store IS the committed seed fixture, so anything left behind is a permanent
  // addition to it.
  let created: string[] = [];

  test.afterEach(async () => {
    await Promise.all(created.map(deleteTask));
    created = [];
  });

  test('a task with a note shows a Note chip; one without does not @responsive', async ({
    page,
  }) => {
    const NAMED = 'E2E note quick-view probe';
    const BLANK = 'E2E no-note probe';
    // Two tasks created here rather than trusting a seeded fixture's notes field —
    // #340's own e2e run picked a seeded "no note" control that, it turned out,
    // carried one ("Replace water filter": "Under-sink RO filter"), which false-
    // failed the very assertion this test exists for.
    const [taskId, blankId] = await Promise.all([
      createTask({
        name: NAMED,
        recurrence_type: 'one-off',
        due: new Date(Date.now() + 86_400_000).toISOString(),
        notes: 'Use a **HEPA** filter, part #A1B2.',
      }),
      createTask({
        name: BLANK,
        recurrence_type: 'one-off',
        due: new Date(Date.now() + 86_400_000).toISOString(),
      }),
    ]);
    created.push(taskId, blankId);

    const card = await openCardDashboard(page);
    const row = card.locator('.hk-row', { hasText: NAMED });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(row.locator('.hk-note-chip')).toBeVisible();

    const noNote = card.locator('.hk-row', { hasText: BLANK });
    await expect(noNote).toHaveCount(1);
    await expect(noNote.locator('.hk-note-chip')).toHaveCount(0);
  });

  test('tapping the chip opens the full note as Markdown, read-only @responsive', async ({
    page,
  }) => {
    const NAME = 'E2E note dialog probe';
    const taskId = await createTask({
      name: NAME,
      recurrence_type: 'one-off',
      due: new Date(Date.now() + 86_400_000).toISOString(),
      notes: 'Use a **HEPA** filter, part #A1B2.',
    });
    created.push(taskId);

    const card = await openCardDashboard(page);
    const row = card.locator('.hk-row', { hasText: NAME });
    await row.locator('.hk-note-chip').click();

    // Assert on what's inside the dialog, not on `ha-dialog` itself — the host
    // element has no box of its own (see card-defer.spec.ts).
    const dialog = page.locator('ha-dialog[open]').first();
    await expect(dialog).toHaveAttribute('heading', new RegExp(NAME));
    // Rendered as Markdown, not escaped text: the emphasis becomes a real <strong>.
    await expect(dialog.locator('strong', { hasText: 'HEPA' })).toBeVisible();
    // Read-only: no form to edit the note from here — editing stays panel-only.
    await expect(dialog.locator('ha-form')).toHaveCount(0);

    await dialog.locator('ha-button', { hasText: 'Close' }).click();
    await expect(page.locator('ha-dialog[open]')).toHaveCount(0);
  });

  test('the note chip leaves Done and the row untouched @responsive', async ({ page }) => {
    const NAME = 'E2E note isolation probe';
    const taskId = await createTask({
      name: NAME,
      recurrence_type: 'one-off',
      due: new Date(Date.now() + 86_400_000).toISOString(),
      notes: 'Careful: shuts off at the street valve.',
    });
    created.push(taskId);

    const card = await openCardDashboard(page);
    const row = card.locator('.hk-row', { hasText: NAME });
    await row.locator('.hk-note-chip').click();
    // Assert on content inside the dialog, not on `ha-dialog` itself — the host
    // element has no box of its own (see card-defer.spec.ts).
    const dialog = page.locator('ha-dialog[open]').first();
    await expect(dialog.locator('.hk-note-body')).toContainText('street valve');

    // The row's Done button is still there and untouched by the tap.
    await expect(row.locator('.hk-done')).toBeVisible();
    expect(page.url()).not.toContain('/home-keeper/tasks/');
  });
});
