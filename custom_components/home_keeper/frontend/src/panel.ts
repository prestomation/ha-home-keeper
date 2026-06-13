import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import type { Freq, Hass, PanelInfo, Task, Unit } from './types';
import {
  deviceName,
  dueLabel,
  escapeHTML,
  isOverdue,
  recurrenceSummary,
} from './utils';

const STYLES = `
  :host { display: block; }
  .hk-wrap {
    padding: 16px;
    max-width: 920px;
    margin: 0 auto;
    color: var(--primary-text-color);
  }
  .hk-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 16px;
  }
  .hk-title { font-size: 1.5rem; font-weight: 500; }
  .hk-sub { color: var(--secondary-text-color); font-size: 0.85rem; }
  button.hk-btn {
    background: var(--primary-color); color: var(--text-primary-color, #fff);
    border: none; border-radius: 8px; padding: 8px 14px; cursor: pointer;
    font-size: 0.9rem;
  }
  button.hk-btn.secondary {
    background: var(--secondary-background-color); color: var(--primary-text-color);
  }
  button.hk-btn.danger { background: var(--error-color, #db4437); }
  .hk-card {
    background: var(--card-background-color, #fff);
    border-radius: 12px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.1));
    padding: 12px 16px; margin-bottom: 10px;
    display: flex; align-items: center; gap: 12px;
  }
  .hk-card .grow { flex: 1; min-width: 0; }
  .hk-name { font-weight: 500; }
  .hk-meta { color: var(--secondary-text-color); font-size: 0.82rem; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 0.72rem; font-weight: 600; margin-left: 8px;
  }
  .badge.overdue { background: var(--error-color, #db4437); color: #fff; }
  .badge.ok { background: var(--success-color, #43a047); color: #fff; }
  .badge.device { background: var(--secondary-background-color); color: var(--secondary-text-color); }
  .hk-empty { text-align: center; color: var(--secondary-text-color); padding: 40px 0; }
  .hk-form { background: var(--card-background-color,#fff); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .hk-form label { display:block; font-size:0.8rem; color: var(--secondary-text-color); margin: 10px 0 4px; }
  .hk-form input, .hk-form select, .hk-form textarea {
    width: 100%; box-sizing: border-box; padding: 8px; border-radius: 6px;
    border: 1px solid var(--divider-color, #ccc);
    background: var(--primary-background-color); color: var(--primary-text-color);
  }
  .hk-row { display: flex; gap: 12px; }
  .hk-row > div { flex: 1; }
  .hk-actions { display: flex; gap: 8px; margin-top: 16px; }
  .ver { color: var(--secondary-text-color); font-size: 0.7rem; text-align: right; margin-top: 12px; }
`;

interface EditState {
  open: boolean;
  task: Partial<Task> | null; // null when not editing
}

export class HomeKeeperPanel extends HTMLElement {
  private _hass?: Hass;
  public panel?: PanelInfo;
  public narrow = false;
  private _tasks: Task[] = [];
  private _edit: EditState = { open: false, task: null };
  private _loaded = false;

