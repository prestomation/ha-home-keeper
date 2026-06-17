import * as api from './api';
import {
  filterTasks,
  groupTasks,
  sortTasks,
  type CardFilter,
  type CardGroupBy,
  type CardSort,
  type Group,
  type HomeKeeperCardConfig,
} from './card-filter';
import {
  buildTaskPayload,
  selArea,
  selBool,
  selDevice,
  selNumber,
  selSelect,
  selText,
  taskFormData,
  taskSchema,
  type FormField,
  type HaFormElement,
} from './forms';
import { setLanguage, t, tn } from './i18n';
import type { Hass, Task } from './types';
import {
  areaName,
  deviceName,
  dueLabel,
  escapeHTML,
  isOverdue,
  recurrenceSummary,
} from './utils';

// mdi:check-circle-outline — the trailing "mark done" action on each row.
const MDI_CHECK =
  'M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,' +
  '20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,' +
  '20 12,20M16.59,7.58L10,14.17L7.41,11.59L6,13L10,17L18,9L16.59,7.58Z';
// mdi:plus — the header "add task" action.
const MDI_PLUS = 'M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z';

// HA registers many of its components lazily. On a cold dashboard load they may
// not be defined yet, so we wait (best-effort) before the first paint — exactly
// as the panel does — to avoid flashing un-upgraded custom elements.
const REQUIRED_COMPONENTS = [
  'ha-card',
  'ha-form',
  'ha-button',
  'ha-icon-button',
  'ha-assist-chip',
  'ha-alert',
  'ha-spinner',
  'ha-icon',
];

/**
 * English-only strings for the card's *editor* and the "add card" picker. The
 * card's runtime list reuses the panel's translated keys via `t()`; the config
 * UI (admin-facing) stays in English so we don't ship machine translations into
 * the shared, parity-checked locale tables.
 */
const S: Record<string, string> = {
  name: 'Home Keeper Tasks',
  description: 'A resizable list of Home Keeper maintenance tasks with one-tap completion.',
  defaultTitle: 'Tasks',
  empty: 'No tasks yet.',
  loadError: "Couldn't load tasks. Is the Home Keeper integration set up?",
  // editor field labels (keyed by config field name for computeLabel)
  title: 'Title',
  filter: 'Filter',
  sort: 'Sort by',
  group_by: 'Group by',
  areas: 'Limit to areas',
  devices: 'Limit to devices',
  recurrence_types: 'Limit to recurrence types',
  horizon_days: 'Show tasks due within (days, 0 = no limit)',
  max_items: 'Max tasks shown (0 = unlimited)',
  show_add: 'Show add button',
  show_notes: 'Show notes',
  show_area: 'Show area / device',
  hide_managed: 'Hide integration-managed tasks',
  show_disabled: 'Include disabled tasks',
  confirm_complete: 'Confirm before completing',
};

const FILTER_OPTS: { value: CardFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'overdue', label: 'Overdue' },
  { value: 'today', label: 'Due by today (incl. overdue)' },
  { value: 'soon', label: 'Due soon' },
  { value: 'no_due', label: 'No due date' },
];
const SORT_OPTS: { value: CardSort; label: string }[] = [
  { value: 'due', label: 'Next due' },
  { value: 'name', label: 'Name' },
  { value: 'recent', label: 'Recently completed' },
  { value: 'area', label: 'Area' },
];
const GROUP_OPTS: { value: CardGroupBy; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'status', label: 'Status' },
  { value: 'area', label: 'Area' },
  { value: 'device', label: 'Device' },
];
const RECURRENCE_OPTS = [
  { value: 'floating', label: 'Floating' },
  { value: 'fixed', label: 'Fixed' },
  { value: 'triggered', label: 'Triggered (monitored)' },
];

