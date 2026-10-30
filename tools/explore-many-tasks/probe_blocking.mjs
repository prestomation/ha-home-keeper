#!/usr/bin/env node
// EXPLORATION TOOL (not product code). Does an operation block the HA event loop?
// A 2nd websocket sends `ping` every 25 ms. The max round trip while an operation runs
// is the stall. Also repeats add_task and update_task to see the cost of one store save.
//   node tools/explore-many-tasks/probe_blocking.mjs
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
const HERE = dirname(fileURLToPath(import.meta.url));
const HA = process.env.HA_URL || 'http://localhost:8123';
const tok = JSON.parse(readFileSync(resolve(HERE, '../../tests/e2e/.auth/token.json'), 'utf8')).access_token;
const now = () => performance.now();

function open() {
  return new Promise((res, rej) => {
    const ws = new WebSocket(HA.replace('http', 'ws') + '/api/websocket');
    let id = 1; const pend = new Map();
    ws.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.type === 'auth_required') ws.send(JSON.stringify({ type: 'auth', access_token: tok }));
      else if (d.type === 'auth_ok') res({ ws, call: (msg) => new Promise((r) => { const i = id++; pend.set(i, { r, t0: now() }); ws.send(JSON.stringify({ id: i, ...msg })); }) });
      else if (pend.has(d.id)) { const p = pend.get(d.id); pend.delete(d.id); p.r({ d, ms: now() - p.t0, bytes: m.data.length }); }
    };
    ws.onerror = rej;
  });
}
const a = await open(); const b = await open();
const LL = (await a.call({ type: 'auth/long_lived_access_token', client_name: 'probe', lifespan: 1 })).d.result;
const rest = async (path, init = {}) => { const t0 = now(); const r = await fetch(HA + path, { ...init, headers: { Authorization: `Bearer ${LL}`, 'Content-Type': 'application/json' } }); const t = await r.text(); return { ms: now() - t0, bytes: t.length, status: r.status, body: t }; };
const svc = (n, data, resp) => rest(`/api/services/home_keeper/${n}${resp ? '?return_response' : ''}`, { method: 'POST', body: JSON.stringify(data) });

async function withPing(label, fn) {
  const lat = []; let run = true;
  const loop = (async () => { while (run) { const r = await b.call({ type: 'ping' }); lat.push(r.ms); await new Promise((x) => setTimeout(x, 25)); } })();
  await new Promise((x) => setTimeout(x, 200));
  const t0 = now(); const res = await fn(); const ms = now() - t0;
  run = false; await loop;
  const during = lat.slice(0);
  console.log(JSON.stringify({ op: label, ms: Math.round(ms), ping_max_ms: Math.round(Math.max(...during)), ping_count: during.length, ...res }));
}
const cal = (await (await fetch(HA + '/api/states', { headers: { Authorization: `Bearer ${LL}` } })).json()).find((s) => s.entity_id.startsWith('calendar.home_keeper')).entity_id;
await withPing('idle', async () => { await new Promise((x) => setTimeout(x, 1000)); return {}; });
await withPing('get_tasks', async () => { const r = await a.call({ type: 'home_keeper/get_tasks' }); return { bytes: r.bytes }; });
await withPing('calendar_1_month', async () => { const r = await rest(`/api/calendars/${cal}?start=2026-10-01T00:00:00Z&end=2026-11-01T00:00:00Z`); return { bytes: r.bytes }; });
await withPing('calendar_1_week', async () => { const r = await rest(`/api/calendars/${cal}?start=2026-10-26T00:00:00Z&end=2026-11-02T00:00:00Z`); return { bytes: r.bytes }; });
const ids = [];
for (let i = 0; i < 5; i++) {
  await withPing(`add_task_${i}`, async () => { const r = await svc('add_task', { name: `probe ${i}`, recurrence_type: 'floating', interval: 1, unit: 'months' }, true); const j = JSON.parse(r.body); ids.push((j.service_response ?? j).task_id); return {}; });
}
for (const id of ids.slice(0, 2)) await withPing('update_task', async () => { await svc('update_task', { task_id: id, notes: 'x' }); return {}; });
for (const id of ids) await svc('delete_task', { task_id: id });
process.exit(0);
