/**
 * Playwright global setup — bootstrap Home Assistant auth for the panel e2e tests.
 *
 * 1. Complete HA onboarding via the onboarding API (creates the `test` user) — or
 *    no-op if onboarding was already done.
 * 2. Wait for the seeded Home Keeper entities to appear.
 * 3. Drive a real browser login once and persist the storage state so every spec
 *    starts authenticated.
 * 4. Persist the raw access token beside it, so specs can seed and (crucially)
 *    **clean up** their own fixtures over REST — see `helpers.ts`. Without a
 *    teardown path every run left its tasks in the seeded store, and eight of
 *    those leaked records reached git.
 * 5. Mark every shipped preset as seen and hidden for the test user. The preset
 *    suggestion dialog opens by itself on the Tasks tab, and a modal that no spec
 *    expects would block the clicks of every spec after it. A spec or capture that
 *    shows the suggestions calls `suggestOnly` and `markAllPresetsSeen` after.
 * 6. Make a second user who is not an admin (`viewer`), and save its storage state
 *    and token beside the first. A capture that shows the view-only panel opens a
 *    browser context with that state (`VIEWER_STATE_PATH`).
 *
 * The API flow mirrors tests/integration/conftest.py.
 */
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'fs';
import { dirname, resolve } from 'path';
import { INTRO_KEY, markAllPresetsSeen, setUserData, wsCommand } from './user-data';

const HA_URL = process.env.HA_URL || 'http://localhost:8123';
const CLIENT_ID = `${HA_URL}/`;
const STATE_PATH = resolve(__dirname, '.auth/state.json');
const TOKEN_PATH = resolve(__dirname, '.auth/token.json');
const USERNAME = 'test';
const PASSWORD = 'testtest1';
export const VIEWER_STATE_PATH = resolve(__dirname, '.auth/viewer-state.json');
export const VIEWER_TOKEN_PATH = resolve(__dirname, '.auth/viewer-token.json');
const VIEWER_USERNAME = 'viewer';
const VIEWER_PASSWORD = 'viewerpass1';

async function waitForHA(timeoutMs = 120_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${HA_URL}/api/`);
      if (r.status === 200 || r.status === 401) return;
    } catch {
      /* not up yet */
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error(`Home Assistant did not respond within ${timeoutMs}ms at ${HA_URL}`);
}

interface Tokens {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
}

async function exchangeCode(code: string): Promise<Tokens> {
  const r = await fetch(`${HA_URL}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ grant_type: 'authorization_code', code, client_id: CLIENT_ID }),
  });
  if (!r.ok) throw new Error(`token exchange failed: ${r.status} ${await r.text()}`);
  return (await r.json()) as Tokens;
}

/** Log in over the auth API and return an access token. Throws on bad credentials. */
async function login(username: string, password: string): Promise<string> {
  let lf = await fetch(`${HA_URL}/auth/login_flow`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: CLIENT_ID,
      handler: ['homeassistant', null],
      redirect_uri: `${HA_URL}/?auth_callback=1`,
    }),
  });
  const flowId = (await lf.json()).flow_id;
  lf = await fetch(`${HA_URL}/auth/login_flow/${flowId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password, client_id: CLIENT_ID }),
  });
  const result = (await lf.json()).result;
  if (typeof result !== 'string') throw new Error(`login failed for ${username}`);
  return (await exchangeCode(result)).access_token;
}

/**
 * The token of the `viewer` user, who is not an admin. Log in first and make the user
 * only when that fails: Home Assistant keeps users across runs against the same
 * container, and to make the credentials twice is an error. The same flow as the
 * `non_admin_token` fixture in tests/integration/test_admin_gates.py.
 */
async function ensureViewer(ownerToken: string): Promise<string> {
  try {
    return await login(VIEWER_USERNAME, VIEWER_PASSWORD);
  } catch {
    /* not made yet */
  }
  const created = await wsCommand(ownerToken, {
    type: 'config/auth/create',
    name: 'Sam',
    group_ids: ['system-users'],
  });
  await wsCommand(ownerToken, {
    type: 'config/auth_provider/homeassistant/create',
    user_id: created.user.id,
    username: VIEWER_USERNAME,
    password: VIEWER_PASSWORD,
  });
  return login(VIEWER_USERNAME, VIEWER_PASSWORD);
}

async function ensureOnboarded(): Promise<string> {
  const r = await fetch(`${HA_URL}/api/onboarding/users`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      client_id: CLIENT_ID,
      name: 'Test',
      username: USERNAME,
      password: PASSWORD,
      language: 'en',
    }),
  });

  if (r.status === 403 || r.status === 404) {
    // Onboarding already completed (403), or the endpoint is gone post-onboarding
    // (404 on some HA versions / leftover local state) — just log in instead.
    return login(USERNAME, PASSWORD);
  }
  if (!r.ok) throw new Error(`onboarding users failed: ${r.status} ${await r.text()}`);

  const tokens = await exchangeCode((await r.json()).auth_code);
  const headers = { Authorization: `Bearer ${tokens.access_token}`, 'Content-Type': 'application/json' };
  for (const [endpoint, payload] of [
    ['core_config', {}],
    ['analytics', {}],
    ['integration', { client_id: CLIENT_ID, redirect_uri: `${HA_URL}/?auth_callback=1` }],
  ] as const) {
    try {
      await fetch(`${HA_URL}/api/onboarding/${endpoint}`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });
    } catch {
      /* ignore */
    }
  }
  return tokens.access_token;
}

async function waitForTasks(accessToken: string, timeoutMs = 90_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const r = await fetch(`${HA_URL}/api/states`, {
        headers: { Authorization: `Bearer ${accessToken}` },
      });
      if (r.ok) {
        const states: Array<{ entity_id: string }> = await r.json();
        if (states.some((s) => s.entity_id.startsWith('todo.home_keeper'))) return;
      }
    } catch {
      /* retry */
    }
    await new Promise((res) => setTimeout(res, 2000));
  }
  throw new Error('Home Keeper entities did not appear in time');
}

export default async function globalSetup(): Promise<void> {
  await waitForHA();
  const token = await ensureOnboarded();
  await waitForTasks(token);
  await markAllPresetsSeen(token);

  const viewerToken = await ensureViewer(token);
  await markAllPresetsSeen(viewerToken);
  await setUserData(viewerToken, INTRO_KEY, true);

  await browserLogin(USERNAME, PASSWORD, STATE_PATH);
  writeFileSync(TOKEN_PATH, JSON.stringify({ access_token: token }), 'utf8');
  await browserLogin(VIEWER_USERNAME, VIEWER_PASSWORD, VIEWER_STATE_PATH);
  writeFileSync(VIEWER_TOKEN_PATH, JSON.stringify({ access_token: viewerToken }), 'utf8');
}

/** Log in once in a real browser and save the storage state at *statePath*. */
async function browserLogin(username: string, password: string, statePath: string): Promise<void> {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_EXEC || undefined,
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.goto(`${HA_URL}/`, { waitUntil: 'domcontentloaded' });
    const field = page.locator('input[autocomplete="username"]');
    await field.waitFor({ state: 'visible', timeout: 30_000 });
    await field.fill(username);
    await page.locator('input[autocomplete="current-password"]').fill(password);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !!window.localStorage.getItem('hassTokens'), null, {
      timeout: 30_000,
    });
    await page.waitForLoadState('networkidle');

    mkdirSync(dirname(statePath), { recursive: true });
    await context.storageState({ path: statePath });
    // eslint-disable-next-line no-console
    console.log(`[global-setup] saved authenticated storage state to ${statePath}`);
  } finally {
    await browser.close();
  }
}
