#!/usr/bin/env node
// EXPLORATION TOOL (not product code). Backend measurements for a home with many tasks.
//
// Needs a running Home Assistant (see README.md) and tests/e2e/.auth/token.json,
// which the Playwright global setup writes. Prints one JSON object with the numbers.
//
//   node tools/explore-many-tasks/measure_backend.mjs [--complete 30] [--container NAME]
//
// It measures: websocket list calls (time and size), the entity set (counts per domain
// and the largest state attributes), the to-do and calendar reads, one task completion,
// a burst of completions (event rate and time per call), add_task, and the container
// memory before and after.
import { readFileSync } from 'node:fs';
import { execSync } from 'node:child_process';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const HA = process.env.HA_URL || 'http://localhost:8123';
const args = process.argv.slice(2);
const opt = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const BURST = Number(opt('--complete', 30));
const CONTAINER = opt('--container', '');

const tok = JSON.parse(
  readFileSync(resolve(HERE, '../../tests/e2e/.auth/token.json'), 'utf8'),
).access_token;

const out = {};
const now = () => performance.now();

// ---- websocket ---------------------------------------------------------------
const ws = new WebSocket(HA.replace('http', 'ws') + '/api/websocket');
let nextId = 1;
const pending = new Map();
const events = [];
await new Promise((res, rej) => {
  ws.onmessage = (m) => {
    const d = JSON.parse(m.data);
    if (d.type === 'auth_required') ws.send(JSON.stringify({ type: 'auth', access_token: tok }));
    else if (d.type === 'auth_ok') res();
    else if (d.type === 'auth_invalid') rej(new Error('auth invalid'));
  };
  ws.onerror = rej;
});
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.type === 'event') {
    events.push({ t: now(), type: d.event.event_type, id: d.id });
    return;
  }
  const p = pending.get(d.id);
  if (p) {
    pending.delete(d.id);
    p.res({ msg: d, bytes: m.data.length, ms: now() - p.t0 });
  }
};
function call(msg) {
  const id = nextId++;
  return new Promise((res) => {
    pending.set(id, { res, t0: now() });
    ws.send(JSON.stringify({ id, ...msg }));
  });
}

// A long-lived token, so a long run does not meet an expired access token.
const ll = await call({ type: 'auth/long_lived_access_token', client_name: 'explore', lifespan: 1 });
const LL = ll.msg.result;

