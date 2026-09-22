import { test, expect, Locator, Page } from '@playwright/test';
import { openCardDashboard } from './tests/helpers';
import { TASK } from './fixture-ids';
import { PHONE } from './viewports';

/**
 * One-off capture of the Home Keeper dashboard card for the README / PR. Run via:
 *   SHOT_DIR=../../docs/images npx playwright test \
 *     screenshots-card.capture.ts --config=screenshots-card.config.ts
 * Kept out of the *.spec.ts suite so it doesn't run as a normal test.
 */
const OUT = process.env.SHOT_DIR || '/tmp/home-keeper-shots';

async function fillText(scope: Locator, nth: number, value: string): Promise<void> {
  await scope.locator('ha-selector-text').nth(nth).locator('input, textarea').fill(value);
}

/**
 * Clip a tight screenshot of a card's inner `ha-card`. We clip by bounding box at
 * scroll-0 (rather than element.screenshot, which auto-scrolls and lets HA's
 * sticky view header overlay the card's own header) with a tall viewport so the
 * whole card fits above the fold.
 */
async function shotCard(page: Page, card: Locator, path: string): Promise<void> {
  const box = await card.locator('ha-card').first().boundingBox();
  if (!box) throw new Error(`no bounding box for ${path}`);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path, clip: box });
}

/**
 * Photograph a dialog, clipped to the dialog rather than the page. A full-page shot
 * leaves a ~400px dialog adrift in a 1280x3400 image, which documents nothing.
 *
 * `ha-dialog` has no box of its own and its surface lives in its shadow root, so
 * `closest()` from the slotted body cannot reach it. Measure what we do own instead:
 * the union of the dialog's own slotted children — the heading, the body and the
 * footer — which is the surface, less its padding. `PAD` puts that padding and a
 * little of the scrim back.
 */
async function shotDialog(page: Page, dialog: Locator, path: string): Promise<void> {
  const PAD = 22;
  const box = await dialog.evaluate((el) => {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const child of Array.from(el.children)) {
      const r = child.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      x0 = Math.min(x0, r.x);
      y0 = Math.min(y0, r.y);
      x1 = Math.max(x1, r.x + r.width);
      y1 = Math.max(y1, r.y + r.height);
    }
    return { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
  });
  if (!Number.isFinite(box.width) || !Number.isFinite(box.height)) {
    throw new Error(`no measurable dialog content for ${path}`);
  }
  const view = page.viewportSize() ?? { width: box.width, height: box.height };
  const x = Math.max(0, box.x - PAD);
  const y = Math.max(0, box.y - PAD);
  await page.screenshot({
    path,
    clip: {
      x,
      y,
      width: Math.min(view.width - x, box.width + PAD * 2),
      height: Math.min(view.height - y, box.height + PAD * 2),
    },
  });
}

