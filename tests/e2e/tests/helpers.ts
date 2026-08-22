import { Page, expect } from '@playwright/test';
import { readFileSync } from 'fs';
import { resolve } from 'path';

/** Route for the Home Keeper sidebar panel. */
export const PANEL_URL = '/home-keeper';
/** YAML e2e dashboard rendering the native to-do + calendar cards. */
export const DASHBOARD = '/home-keeper-e2e/card';
/** The single native to-do list entity backed by the task store. */
export const TODO_ENTITY = 'todo.home_keeper_tasks';

const HA_URL = process.env.HA_URL || 'http://localhost:8123';

let cachedToken: string | null = null;

/** The access token global-setup persisted, for REST seeding/teardown. */
function token(): string {
  if (cachedToken === null) {
    const path = resolve(__dirname, '..', '.auth', 'token.json');
    cachedToken = JSON.parse(readFileSync(path, 'utf8')).access_token as string;
  }
  return cachedToken;
}

async function api(path: string, init: RequestInit = {}): Promise<unknown> {
  const r = await fetch(`${HA_URL}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${token()}`,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!r.ok) throw new Error(`${init.method || 'GET'} ${path} -> ${r.status} ${await r.text()}`);
  return r.json();
}

/** Call a HA service. `returnResponse` opts into the ?return_response variant. */
export async function callService(
  domain: string,
  service: string,
  data: Record<string, unknown> = {},
  returnResponse = false,
): Promise<any> {
  const suffix = returnResponse ? '?return_response' : '';
  const body = await api(`/api/services/${domain}/${service}${suffix}`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
  // HA wraps a response-returning service's payload under "service_response".
  return (body as any)?.service_response ?? body;
}

/**
 * Create a task over the service API and return its id.
 *
 * Specs that call this MUST hand the id to `deleteTask` in an `afterEach` — the
 * e2e container's task store is the committed seed fixture, so anything left
 * behind is a permanent addition to it.
 */
export async function createTask(fields: Record<string, unknown>): Promise<string> {
  const resp = await callService('home_keeper', 'add_task', fields, true);
  return resp.task_id as string;
}

/** Delete a task by id. Safe to call for an id that's already gone. */
export async function deleteTask(taskId: string | undefined): Promise<void> {
  if (!taskId) return;
  try {
    await callService('home_keeper', 'delete_task', { task_id: taskId });
  } catch {
    /* already deleted, or the test that created it failed before it existed */
  }
}

/** Every task currently in the store. */
export async function listTasks(): Promise<Array<Record<string, any>>> {
  return (await callService('home_keeper', 'list_tasks', {}, true)).tasks;
}

/**
 * The summaries the to-do entity is currently offering (all needs_action).
 *
 * This — not the entity's *state* — is the authoritative, promptly-updated view
 * of the list. `todo_items` is computed on demand, so it reflects a completion
 * immediately; the state string (the needs_action count) is only rewritten when
 * the coordinator refreshes, which is a 5-minute interval plus debounced explicit
 * refreshes. Asserting on the count is therefore racy under load — it cost this
 * suite a CI-only failure. Count `todoSummaries().length` instead.
 */
export async function todoSummaries(): Promise<string[]> {
  const resp = await callService('todo', 'get_items', { entity_id: TODO_ENTITY }, true);
  return resp[TODO_ENTITY].items.map((i: { summary: string }) => i.summary);
}

/**
 * Navigate to the Home Keeper panel and wait for the custom element to upgrade.
 * The element renders into its shadow root, so we wait for it to be attached.
 */
export async function openPanel(page: Page): Promise<void> {
  await page.goto(PANEL_URL, { waitUntil: 'domcontentloaded' });
  await page.locator('home-keeper-panel').first().waitFor({ state: 'attached', timeout: 45_000 });
  // Wait for the panel to finish its first render (title appears in shadow DOM).
  await expect(page.locator('home-keeper-panel').first()).toBeVisible();
}

export async function openDashboard(page: Page): Promise<void> {
  await page.goto(DASHBOARD, { waitUntil: 'domcontentloaded' });
  await page.locator('hui-view, home-assistant').first().waitFor({ state: 'attached', timeout: 45_000 });
}

/**
 * Open the e2e dashboard and wait for the (first) custom Home Keeper card to
 * upgrade and render its first row. Returns the card locator. The card lives in
 * the dashboard's nested shadow DOM, which Playwright locators pierce.
 */
export async function openCardDashboard(page: Page) {
  // The card JS is an auto-registered extra module. card-index.ts fires
  // ll-custom-cards-update so the picker refreshes when the module loads late,
  // but on a cold frontend the element may not yet be upgraded when we first
  // arrive. Retry a couple of times so the first test isn't flaky.
  let lastErr: unknown;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (attempt === 0) await openDashboard(page);
    else await page.reload({ waitUntil: 'domcontentloaded' });
    const card = page.locator('home-keeper-card').first();
    try {
      await card.waitFor({ state: 'attached', timeout: 20_000 });
      await expect(card.locator('.hk-row, .hk-empty').first()).toBeVisible({ timeout: 20_000 });
      return card;
    } catch (err) {
      lastErr = err;
    }
  }
  throw lastErr;
}