async function rest(path, init = {}) {
  const t0 = now();
  const r = await fetch(HA + path, {
    ...init,
    headers: { Authorization: `Bearer ${LL}`, 'Content-Type': 'application/json' },
  });
  const text = await r.text();
  return { status: r.status, ms: now() - t0, bytes: text.length, body: text };
}
const svc = async (name, data, response = false) => {
  const r = await rest(`/api/services/home_keeper/${name}${response ? '?return_response' : ''}`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
  return { ...r, json: r.body && r.status === 200 ? JSON.parse(r.body) : null };
};
const dockerOk = () => {
  try {
    execSync('docker info', { stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
};
const mem = () => {
  if (!CONTAINER || !dockerOk()) return null;
  try {
    return execSync(
      `docker stats --no-stream --format '{{.MemUsage}} {{.CPUPerc}}' ${CONTAINER}`,
    ).toString().trim();
  } catch {
    return null;
  }
};

out.memory_before = mem();

// ---- list calls --------------------------------------------------------------
const lists = {};
for (const type of [
  'home_keeper/get_tasks',
  'home_keeper/get_assets',
  'home_keeper/get_options',
  'home_keeper/get_profiles',
  'home_keeper/get_spend',
  'home_keeper/get_companions',
]) {
  const runs = [];
  for (let i = 0; i < 3; i++) {
    const r = await call({ type });
    runs.push({ ms: Math.round(r.ms), bytes: r.bytes, ok: r.msg.success });
  }
  lists[type] = runs;
}
out.ws_lists = lists;
const ls = await svc('list_tasks', {}, true);
out.service_list_tasks = { ms: Math.round(ls.ms), bytes: ls.bytes };
const tasks = (await call({ type: 'home_keeper/get_tasks' })).msg.result.tasks;
out.task_count = tasks.length;

// ---- entities ----------------------------------------------------------------
const st = await rest('/api/states');
const states = JSON.parse(st.body);
out.states_call = { ms: Math.round(st.ms), bytes: st.bytes, total: states.length };
const hk = states.filter((s) => /home_keeper/.test(s.entity_id) || /home_keeper/.test(JSON.stringify(s.attributes).slice(0, 4000) ));
const byDomain = {};
for (const s of hk) byDomain[s.entity_id.split('.')[0]] = (byDomain[s.entity_id.split('.')[0]] || 0) + 1;
out.hk_entities_by_domain = byDomain;
const sized = hk
  .map((s) => ({ id: s.entity_id, state_len: s.state.length, attr_bytes: JSON.stringify(s.attributes).length }))
  .sort((a, b) => b.attr_bytes - a.attr_bytes);
out.largest_attributes = sized.slice(0, 5);
out.attribute_limit_16384_exceeded = sized.filter((s) => s.attr_bytes > 16384).map((s) => s.id);

// ---- to-do and calendar ------------------------------------------------------
const todoId = states.find((s) => s.entity_id.startsWith('todo.home_keeper'))?.entity_id;
if (todoId) {
  const t0 = now();
  const r = await rest('/api/services/todo/get_items?return_response', {
    method: 'POST',
    body: JSON.stringify({ entity_id: todoId }),
  });
  out.todo_get_items = { entity: todoId, ms: Math.round(now() - t0), bytes: r.bytes, items: JSON.parse(r.body).service_response?.[todoId]?.items?.length };
  const sub = await call({ type: 'todo/item/list', entity_id: todoId });
  out.todo_item_list = { ms: Math.round(sub.ms), bytes: sub.bytes };
}
const cal = states.find((s) => s.entity_id.startsWith('calendar.home_keeper'))?.entity_id;
if (cal) {
  out.calendar = {};
  for (const [label, days] of [['1_month', 31], ['1_year', 366], ['5_years', 1830]]) {
    const start = new Date('2026-10-01T00:00:00Z');
    const end = new Date(start.getTime() + days * 86400000);
    const r = await rest(`/api/calendars/${cal}?start=${start.toISOString()}&end=${end.toISOString()}`);
    out.calendar[label] = { ms: Math.round(r.ms), bytes: r.bytes, events: r.status === 200 ? JSON.parse(r.body).length : r.status };
  }
}

// ---- one add, one completion ------------------------------------------------
const add = await svc('add_task', { name: 'explore single add', recurrence_type: 'floating', interval: 1, unit: 'months' }, true);
out.add_task_ms = Math.round(add.ms);
const addedId = add.json?.service_response?.task_id ?? add.json?.task_id;
const one = await svc('complete_task', { task_id: addedId });
out.complete_task_ms = Math.round(one.ms);

// ---- burst ------------------------------------------------------------------
await call({ type: 'subscribe_events' });
const target = tasks.filter((t) => t.enabled !== false && t.recurrence_type === 'floating').slice(0, BURST);
const times = [];
const e0 = events.length;
const b0 = now();
for (const t of target) {
  const r = await svc('complete_task', { task_id: t.id });
  times.push(r.ms);
}
const bms = now() - b0;
await new Promise((r) => setTimeout(r, 3000));
const burstEvents = events.slice(e0);
const perType = {};
for (const e of burstEvents) perType[e.type] = (perType[e.type] || 0) + 1;
out.burst = {
  completions: target.length,
  total_ms: Math.round(bms),
  per_call_ms_avg: Math.round(times.reduce((a, b) => a + b, 0) / (times.length || 1)),
  per_call_ms_max: Math.round(Math.max(...times, 0)),
  events_total: burstEvents.length,
  events_per_second: Number((burstEvents.length / ((now() - b0) / 1000)).toFixed(1)),
  events_by_type: Object.fromEntries(Object.entries(perType).sort((a, b) => b[1] - a[1]).slice(0, 8)),
};

await svc('delete_task', { task_id: addedId });
out.memory_after = mem();
console.log(JSON.stringify(out, null, 2));
ws.close();
process.exit(0);
