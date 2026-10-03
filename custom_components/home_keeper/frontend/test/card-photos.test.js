// Task photos on the dashboard card (#399): the cover on a row, and photos in the
// New task form, which upload after Create. Any user can do this, so the card shows
// the controls with no admin check.
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { HomeKeeperCard } from '../src/card.ts';
import { t } from '../src/i18n.ts';

beforeAll(() => {
  for (const tag of [
    'ha-card',
    'ha-form',
    'ha-button',
    'ha-icon-button',
    'ha-assist-chip',
    'ha-alert',
    'ha-spinner',
    'ha-icon',
  ]) {
    if (!customElements.get(tag)) customElements.define(tag, class extends HTMLElement {});
  }
  if (!customElements.get('home-keeper-card')) {
    customElements.define('home-keeper-card', HomeKeeperCard);
  }
});

// An XMLHttpRequest that answers each upload by itself: a URL in `failUrls` gets a
// 500, every other URL gets the task back.
class AutoXHR {
  static sent = [];
  static failUrls = new Set();
  constructor() {
    this.upload = new EventTarget();
    this._listeners = new EventTarget();
  }
  open(method, url) {
    this.url = url;
  }
  setRequestHeader() {}
  addEventListener(type, fn) {
    this._listeners.addEventListener(type, fn);
  }
  send(body) {
    AutoXHR.sent.push({ url: this.url, file: body.get('file') });
    const fail = [...AutoXHR.failUrls].some((u) => this.url.includes(u));
    setTimeout(() => {
      this.status = fail ? 500 : 200;
      this.responseText = fail ? '{"message":"boom"}' : '{"task":{"id":"new1"}}';
      this._listeners.dispatchEvent(new Event('load'));
    }, 0);
  }
  abort() {}
}

let realXHR;
let realCreate;
let realRevoke;
const revoked = [];
beforeEach(() => {
  AutoXHR.sent = [];
  AutoXHR.failUrls = new Set();
  revoked.length = 0;
  realXHR = globalThis.XMLHttpRequest;
  globalThis.XMLHttpRequest = AutoXHR;
  realCreate = URL.createObjectURL;
  realRevoke = URL.revokeObjectURL;
  URL.createObjectURL = (f) => `blob:${f.name}`;
  URL.revokeObjectURL = (u) => revoked.push(u);
});
afterEach(() => {
  globalThis.XMLHttpRequest = realXHR;
  URL.createObjectURL = realCreate;
  URL.revokeObjectURL = realRevoke;
  document.body.innerHTML = '';
});

async function waitFor(fn, timeout = 2000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => setTimeout(r, 20));
  }
  return false;
}

const photo = (id) => ({ id, name: `${id}.jpg`, filename: `${id}.jpg`, content_type: 'image/jpeg', size: 1 });
const task = (over = {}) => ({
  id: 't1',
  name: 'Repair insulation',
  recurrence_type: 'floating',
  interval: 1,
  unit: 'months',
  next_due: new Date(Date.now() + 86_400_000).toISOString(),
  completions: [],
  ...over,
});

/** A card whose hass is a user who is not an admin, and records the websocket calls. */
function makeCard(tasks, { signFails = false } = {}) {
  const card = document.createElement('home-keeper-card');
  card.setConfig({ type: 'custom:home-keeper-card' });
  document.body.appendChild(card);
  const calls = [];
  card.hass = {
    language: 'en',
    user: { is_admin: false },
    auth: { data: { access_token: 'tok' } },
    callWS: async (msg) => {
      calls.push(msg);
      if (msg.type === 'home_keeper/get_tasks') return { tasks };
      if (msg.type === 'home_keeper/add_task') return { task: { id: 'new1', name: msg.task?.name } };
      if (msg.type === 'home_keeper/sign_task_photo_urls') {
        if (signFails) throw new Error('nope');
        return {
          urls: msg.photos.map((p) => ({ ...p, url: `/signed/${p.task_id}/${p.photo_id}/${p.thumb ? 'thumb' : 'full'}` })),
        };
      }
      return {};
    },
  };
  return { card, calls };
}

const sr = (card) => card.shadowRoot;

describe('the cover on a card row', () => {
  it('shows the signed thumbnail, linked to the original', async () => {
    const { card, calls } = makeCard([task({ photos: [photo('p1'), photo('p2')] }), task({ id: 't2' })]);
    await waitFor(() => sr(card)?.querySelector('.hk-cover'));
    const links = sr(card).querySelectorAll('.hk-cover');
    expect(links).toHaveLength(1);
    const link = links[0];
    expect(link.getAttribute('href')).toBe('/signed/t1/p1/full');
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('aria-label')).toBe(t('photos.open', { name: 'p1.jpg' }));
    const img = link.querySelector('img');
    expect(img.getAttribute('src')).toBe('/signed/t1/p1/thumb');
    expect(img.getAttribute('alt')).toBe(t('photos.coverAlt', { task: 'Repair insulation' }));
    expect(link.closest('.grow')).toBeTruthy();
    const signs = calls.filter((m) => m.type === 'home_keeper/sign_task_photo_urls');
    expect(signs).toHaveLength(1);
    expect(signs[0].photos).toEqual([
      { task_id: 't1', photo_id: 'p1', thumb: true },
      { task_id: 't1', photo_id: 'p1', thumb: false },
    ]);
  });

  it('shows the rows with no cover when the sign fails', async () => {
    const { card } = makeCard([task({ photos: [photo('p1')] })], { signFails: true });
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(sr(card).querySelector('.hk-row .hk-name').textContent).toBe('Repair insulation');
    expect(sr(card).querySelector('.hk-cover')).toBeNull();
  });

  it('signs nothing when no task has a photo', async () => {
    const { card, calls } = makeCard([task()]);
    await waitFor(() => sr(card)?.querySelector('.hk-row'));
    expect(calls.some((m) => m.type === 'home_keeper/sign_task_photo_urls')).toBe(false);
  });
});