/** The native to-do card. Assumes the dashboard is already open. */
export const todoCard = (page: Page) =>
  page.locator('hui-todo-list-card, todo-list-card').first();

/** The native calendar card. Assumes the dashboard is already open. */
export const calendarCard = (page: Page) => page.locator('ha-calendar, hui-calendar-card').first();

/** Open the dashboard and return the native to-do card, rendered. */
export async function openTodoCard(page: Page) {
  await openDashboard(page);
  const card = todoCard(page);
  await card.waitFor({ state: 'attached', timeout: 45_000 });
  await expect(card).toBeVisible({ timeout: 30_000 });
  return card;
}

/**
 * Assert a task has left **every** active surface: the native to-do list, the
 * calendar, and the panel's active list (it may still sit in the panel's
 * collapsed Completed/Monitored section, which is deliberately not "active").
 *
 * The suite had no vocabulary for absence before #221, which is how a task that
 * was "Completed" in the panel and still `needs_action` on the to-do entity
 * passed every test the project had. Presence is easy to assert by accident;
 * disappearance has to be asked for.
 */
export async function expectAbsentFromActiveSurfaces(page: Page, name: string): Promise<void> {
  // The entity itself: Home Keeper never emits a COMPLETED item, so absence from
  // the entity's item list *is* absence from needs_action.
  await expect
    .poll(async () => await todoSummaries(), { timeout: 20_000 })
    .not.toContain(name);

  // Both native cards live on the same dashboard, so one navigation covers them.
  const todo = await openTodoCard(page);
  await expect(todo).not.toContainText(name);

  const calendar = calendarCard(page);
  await expect(calendar).toBeVisible({ timeout: 30_000 });
  await expect(calendar).not.toContainText(name);

  await openPanel(page);
  const panel = page.locator('home-keeper-panel').first();
  // Cards inside a collapsed <details> are not visible, so scope to visible ones:
  // a completed one-off legitimately still exists in the Completed section.
  await expect(panel.locator('ha-card.hk-card:visible', { hasText: name })).toHaveCount(0);
}

/** Assert a task is present on the to-do list — the before half of a transition. */
export async function expectOnTodoList(page: Page, name: string): Promise<void> {
  await expect.poll(async () => await todoSummaries(), { timeout: 20_000 }).toContain(name);
  const todo = await openTodoCard(page);
  await expect(todo).toContainText(name);
}

/** Collect panel-relevant console/page errors. Attach BEFORE navigating. */
export function trackPanelErrors(page: Page): string[] {
  const errors: string[] = [];
  const isRelated = (s: string) => /home.?keeper/i.test(s);
  page.on('pageerror', (e) => {
    const text = `${e.message}\n${e.stack || ''}`;
    if (isRelated(text)) errors.push(`pageerror: ${text}`);
  });
  page.on('console', (msg) => {
    if (msg.type() === 'error' && isRelated(msg.text())) {
      errors.push(`console.error: ${msg.text()}`);
    }
  });
  return errors;
}