const STYLES = `
  :host { display: block; height: 100%; }
  ha-card {
    height: 100%; display: flex; flex-direction: column; overflow: hidden;
  }
  .hk-head {
    display: flex; align-items: center; gap: 8px;
    padding: 12px 16px 8px; flex: none;
  }
  .hk-title { font-size: 1.25rem; font-weight: 400; flex: 1; min-width: 0; }
  .hk-body { flex: 1; min-height: 0; overflow: auto; padding: 0 8px 8px; }
  .hk-row {
    display: flex; align-items: center; gap: 8px; padding: 8px 8px;
    border-bottom: 1px solid var(--divider-color);
  }
  .hk-row:last-child { border-bottom: none; }
  .hk-row .grow { flex: 1; min-width: 0; cursor: pointer; }
  .hk-row.overdue { box-shadow: inset 3px 0 0 0 var(--error-color); }
  .hk-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  }
  .hk-meta {
    color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px;
    overflow: hidden; text-overflow: ellipsis;
  }
  .hk-notes { color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px; }
  .hk-chips { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
  ha-assist-chip.hk-overdue {
    --ha-assist-chip-container-color: var(--error-color);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --ha-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --md-assist-chip-outline-color: transparent;
  }
  /* Managed-by: a compact circular icon badge (the integration's own icon),
     centered, with the full "Managed by X" as a tooltip. */
  .hk-managed {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; border-radius: 50%; flex: none;
    background: var(--info-color, #039BE5); color: #fff;
    --mdc-icon-size: 18px;
  }
  ha-icon-button.hk-done { color: var(--primary-color); flex: none; }
  .hk-loading { display: flex; justify-content: center; padding: 32px 0; }
  .hk-empty { padding: 16px; }
  .hk-more {
    text-align: center; color: var(--secondary-text-color);
    font-size: 0.85rem; padding: 8px;
  }
  details.hk-group { margin: 4px 0; }
  details.hk-group > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center;
    gap: 8px; padding: 8px; user-select: none;
  }
  details.hk-group > summary::-webkit-details-marker { display: none; }
  details.hk-group > summary::before {
    content: ''; width: 0; height: 0; flex: none;
    border-left: 5px solid var(--secondary-text-color);
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    transition: transform 0.15s ease;
  }
  details.hk-group[open] > summary::before { transform: rotate(90deg); }
  .hk-group-title { font-weight: 600; font-size: 0.95rem; flex: 1; }
  .hk-group-count {
    font-size: 0.8rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 999px; padding: 1px 8px;
  }
  .hk-form { padding: 8px 16px 16px; border-bottom: 1px solid var(--divider-color); }
  .hk-form-title { font-size: 1.05rem; font-weight: 500; margin-bottom: 8px; }
  .hk-form-actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
  .hk-form-actions .spacer { flex: 1; }
`;

interface EditState {
  open: boolean;
  task: Partial<Task> | null;
  error?: string;
}

export class HomeKeeperCard extends HTMLElement {
  private _hass?: Hass;
  private _config: HomeKeeperCardConfig = { type: '' };
  private _tasks: Task[] = [];
  private _loaded = false;
  // Set when the last load failed (e.g. integration not set up); rendered as an
  // error instead of an endless spinner. Cleared on the next successful load.
  private _error = false;
  private _signal = '';
  // Task ids with a completion request in flight, so a double-tap of Done can't
  // record two completions.
  private _completing = new Set<string>();
  private _edit: EditState = { open: false, task: null };
  private _collapsed = new Set<string>();
  private _liveHassEls: Array<{ hass?: Hass }> = [];
  private _unsub?: () => void;
  private _subscribing = false;
  private _refreshing = false;
  private _booted = false;
  // The websocket connection our event subscription is bound to, so we can
  // re-subscribe if HA hands us a fresh connection after a reconnect.
  private _subConn?: Hass['connection'];

  // ── Lovelace lifecycle ──────────────────────────────────────────────────────
  static getConfigElement(): HTMLElement {
    return document.createElement('home-keeper-card-editor');
  }

  static getStubConfig(): HomeKeeperCardConfig {
    return { type: 'custom:home-keeper-card', filter: 'all', sort: 'due', group_by: 'none' };
  }

  setConfig(config: HomeKeeperCardConfig): void {
    if (!config || typeof config !== 'object') {
      throw new Error('Invalid Home Keeper card configuration');
    }
    this._config = { ...config };
    if (this._loaded) this._render();
  }

