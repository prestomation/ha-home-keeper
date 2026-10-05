/**
 * Read and write Home Assistant's per-user frontend data over the websocket.
 *
 * The panel keeps a few per-user answers there (the first-run intro, the preset
 * suggestions). A test sets them to put the panel in a known state. The token must
 * belong to the user the browser logs in as, because the data is per user.
 *
 * Uses the `ws` package, not the global `WebSocket`: CI runs Node 20, which has none.
 */
import WebSocket from 'ws';

/** The preset suggestions' key. */
export const PRESET_NUDGE_KEY = 'home_keeper_preset_nudge';
export const INTRO_KEY = 'home_keeper_intro_dismissed';
/** The one preset the e2e container matches: it has a single update entity. */
export const FIRMWARE_PRESET = 'firmware_update_available';

const HA_URL = process.env.HA_URL || 'http://localhost:8123';

/** Run one websocket command as *token* and return its result. */
export async function wsCommand(token: string, payload: Record<string, unknown>): Promise<any> {
  const ws = new WebSocket(`${HA_URL.replace(/^http/, 'ws')}/api/websocket`);
  try {
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`websocket timeout: ${payload.type}`)), 15_000);
      ws.on('error', (err) => reject(new Error(`websocket error: ${payload.type}: ${err}`)));
      ws.on('message', (data) => {
        const msg = JSON.parse(String(data));
        if (msg.type === 'auth_required') {
          ws.send(JSON.stringify({ type: 'auth', access_token: token }));
        } else if (msg.type === 'auth_ok') {
          ws.send(JSON.stringify({ id: 1, ...payload }));
        } else if (msg.type === 'auth_invalid') {
          clearTimeout(timer);
          reject(new Error('websocket auth failed'));
        } else if (msg.type === 'result' && msg.id === 1) {
          clearTimeout(timer);
          if (msg.success) resolve(msg.result);
          else reject(new Error(`${payload.type}: ${JSON.stringify(msg.error)}`));
        }
      });
    });
  } finally {
    ws.close();
  }
}

export async function getUserData(token: string, key: string): Promise<unknown> {
  const res = await wsCommand(token, { type: 'frontend/get_user_data', key });
  return res?.value ?? null;
}

export async function setUserData(token: string, key: string, value: unknown): Promise<void> {
  await wsCommand(token, { type: 'frontend/set_user_data', key, value });
}

/** Every shipped preset id, read from Home Assistant, so a new preset needs no edit here. */
export async function presetIds(token: string): Promise<string[]> {
  const res = await wsCommand(token, { type: 'home_keeper/list_declarative_presets' });
  return (res?.presets ?? []).map((p: { id: string }) => p.id);
}

/** Mark every preset seen and hidden, so no suggestion dialog or card appears. */
export async function markAllPresetsSeen(token: string): Promise<void> {
  const ids = await presetIds(token);
  await setUserData(token, PRESET_NUDGE_KEY, { shown: ids, dismissed: ids });
}

/**
 * Leave only *id* to suggest: every other preset is hidden. With *shown* false the
 * dialog offers it on the next load; with *shown* true only the card lists it. This
 * keeps a spec to the preset it is about, whatever else the container matches.
 */
export async function suggestOnly(token: string, id: string, shown = false): Promise<void> {
  const others = (await presetIds(token)).filter((x) => x !== id);
  await setUserData(token, PRESET_NUDGE_KEY, { shown: shown ? [id] : [], dismissed: others });
}
