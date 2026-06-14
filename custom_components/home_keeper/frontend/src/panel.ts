import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import { setLanguage, t, tn } from './i18n';
import type { Asset, AssetKind, Hass, PanelInfo, Part, Task } from './types';
import {
  assetSummary,
  deviceName,
  dueLabel,
  escapeHTML,
  isOverdue,
  recurrenceSummary,
} from './utils';

/**
 * The Home Keeper panel is built entirely from Home Assistant's own web
 * components (the HA design language): `ha-form` for every form (which also
 * lazy-loads its selector widgets — text, number, select, date/time, and the
 * searchable device/area/icon pickers), `ha-card` for list rows, `ha-tab-group`
 * for navigation, `ha-button`/`ha-icon-button` for actions, `ha-assist-chip`
 * for status, and `ha-alert` for empty/error states. The header reuses
 * `ha-menu-button` so the sidebar toggle works on mobile.
 *
 * Because HA components take object/array properties (`.hass`, `.schema`,
 * `.data`) that can't be expressed as HTML attributes, we render the static
 * chrome with innerHTML and then "hydrate" the live components in a follow-up
 * pass (`_hydrate`), wiring `value-changed`/`click` there.
 */

// Components we rely on. They are part of HA's frontend bundle but some load
// lazily; wait for them (best-effort) before the first render so the panel
// doesn't flash un-upgraded custom elements.
const REQUIRED_COMPONENTS = [
  'ha-form',
  'ha-card',
  'ha-button',
  'ha-icon-button',
  'ha-tab-group',
  'ha-tab-group-tab',
  'ha-alert',
  'ha-assist-chip',
  'ha-menu-button',
];

const STYLES = `
  :host { display: block; }
  .hk-toolbar {
    display: flex; align-items: center; gap: 12px; height: 56px;
    padding: 0 16px;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    --mdc-icon-button-size: 40px;
    box-shadow: var(--ha-card-box-shadow, 0 2px 2px rgba(0,0,0,.1));
  }
  .hk-toolbar-title { font-size: 1.25rem; font-weight: 400; flex: 1; }
  .hk-wrap { padding: 16px; max-width: 920px; margin: 0 auto; }
  ha-tab-group { margin-bottom: 16px; }
  .hk-actionbar { display: flex; justify-content: flex-end; margin-bottom: 12px; }
  ha-card.hk-card { margin-bottom: 12px; }
  .hk-card-row {
    display: flex; align-items: center; gap: 12px; padding: 12px 16px;
  }
  .hk-card-row .grow { flex: 1; min-width: 0; }
  .hk-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap;
  }
  .hk-meta { color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px; }
  .hk-card-actions { display: flex; align-items: center; gap: 4px; }
  ha-assist-chip.hk-overdue {
    --ha-assist-chip-container-color: var(--error-color);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --ha-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --md-assist-chip-outline-color: transparent;
  }
  .hk-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  .hk-form-card { margin-bottom: 16px; }
  .hk-form-inner { padding: 16px; }
  .hk-form-title { font-size: 1.1rem; font-weight: 500; margin-bottom: 8px; }
  .hk-section {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 20px 0 8px;
  }
  .hk-part {
    border: 1px solid var(--divider-color); border-radius: 8px;
    padding: 8px 12px 12px; margin-bottom: 10px;
  }
  .hk-part-head { display: flex; align-items: center; justify-content: space-between; }
  .hk-part-head .label { font-size: 0.85rem; color: var(--secondary-text-color); }
  .hk-form-actions { display: flex; gap: 8px; margin-top: 20px; }
  .hk-loading { display: flex; justify-content: center; padding: 48px 0; }
  .ver { color: var(--secondary-text-color); font-size: 0.7rem; text-align: right; margin-top: 16px; }
`;

// Minimal shape of an `ha-form` element (only what we set/read).
interface HaFormElement extends HTMLElement {
  hass?: Hass;
  schema?: unknown[];
  data?: Record<string, unknown>;
  computeLabel?: (schema: { name: string }) => string;
}

type Selector = Record<string, unknown>;
interface FormField {
  name: string;
  required?: boolean;
  selector?: Selector;
  type?: string;
  schema?: FormField[];
}