describe('photos in the card New task form', () => {
  const img = (name, type = 'image/jpeg') => new File(['x'], name, { type });

  async function openForm(tasks = [task()]) {
    const made = makeCard(tasks);
    await waitFor(() => sr(made.card)?.querySelector('#hk-add'));
    sr(made.card).querySelector('#hk-add').click();
    await waitFor(() => sr(made.card).querySelector('.hk-form-photos'));
    return made;
  }

  function pick(card, files) {
    const input = sr(card).querySelector('.hk-form-photos input[type="file"]');
    Object.defineProperty(input, 'files', { value: files, configurable: true });
    input.dispatchEvent(new Event('change'));
  }

  function fillName(card, name) {
    const form = sr(card).querySelector('.hk-form ha-form');
    form.dispatchEvent(new CustomEvent('value-changed', { detail: { value: { ...form.data, name } } }));
  }

  const tiles = (card) => [...sr(card).querySelectorAll('.hk-form-photos .hk-staged img')].map((i) => i.alt);

  it('offers Add photo to a user who is not an admin', async () => {
    const { card } = await openForm();
    const add = sr(card).querySelector('.hk-form-photos .hk-photo-add');
    expect(add.textContent).toContain(t('photos.add'));
    const input = sr(card).querySelector('.hk-form-photos input[type="file"]');
    expect(input.multiple).toBe(true);
    expect(input.accept).toBe('image/png,image/jpeg,image/webp,image/gif');
    expect(sr(card).querySelector('.hk-form-photos .hk-photo-strip')).toBeNull();
  });

  it('shows the picked photos, the first as the cover, and removes one', async () => {
    const { card } = await openForm();
    pick(card, [img('a.jpg'), img('b.jpg')]);
    await waitFor(() => tiles(card).length === 2);
    expect(tiles(card)).toEqual(['a.jpg', 'b.jpg']);
    expect(sr(card).querySelectorAll('.hk-form-photos .hk-photo-badge')).toHaveLength(1);
    expect(sr(card).querySelector('.hk-form-photos .hk-staged-cover')).toBeNull();
    sr(card).querySelector('.hk-form-photos .hk-staged-remove').click();
    await waitFor(() => tiles(card).length === 1);
    expect(tiles(card)).toEqual(['b.jpg']);
    expect(revoked).toEqual(['blob:a.jpg']);
  });

  it('shows why a file was refused, in the form', async () => {
    const { card } = await openForm();
    pick(card, [img('manual.pdf', 'application/pdf')]);
    await waitFor(() => sr(card).querySelector('.hk-form ha-alert'));
    expect(sr(card).querySelector('.hk-form ha-alert').textContent).toBe(
      t('photos.notImage', { name: 'manual.pdf' }),
    );
    expect(tiles(card)).toEqual([]);
  });

  it('hides Add photo when 6 photos are picked', async () => {
    const { card } = await openForm();
    pick(card, Array.from({ length: 6 }, (_, i) => img(`${i}.jpg`)));
    await waitFor(() => tiles(card).length === 6);
    expect(sr(card).querySelector('.hk-form-photos .hk-photo-add')).toBeNull();
  });

  it('uploads the photos in order to the new task after Create', async () => {
    const { card, calls } = await openForm();
    pick(card, [img('a.jpg'), img('b.jpg')]);
    await waitFor(() => tiles(card).length === 2);
    const keys = card._edit.photos.map((s) => s.key);
    fillName(card, 'Repair insulation');
    sr(card).querySelector('#hk-create').click();
    await waitFor(() => !card._edit.open);
    expect(calls.filter((m) => m.type === 'home_keeper/add_task')).toHaveLength(1);
    expect(AutoXHR.sent.map((s) => s.url)).toEqual(keys.map((k) => `/api/home_keeper/task_photo/new1/${k}`));
    expect(AutoXHR.sent.map((s) => s.file.name)).toEqual(['a.jpg', 'b.jpg']);
    expect(revoked.sort()).toEqual(['blob:a.jpg', 'blob:b.jpg']);
  });

  it('keeps the task and closes the form when a photo fails, with a toast', async () => {
    const { card, calls } = await openForm();
    const toasts = [];
    card.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    pick(card, [img('a.jpg'), img('b.jpg')]);
    await waitFor(() => tiles(card).length === 2);
    AutoXHR.failUrls.add(card._edit.photos[1].key);
    fillName(card, 'Repair insulation');
    sr(card).querySelector('#hk-create').click();
    await waitFor(() => !card._edit.open);
    expect(AutoXHR.sent).toHaveLength(2);
    expect(calls.filter((m) => m.type === 'home_keeper/add_task')).toHaveLength(1);
    expect(toasts).toEqual([t('photos.uploadPartial', { n: '1' })]);
  });

  it('uploads nothing and shows no toast for a task with no photos', async () => {
    const { card } = await openForm();
    const toasts = [];
    card.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    fillName(card, 'Plain');
    sr(card).querySelector('#hk-create').click();
    await waitFor(() => !card._edit.open);
    expect(AutoXHR.sent).toEqual([]);
    expect(toasts).toEqual([]);
  });

  it('drops the picked photos on Cancel', async () => {
    const { card } = await openForm();
    pick(card, [img('a.jpg')]);
    await waitFor(() => tiles(card).length === 1);
    const cancel = [...sr(card).querySelectorAll('.hk-form-actions ha-button')].find(
      (b) => b.textContent === t('btn.cancel'),
    );
    cancel.click();
    await waitFor(() => !card._edit.open);
    expect(revoked).toEqual(['blob:a.jpg']);
  });
});
