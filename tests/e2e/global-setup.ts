/**
 * Playwright global setup — bootstrap Home Assistant auth for the panel e2e tests.
 *
 * 1. Complete HA onboarding via the onboarding API (creates the `test` user) — or
 *    no-op if onboarding was already done.
 * 2. Wait for the seeded Home Keeper entities to appear.
 * 3. Drive a real browser login once and persist the storage state so every spec
 *    starts authenticated.
 *
 * The API flow mirrors tests/integration/conftest.py.
 */
import { chromium } from '@playwright/test';
import { mkdirSync } from 'fs';
import { dirname, resolve } from 'path';

const HA_URL = process.env.HA_URL || 'http://localhost:8123';
const CLIENT_ID = `${HA_URL}/`;
const STATE_PATH = resolve(__dirname, '.auth/state.json');
const USERNAME = 'test';
const PASSWORD = 'testtest1';

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
      body: JSON.stringify({ username: USERNAME, password: PASSWORD, client_id: CLIENT_ID }),
    });
    return (await exchangeCode((await lf.json()).result)).access_token;
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

  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_EXEC || undefined,
  });
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.goto(`${HA_URL}/`, { waitUntil: 'domcontentloaded' });
    const username = page.locator('input[autocomplete="username"]');
    await username.waitFor({ state: 'visible', timeout: 30_000 });
    await username.fill(USERNAME);
    await page.locator('input[autocomplete="current-password"]').fill(PASSWORD);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !!window.localStorage.getItem('hassTokens'), null, {
      timeout: 30_000,
    });
    await page.waitForLoadState('networkidle');

    mkdirSync(dirname(STATE_PATH), { recursive: true });
    await context.storageState({ path: STATE_PATH });
    // eslint-disable-next-line no-console
    console.log(`[global-setup] saved authenticated storage state to ${STATE_PATH}`);
  } finally {
    await browser.close();
  }
}