  /** Estimated height in masonry/legacy views (≈ one unit per visible row). */
  getCardSize(): number {
    const n = this._loaded ? this._visibleCount() : 3;
    return Math.max(3, Math.min(n + 1, 12));
  }

  /** Make the card freely resizable in sections view (content scrolls). */
  getGridOptions(): Record<string, unknown> {
    return { columns: 12, rows: 4, min_columns: 6, min_rows: 2 };
  }

  set hass(hass: Hass) {
    const first = !this._hass;
    setLanguage(hass.language);
    this._hass = hass;
    for (const el of this._liveHassEls) el.hass = hass;
    // (Re)subscribe — picks up a fresh connection after a websocket reconnect.
    void this._subscribe();
    if (first) {
      if (this._booted) void this._refresh();
      else void this._boot();
      return;
    }
    // Refresh when any Home Keeper entity changes (completion, add/edit/delete
    // from any surface) — cheap signal over the relevant states.
    const sig = this._stateSignal(hass);
    if (sig !== this._signal) {
      this._signal = sig;
      if (this._loaded) void this._refresh();
    }
  }
  get hass(): Hass | undefined {
    return this._hass;
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    void this._subscribe();
    void this._boot();
  }

  disconnectedCallback(): void {
    if (this._unsub) {
      this._unsub();
      this._unsub = undefined;
      this._subConn = undefined;
    }
  }

  /** One-time first paint: wait for lazy HA components, then render + load. */
  private async _boot(): Promise<void> {
    if (this._booted) return;
    this._booted = true;
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    await Promise.all(
      REQUIRED_COMPONENTS.map((n) =>
        Promise.race([customElements.whenDefined(n), new Promise((r) => setTimeout(r, 2000))]),
      ),
    );
    this._render();
    if (this._hass && !this._loaded) await this._refresh();
  }

  /**
   * Cheap fingerprint that drives live updates. The integration's two singleton
   * `CoordinatorEntity`s — `todo.home_keeper_tasks` and
   * `calendar.home_keeper_upcoming_tasks` — re-write their state (bumping
   * `last_updated`) on every coordinator refresh, which fires on any task
   * mutation (complete/add/edit/delete/trigger). Watching every Home
   * Keeper-named entity's count + newest stamp therefore changes whenever the
   * task set does; completions also arrive instantly via the event subscription.
   */
  private _stateSignal(hass: Hass): string {
    const states = hass.states;
    if (!states) return '';
    let n = 0;
    let max = 0;
    for (const id in states) {
      if (!id.includes('home_keeper')) continue;
      n++;
      const ts = Date.parse(states[id].last_updated);
      if (ts > max) max = ts;
    }
    return `${n}:${max}`;
  }

  /** Subscribe to the task-completed event for instant cross-surface updates. */
  private async _subscribe(): Promise<void> {
    const conn = this._hass?.connection;
    if (!conn) return;
    // Drop a stale subscription if HA reconnected with a new connection object.
    if (this._unsub && this._subConn && this._subConn !== conn) {
      this._unsub();
      this._unsub = undefined;
    }
    if (this._unsub || this._subscribing) return;
    this._subscribing = true;
    try {
      this._unsub = await conn.subscribeEvents(() => void this._refresh(), 'home_keeper_task_completed');
      this._subConn = conn;
    } catch {
      // Subscription unavailable — the state-signal path still keeps us current.
    } finally {
      this._subscribing = false;
    }
  }

  private async _refresh(): Promise<void> {
    if (!this._hass || this._refreshing) return;
    this._refreshing = true;
    try {
      this._tasks = await api.getTasks(this._hass);
      this._error = false;
      this._signal = this._stateSignal(this._hass);
    } catch (err) {
      // Surface an error rather than spinning forever. We still mark the card
      // "loaded" so the live-refresh path keeps retrying on the next state
      // change (e.g. once the integration finishes setting up).
      this._error = true;
      // eslint-disable-next-line no-console
      console.error('home-keeper-card: failed to load tasks', err);
    } finally {
      this._loaded = true;
      this._refreshing = false;
    }
    this._render();
  }