  set hass(hass: Hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && !this._loaded) {
      void this._refresh();
    }
  }
  get hass(): Hass | undefined {
    return this._hass;
  }

  connectedCallback(): void {
    this.attachShadow({ mode: 'open' });
    this._render();
    if (this._hass && !this._loaded) void this._refresh();
  }

  private async _refresh(): Promise<void> {
    if (!this._hass) return;
    try {
      this._tasks = await api.getTasks(this._hass);
      this._loaded = true;
    } catch (err) {
      // Leave list as-is; surface nothing fatal for the prototype.
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load tasks', err);
    }
    this._render();
  }

  // ── form helpers ───────────────────────────────────────────────────────────
  private _openCreate(): void {
    this._edit = {
      open: true,
      task: { recurrence_type: 'floating', interval: 1, unit: 'months' },
    };
    this._render();
  }
  private _openEdit(task: Task): void {
    this._edit = { open: true, task: { ...task } };
    this._render();
  }
  private _closeForm(): void {
    this._edit = { open: false, task: null };
    this._render();
  }

  private async _submitForm(): Promise<void> {
    if (!this._hass || !this._edit.task) return;
    const root = this.shadowRoot!;
    const val = (id: string): string =>
      (root.getElementById(id) as HTMLInputElement | HTMLSelectElement | null)?.value ?? '';
    const recurrence_type = val('f-type') as Task['recurrence_type'];
    const payload: Partial<Task> = {
      name: val('f-name'),
      notes: val('f-notes'),
      recurrence_type,
      interval: Math.max(1, parseInt(val('f-interval'), 10) || 1),
      device_id: val('f-device') || null,
    };
    if (recurrence_type === 'floating') {
      payload.unit = val('f-unit') as Unit;
    } else {
      payload.freq = val('f-freq') as Freq;
      payload.anchor = val('f-anchor');
    }
    try {
      if (this._edit.task.id) {
        await api.updateTask(this._hass, this._edit.task.id, payload);
      } else {
        await api.addTask(this._hass, payload);
      }
      this._closeForm();
      await this._refresh();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('home-keeper: save failed', err);
      const msg = root.getElementById('f-error');
      if (msg) msg.textContent = String((err as { message?: string })?.message || err);
    }
  }

  private async _complete(task: Task): Promise<void> {
    if (!this._hass) return;
    await api.completeTask(this._hass, task.id);
    await this._refresh();
  }
  private async _delete(task: Task): Promise<void> {
    if (!this._hass) return;
    await api.deleteTask(this._hass, task.id);
    await this._refresh();
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _render(): void {
    if (!this.shadowRoot) return;
    const tasks = [...this._tasks].sort((a, b) => {
      const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
      const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
      return ad - bd;
    });

    const list = tasks.length
      ? tasks.map((t) => this._taskCard(t)).join('')
      : `<div class="hk-empty">No tasks yet. Click <b>Add task</b> to create your first maintenance reminder.</div>`;

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-wrap">
        <div class="hk-header">
          <div>
            <div class="hk-title">Home Keeper</div>
            <div class="hk-sub">Home maintenance &amp; chores</div>
          </div>
          <button class="hk-btn" id="add-btn">+ Add task</button>
        </div>
        ${this._edit.open ? this._formHTML() : ''}
        <div id="hk-list">${list}</div>
        <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
      </div>
    `;
    this._wire();
  }

  private _taskCard(t: Task): string {
    const overdue = isOverdue(t);
    const badge = overdue
      ? `<span class="badge overdue">Overdue</span>`
      : `<span class="badge ok">${escapeHTML(dueLabel(t))}</span>`;
    const dev = t.device_id
      ? `<span class="badge device">${escapeHTML(deviceName(this._hass?.devices, t.device_id))}</span>`
      : '';
    return `
      <div class="hk-card" data-id="${escapeHTML(t.id)}">
        <div class="grow">
          <div class="hk-name">${escapeHTML(t.name)}${badge}${dev}</div>
          <div class="hk-meta">${escapeHTML(recurrenceSummary(t))}${
            t.next_due ? ` · due ${escapeHTML(new Date(t.next_due).toLocaleDateString())}` : ''
          }</div>
        </div>
        <button class="hk-btn done-btn" data-id="${escapeHTML(t.id)}">Done</button>
        <button class="hk-btn secondary edit-btn" data-id="${escapeHTML(t.id)}">Edit</button>
        <button class="hk-btn danger del-btn" data-id="${escapeHTML(t.id)}">Delete</button>
      </div>`;
  }

  private _formHTML(): string {
    const t = this._edit.task || {};
    const isFixed = t.recurrence_type === 'fixed';
    const devices = this._hass?.devices || {};
    const deviceOptions = ['<option value="">— None (standalone) —</option>']
      .concat(
        Object.values(devices)
          .map((d) => ({ id: d.id, name: d.name_by_user || d.name || d.id }))
          .sort((a, b) => a.name.localeCompare(b.name))
          .map(
            (d) =>
              `<option value="${escapeHTML(d.id)}" ${
                t.device_id === d.id ? 'selected' : ''
              }>${escapeHTML(d.name)}</option>`,
          ),
      )
      .join('');

    return `
      <div class="hk-form" id="hk-form">
        <div class="hk-title" style="font-size:1.1rem">${t.id ? 'Edit task' : 'New task'}</div>
        <label for="f-name">Name</label>
        <input id="f-name" type="text" value="${escapeHTML(t.name || '')}" placeholder="Replace furnace filter" />
        <label for="f-notes">Notes</label>
        <textarea id="f-notes" rows="2">${escapeHTML(t.notes || '')}</textarea>

        <div class="hk-row">
          <div>
            <label for="f-type">Recurrence</label>
            <select id="f-type">
              <option value="floating" ${!isFixed ? 'selected' : ''}>Floating (from completion)</option>
              <option value="fixed" ${isFixed ? 'selected' : ''}>Fixed (anchored schedule)</option>
            </select>
          </div>
          <div>
            <label for="f-interval">Every</label>
            <input id="f-interval" type="number" min="1" value="${escapeHTML(t.interval || 1)}" />
          </div>
          <div id="unit-wrap" style="${isFixed ? 'display:none' : ''}">
            <label for="f-unit">Unit</label>
            <select id="f-unit">
              <option value="days" ${t.unit === 'days' ? 'selected' : ''}>days</option>
              <option value="weeks" ${t.unit === 'weeks' ? 'selected' : ''}>weeks</option>
              <option value="months" ${t.unit === 'months' || !t.unit ? 'selected' : ''}>months</option>
            </select>
          </div>
          <div id="freq-wrap" style="${isFixed ? '' : 'display:none'}">
            <label for="f-freq">Frequency</label>
            <select id="f-freq">
              <option value="DAILY" ${t.freq === 'DAILY' ? 'selected' : ''}>daily</option>
              <option value="WEEKLY" ${t.freq === 'WEEKLY' ? 'selected' : ''}>weekly</option>
              <option value="MONTHLY" ${t.freq === 'MONTHLY' ? 'selected' : ''}>monthly</option>
            </select>
          </div>
        </div>

        <div id="anchor-wrap" style="${isFixed ? '' : 'display:none'}">
          <label for="f-anchor">First occurrence (sets time of day)</label>
          <input id="f-anchor" type="datetime-local" value="${escapeHTML((t.anchor || '').slice(0, 16))}" />
        </div>

        <label for="f-device">Attach to device (optional)</label>
        <select id="f-device">${deviceOptions}</select>

        <div id="f-error" style="color:var(--error-color);font-size:0.8rem;margin-top:8px"></div>
        <div class="hk-actions">
          <button class="hk-btn" id="f-save">${t.id ? 'Save' : 'Create'}</button>
          <button class="hk-btn secondary" id="f-cancel">Cancel</button>
        </div>
      </div>`;
  }

  private _wire(): void {
    const root = this.shadowRoot!;
    root.getElementById('add-btn')?.addEventListener('click', () => this._openCreate());

    if (this._edit.open) {
      root.getElementById('f-save')?.addEventListener('click', () => void this._submitForm());
      root.getElementById('f-cancel')?.addEventListener('click', () => this._closeForm());
      // Toggle floating/fixed field visibility live.
      root.getElementById('f-type')?.addEventListener('change', (e) => {
        const fixed = (e.target as HTMLSelectElement).value === 'fixed';
        (root.getElementById('unit-wrap') as HTMLElement).style.display = fixed ? 'none' : '';
        (root.getElementById('freq-wrap') as HTMLElement).style.display = fixed ? '' : 'none';
        (root.getElementById('anchor-wrap') as HTMLElement).style.display = fixed ? '' : 'none';
      });
    }

    const byId = (id: string): Task | undefined => this._tasks.find((t) => t.id === id);
    root.querySelectorAll<HTMLButtonElement>('.done-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id!);
        if (t) void this._complete(t);
      }),
    );
    root.querySelectorAll<HTMLButtonElement>('.edit-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id!);
        if (t) this._openEdit(t);
      }),
    );
    root.querySelectorAll<HTMLButtonElement>('.del-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id!);
        if (t) void this._delete(t);
      }),
    );
  }
}