test('capture Home Keeper card screenshots', async ({ page }) => {
  // Tall viewport so even the second (grouped) card sits above the fold and its
  // clip stays inside the rendered image. The default card carries the water-filter
  // task whose appliance link-chips wrap over several rows, so give it ample room.
  // Due today added a fourth per-row action. At this dashboard's column width the
  // row wraps its actions onto their own line rather than squeezing the name (see
  // the container query in card.ts), which costs a line per row where the verb is
  // offered — so keep the headroom rather than trimming back to the old 2600.
  await page.setViewportSize({ width: 1280, height: 3400 });
  const card = await openCardDashboard(page);
  await expect(card.locator('.hk-name').first()).toBeVisible();

  // The seeded water-filter task points at a placeholder device_id; re-attach it to
  // its real (runtime-provisioned) appliance device so the row's device chip resolves
  // to "Garage water heater" rather than a raw id — and its pinned links still resolve
  // (they reference the appliance by id, independent of the device).
  await page.evaluate(async (IDS) => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const hass = (document.querySelector('home-assistant') as any)?.hass;
    if (!hass) return;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const { assets } = await hass.callWS({ type: 'home_keeper/get_assets' });
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const wh = assets.find((a: any) => a.name === 'Garage water heater');
    if (wh?.device_id) {
      await hass.callService('home_keeper', 'update_task', {
        task_id: IDS.TASK.waterFilter,
        device_id: wh.device_id,
      });
    }
  }, { TASK });
  await page.waitForTimeout(1500); // attaching a device reloads the entry; let it settle
  await expect(card.locator('a.hk-link-chip').first()).toBeVisible();
  await page.waitForTimeout(500); // let layout / chips settle

  // 1. The whole dashboard view (default card + grouped card + native cards).
  await page.screenshot({ path: `${OUT}/card-dashboard.png`, fullPage: true });

  // 2. The default card on its own. The seeded water-filter task pins some of its
  // appliance's documents, so this clip also shows the per-task document chips.
  await shotCard(page, card, `${OUT}/card-default.png`);

  // 2b. Same card, named for the per-task "documents to show on card" feature — the
  // water-filter row carries "Owner's manual", "Reorder filter" and a file chip.
  await expect(card.locator('a.hk-link-chip').first()).toBeVisible();
  await shotCard(page, card, `${OUT}/card-task-links.png`);

  // 2c. Snooze, skip and pull forward, on the row (#268, then pull forward
  // alongside them). All 3 sit ahead of Done as their own buttons, so the default
  // card clip already shows them — this shot names the feature, and the dialogs
  // snooze/skip open get their own below (pull forward acts immediately, no dialog).
  await expect(card.locator('.hk-defer-snooze').first()).toBeVisible();
  await expect(card.locator('.hk-defer-due-today').first()).toBeVisible();
  await shotCard(page, card, `${OUT}/card-skip-snooze-row.png`);

  // 3. The grouped-by-status card.
  const grouped = page.locator('home-keeper-card').nth(1);
  await expect(grouped.locator('details.hk-group').first()).toBeVisible();
  await shotCard(page, grouped, `${OUT}/card-grouped.png`);

  // 3b. The label-filtered "Dog" card — only tasks carrying the `dog` label, with
  // each row's label chips shown (exercises labels filter + show_labels).
  const labelCard = page.locator('home-keeper-card').nth(2);
  await expect(labelCard.locator('.hk-name').first()).toBeVisible();
  await expect(labelCard.locator('ha-assist-chip.hk-label').first()).toBeVisible();
  await shotCard(page, labelCard, `${OUT}/card-label-filter.png`);

  // 4. The inline add/edit form opened from the card header.
  await card.locator('#hk-add').click();
  const form = card.locator('.hk-form');
  await expect(form.locator('ha-form').first()).toBeVisible();
  await fillText(form, 0, 'Replace dishwasher filter');
  await page.waitForTimeout(400);
  await shotCard(page, card, `${OUT}/card-add-form.png`);

  // 5. The card's default title fallback (#150 follow-up: was hardcoded English,
  // S.defaultTitle, now t('tab.tasks')) plus the no-tasks-match-filter message.
  // Reconfigure the label-filtered card in place (setConfig, no dashboard YAML
  // change) to a label no seeded task carries, and clear its title. (The *other*
  // empty-state string this PR fixed, t('card.empty') for zero tasks total rather
  // than zero filter matches, needs every seeded task gone — not reachable here
  // without destructively wiping the shared e2e fixture data.)
  type ConfigurableCard = { setConfig: (c: Record<string, unknown>) => void };
  await labelCard.evaluate((el: ConfigurableCard) =>
    el.setConfig({ type: 'custom:home-keeper-card', labels: ['no-such-label-xyz'] }),
  );
  await expect(labelCard.locator('.hk-empty')).toBeVisible();
  await shotCard(page, labelCard, `${OUT}/card-title-fallback.png`);

  // 5b. Same non-matching filter, but with hide_when_empty: true — the card
  // collapses out of the dashboard layout entirely instead of showing the "No
  // tasks match" alert. Capture the whole view to show it's gone (compare against
  // card-dashboard.png, which shows all three cards present).
  await labelCard.evaluate((el: ConfigurableCard) =>
    el.setConfig({
      type: 'custom:home-keeper-card',
      labels: ['no-such-label-xyz'],
      hide_when_empty: true,
    }),
  );
  await expect(labelCard).toBeHidden();
  await page.screenshot({ path: `${OUT}/card-hide-empty.png`, fullPage: true });

  // 6. Truncated list ("+N more" — previously an untranslated template literal).
  // Close the add form from step 4, then reconfigure the default card to a small
  // max_items so the seeded task set (well over a dozen) overflows.
  await card.locator('.hk-form ha-button', { hasText: 'Cancel' }).click();
  await expect(card.locator('.hk-form')).toBeHidden();
  await card.evaluate((el: ConfigurableCard) =>
    el.setConfig({ type: 'custom:home-keeper-card', title: 'Home maintenance', max_items: 3 }),
  );
  await expect(card.locator('.hk-more')).toBeVisible();
  await shotCard(page, card, `${OUT}/card-more-hidden.png`);

  // 7. Note quick-view (#340): a task with a note shows a Note chip on its row, and
  // the chip opens the full note in a read-only dialog, rendered as Markdown.
  // Reset the card back to its plain default first (the step above left it capped
  // at max_items: 3, which would crop most rows out of the list).
  //
  // The fridge-filter task, by id and not `.first()`: its note is the long Markdown
  // one — a lead line, a numbered procedure and a block quote — which is the note
  // this feature exists for. The water-filter row sorts first and carries a 1-line
  // note ("Under-sink RO filter") that documents nothing about Markdown.
  await card.evaluate((el: ConfigurableCard) =>
    el.setConfig({ type: 'custom:home-keeper-card', title: 'Home maintenance' }),
  );
  const noteChip = card.locator(`.hk-note-chip[data-id="${TASK.fridgeFilter}"]`);
  await expect(noteChip).toBeVisible();
  await shotCard(page, card, `${OUT}/card-note-chip.png`);
  await noteChip.click();
  // Assert on content inside the dialog, not on `ha-dialog` itself — the host
  // element has no box of its own (see card-defer.spec.ts / card-note.spec.ts).
  const noteDialog = page.locator('ha-dialog[open]').first();
  await expect(noteDialog.locator('.hk-note-body')).toBeVisible();
  await page.waitForTimeout(300);
  // Clip to the dialog's own surface. A full-page shot puts a ~400px dialog in the
  // middle of a 1280x3400 page, where it documents nothing.
  await shotDialog(page, noteDialog, `${OUT}/card-note-dialog.png`);
  // `ha-button`, not getByRole: `ha-dialog`'s own header close icon also has an
  // accessible name of "Close" and would otherwise match too (see card-note.spec.ts).
  await noteDialog.locator('ha-button', { hasText: 'Close' }).click();
  await expect(page.locator('ha-dialog[open]')).toHaveCount(0);

  // 7b. The phone layout is a different arrangement, not a narrower one — the row
  // wraps its chips and actions — so the note chip and its dialog get their own
  // shot at phone width too. Last in the file, since it changes the viewport.
  await page.setViewportSize(PHONE);
  const mobileCard = await openCardDashboard(page);
  const mobileNoteChip = mobileCard.locator(`.hk-note-chip[data-id="${TASK.fridgeFilter}"]`);
  await expect(mobileNoteChip).toBeVisible();
  await mobileNoteChip.scrollIntoViewIfNeeded();
  await shotCard(page, mobileCard, `${OUT}/card-note-chip-mobile.png`);
  await mobileNoteChip.click();
  const mobileNoteDialog = page.locator('ha-dialog[open]').first();
  await expect(mobileNoteDialog.locator('.hk-note-body')).toBeVisible();
  await page.waitForTimeout(300);
  await shotDialog(page, mobileNoteDialog, `${OUT}/card-note-dialog-mobile.png`);
});
