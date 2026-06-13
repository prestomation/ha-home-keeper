import { test, expect } from '@playwright/test';
import { openPanel, openDashboard, trackPanelErrors } from './helpers';

test.describe('Home Keeper panel — smoke', () => {
  test('panel renders with seeded tasks and no panel errors', async ({ page }) => {
    const errors = trackPanelErrors(page);
    await openPanel(page);

    const panel = page.locator('home-keeper-panel').first();
    await expect(panel.locator('.hk-title').first()).toContainText('Home Keeper');
    // Seeded tasks appear in the list.
    await expect(panel.locator('.hk-name')).toContainText(['Replace fridge filter']);
    await expect(panel.locator('#add-btn')).toBeVisible();

    expect(errors, `panel errors:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('overdue task shows an overdue badge', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    // The seeded water filter is overdue.
    await expect(panel.locator('.badge.overdue').first()).toBeVisible();
  });

  test('clicking Add task opens the create form with recurrence fields', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await expect(panel.locator('#hk-form')).toBeVisible();
    await expect(panel.locator('#f-name')).toBeVisible();
    await expect(panel.locator('#f-type')).toBeVisible();
    await expect(panel.locator('#f-device')).toBeVisible();
  });

  test('switching to a fixed schedule reveals the frequency + anchor fields', async ({ page }) => {
    await openPanel(page);
    const panel = page.locator('home-keeper-panel').first();
    await panel.locator('#add-btn').click();
    await panel.locator('#f-type').selectOption('fixed');
    await expect(panel.locator('#freq-wrap')).toBeVisible();
    await expect(panel.locator('#anchor-wrap')).toBeVisible();
  });

  test('native to-do + calendar cards render on the dashboard', async ({ page }) => {
    await openDashboard(page);
    await expect(page.locator('hui-todo-list-card, todo-list-card').first()).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.locator('ha-calendar, hui-calendar-card').first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
