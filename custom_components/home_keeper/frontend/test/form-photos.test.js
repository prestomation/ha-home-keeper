// Photos in the panel task form (#399): a new task keeps the photos in the browser
// and uploads them after Create; a saved task shows the live strip of its task page.
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { definePanelStubs, emitChange, makeHass, mountPanel, waitFor } from './panel-harness.js';
import { t } from '../src/i18n.ts';

// An XMLHttpRequest that answers each upload by itself. A URL in `failUrls` gets a
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
      this.responseText = fail ? '{"message":"boom"}' : '{"task":{"id":"new1","photos":[]}}';
      this._listeners.dispatchEvent(new Event('load'));
    }, 0);
  }
  abort() {}
}

let realXHR;
let realCreate;
let realRevoke;
const revoked = [];

beforeAll(definePanelStubs);
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

/** A hass that answers add_task with task `new1`, and records the websocket calls. */
function hassWith(tasks = []) {
  const base = makeHass({ tasks });
  const calls = [];
  return {
    ...base,
    auth: { data: { access_token: 'tok' } },
    calls,
    callWS(msg) {
      calls.push(msg);
      if (msg.type === 'home_keeper/add_task') {
        return Promise.resolve({ task: { id: 'new1', name: msg.task?.name ?? 'x', photos: [] } });
      }
      return base.callWS(msg);
    },
  };
}

const img = (name, type = 'image/jpeg') => new File(['x'], name, { type });

/** Pick *files* in the staged Add tile's hidden input. */
function pick(panel, files) {
  const input = panel.shadowRoot.querySelector('.hk-form-photos .hk-staged-add + input[type="file"]');
  expect(input, 'the Add tile has a file input').toBeTruthy();
  Object.defineProperty(input, 'files', { value: files, configurable: true });
  input.dispatchEvent(new Event('change'));
}

const staged = (panel) =>
  [...panel.shadowRoot.querySelectorAll('.hk-form-photos .hk-staged')].map((el) => el.querySelector('img').alt);

async function openNewTask() {
  const hass = hassWith();
  const { panel, addBtn } = await mountPanel('/tasks', hass);
  addBtn.click();
  await waitFor(() => panel.shadowRoot.querySelector('.hk-form-photos'));
  return { panel, hass };
}