const selText = (multiline = false): Selector => ({ text: multiline ? { multiline: true } : {} });
const selNumber = (min = 0): Selector => ({ number: { min, mode: 'box' } });
const selBool = (): Selector => ({ boolean: {} });
const selDate = (): Selector => ({ date: {} });
const selDateTime = (): Selector => ({ datetime: {} });
const selDevice = (multiple = false): Selector => ({ device: multiple ? { multiple: true } : {} });
const selArea = (): Selector => ({ area: {} });
const selIcon = (): Selector => ({ icon: {} });
const selSelect = (options: { value: string; label: string }[]): Selector => ({
  select: { mode: 'dropdown', options, sort: false },
});

// ── datetime <-> HA selector string helpers ────────────────────────────────
// HA's datetime selector uses local "YYYY-MM-DD HH:mm:ss"; we persist ISO.
function isoToHaDateTime(iso?: string | null): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(
    d.getMinutes(),
  )}:${p(d.getSeconds())}`;
}
function haDateTimeToIso(value?: string | null): string | undefined {
  if (!value) return undefined;
  const d = new Date(value.replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return undefined;
  return d.toISOString();
}

interface EditState {
  open: boolean;
  task: Partial<Task> | null;
  error?: string;
}
interface AssetEditState {
  open: boolean;
  asset: Partial<Asset> | null;
  error?: string;
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
  // Live HA components that need `.hass` refreshed when hass updates.
  private _liveHassEls: Array<{ hass?: Hass }> = [];

  set hass(hass: Hass) {
    const first = !this._hass;
    // Keep the i18n module pointed at the user's HA language before any render.
    setLanguage(hass.language);
    this._hass = hass;
    // Keep selectors/pickers current without a disruptive full re-render.
    for (const el of this._liveHassEls) el.hass = hass;
    if (first && !this._loaded) void this._refresh();
  }
  get hass(): Hass | undefined {
    return this._hass;
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    void this._init();
  }

  private async _init(): Promise<void> {
    // Best-effort: let HA's lazy components register before first paint.
    await Promise.all(
      REQUIRED_COMPONENTS.map((n) =>
        Promise.race([
          customElements.whenDefined(n),
          new Promise((r) => setTimeout(r, 4000)),
        ]),
      ),
    );
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
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load data', err);
    }
    this._render();
  }

  // ── task form lifecycle ─────────────────────────────────────────────────────
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
    const task = this._edit.task;
    if (!task.name || !String(task.name).trim()) {
      this._edit.error = t('error.nameRequired');
      this._render();
      return;
    }
    const payload: Partial<Task> = {
      name: task.name,
      notes: task.notes || '',
      recurrence_type: task.recurrence_type,
      interval: Math.max(1, Number(task.interval) || 1),
      device_id: task.device_id || null,
    };
    if (task.recurrence_type === 'floating') {
      payload.unit = task.unit || 'months';
    } else {
      payload.freq = task.freq || 'DAILY';
      payload.anchor = haDateTimeToIso(task.anchor) ?? task.anchor;
    }
    try {
      if (task.id) await api.updateTask(this._hass, task.id, payload);
      else await api.addTask(this._hass, payload);
      this._closeForm();
      await this._refresh();
    } catch (err) {
      this._edit.error = String((err as { message?: string })?.message || err);
      this._render();
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

  // ── asset form lifecycle ────────────────────────────────────────────────────
  private _openCreateAsset(): void {
    this._assetEdit = { open: true, asset: { kind: 'virtual', parts: [] } };
    this._render();
  }
  private _openEditAsset(asset: Asset): void {
    this._assetEdit = { open: true, asset: { ...asset, parts: [...(asset.parts || [])] } };
    this._render();
  }
  private _closeAssetForm(): void {
    this._assetEdit = { open: false, asset: null };
    this._render();
  }

  private async _submitAssetForm(): Promise<void> {
    if (!this._hass || !this._assetEdit.asset) return;
    const a = this._assetEdit.asset;
    if (a.kind === 'virtual' && !String(a.name || '').trim()) {
      this._assetEdit.error = t('error.nameRequiredAppliance');
      this._render();
      return;
    }
    if (a.kind === 'existing' && !a.device_id) {
      this._assetEdit.error = t('error.pickDevice');
      this._render();
      return;
    }
    const parts = (a.parts || []).filter((p) => p.name && p.name.trim());
    const payload: Partial<Asset> = { ...a, parts };
    try {
      if (a.id) await api.updateAsset(this._hass, a.id, payload);
      else await api.addAsset(this._hass, payload);
      this._closeAssetForm();
      await this._refresh();
    } catch (err) {
      this._assetEdit.error = String((err as { message?: string })?.message || err);
      this._render();
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
    this._liveHassEls = [];
    const onTasks = this._view === 'tasks';
    const addLabel = onTasks ? t('btn.addTask') : t('btn.addAppliance');

    const body = !this._loaded
      ? `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`
      : `
        <div class="hk-actionbar">
          <ha-button raised id="add-btn">${escapeHTML(addLabel)}</ha-button>
        </div>
        <div id="hk-form-host"></div>
        <div id="hk-list">${onTasks ? this._tasksList() : this._assetsList()}</div>`;

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-toolbar">
        <span id="menu-host"></span>
        <div class="hk-toolbar-title">${escapeHTML(t('app.title'))}</div>
      </div>
      <div class="hk-wrap">
        <ha-tab-group>
          <ha-tab-group-tab id="tab-tasks" panel="tasks" ${onTasks ? 'active' : ''}>${escapeHTML(t('tab.tasks'))}</ha-tab-group-tab>
          <ha-tab-group-tab id="tab-appliances" panel="appliances" ${onTasks ? '' : 'active'}>${escapeHTML(t('tab.appliances'))}</ha-tab-group-tab>
        </ha-tab-group>
        ${body}
        <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
      </div>
    `;
    this._hydrate();
  }

  private _tasksList(): string {
    const tasks = [...this._tasks].sort((a, b) => {
      const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
      const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
      return ad - bd;
    });
    if (!tasks.length) {
      const addTask = `<b>${escapeHTML(t('btn.addTask'))}</b>`;
      return `<ha-alert alert-type="info">${t('tasks.empty', { addTask })}</ha-alert>`;
    }
    return tasks.map((t) => this._taskCard(t)).join('');
  }

  private _assetsList(): string {
    const assets = [...this._assets].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    if (!assets.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('appliances.empty'))}</ha-alert>`;
    }
    return assets.map((x) => this._assetCard(x)).join('');
  }

  private _taskCard(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task))}"></ha-assist-chip>`;
    const dev = task.device_id
      ? `<ha-assist-chip label="${escapeHTML(deviceName(this._hass?.devices, task.device_id))}"></ha-assist-chip>`
      : '';
    const dueText = task.next_due
      ? ` · ${escapeHTML(t('form.task.due', { date: new Date(task.next_due).toLocaleDateString() }))}`
      : '';
    return `
      <ha-card class="hk-card" data-id="${escapeHTML(task.id)}">
        <div class="hk-card-row">
          <div class="grow">
            <div class="hk-name">${escapeHTML(task.name)}</div>
            <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}${dueText}</div>
            <div class="hk-chips">${statusChip}${dev}</div>
          </div>
          <div class="hk-card-actions">
            <ha-button class="done-btn" data-id="${escapeHTML(task.id)}">${escapeHTML(t('btn.done'))}</ha-button>
            <ha-icon-button class="edit-btn" data-id="${escapeHTML(task.id)}" label="${escapeHTML(t('btn.edit'))}"></ha-icon-button>
            <ha-icon-button class="del-btn" data-id="${escapeHTML(task.id)}" label="${escapeHTML(t('btn.delete'))}"></ha-icon-button>
          </div>
        </div>
      </ha-card>`;
  }

  private _assetCard(x: Asset): string {
    const kindChip =
      x.kind === 'virtual'
        ? `<ha-assist-chip label="${escapeHTML(t('chip.virtualDevice'))}"></ha-assist-chip>`
        : `<ha-assist-chip label="${escapeHTML(deviceName(this._hass?.devices, x.device_id))}"></ha-assist-chip>`;
    const title =
      x.name || deviceName(this._hass?.devices, x.device_id) || t('appliance.fallbackName');
    const subCount = this._assets.filter((a) => a.parent_asset_id === x.id).length;
    const relCount = x.related_device_ids?.length ?? 0;
    const extra = [
      subCount
        ? `<ha-assist-chip label="${escapeHTML(tn('asset.subdevices', subCount))}"></ha-assist-chip>`
        : '',
      relCount
        ? `<ha-assist-chip label="${escapeHTML(tn('asset.related', relCount))}"></ha-assist-chip>`
        : '',
      x.parent_asset_id
        ? `<ha-assist-chip label="${escapeHTML(
            t('chip.subdeviceOf', { name: this._assetName(x.parent_asset_id) }),
          )}"></ha-assist-chip>`
        : '',
    ].join('');
    return `
      <ha-card class="hk-card" data-id="${escapeHTML(x.id)}">
        <div class="hk-card-row">
          <div class="grow">
            <div class="hk-name">${escapeHTML(title)}</div>
            <div class="hk-meta">${escapeHTML(assetSummary(x, this._hass?.areas))}</div>
            <div class="hk-chips">${kindChip}${extra}</div>
          </div>
          <div class="hk-card-actions">
            <ha-icon-button class="asset-edit-btn" data-id="${escapeHTML(x.id)}" label="${escapeHTML(t('btn.edit'))}"></ha-icon-button>
            <ha-icon-button class="asset-del-btn" data-id="${escapeHTML(x.id)}" label="${escapeHTML(t('btn.delete'))}"></ha-icon-button>
          </div>
        </div>
      </ha-card>`;
  }

  private _assetName(assetId: string): string {
    return this._assets.find((a) => a.id === assetId)?.name || assetId;
  }

  // ── ha-form schemas ─────────────────────────────────────────────────────────
  private _taskSchema(task: Partial<Task>): FormField[] {
    const isFixed = task.recurrence_type === 'fixed';
    const cadence: FormField = isFixed
      ? {
          name: '',
          type: 'grid',
          schema: [
            { name: 'interval', selector: selNumber(1) },
            {
              name: 'freq',
              selector: selSelect([
                { value: 'DAILY', label: t('opt.freq.daily') },
                { value: 'WEEKLY', label: t('opt.freq.weekly') },
                { value: 'MONTHLY', label: t('opt.freq.monthly') },
              ]),
            },
          ],
        }
      : {
          name: '',
          type: 'grid',
          schema: [
            { name: 'interval', selector: selNumber(1) },
            {
              name: 'unit',
              selector: selSelect([
                { value: 'days', label: t('opt.unit.days') },
                { value: 'weeks', label: t('opt.unit.weeks') },
                { value: 'months', label: t('opt.unit.months') },
              ]),
            },
          ],
        };
    return [
      { name: 'name', required: true, selector: selText() },
      { name: 'notes', selector: selText(true) },
      {
        name: 'recurrence_type',
        selector: selSelect([
          { value: 'floating', label: t('opt.recurrence.floating') },
          { value: 'fixed', label: t('opt.recurrence.fixed') },
        ]),
      },
      cadence,
      ...(isFixed ? [{ name: 'anchor', selector: selDateTime() } as FormField] : []),
      { name: 'device_id', selector: selDevice() },
    ];
  }

  private _taskFormData(t: Partial<Task>): Record<string, unknown> {
    return {
      name: t.name ?? '',
      notes: t.notes ?? '',
      recurrence_type: t.recurrence_type ?? 'floating',
      interval: t.interval ?? 1,
      unit: t.unit ?? 'months',
      freq: t.freq ?? 'DAILY',
      anchor: isoToHaDateTime(t.anchor) ?? '',
      device_id: t.device_id ?? undefined,
    };
  }

  private _eligibleParents(x: Partial<Asset>): { value: string; label: string }[] {
    const banned = new Set<string>();
    if (x.id) {
      banned.add(x.id);
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
      .map((a) => ({ value: a.id, label: a.name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }

  /**
   * Identity schema (kind + virtual/existing fields + area). The `kind` field is
   * omitted once the asset exists (it's immutable after creation, and ha-form
   * has no per-field disable), so editing can't put it in an inconsistent state.
   */
  private _assetIdentitySchema(x: Partial<Asset>, editing: boolean): FormField[] {
    const fields: FormField[] = [];
    if (!editing) {
      fields.push({
        name: 'kind',
        selector: selSelect([
          { value: 'virtual', label: t('opt.kind.virtual') },
          { value: 'existing', label: t('opt.kind.existing') },
        ]),
      });
    }
    if (x.kind === 'existing') {
      fields.push({ name: 'device_id', required: true, selector: selDevice() });
    } else {
      fields.push({ name: 'name', required: true, selector: selText() });
      fields.push({
        name: '',
        type: 'grid',
        schema: [
          { name: 'manufacturer', selector: selText() },
          { name: 'model', selector: selText() },
          { name: 'serial_number', selector: selText() },
        ],
      });
      fields.push({
        name: '',
        type: 'grid',
        schema: [
          { name: 'icon', selector: selIcon() },
          { name: 'parent_asset_id', selector: selSelect(this._eligibleParents(x)) },
        ],
      });
    }
    fields.push({ name: 'area_id', selector: selArea() });
    return fields;
  }

  private _ownershipSchema(): FormField[] {
    return [
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'purchase_date', selector: selDate() },
          { name: 'install_date', selector: selDate() },
          { name: 'warranty_expiry', selector: selDate() },
        ],
      },
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'warranty_provider', selector: selText() },
          { name: 'cost', selector: selNumber(0) },
          { name: 'vendor', selector: selText() },
        ],
      },
    ];
  }

  private _referenceSchema(): FormField[] {
    return [
      { name: 'manual_url', selector: selText() },
      { name: 'notes', selector: selText(true) },
    ];
  }

  private _partSchema(p: Part): FormField[] {
    const isWear = p.type === 'wear';
    const base: FormField[] = [
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'part_name', selector: selText() },
          { name: 'part_number', selector: selText() },
          {
            name: 'type',
            selector: selSelect([
              { value: 'consumable', label: t('opt.part.consumable') },
              { value: 'wear', label: t('opt.part.wear') },
            ]),
          },
        ],
      },
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'vendor', selector: selText() },
          { name: 'cost', selector: selNumber(0) },
        ],
      },
    ];
    if (isWear) {
      base.push({
        name: '',
        type: 'grid',
        schema: [
          { name: 'replace_interval', selector: selNumber(1) },
          {
            name: 'replace_unit',
            selector: selSelect([
              { value: 'days', label: t('opt.unit.days') },
              { value: 'weeks', label: t('opt.unit.weeks') },
              { value: 'months', label: t('opt.unit.months') },
            ]),
          },
        ],
      });
    }
    return base;
  }

  // ── hydration: build/configure live HA components ───────────────────────────
  private _hydrate(): void {
    const root = this.shadowRoot;
    if (!root) return;

    // Header sidebar toggle.
    const menuHost = root.getElementById('menu-host');
    if (menuHost) {
      const mb = document.createElement('ha-menu-button') as HTMLElement & {
        hass?: Hass;
        narrow?: boolean;
      };
      mb.hass = this._hass;
      mb.narrow = this.narrow;
      this._liveHassEls.push(mb);
      menuHost.appendChild(mb);
    }

    // Tab navigation. Listen on each tab (click) and on the group's shoelace
    // `sl-tab-show` event (whichever fires) — both funnel through _switchView,
    // which is a no-op when the view is unchanged.
    root.getElementById('tab-tasks')?.addEventListener('click', () => this._switchView('tasks'));
    root
      .getElementById('tab-appliances')
      ?.addEventListener('click', () => this._switchView('appliances'));
    root.querySelector('ha-tab-group')?.addEventListener('sl-tab-show', (e: Event) => {
      const name = (e as CustomEvent<{ name?: string }>).detail?.name;
      if (name === 'tasks' || name === 'appliances') this._switchView(name);
    });

    root.getElementById('add-btn')?.addEventListener('click', () => {
      if (this._view === 'tasks') this._openCreate();
      else this._openCreateAsset();
    });

    // Forms.
    const host = root.getElementById('hk-form-host');
    if (host) {
      if (this._view === 'tasks' && this._edit.open) this._renderTaskForm(host);
      else if (this._view === 'appliances' && this._assetEdit.open) this._renderAssetForm(host);
    }

    // Card actions.
    if (this._view === 'tasks') this._wireTaskCards(root);
    else this._wireAssetCards(root);
  }

  private _switchView(view: 'tasks' | 'appliances'): void {
    if (this._view === view) return;
    this._view = view;
    this._render();
  }

  private _makeForm(
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
  ): HaFormElement {
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = schema;
    form.data = data;
    form.computeLabel = (s: { name: string }): string => (s.name ? t('field.' + s.name) : '');
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      onChange(value);
    });
    this._liveHassEls.push(form);
    return form;
  }

  private _renderTaskForm(host: HTMLElement): void {
    const task = this._edit.task || {};
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-form';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    inner.innerHTML = `<div class="hk-form-title">${escapeHTML(
      task.id ? t('form.task.edit') : t('form.task.new'),
    )}</div>`;

    const form = this._makeForm(this._taskSchema(task), this._taskFormData(task), (value) => {
      const prevType = this._edit.task?.recurrence_type;
      this._edit.task = {
        ...this._edit.task,
        ...value,
        interval: Number(value.interval) || 1,
      } as Partial<Task>;
      this._edit.error = undefined;
      // Recurrence type toggles which cadence fields show -> re-render.
      if (value.recurrence_type !== prevType) this._render();
    });
    form.id = 'hk-task-form';
    inner.appendChild(form);

    if (this._edit.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = this._edit.error;
      inner.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'hk-form-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.id = 'f-save';
    save.textContent = task.id ? t('btn.save') : t('btn.create');
    save.addEventListener('click', () => void this._submitForm());
    const cancel = document.createElement('ha-button');
    cancel.id = 'f-cancel';
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeForm());
    actions.append(save, cancel);
    inner.appendChild(actions);

    card.appendChild(inner);
    host.appendChild(card);
  }

  private _renderAssetForm(host: HTMLElement): void {
    const x = this._assetEdit.asset || {};
    const editing = Boolean(x.id);
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-asset-form';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    inner.innerHTML = `<div class="hk-form-title">${escapeHTML(
      editing ? t('form.appliance.edit') : t('form.appliance.new'),
    )}</div>`;

    const mergeAsset = (value: Record<string, unknown>): void => {
      this._assetEdit.asset = { ...this._assetEdit.asset, ...value } as Partial<Asset>;
      this._assetEdit.error = undefined;
    };

    // Identity (kind toggle re-renders since the schema changes).
    const identity = this._makeForm(
      this._assetIdentitySchema(x, editing),
      {
        kind: x.kind ?? 'virtual',
        device_id: x.device_id ?? undefined,
        name: x.name ?? '',
        manufacturer: x.manufacturer ?? '',
        model: x.model ?? '',
        serial_number: x.serial_number ?? '',
        icon: x.icon ?? '',
        parent_asset_id: x.parent_asset_id ?? undefined,
        area_id: x.area_id ?? undefined,
      },
      (value) => {
        const prevKind = this._assetEdit.asset?.kind;
        mergeAsset(value);
        if (!editing && value.kind !== prevKind) this._render();
      },
    );
    inner.appendChild(identity);

    inner.appendChild(this._section(t('section.ownership')));
    inner.appendChild(
      this._makeForm(
        this._ownershipSchema(),
        {
          purchase_date: x.purchase_date ?? '',
          install_date: x.install_date ?? '',
          warranty_expiry: x.warranty_expiry ?? '',
          warranty_provider: x.warranty_provider ?? '',
          cost: x.cost ?? undefined,
          vendor: x.vendor ?? '',
        },
        mergeAsset,
      ),
    );

    this._renderPartsEditor(inner);

    inner.appendChild(this._section(t('section.related')));
    inner.appendChild(
      this._makeForm(
        [{ name: 'related_device_ids', selector: selDevice(true) }],
        { related_device_ids: x.related_device_ids ?? [] },
        mergeAsset,
      ),
    );

    inner.appendChild(this._section(t('section.reference')));
    inner.appendChild(
      this._makeForm(
        this._referenceSchema(),
        { manual_url: x.manual_url ?? '', notes: x.notes ?? '' },
        mergeAsset,
      ),
    );

    if (this._assetEdit.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = this._assetEdit.error;
      inner.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'hk-form-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.id = 'a-save';
    save.textContent = editing ? t('btn.save') : t('btn.create');
    save.addEventListener('click', () => void this._submitAssetForm());
    const cancel = document.createElement('ha-button');
    cancel.id = 'a-cancel';
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeAssetForm());
    actions.append(save, cancel);
    inner.appendChild(actions);

    card.appendChild(inner);
    host.appendChild(card);
  }

  private _renderPartsEditor(inner: HTMLElement): void {
    inner.appendChild(this._section(t('section.parts')));
    const parts = this._assetEdit.asset?.parts || [];
    parts.forEach((p, i) => {
      const box = document.createElement('div');
      box.className = 'hk-part';
      box.dataset.idx = String(i);
      const head = document.createElement('div');
      head.className = 'hk-part-head';
      head.innerHTML = `<span class="label">${escapeHTML(t('section.part_n', { n: i + 1 }))}</span>`;
      const del = document.createElement('ha-icon-button');
      del.className = 'part-del';
      del.setAttribute('label', t('btn.removePart'));
      del.addEventListener('click', () => {
        const list = this._assetEdit.asset?.parts || [];
        this._assetEdit.asset!.parts = list.filter((_, j) => j !== i);
        this._render();
      });
      head.appendChild(del);
      box.appendChild(head);

      const form = this._makeForm(
        this._partSchema(p),
        {
          part_name: p.name ?? '',
          part_number: p.part_number ?? '',
          type: p.type ?? 'consumable',
          vendor: p.vendor ?? '',
          cost: p.cost ?? undefined,
          replace_interval: p.replace_interval ?? undefined,
          replace_unit: p.replace_unit ?? 'months',
        },
        (value) => {
          const prevType = this._assetEdit.asset?.parts?.[i]?.type;
          const updated: Part = {
            id: p.id,
            last_replaced: p.last_replaced ?? null,
            name: String(value.part_name ?? ''),
            part_number: String(value.part_number ?? ''),
            type: (value.type as Part['type']) ?? 'consumable',
            vendor: String(value.vendor ?? ''),
            cost: value.cost != null && value.cost !== '' ? Number(value.cost) : null,
            replace_interval:
              value.type === 'wear' && value.replace_interval
                ? Number(value.replace_interval)
                : null,
            replace_unit:
              value.type === 'wear' && value.replace_interval
                ? (value.replace_unit as Part['replace_unit'])
                : null,
          };
          const list = [...(this._assetEdit.asset?.parts || [])];
          list[i] = updated;
          this._assetEdit.asset!.parts = list;
          if (value.type !== prevType) this._render();
        },
      );
      box.appendChild(form);

      if (p.last_replaced) {
        const note = document.createElement('div');
        note.className = 'hk-meta';
        note.textContent = t('part.lastReplaced', { date: p.last_replaced });
        box.appendChild(note);
      } else if (p.type === 'wear') {
        const note = document.createElement('div');
        note.className = 'hk-meta';
        note.textContent = t('part.wearHint');
        box.appendChild(note);
      }
      inner.appendChild(box);
    });

    const add = document.createElement('ha-button');
    add.id = 'a-add-part';
    add.textContent = t('btn.addPart');
    add.addEventListener('click', () => {
      const list = [...(this._assetEdit.asset?.parts || [])];
      list.push({ name: '', type: 'consumable' });
      this._assetEdit.asset!.parts = list;
      this._render();
    });
    inner.appendChild(add);
  }

  private _section(title: string): HTMLElement {
    const el = document.createElement('div');
    el.className = 'hk-section';
    el.textContent = title;
    return el;
  }

  private _wireTaskCards(root: ShadowRoot): void {
    const byId = (id?: string): Task | undefined => this._tasks.find((t) => t.id === id);
    root.querySelectorAll<HTMLElement>('.done-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id);
        if (t) void this._complete(t);
      }),
    );
    root.querySelectorAll<HTMLElement>('.edit-btn').forEach((b) => {
      this._setIcon(b, 'M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z');
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id);
        if (t) this._openEdit(t);
      });
    });
    root.querySelectorAll<HTMLElement>('.del-btn').forEach((b) => {
      this._setIcon(b, 'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z');
      b.addEventListener('click', () => {
        const t = byId(b.dataset.id);
        if (t) void this._delete(t);
      });
    });
  }

  private _wireAssetCards(root: ShadowRoot): void {
    const byId = (id?: string): Asset | undefined => this._assets.find((x) => x.id === id);
    root.querySelectorAll<HTMLElement>('.asset-edit-btn').forEach((b) => {
      this._setIcon(b, 'M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z');
      b.addEventListener('click', () => {
        const x = byId(b.dataset.id);
        if (x) this._openEditAsset(x);
      });
    });
    root.querySelectorAll<HTMLElement>('.asset-del-btn').forEach((b) => {
      this._setIcon(b, 'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z');
      b.addEventListener('click', () => {
        const x = byId(b.dataset.id);
        if (x) void this._deleteAsset(x);
      });
    });
  }

  /** Give an ha-icon-button its mdi icon via the native `path` property. */
  private _setIcon(button: HTMLElement, path: string): void {
    (button as HTMLElement & { path?: string }).path = path;
  }
}
