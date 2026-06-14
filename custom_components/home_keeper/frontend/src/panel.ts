import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import type { Asset, AssetKind, Freq, Hass, PanelInfo, Part, Task, Unit } from './types';
import {
  areaName,
  assetSummary,
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
  .hk-tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .hk-tab {
    background: none; border: none; cursor: pointer; padding: 8px 4px;
    font-size: 0.95rem; color: var(--secondary-text-color);
    border-bottom: 2px solid transparent;
  }
  .hk-tab.active { color: var(--primary-text-color); border-bottom-color: var(--primary-color); font-weight: 600; }
  .badge.kind { background: var(--primary-color); color: var(--text-primary-color, #fff); }
  .hk-fieldset-title { font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 18px 0 4px; }
  .hk-part { border: 1px solid var(--divider-color, #ccc); border-radius: 8px;
    padding: 10px; margin-bottom: 8px; }
  .hk-part .hk-row { align-items: flex-end; }
  .hk-part .part-del { padding: 6px 10px; flex: 0 0 auto; align-self: flex-end; }
  .hk-chip { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.72rem;
    background: var(--secondary-background-color); color: var(--secondary-text-color); margin-right: 6px; }
  select[multiple] { min-height: 96px; }
`;

interface EditState {
  open: boolean;
  task: Partial<Task> | null; // null when not editing
}

interface AssetEditState {
  open: boolean;
  asset: Partial<Asset> | null; // null when not editing
}

export class HomeKeeperPanel extends HTMLElement {
  private _hass?: Hass;
  public panel?: PanelInfo;
  public narrow = false;
  private _tasks: Task[] = [];
  private _assets: Asset[] = [];
  private _edit: EditState = { open: false, task: null };
  private _assetEdit: AssetEditState = { open: false, asset: null };
  private _view: 'tasks' | 'appliances' = 'tasks';
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
      const [tasks, assets] = await Promise.all([
        api.getTasks(this._hass),
        api.getAssets(this._hass),
      ]);
      this._tasks = tasks;
      this._assets = assets;
      this._loaded = true;
    } catch (err) {
      // Leave lists as-is; surface nothing fatal for the prototype.
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load data', err);
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

  // ── appliance (asset) helpers ───────────────────────────────────────────────
  private _openCreateAsset(): void {
    this._assetEdit = { open: true, asset: { kind: 'virtual' } };
    this._render();
  }
  private _openEditAsset(asset: Asset): void {
    this._assetEdit = { open: true, asset: { ...asset } };
    this._render();
  }
  private _closeAssetForm(): void {
    this._assetEdit = { open: false, asset: null };
    this._render();
  }

  /** Read the live asset form (incl. parts/related/parent) into a payload. */
  private _collectAssetForm(): Partial<Asset> {
    const root = this.shadowRoot!;
    const val = (id: string): string =>
      (root.getElementById(id) as HTMLInputElement | HTMLSelectElement | null)?.value ?? '';
    const kind = val('a-kind') as AssetKind;
    const partCount = root.querySelectorAll('.hk-part').length;
    const parts: Part[] = [];
    for (let i = 0; i < partCount; i++) {
      const name = val(`p-name-${i}`).trim();
      if (!name) continue; // skip empty rows
      const type = (val(`p-type-${i}`) as Part['type']) || 'consumable';
      const interval = val(`p-int-${i}`);
      parts.push({
        id: val(`p-id-${i}`) || undefined,
        name,
        part_number: val(`p-number-${i}`),
        type,
        vendor: val(`p-vendor-${i}`),
        cost: val(`p-cost-${i}`) ? Number(val(`p-cost-${i}`)) : null,
        replace_interval: type === 'wear' && interval ? Number(interval) : null,
        replace_unit: type === 'wear' && interval ? (val(`p-unit-${i}`) as Unit) : null,
        last_replaced: val(`p-lastreplaced-${i}`) || null,
      });
    }
    const relatedSel = root.getElementById('a-related') as HTMLSelectElement | null;
    const related = relatedSel
      ? Array.from(relatedSel.selectedOptions).map((o) => o.value)
      : [];
    const payload: Partial<Asset> = {
      kind,
      area_id: val('a-area') || null,
      purchase_date: val('a-purchase') || null,
      install_date: val('a-install') || null,
      warranty_expiry: val('a-warranty') || null,
      warranty_provider: val('a-warranty-provider'),
      vendor: val('a-vendor'),
      cost: val('a-cost') ? Number(val('a-cost')) : null,
      manual_url: val('a-manual'),
      notes: val('a-notes'),
      parts,
      related_device_ids: related,
    };
    if (kind === 'virtual') {
      payload.name = val('a-name');
      payload.manufacturer = val('a-manufacturer');
      payload.model = val('a-model');
      payload.serial_number = val('a-serial');
      payload.icon = val('a-icon');
      payload.parent_asset_id = val('a-parent') || null;
    } else {
      payload.device_id = val('a-device') || null;
    }
    return payload;
  }

  /**
   * Sync the live form into the working edit state.
   * MUST be called before any mutation of `_assetEdit.asset.parts` that triggers a
   * re-render (add/remove part, change part type) — otherwise the user's typed-but-
   * unsubmitted input in the other fields is lost on the rebuild.
   */
  private _syncAssetFormToState(): void {
    if (this._assetEdit.asset) {
      this._assetEdit.asset = { ...this._assetEdit.asset, ...this._collectAssetForm() };
    }
  }

  private async _submitAssetForm(): Promise<void> {
    if (!this._hass || !this._assetEdit.asset) return;
    const root = this.shadowRoot!;
    const payload = this._collectAssetForm();
    try {
      if (this._assetEdit.asset.id) {
        await api.updateAsset(this._hass, this._assetEdit.asset.id, payload);
      } else {
        await api.addAsset(this._hass, payload);
      }
      this._closeAssetForm();
      await this._refresh();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('home-keeper: asset save failed', err);
      const msg = root.getElementById('a-error');
      if (msg) msg.textContent = String((err as { message?: string })?.message || err);
    }
  }

  private async _deleteAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    await api.deleteAsset(this._hass, asset.id);
    await this._refresh();
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _render(): void {
    if (!this.shadowRoot) return;
    const onTasks = this._view === 'tasks';
    const addLabel = onTasks ? '+ Add task' : '+ Add appliance';

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-wrap">
        <div class="hk-header">
          <div>
            <div class="hk-title">Home Keeper</div>
            <div class="hk-sub">Home maintenance &amp; chores</div>
          </div>
          <button class="hk-btn" id="add-btn">${addLabel}</button>
        </div>
        <div class="hk-tabs">
          <button class="hk-tab ${onTasks ? 'active' : ''}" id="tab-tasks">Tasks</button>
          <button class="hk-tab ${onTasks ? '' : 'active'}" id="tab-appliances">Appliances</button>
        </div>
        ${onTasks ? this._tasksView() : this._appliancesView()}
        <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
      </div>
    `;
    this._wire();
  }

  private _tasksView(): string {
    const tasks = [...this._tasks].sort((a, b) => {
      const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
      const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
      return ad - bd;
    });
    const list = tasks.length
      ? tasks.map((t) => this._taskCard(t)).join('')
      : `<div class="hk-empty">No tasks yet. Click <b>Add task</b> to create your first maintenance reminder.</div>`;
    return `${this._edit.open ? this._formHTML() : ''}<div id="hk-list">${list}</div>`;
  }

  private _appliancesView(): string {
    const assets = [...this._assets].sort((a, b) =>
      (a.name || '').localeCompare(b.name || ''),
    );
    const list = assets.length
      ? assets.map((x) => this._assetCard(x)).join('')
      : `<div class="hk-empty">No appliances yet. Add one to create a device page your tasks (and batteries) can share — fridge, furnace, water heater…</div>`;
    return `${this._assetEdit.open ? this._assetFormHTML() : ''}<div id="hk-asset-list">${list}</div>`;
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

  private _assetCard(x: Asset): string {
    const devLabel =
      x.kind === 'virtual'
        ? `<span class="badge kind">Virtual device</span>`
        : `<span class="badge device">${escapeHTML(deviceName(this._hass?.devices, x.device_id))}</span>`;
    const title = x.name || deviceName(this._hass?.devices, x.device_id) || 'Appliance';
    const subCount = this._assets.filter((a) => a.parent_asset_id === x.id).length;
    const relCount = x.related_device_ids?.length ?? 0;
    const rels = [
      subCount ? `<span class="hk-chip">${subCount} subdevice${subCount === 1 ? '' : 's'}</span>` : '',
      relCount ? `<span class="hk-chip">${relCount} related</span>` : '',
      x.parent_asset_id ? `<span class="hk-chip">subdevice of ${escapeHTML(this._assetName(x.parent_asset_id))}</span>` : '',
    ].join('');
    return `
      <div class="hk-card" data-id="${escapeHTML(x.id)}">
        <div class="grow">
          <div class="hk-name">${escapeHTML(title)}${devLabel}</div>
          <div class="hk-meta">${escapeHTML(assetSummary(x, this._hass?.areas))}</div>
          ${rels ? `<div class="hk-meta">${rels}</div>` : ''}
        </div>
        <button class="hk-btn secondary asset-edit-btn" data-id="${escapeHTML(x.id)}">Edit</button>
        <button class="hk-btn danger asset-del-btn" data-id="${escapeHTML(x.id)}">Delete</button>
      </div>`;
  }

  private _assetName(assetId: string): string {
    return this._assets.find((a) => a.id === assetId)?.name || assetId;
  }

  private _assetFormHTML(): string {
    const x = this._assetEdit.asset || {};
    const isExisting = x.kind === 'existing';
    const editing = Boolean(x.id);
    const devices = this._hass?.devices || {};
    const deviceOptions = ['<option value="">— Select a device —</option>']
      .concat(
        Object.values(devices)
          .map((d) => ({ id: d.id, name: d.name_by_user || d.name || d.id }))
          .sort((a, b) => a.name.localeCompare(b.name))
          .map(
            (d) =>
              `<option value="${escapeHTML(d.id)}" ${x.device_id === d.id ? 'selected' : ''}>${escapeHTML(d.name)}</option>`,
          ),
      )
      .join('');
    const areas = this._hass?.areas || {};
    const areaOptions = ['<option value="">— No area —</option>']
      .concat(
        Object.values(areas)
          .map((a) => ({ id: a.area_id, name: a.name }))
          .sort((a, b) => a.name.localeCompare(b.name))
          .map(
            (a) =>
              `<option value="${escapeHTML(a.id)}" ${x.area_id === a.id ? 'selected' : ''}>${escapeHTML(a.name)}</option>`,
          ),
      )
      .join('');

    const dateInput = (id: string, label: string, value?: string | null): string => `
      <div>
        <label for="${id}">${label}</label>
        <input id="${id}" type="date" value="${escapeHTML((value || '').slice(0, 10))}" />
      </div>`;

    const parentOptions = ['<option value="">— None (standalone) —</option>']
      .concat(
        this._eligibleParents(x).map(
          (p) =>
            `<option value="${escapeHTML(p.id)}" ${x.parent_asset_id === p.id ? 'selected' : ''}>${escapeHTML(p.name)}</option>`,
        ),
      )
      .join('');
    const related = new Set(x.related_device_ids || []);
    const relatedOptions = Object.values(devices)
      .map((d) => ({ id: d.id, name: d.name_by_user || d.name || d.id }))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(
        (d) =>
          `<option value="${escapeHTML(d.id)}" ${related.has(d.id) ? 'selected' : ''}>${escapeHTML(d.name)}</option>`,
      )
      .join('');

    return `
      <div class="hk-form" id="hk-asset-form">
        <div class="hk-title" style="font-size:1.1rem">${editing ? 'Edit appliance' : 'New appliance'}</div>

        <label for="a-kind">Type</label>
        <select id="a-kind" ${editing ? 'disabled' : ''}>
          <option value="virtual" ${!isExisting ? 'selected' : ''}>New appliance (Home Keeper creates a device)</option>
          <option value="existing" ${isExisting ? 'selected' : ''}>Existing device (add details to it)</option>
        </select>

        <div id="a-virtual-wrap" style="${isExisting ? 'display:none' : ''}">
          <label for="a-name">Name</label>
          <input id="a-name" type="text" value="${escapeHTML(x.name || '')}" placeholder="Kitchen fridge" />
          <div class="hk-row">
            <div>
              <label for="a-manufacturer">Manufacturer</label>
              <input id="a-manufacturer" type="text" value="${escapeHTML(x.manufacturer || '')}" />
            </div>
            <div>
              <label for="a-model">Model</label>
              <input id="a-model" type="text" value="${escapeHTML(x.model || '')}" />
            </div>
            <div>
              <label for="a-serial">Serial number</label>
              <input id="a-serial" type="text" value="${escapeHTML(x.serial_number || '')}" />
            </div>
          </div>
          <div class="hk-row">
            <div>
              <label for="a-icon">Icon (mdi)</label>
              <input id="a-icon" type="text" value="${escapeHTML(x.icon || '')}" placeholder="mdi:piano" />
            </div>
            <div>
              <label for="a-parent">Subdevice of (parent appliance)</label>
              <select id="a-parent">${parentOptions}</select>
            </div>
          </div>
        </div>

        <div id="a-existing-wrap" style="${isExisting ? '' : 'display:none'}">
          <label for="a-device">Device</label>
          <select id="a-device">${deviceOptions}</select>
        </div>

        <label for="a-area">Area</label>
        <select id="a-area">${areaOptions}</select>

        <div class="hk-fieldset-title">Ownership &amp; warranty</div>
        <div class="hk-row">
          ${dateInput('a-purchase', 'Purchase date', x.purchase_date)}
          ${dateInput('a-install', 'Install date', x.install_date)}
          ${dateInput('a-warranty', 'Warranty expiry', x.warranty_expiry)}
        </div>
        <div class="hk-row">
          <div>
            <label for="a-warranty-provider">Warranty provider</label>
            <input id="a-warranty-provider" type="text" value="${escapeHTML(x.warranty_provider || '')}" />
          </div>
          <div>
            <label for="a-cost">Cost</label>
            <input id="a-cost" type="number" step="0.01" min="0" value="${escapeHTML(x.cost ?? '')}" />
          </div>
          <div>
            <label for="a-vendor">Vendor / where to rebuy</label>
            <input id="a-vendor" type="text" value="${escapeHTML(x.vendor || '')}" />
          </div>
        </div>

        <div class="hk-fieldset-title">Parts &amp; wear items</div>
        <div id="a-parts-list">${(x.parts || []).map((p, i) => this._partRowHTML(p, i)).join('')}</div>
        <button class="hk-btn secondary" id="a-add-part" type="button">+ Add part</button>

        <div class="hk-fieldset-title">Related devices</div>
        <label for="a-related">Associate other devices (e.g. a sensor) with this appliance</label>
        <select id="a-related" multiple>${relatedOptions}</select>

        <div class="hk-fieldset-title">Reference</div>
        <label for="a-manual">Manual / docs URL</label>
        <input id="a-manual" type="url" value="${escapeHTML(x.manual_url || '')}" placeholder="https://…" />
        <label for="a-notes">Notes</label>
        <textarea id="a-notes" rows="2">${escapeHTML(x.notes || '')}</textarea>

        <div id="a-error" style="color:var(--error-color);font-size:0.8rem;margin-top:8px"></div>
        <div class="hk-actions">
          <button class="hk-btn" id="a-save">${editing ? 'Save' : 'Create'}</button>
          <button class="hk-btn secondary" id="a-cancel">Cancel</button>
        </div>
      </div>`;
  }

  private _partRowHTML(p: Part, i: number): string {
    const isWear = p.type === 'wear';
    const unit = (u: Unit): string =>
      `<option value="${u}" ${p.replace_unit === u ? 'selected' : ''}>${u}</option>`;
    return `
      <div class="hk-part" data-idx="${i}">
        <input type="hidden" id="p-id-${i}" value="${escapeHTML(p.id || '')}" />
        <input type="hidden" id="p-lastreplaced-${i}" value="${escapeHTML(p.last_replaced || '')}" />
        <div class="hk-row">
          <div style="flex:2">
            <label>Part</label>
            <input id="p-name-${i}" type="text" value="${escapeHTML(p.name || '')}" placeholder="Shade material" />
          </div>
          <div>
            <label>Part #</label>
            <input id="p-number-${i}" type="text" value="${escapeHTML(p.part_number || '')}" />
          </div>
          <div>
            <label>Type</label>
            <select id="p-type-${i}" class="p-type">
              <option value="consumable" ${!isWear ? 'selected' : ''}>consumable</option>
              <option value="wear" ${isWear ? 'selected' : ''}>wear item</option>
            </select>
          </div>
          <button class="hk-btn danger part-del" data-idx="${i}" type="button">×</button>
        </div>
        <div class="hk-row">
          <div>
            <label>Vendor</label>
            <input id="p-vendor-${i}" type="text" value="${escapeHTML(p.vendor || '')}" />
          </div>
          <div>
            <label>Cost</label>
            <input id="p-cost-${i}" type="number" step="0.01" min="0" value="${escapeHTML(p.cost ?? '')}" />
          </div>
          <div class="p-wear-${i}" style="${isWear ? '' : 'display:none'}">
            <label>Replace every</label>
            <input id="p-int-${i}" type="number" min="1" value="${escapeHTML(p.replace_interval ?? '')}" />
          </div>
          <div class="p-wear-${i}" style="${isWear ? '' : 'display:none'}">
            <label>Unit</label>
            <select id="p-unit-${i}">${unit('days')}${unit('weeks')}${unit('months')}</select>
          </div>
        </div>
        ${p.last_replaced ? `<div class="hk-meta">Last replaced ${escapeHTML(p.last_replaced)} · a maintenance task tracks the next one</div>` : isWear ? `<div class="hk-meta">A wear item with an interval creates a maintenance task on this appliance.</div>` : ''}
      </div>`;
  }

  /** Virtual assets that may be a parent (excludes self + descendants → no cycles). */
  private _eligibleParents(x: Partial<Asset>): { id: string; name: string }[] {
    const banned = new Set<string>();
    if (x.id) {
      banned.add(x.id);
      // Walk descendants: any asset whose parent chain reaches x.id.
      const childrenOf = (pid: string): void => {
        for (const a of this._assets) {
          if (a.parent_asset_id === pid && !banned.has(a.id)) {
            banned.add(a.id);
            childrenOf(a.id);
          }
        }
      };
      childrenOf(x.id);
    }
    return this._assets
      .filter((a) => a.kind === 'virtual' && !banned.has(a.id))
      .map((a) => ({ id: a.id, name: a.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  private _wire(): void {
    const root = this.shadowRoot!;
    root.getElementById('tab-tasks')?.addEventListener('click', () => {
      this._view = 'tasks';
      this._render();
    });
    root.getElementById('tab-appliances')?.addEventListener('click', () => {
      this._view = 'appliances';
      this._render();
    });
    root.getElementById('add-btn')?.addEventListener('click', () =>
      this._view === 'tasks' ? this._openCreate() : this._openCreateAsset(),
    );

    if (this._view === 'appliances') {
      this._wireAssets(root);
      return;
    }

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

  private _wireAssets(root: ShadowRoot): void {
    if (this._assetEdit.open) {
      root.getElementById('a-save')?.addEventListener('click', () => void this._submitAssetForm());
      root.getElementById('a-cancel')?.addEventListener('click', () => this._closeAssetForm());
      // Toggle virtual/existing field visibility live.
      root.getElementById('a-kind')?.addEventListener('change', (e) => {
        const existing = (e.target as HTMLSelectElement).value === 'existing';
        (root.getElementById('a-virtual-wrap') as HTMLElement).style.display = existing ? 'none' : '';
        (root.getElementById('a-existing-wrap') as HTMLElement).style.display = existing ? '' : 'none';
      });
      // Parts editor: add / remove / toggle wear fields (re-render, preserving input).
      root.getElementById('a-add-part')?.addEventListener('click', () => {
        this._syncAssetFormToState();
        const a = this._assetEdit.asset!;
        a.parts = [...(a.parts || []), { name: '', type: 'consumable' }];
        this._render();
      });
      root.querySelectorAll<HTMLButtonElement>('.part-del').forEach((b) =>
        b.addEventListener('click', () => {
          this._syncAssetFormToState();
          const a = this._assetEdit.asset!;
          const idx = Number(b.dataset.idx);
          a.parts = (a.parts || []).filter((_, i) => i !== idx);
          this._render();
        }),
      );
      root.querySelectorAll<HTMLSelectElement>('.p-type').forEach((sel) =>
        sel.addEventListener('change', () => {
          this._syncAssetFormToState();
          this._render();
        }),
      );
    }

    const byId = (id: string): Asset | undefined => this._assets.find((x) => x.id === id);
    root.querySelectorAll<HTMLButtonElement>('.asset-edit-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const x = byId(b.dataset.id!);
        if (x) this._openEditAsset(x);
      }),
    );
    root.querySelectorAll<HTMLButtonElement>('.asset-del-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const x = byId(b.dataset.id!);
        if (x) void this._deleteAsset(x);
      }),
    );
  }
}