  // ── data shaping ──────────────────────────────────────────────────────────
  /** The filtered+sorted task list (pre-grouping, pre-truncation). */
  private _shaped(now = Date.now()): Task[] {
    const devices = this._hass?.devices;
    const filtered = filterTasks(this._tasks, this._config, devices, now);
    return sortTasks(filtered, this._config.sort ?? 'due', this._hass?.areas, devices);
  }

  private _visibleCount(): number {
    const shaped = this._shaped();
    const max = Math.max(0, Number(this._config.max_items) || 0);
    return max > 0 ? Math.min(shaped.length, max) : shaped.length;
  }

  // ── completion / CRUD ───────────────────────────────────────────────────────
  private async _complete(task: Task): Promise<void> {
    // Ignore a re-entrant tap while this task's completion is already in flight,
    // so a double-click doesn't record two completions.
    if (!this._hass || this._completing.has(task.id)) return;
    const prompt = task.managed_by?.completion_prompt;
    if (this._config.confirm_complete || prompt) {
      const msg = prompt || t('btn.done') + ' — ' + task.name + '?';
      if (!window.confirm(msg)) return;
    }
    this._completing.add(task.id);
    try {
      await api.completeTask(this._hass, task.id);
    } catch (err) {
      console.error('home-keeper-card: complete failed', err);
    } finally {
      this._completing.delete(task.id);
    }
    await this._refresh();
  }

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
    const payload = buildTaskPayload(task);
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