describe('the New task form', () => {
  it('shows an empty Photos section under Basics, with the Add tile and the help line', async () => {
    const { panel } = await openNewTask();
    const section = panel.shadowRoot.querySelector('.hk-form-photos');
    const basics = panel.shadowRoot.querySelector('#hk-task-form-basics');
    expect(basics.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.querySelector('.hk-form-photos-head').textContent).toContain(t('photos.title'));
    expect(section.querySelector('.hk-form-photos-head').textContent).toContain(
      t('photos.count', { n: '0', max: '6' }),
    );
    expect(section.querySelector('.hk-staged-add').textContent).toContain(t('photos.add'));
    expect(section.querySelector('.hk-staged-help').textContent).toBe(t('photos.stagedHelp'));
    const input = section.querySelector('input[type="file"]');
    expect(input.multiple).toBe(true);
    expect(input.accept).toBe('image/png,image/jpeg,image/webp,image/gif');
  });

  it('stages picked photos, makes another one the cover, and removes one', async () => {
    const { panel } = await openNewTask();
    pick(panel, [img('a.jpg'), img('b.png', 'image/png')]);
    await waitFor(() => staged(panel).length === 2);
    expect(staged(panel)).toEqual(['a.jpg', 'b.png']);
    const head = panel.shadowRoot.querySelector('.hk-form-photos-head');
    expect(head.textContent).toContain(t('photos.count', { n: '2', max: '6' }));
    const cover = panel.shadowRoot.querySelector('.hk-form-photos .hk-staged-cover');
    cover.click();
    await waitFor(() => staged(panel)[0] === 'b.png');
    expect(staged(panel)).toEqual(['b.png', 'a.jpg']);
    const tiles = panel.shadowRoot.querySelectorAll('.hk-form-photos .hk-staged');
    expect(tiles[0].querySelector('.hk-photo-badge')).toBeTruthy();
    tiles[1].querySelector('.hk-staged-remove').click();
    await waitFor(() => staged(panel).length === 1);
    expect(staged(panel)).toEqual(['b.png']);
    expect(revoked).toEqual(['blob:a.jpg']);
  });

  it('refuses a file that is not an image, with a toast', async () => {
    const { panel } = await openNewTask();
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    pick(panel, [img('manual.pdf', 'application/pdf')]);
    await waitFor(() => toasts.length);
    expect(toasts).toEqual([t('photos.notImage', { name: 'manual.pdf' })]);
    expect(staged(panel)).toEqual([]);
  });

  it('hides the Add tile when 6 photos are staged', async () => {
    const { panel } = await openNewTask();
    pick(panel, Array.from({ length: 6 }, (_, i) => img(`${i}.jpg`)));
    await waitFor(() => staged(panel).length === 6);
    expect(panel.shadowRoot.querySelector('.hk-form-photos .hk-staged-add')).toBeNull();
  });

  it('uploads the photos in order to the new task after Create, then closes', async () => {
    const { panel, hass } = await openNewTask();
    pick(panel, [img('a.jpg'), img('b.jpg')]);
    await waitFor(() => staged(panel).length === 2);
    panel.shadowRoot.querySelector('.hk-form-photos .hk-staged-cover').click();
    await waitFor(() => staged(panel)[0] === 'b.jpg');
    const keys = panel._edit.photos.map((s) => s.key);
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'Fix insulation' });
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => !panel._edit.open);
    expect(hass.calls.filter((m) => m.type === 'home_keeper/add_task')).toHaveLength(1);
    expect(AutoXHR.sent.map((s) => s.url)).toEqual(
      keys.map((k) => `/api/home_keeper/task_photo/new1/${k}`),
    );
    expect(AutoXHR.sent.map((s) => s.file.name)).toEqual(['b.jpg', 'a.jpg']);
    expect(revoked.sort()).toEqual(['blob:a.jpg', 'blob:b.jpg']);
    expect(location.pathname).not.toContain('new1');
  });

  it('keeps the task when a photo fails, says so, and opens the task page', async () => {
    const { panel, hass } = await openNewTask();
    const toasts = [];
    panel.addEventListener('hass-notification', (e) => toasts.push(e.detail.message));
    const navigations = [];
    panel.addEventListener('location-changed', () => navigations.push(location.pathname));
    pick(panel, [img('a.jpg'), img('b.jpg')]);
    await waitFor(() => staged(panel).length === 2);
    AutoXHR.failUrls.add(panel._edit.photos[0].key);
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'Fix insulation' });
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => navigations.length);
    expect(AutoXHR.sent).toHaveLength(2);
    expect(hass.calls.filter((m) => m.type === 'home_keeper/add_task')).toHaveLength(1);
    expect(panel._edit.open).toBe(false);
    expect(navigations).toEqual(['/home-keeper/tasks/new1']);
    expect(toasts).toContain(t('photos.uploadPartial', { n: '1' }));
  });

  it('uploads nothing for a task with no photos', async () => {
    const { panel } = await openNewTask();
    emitChange(panel.shadowRoot.querySelector('#hk-task-form-basics'), { name: 'Plain' });
    panel.shadowRoot.querySelector('#f-save').click();
    await waitFor(() => !panel._edit.open);
    expect(AutoXHR.sent).toEqual([]);
  });

  it('drops the staged photos on Cancel', async () => {
    const { panel } = await openNewTask();
    pick(panel, [img('a.jpg')]);
    await waitFor(() => staged(panel).length === 1);
    panel.shadowRoot.querySelector('#f-cancel').click();
    await waitFor(() => !panel._edit.open);
    expect(revoked).toEqual(['blob:a.jpg']);
    expect(panel._edit.photos).toBeUndefined();
  });
});

describe('the Edit task form', () => {
  const saved = {
    id: 't1',
    name: 'Fridge filter',
    recurrence_type: 'floating',
    interval: 1,
    unit: 'months',
    next_due: '2030-01-01T00:00:00+00:00',
    completions: [],
    photos: [
      { id: 'p1', name: 'one.jpg', filename: 'one.jpg', content_type: 'image/jpeg', size: 1 },
      { id: 'p2', name: 'two.jpg', filename: 'two.jpg', content_type: 'image/jpeg', size: 1 },
    ],
  };

  it('shows the stored photos with the live controls of the task page', async () => {
    const { panel } = await mountPanel('/tasks', hassWith([saved]));
    await waitFor(() => panel._tasks.length);
    panel._openEdit(panel._tasks[0]);
    const section = await waitFor(() => panel.shadowRoot.querySelector('.hk-form-photos'));
    expect([...section.querySelectorAll('[data-photo-tile]')].map((el) => el.dataset.photoTile)).toEqual([
      'p1',
      'p2',
    ]);
    expect(section.querySelector('.hk-photo-cover-btn').dataset.photoId).toBe('p2');
    expect(section.querySelector('.hk-photo-add')).toBeTruthy();
    expect(section.querySelector('.hk-staged-add')).toBeNull();
    expect(section.querySelector('.hk-form-photos-head').textContent).toContain(
      t('photos.count', { n: '2', max: '6' }),
    );
  });

  it('shows no Photos section for a task whose owner locks its photos and has none', async () => {
    const locked = { ...saved, photos: [], managed_by: { integration: 'x', locked_fields: ['photos'] } };
    const { panel } = await mountPanel('/tasks', hassWith([locked]));
    await waitFor(() => panel._tasks.length);
    panel._openEdit(panel._tasks[0]);
    await waitFor(() => panel.shadowRoot.querySelector('#hk-task-form-basics'));
    expect(panel.shadowRoot.querySelector('.hk-form-photos')).toBeNull();
  });
});
