import * as api from './api';
import {
  filterTasks,
  groupTasks,
  profileMatches,
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
  selLabel,
  selNumber,
  selSelect,
  selText,
  taskFormData,
  taskSchema,
  type FormField,
  type HaFormElement,
} from './forms';
import { documentLabel, isDisplayableDocument } from './documents';
import { setLanguage, t, tn } from './i18n';
import type { Asset, Hass, HassLabel, Profile, Task } from './types';
import {
  areaName,
  deviceName,
  dueLabel,
  escapeHTML,
  isOverdue,
  labelName,
  recurrenceSummary,
} from './utils';

// mdi:check-circle-outline — the trailing "mark done" action on each row.
const MDI_CHECK =
  'M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,' +
  '20C7.59,20 4,16.41 4,12C4,7.59 7.59,4 12,4C16.41,4 20,7.59 20,12C20,16.41 16.41,' +
  '20 12,20M16.59,7.58L10,14.17L7.41,11.59L6,13L10,17L18,9L16.59,7.58Z';
// mdi:plus — the header "add task" action.
const MDI_PLUS = 'M19,13H13V19H11V13H5V11H11V5H13V11H19V13Z';
// `ha-icon` names for the per-task document chips (external link / metadata link vs
// an uploaded file). These are icon attributes, not SVG paths like the buttons above.
const MDI_OPEN_IN_NEW = 'mdi:open-in-new';
const MDI_FILE = 'mdi:file-document-outline';

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
  profile: 'Filter by profile (saved filter)',
  profileNone: 'None',
  filter: 'Filter',
  sort: 'Sort by',
  group_by: 'Group by',
  areas: 'Limit to areas',
  devices: 'Limit to devices',
  labels: 'Limit to labels',
  label_match: 'Label match',
  recurrence_types: 'Limit to recurrence types',
  horizon_days: 'Show tasks due within (days, 0 = no limit)',
  max_items: 'Max tasks shown (0 = unlimited)',
  show_add: 'Show add button',
  show_notes: 'Show notes',
  show_area: 'Show area / device',
  show_labels: 'Show labels',
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
const LABEL_MATCH_OPTS = [
  { value: 'any', label: 'Any selected label' },
  { value: 'all', label: 'All selected labels' },
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
  .hk-row .grow { flex: 1; min-width: 0; }
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
  /* Per-task document chips: a row of compact, clearly-tappable affordances that open
     the appliance's manual / file / other associated URL in a new tab. */
  .hk-docs { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
  .hk-doc {
    display: inline-flex; align-items: center; gap: 4px; min-width: 0;
    color: var(--primary-color); text-decoration: none; font-size: 0.85rem;
    --mdc-icon-size: 16px;
  }
  .hk-doc > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hk-doc:hover { text-decoration: underline; }
  /* Label chips read as a distinct, primary-tinted tag so they stand apart from
     the neutral status / area chips. */
  ha-assist-chip.hk-label {
    --ha-assist-chip-container-color: var(--primary-color);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --ha-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --md-assist-chip-outline-color: transparent;
  }
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
  /* A completion-blocked task's mark-done looks inert but stays tappable to explain. */
  ha-icon-button.hk-done.blocked { color: var(--disabled-text-color); }
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

/** A resolved "show on card" document chip — always a plain anchor. `url` is the
 *  stored link for a link/metadata document, or a pre-signed URL for an uploaded file
 *  (so the tap is native; see `_signDocuments`). `icon` is its `ha-icon` name. */
interface DocumentChip {
  name: string;
  url: string;
  icon: string;
}

export class HomeKeeperCard extends HTMLElement {
  private _hass?: Hass;
  private _config: HomeKeeperCardConfig = { type: '' };
  private _tasks: Task[] = [];
  private _profiles: Profile[] = [];
  // Appliance data, loaded only when a task references "show on card" links, so the
  // card can resolve those references to live document/metadata names + URLs.
  private _assets: Asset[] = [];
  // Short-lived signed URLs for pinned *file* documents, keyed `assetId:docId`, minted
  // at refresh so a file chip can be a plain <a href> (a native tap — the iOS app's
  // WKWebView blocks an async window.open). Re-signed before expiry; see _signDocuments.
  private _signedDocs = new Map<string, { url: string; signedAt: number }>();
  // HA label registry (id -> entry), fetched once so label chips can show real
  // names rather than raw ids. Empty until loaded; lookups fall back to the id.
  private _labels: Record<string, HassLabel> = {};
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
    await this._loadLabels();
    this._render();
    if (this._hass && !this._loaded) await this._refresh();
  }

  /** Fetch the HA label registry once (best-effort) so chips can show names. */
  private async _loadLabels(): Promise<void> {
    if (!this._hass || Object.keys(this._labels).length) return;
    try {
      this._labels = await api.getLabels(this._hass);
    } catch {
      // Registry unavailable — chips fall back to the raw label id.
    }
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
      // Profiles are only needed when the card filters by one; fetch best-effort.
      if (this._config.profile) {
        this._profiles = await api.getProfiles(this._hass).catch(() => [] as Profile[]);
      }
      // Appliance data is only needed to resolve per-task "show on card" links; fetch
      // best-effort and only when a task actually references one.
      this._assets = this._tasks.some((tk) => tk.card_links?.length)
        ? await api.getAssets(this._hass).catch(() => [] as Asset[])
        : [];
      // Pre-sign any pinned file documents so their chips render as plain anchors.
      await this._signDocuments();
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
    const areas = this._hass?.areas;
    // A configured profile defines the task set; otherwise use the card's own filters.
    const profile = this._config.profile
      ? this._profiles.find(
          (p) => p.id === this._config.profile || p.name === this._config.profile,
        )
      : undefined;
    const filtered = profile
      ? this._tasks.filter((t) => profileMatches(t, profile.filter, devices, areas, now))
      : filterTasks(this._tasks, this._config, devices, now, areas);
    return sortTasks(filtered, this._config.sort ?? 'due', areas, devices);
  }

  private _visibleCount(): number {
    const shaped = this._shaped();
    const max = Math.max(0, Number(this._config.max_items) || 0);
    return max > 0 ? Math.min(shaped.length, max) : shaped.length;
  }

  // ── completion / CRUD ───────────────────────────────────────────────────────
  /** Surface a transient message via HA's toast notification. */
  private _toast(message: string): void {
    this.dispatchEvent(
      new CustomEvent('hass-notification', {
        detail: { message },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Navigate to the sidebar panel's detail page for a task (HA SPA navigation). */
  private _navigateToPanel(taskId: string): void {
    history.pushState(null, '', `/home-keeper/tasks/${encodeURIComponent(taskId)}`);
    window.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** A completion-blocked task (e.g. a synced problem sensor) can't be marked done
   *  here — its owning integration clears it. Explain why instead of completing. */
  private _notifyBlocked(task: Task): void {
    this._toast(task.managed_by?.completion_prompt || t('done.blocked'));
  }

  private async _complete(task: Task): Promise<void> {
    // Ignore a re-entrant tap while this task's completion is already in flight,
    // so a double-click doesn't record two completions.
    if (!this._hass || this._completing.has(task.id)) return;
    // A task that *requires* completion detail can't be finished from the card's
    // quick mark-done (there's no dialog here) — send the user to the panel, where
    // the capture dialog lives. (Optional capture still quick-completes; details
    // can be added later by editing the completion in the panel.)
    if (task.completion_detail === 'required') {
      this._toast(t('done.needsDetails'));
      this._navigateToPanel(task.id);
      return;
    }
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
    // The card only *creates* tasks (the header "+" button). Editing and deleting
    // live in the sidebar panel, so there's no update/delete path here.
    try {
      await api.addTask(this._hass, buildTaskPayload(task));
      this._closeForm();
      await this._refresh();
    } catch (err) {
      this._edit.error = String((err as { message?: string })?.message || err);
      this._render();
    }
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

  /**
   * Pre-mint signed URLs for every pinned **file** document so its chip can be a plain
   * `<a href>` opened by a native tap. This sidesteps the iOS app's WKWebView, which
   * blocks a `window.open` issued after the async signing round-trip (links open fine
   * because they're native anchors with no async gap). Cached and only re-signed when
   * stale, so frequent dashboard refreshes don't spam the signing command; entries for
   * no-longer-referenced files are dropped. Best-effort — a failed sign just leaves that
   * chip out until the next refresh.
   */
  private async _signDocuments(): Promise<void> {
    if (!this._hass) return;
    // Re-sign comfortably before the backend's 1h TTL so an idle dashboard's hrefs
    // stay valid; a fresh cache entry is reused across refreshes until then.
    const RESIGN_AFTER_MS = 45 * 60 * 1000;
    const now = Date.now();
    const needed = new Map<string, { assetId: string; docId: string }>();
    for (const task of this._tasks) {
      for (const ref of task.card_links ?? []) {
        const doc = this._assets
          .find((a) => a.id === ref.asset_id)
          ?.documents?.find((d) => d.id === ref.entry_id);
        if (doc?.kind === 'file' && doc.filename) {
          needed.set(`${ref.asset_id}:${ref.entry_id}`, {
            assetId: ref.asset_id,
            docId: ref.entry_id,
          });
        }
      }
    }
    for (const key of [...this._signedDocs.keys()]) {
      if (!needed.has(key)) this._signedDocs.delete(key);
    }
    await Promise.all(
      [...needed].map(async ([key, { assetId, docId }]) => {
        const cached = this._signedDocs.get(key);
        if (cached && now - cached.signedAt < RESIGN_AFTER_MS) return;
        try {
          const url = await api.signDocumentUrl(this._hass!, assetId, docId);
          this._signedDocs.set(key, { url, signedAt: now });
        } catch {
          // Keep any prior URL; a failed sign just won't refresh it this round.
        }
      }),
    );
  }

  /**
   * Resolve a task's `card_links` references against the loaded appliance data into
   * renderable document chips, each a plain anchor. A **link** document / metadata link
   * uses its stored URL; an **uploaded file** uses the signed URL pre-minted by
   * `_signDocuments` (skipped until it's signed). References to deleted entries — or
   * link URLs that aren't plain http(s) — are silently dropped (defence-in-depth even
   * though the backend only stores http(s)).
   */
  private _resolveDocuments(task: Task): DocumentChip[] {
    const refs = task.card_links;
    if (!refs?.length || !this._assets.length) return [];
    const isHttp = (u: string): boolean => /^https?:\/\//i.test(u);
    const out: DocumentChip[] = [];
    for (const ref of refs) {
      const asset = this._assets.find((a) => a.id === ref.asset_id);
      if (!asset) continue;
      // Document ids and metadata ids never collide (both server-minted, distinctly
      // namespaced), so a document match is authoritative — resolve it and move on.
      const doc = asset.documents?.find((d) => d.id === ref.entry_id);
      if (doc) {
        if (!isDisplayableDocument(doc)) continue;
        if (doc.kind === 'file') {
          // Use the signed URL pre-minted at refresh; skip until it's available.
          const signed = this._signedDocs.get(`${ref.asset_id}:${ref.entry_id}`);
          if (signed) {
            out.push({ name: documentLabel(doc), url: signed.url, icon: MDI_FILE });
          }
        } else if (doc.url && isHttp(doc.url)) {
          out.push({ name: documentLabel(doc), url: doc.url, icon: MDI_OPEN_IN_NEW });
        }
        continue;
      }
      const meta = asset.metadata?.find(
        (m) => m.id === ref.entry_id && m.type === 'link' && m.value,
      );
      if (meta?.value && isHttp(meta.value)) {
        out.push({ name: meta.label, url: meta.value, icon: MDI_OPEN_IN_NEW });
      }
    }
    return out;
  }

  /** One document chip's HTML — always a plain anchor opened by a native tap (works in
   *  the iOS app's WKWebView; file URLs are pre-signed in `_signDocuments`). */
  private _documentChip(chip: DocumentChip): string {
    const name = escapeHTML(chip.name);
    return `<a class="hk-doc" href="${escapeHTML(chip.url)}" target="_blank" rel="noopener noreferrer" title="${name}"><ha-icon icon="${chip.icon}"></ha-icon><span>${name}</span></a>`;
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
    let labelChips = '';
    if (this._config.show_labels && task.labels?.length) {
      const labels = Object.keys(this._labels).length ? this._labels : this._hass?.labels;
      labelChips = task.labels
        .map(
          (id) =>
            `<ha-assist-chip class="hk-label" label="${escapeHTML(labelName(labels, id))}"></ha-assist-chip>`,
        )
        .join('');
    }
    const n = task.completions?.length ?? 0;
    const meta = `${escapeHTML(recurrenceSummary(task))}${n ? ` · ${escapeHTML(tn('history.count', n))}` : ''}`;
    const notes =
      this._config.show_notes && task.notes
        ? `<div class="hk-notes">${escapeHTML(task.notes)}</div>`
        : '';
    // Per-task "show on card" documents — links/metadata open in a new tab; uploaded
    // files open via a signed URL minted on click (see `_hydrate`).
    const docs = this._resolveDocuments(task);
    const docsHtml = docs.length
      ? `<div class="hk-docs">${docs.map((d) => this._documentChip(d)).join('')}</div>`
      : '';
    // A dormant triggered task has nothing to complete — its owner arms it; hide the
    // action. A completion-blocked task (a synced problem sensor) keeps a *disabled*
    // mark-done that, on tap, explains its source clears it.
    const dormant = task.recurrence_type === 'triggered' && !task.next_due;
    const blocked = Boolean(task.managed_by?.completion_blocked);
    const done = dormant
      ? ''
      : `<ha-icon-button class="hk-done${blocked ? ' blocked' : ''}" data-id="${escapeHTML(task.id)}" label="${escapeHTML(t('btn.done'))}"></ha-icon-button>`;
    return `
      <div class="hk-row${overdue ? ' overdue' : ''}">
        <div class="grow">
          <div class="hk-name">${escapeHTML(task.name)}</div>
          <div class="hk-meta">${meta}</div>
          ${notes}
          <div class="hk-chips">${statusChip}${areaChip}${labelChips}${managedChip}</div>
          ${docsHtml}
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
        if (!task) return;
        if (task.managed_by?.completion_blocked) this._notifyBlocked(task);
        else void this._complete(task);
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

  /** Render the card's *create* form (the header "+"). Editing/deleting lives in
   *  the sidebar panel, so this is always a new-task form. */
  private _renderForm(host: HTMLElement): void {
    const task = this._edit.task || {};
    const wrap = document.createElement('div');
    wrap.className = 'hk-form';
    wrap.innerHTML = `<div class="hk-form-title">${escapeHTML(t('form.task.new'))}</div>`;

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
    save.textContent = t('btn.create');
    save.addEventListener('click', () => void this._submitForm());
    const cancel = document.createElement('ha-button');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeForm());
    actions.append(save, cancel);
    wrap.appendChild(actions);
    host.appendChild(wrap);
  }
}

/** GUI editor for the card configuration. Built from a single `ha-form`. */
export class HomeKeeperCardEditor extends HTMLElement {
  private _hass?: Hass;
  private _config: HomeKeeperCardConfig = { type: '' };
  private _form?: HaFormElement;
  private _profiles: Profile[] = [];

  setConfig(config: HomeKeeperCardConfig): void {
    this._config = { ...config };
    this._update();
  }

  set hass(hass: Hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
    void this._maybeLoadProfiles();
  }

  private async _maybeLoadProfiles(): Promise<void> {
    if (!this._hass || this._profiles.length) return;
    this._profiles = await api.getProfiles(this._hass).catch(() => [] as Profile[]);
    if (this._profiles.length && this._form) this._form.schema = this._schema() as unknown[];
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this._render();
  }

  private _schema(): FormField[] {
    return [
      { name: 'title', selector: selText() },
      {
        name: 'profile',
        selector: selSelect([
          { value: '', label: S.profileNone },
          ...this._profiles.map((p) => ({ value: p.id, label: p.name })),
        ]),
      },
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
      { name: 'labels', selector: selLabel(true) },
      { name: 'label_match', selector: selSelect(LABEL_MATCH_OPTS) },
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
          { name: 'show_labels', selector: selBool() },
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