  private async _delete(task: Task): Promise<void> {
    if (!this._hass) return;
    if (!window.confirm(`${t('btn.delete')} — ${task.name}?`)) return;
    try {
      await api.deleteTask(this._hass, task.id);
      this._closeForm();
    } catch (err) {
      this._edit.error = String((err as { message?: string })?.message || err);
      this._render();
      return;
    }
    await this._refresh();
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _render(): void {
    if (!this.shadowRoot) return;
    this._liveHassEls = [];
    const title = this._config.title ?? S.defaultTitle;
    const showAdd = this._config.show_add !== false;

    let body: string;
    if (!this._loaded) {
      body = `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`;
    } else if (this._error) {
      body = `<div class="hk-empty"><ha-alert alert-type="error">${escapeHTML(S.loadError)}</ha-alert></div>`;
    } else {
      body = this._listHtml();
    }

    const header =
      title || showAdd
        ? `<div class="hk-head">
             <div class="hk-title">${escapeHTML(title)}</div>
             ${showAdd ? `<ha-icon-button id="hk-add" label="${escapeHTML(t('btn.addTask'))}"></ha-icon-button>` : ''}
           </div>`
        : '';

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <ha-card>
        ${header}
        <div id="hk-form-host"></div>
        <div class="hk-body">${body}</div>
      </ha-card>`;
    this._hydrate();
  }

  private _listHtml(): string {
    const now = Date.now();
    const shaped = this._shaped(now);
    if (!shaped.length) {
      const empty = this._tasks.length ? t('tasks.noMatch') : S.empty;
      return `<div class="hk-empty"><ha-alert alert-type="info">${escapeHTML(empty)}</ha-alert></div>`;
    }
    const max = Math.max(0, Number(this._config.max_items) || 0);
    const visible = max > 0 ? shaped.slice(0, max) : shaped;
    const hidden = shaped.length - visible.length;

    const groups = groupTasks(
      visible,
      this._config.group_by ?? 'none',
      this._hass?.areas,
      this._hass?.devices,
      now,
    );
    const list = this._renderGroups(groups);
    const more = hidden > 0 ? `<div class="hk-more">${escapeHTML(`+${hidden} more`)}</div>` : '';
    return `${list}${more}`;
  }

  private _renderGroups(groups: Group[]): string {
    if (groups.length === 1 && !groups[0].label) {
      return groups[0].items.map((task) => this._row(task)).join('');
    }
    return groups
      .map((g) => {
        const open = this._collapsed.has(g.key) ? '' : 'open';
        return `
          <details class="hk-group" data-group-key="${escapeHTML(g.key)}" ${open}>
            <summary>
              <span class="hk-group-title">${escapeHTML(g.label)}</span>
              <span class="hk-group-count">${g.items.length}</span>
            </summary>
            <div>${g.items.map((task) => this._row(task)).join('')}</div>
          </details>`;
      })
      .join('');
  }

  private _row(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task))}"></ha-assist-chip>`;
    // Managed-by reads as a compact icon-only chip (the integration's own icon,
    // else a generic one) with the full "Managed by X" as a hover/long-press
    // tooltip — keeps the row tight instead of a full-width pill.
    const mb = task.managed_by;
    let managedChip = '';
    if (mb) {
      const tip = escapeHTML(t('chip.managed', { name: mb.display_name }));
      const icon = escapeHTML(mb.icon || 'mdi:puzzle');
      managedChip = `<span class="hk-managed" title="${tip}" role="img" aria-label="${tip}"><ha-icon icon="${icon}"></ha-icon></span>`;
    }
    let areaChip = '';
    if (this._config.show_area !== false) {
      const area = areaName(this._hass?.areas, task.area_id);
      const dev = task.device_id ? deviceName(this._hass?.devices, task.device_id) : '';
      const label = area || dev;
      if (label) areaChip = `<ha-assist-chip label="${escapeHTML(label)}"></ha-assist-chip>`;
    }
    const n = task.completions?.length ?? 0;
    const meta = `${escapeHTML(recurrenceSummary(task))}${n ? ` · ${escapeHTML(tn('history.count', n))}` : ''}`;
    const notes =
      this._config.show_notes && task.notes
        ? `<div class="hk-notes">${escapeHTML(task.notes)}</div>`
        : '';
    // A dormant triggered task has nothing to complete — its owner arms it.
    const dormant = task.recurrence_type === 'triggered' && !task.next_due;
    const done = dormant
      ? ''
      : `<ha-icon-button class="hk-done" data-id="${escapeHTML(task.id)}" label="${escapeHTML(t('btn.done'))}"></ha-icon-button>`;
    return `
      <div class="hk-row${overdue ? ' overdue' : ''}">
        <div class="grow" data-edit-id="${escapeHTML(task.id)}" role="button" tabindex="0">
          <div class="hk-name">${escapeHTML(task.name)}</div>
          <div class="hk-meta">${meta}</div>
          ${notes}
          <div class="hk-chips">${statusChip}${areaChip}${managedChip}</div>
        </div>
        ${done}
      </div>`;
  }

  // ── hydration ─────────────────────────────────────────────────────────────
  private _hydrate(): void {
    const root = this.shadowRoot;
    if (!root) return;

    const add = root.getElementById('hk-add');
    if (add) {
      (add as HTMLElement & { path?: string }).path = MDI_PLUS;
      add.addEventListener('click', () => this._openCreate());
    }

    const host = root.getElementById('hk-form-host');
    if (host && this._edit.open) this._renderForm(host);

    root.querySelectorAll<HTMLElement>('.hk-done').forEach((b) => {
      (b as HTMLElement & { path?: string }).path = MDI_CHECK;
      b.addEventListener('click', (e) => {
        e.stopPropagation();
        const task = this._tasks.find((x) => x.id === b.dataset.id);
        if (task) void this._complete(task);
      });
    });

    root.querySelectorAll<HTMLElement>('[data-edit-id]').forEach((el) => {
      const open = (): void => {
        const task = this._tasks.find((x) => x.id === el.dataset.editId);
        if (task) this._openEdit(task);
      };
      el.addEventListener('click', open);
      el.addEventListener('keydown', (e) => {
        const key = (e as KeyboardEvent).key;
        if (key === 'Enter' || key === ' ') {
          e.preventDefault();
          open();
        }
      });
    });

    root.querySelectorAll<HTMLDetailsElement>('details.hk-group').forEach((d) =>
      d.addEventListener('toggle', () => {
        const key = d.dataset.groupKey || '';
        if (d.open) this._collapsed.delete(key);
        else this._collapsed.add(key);
      }),
    );
  }

  private _renderForm(host: HTMLElement): void {
    const task = this._edit.task || {};
    const wrap = document.createElement('div');
    wrap.className = 'hk-form';
    wrap.innerHTML = `<div class="hk-form-title">${escapeHTML(
      task.id ? t('form.task.edit') : t('form.task.new'),
    )}</div>`;

    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = taskSchema(task) as unknown[];
    form.data = taskFormData(task);
    form.computeLabel = (s: { name: string }): string => (s.name ? t('field.' + s.name) : '');
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      const prevType = this._edit.task?.recurrence_type;
      this._edit.task = {
        ...this._edit.task,
        ...value,
        interval: Number(value.interval) || 1,
      } as Partial<Task>;
      this._edit.error = undefined;
      if (value.recurrence_type !== prevType) this._render();
    });
    this._liveHassEls.push(form);
    wrap.appendChild(form);

    if (this._edit.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = this._edit.error;
      wrap.appendChild(err);
    }

    const actions = document.createElement('div');
    actions.className = 'hk-form-actions';
    const save = document.createElement('ha-button');
    save.setAttribute('raised', '');
    save.textContent = task.id ? t('btn.save') : t('btn.create');
    save.addEventListener('click', () => void this._submitForm());
    const cancel = document.createElement('ha-button');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeForm());
    actions.append(save, cancel);
    // Editing a non-derived task offers Delete (derived/managed tasks are owned
    // elsewhere — manage them where they're created).
    const existing = task.id ? this._tasks.find((x) => x.id === task.id) : undefined;
    const deletable = existing && !existing.source?.part && !existing.managed_by?.deletion_protected;
    if (deletable) {
      const spacer = document.createElement('span');
      spacer.className = 'spacer';
      const del = document.createElement('ha-button');
      del.textContent = t('btn.delete');
      del.addEventListener('click', () => void this._delete(existing as Task));
      actions.append(spacer, del);
    }
    wrap.appendChild(actions);
    host.appendChild(wrap);
  }
}

/** GUI editor for the card configuration. Built from a single `ha-form`. */
export class HomeKeeperCardEditor extends HTMLElement {
  private _hass?: Hass;
  private _config: HomeKeeperCardConfig = { type: '' };
  private _form?: HaFormElement;

  setConfig(config: HomeKeeperCardConfig): void {
    this._config = { ...config };
    this._update();
  }

  set hass(hass: Hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this._render();
  }

  private _schema(): FormField[] {
    return [
      { name: 'title', selector: selText() },
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'filter', selector: selSelect(FILTER_OPTS) },
          { name: 'sort', selector: selSelect(SORT_OPTS) },
          { name: 'group_by', selector: selSelect(GROUP_OPTS) },
        ],
      },
      { name: 'areas', selector: selArea(true) },
      { name: 'devices', selector: selDevice(true) },
      { name: 'recurrence_types', selector: selSelect(RECURRENCE_OPTS, true) },
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'horizon_days', selector: selNumber(0) },
          { name: 'max_items', selector: selNumber(0) },
        ],
      },
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'show_add', selector: selBool() },
          { name: 'show_notes', selector: selBool() },
          { name: 'show_area', selector: selBool() },
          { name: 'hide_managed', selector: selBool() },
          { name: 'show_disabled', selector: selBool() },
          { name: 'confirm_complete', selector: selBool() },
        ],
      },
    ];
  }

  private _render(): void {
    if (!this.shadowRoot) return;
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = this._schema() as unknown[];
    form.data = this._config as unknown as Record<string, unknown>;
    form.computeLabel = (s: { name: string }): string => S[s.name] ?? s.name;
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      this._config = { ...this._config, ...value } as HomeKeeperCardConfig;
      this.dispatchEvent(
        new CustomEvent('config-changed', {
          detail: { config: this._config },
          bubbles: true,
          composed: true,
        }),
      );
    });
    this._form = form;
    this.shadowRoot.innerHTML = '';
    this.shadowRoot.appendChild(form);
  }

  private _update(): void {
    if (this._form) this._form.data = this._config as unknown as Record<string, unknown>;
  }
}

/** Card metadata for the dashboard "Add card" picker. */
export const CARD_NAME = S.name;
export const CARD_DESCRIPTION = S.description;
