import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import {
  buildTaskPayload,
  selArea,
  selBool,
  selDate,
  selDevice,
  selIcon,
  selNumber,
  selSelect,
  selText,
  settingsSchema,
  taskFormData,
  taskSchema,
  type FormField,
  type HaFormElement,
} from './forms';
import { selEntity } from './forms';
import { setLanguage, t, tn } from './i18n';
import type {
  Asset,
  AssetKind,
  Companion,
  Completion,
  Hass,
  HomeKeeperOptions,
  ManagedBy,
  MetadataEntry,
  MetadataType,
  PanelInfo,
  Part,
  Task,
} from './types';
import {
  areaName,
  assetSummary,
  brandLogoUrl,
  buildPath,
  completionStats,
  deviceDomain,
  deviceName,
  dueLabel,
  escapeHTML,
  isOverdue,
  parseRoute,
  recurrenceSummary,
  tasksForAsset,
  type PanelLocation,
} from './utils';

// mdi:devices — fallback icon when a device has no resolvable brand logo.
const MDI_DEVICES =
  'M3,6H21V4H3A2,2 0 0,0 1,6V18A2,2 0 0,0 3,20H7V18H3V6M13,12H9V13.78C8.39,' +
  '14.33 8,15.11 8,16C8,16.89 8.39,17.67 9,18.22V20H13V18.22C13.61,17.67 14,' +
  '16.88 14,16C14,15.11 13.61,14.33 13,13.78V12M11,17.5A1.5,1.5 0 0,1 9.5,16A1.5,' +
  '1.5 0 0,1 11,14.5A1.5,1.5 0 0,1 12.5,16A1.5,1.5 0 0,1 11,17.5M22,8H16A1,1 0 0,' +
  '0 15,9V19A1,1 0 0,0 16,20H22A1,1 0 0,0 23,19V9A1,1 0 0,0 22,8M21,18H17V10H21V18Z';

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
  'ha-svg-icon',
  // Companion rows render arbitrary mdi icons by name; ha-icon lazy-loads them.
  'ha-icon',
];

// mdi:delete — remove a single completion entry from the history dialog.
const MDI_DELETE =
  'M19,4H15.5L14.5,3H9.5L8.5,4H5V6H19M6,19A2,2 0 0,0 8,21H16A2,2 0 0,0 18,19V7H6V19Z';

// mdi:pencil — edit a single completion's metadata from the history list.
const MDI_EDIT =
  'M20.71,7.04C21.1,6.65 21.1,6 20.71,5.63L18.37,3.29C18,2.9 17.35,2.9 16.96,' +
  '3.29L15.12,5.12L18.87,8.87M3,17.25V21H6.75L17.81,9.93L14.06,6.18L3,17.25Z';

// mdi:autorenew — a wear item (replaced on a recurring schedule).
const MDI_WEAR =
  'M12,6V9L16,5L12,1V4A8,8 0 0,0 4,12C4,13.57 4.46,15.03 5.24,16.26L6.7,14.8C6.25,' +
  '13.97 6,13 6,12A6,6 0 0,1 12,6M18.76,7.74L17.3,9.2C17.74,10.04 18,11 18,12A6,6 0 0,' +
  '1 12,18V15L8,19L12,23V20A8,8 0 0,0 20,12C20,10.43 19.54,8.97 18.76,7.74Z';

// mdi:package-variant-closed — a consumable spare kept in stock.
const MDI_CONSUMABLE =
  'M21,16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,' +
  '22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V7.5C3,7.12 3.21,6.79 3.53,' +
  '6.62L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.79,' +
  '6.79 21,7.12 21,7.5V16.5M12,4.15L6.04,7.5L12,10.85L17.96,7.5L12,4.15M5,15.91L11,19.29V12.58L5,' +
  '9.21V15.91M19,15.91V9.21L13,12.58V19.29L19,15.91Z';


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
  /* A completion-blocked Done (e.g. a synced problem sensor): the inner ha-button is
     natively disabled (greyed), and the wrapping span stays clickable so a tap can
     explain why it can't be completed here. */
  .done-blocked-wrap { cursor: pointer; display: inline-flex; }
  .done-blocked-wrap ha-button { pointer-events: none; }
  ha-assist-chip.hk-overdue {
    --ha-assist-chip-container-color: var(--error-color);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --ha-assist-chip-label-text-color: var(--text-primary-color, #fff);
    --md-assist-chip-outline-color: transparent;
  }
  ha-assist-chip.hk-managed {
    --ha-assist-chip-container-color: var(--info-color, #039BE5);
    --md-assist-chip-label-text-color: #fff;
    --ha-assist-chip-label-text-color: #fff;
    --md-assist-chip-outline-color: transparent;
  }
  ha-assist-chip.hk-orphaned {
    --ha-assist-chip-container-color: var(--warning-color, #FF9800);
    --md-assist-chip-label-text-color: #fff;
    --ha-assist-chip-label-text-color: #fff;
    --md-assist-chip-outline-color: transparent;
  }
  .hk-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
  ha-assist-chip.hk-device-chip { cursor: pointer; }
  .hk-managed-prompt {
    font-size: 0.85rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 6px; padding: 8px 12px; margin-top: 8px;
  }
  .hk-managed-info {
    font-size: 0.8rem; color: var(--secondary-text-color);
    margin-top: 4px; font-style: italic; align-self: center;
  }
  .hk-dev-img {
    width: 18px; height: 18px; object-fit: contain; border-radius: 3px;
    --mdc-icon-size: 18px;
  }
  .hk-form-card { margin-bottom: 16px; }
  .hk-form-inner { padding: 16px; }
  .hk-form-title { font-size: 1.1rem; font-weight: 500; margin-bottom: 8px; }
  .hk-settings-intro {
    color: var(--secondary-text-color); font-size: 0.9rem;
    margin-bottom: 16px; line-height: 1.4;
  }
  #hk-settings ha-form { display: block; }
  /* Companions section (Settings tab). */
  .hk-companion-group {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em; margin: 20px 0 8px;
  }
  .hk-companion {
    display: flex; align-items: center; gap: 12px; padding: 12px 0;
    border-top: 1px solid var(--divider-color);
  }
  .hk-companion-ic { color: var(--state-icon-color, var(--primary-text-color)); flex: 0 0 auto; }
  .hk-companion-body { flex: 1 1 auto; min-width: 0; }
  .hk-companion-name { display: flex; align-items: center; gap: 8px; font-weight: 500; }
  .hk-companion-desc {
    color: var(--secondary-text-color); font-size: 0.9rem; line-height: 1.4; margin-top: 2px;
  }
  .hk-companion-actions { display: flex; align-items: center; gap: 4px; flex: 0 0 auto; flex-wrap: wrap; }
  ha-assist-chip.hk-comp-connected {
    --ha-assist-chip-container-color: var(--success-color, #43a047);
    --ha-assist-chip-filled-container-color: var(--success-color, #43a047);
    --md-assist-chip-label-text-color: var(--text-primary-color, #fff);
  }
  ha-assist-chip.hk-comp-suggested {
    --ha-assist-chip-container-color: var(--warning-color, #ffa600);
  }
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
  .hk-meta-seeds { display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 4px; }
  .hk-meta-seeds ha-button { --mdc-typography-button-font-size: 0.8rem; }

  /* Parts list on the appliance detail page */
  .hk-parts { display: flex; flex-direction: column; }
  .hk-part-row {
    display: flex; align-items: flex-start; gap: 14px; padding: 14px 0;
    border-bottom: 1px solid var(--divider-color);
  }
  .hk-part-row:first-child { padding-top: 2px; }
  .hk-part-row:last-child { border-bottom: none; padding-bottom: 2px; }
  .hk-part-ic {
    flex: none; width: 40px; height: 40px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    background: var(--secondary-background-color);
    color: var(--secondary-text-color); --mdc-icon-size: 22px;
  }
  .hk-part-row.wear .hk-part-ic {
    background: color-mix(in srgb, var(--primary-color) 16%, transparent);
    color: var(--primary-color);
  }
  .hk-part-row .grow { flex: 1; min-width: 0; }
  .hk-part-name {
    font-weight: 500; display: flex; align-items: center; gap: 8px;
    flex-wrap: wrap; word-break: break-word;
  }
  .hk-part-badge {
    font-size: 0.68rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.04em; color: var(--secondary-text-color);
    border: 1px solid var(--divider-color); border-radius: 10px; padding: 1px 8px;
  }
  .hk-part-row.wear .hk-part-badge {
    color: var(--primary-color);
    border-color: color-mix(in srgb, var(--primary-color) 50%, transparent);
  }
  .hk-part-sub {
    color: var(--secondary-text-color); font-size: 0.85rem; margin-top: 2px;
    word-break: break-word;
  }
  .hk-part-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
  .hk-part-chips ha-assist-chip { --ha-assist-chip-container-height: 28px; }
  .hk-form-actions { display: flex; gap: 8px; margin-top: 20px; }
  .hk-loading { display: flex; justify-content: center; padding: 48px 0; }
  .ver { color: var(--secondary-text-color); font-size: 0.7rem; text-align: right; margin-top: 16px; }
  .hk-card-row .grow.clickable { cursor: pointer; }
  ha-card.hk-card.overdue { border-left: 3px solid var(--error-color); }

  /* Filter / group-by controls */
  .hk-controls {
    display: flex; align-items: center; gap: 16px 24px; flex-wrap: wrap;
    margin-bottom: 16px;
  }
  .hk-control { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .hk-seg-label {
    font-size: 0.8rem; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: 0.04em;
  }
  .hk-seg {
    display: inline-flex; border: 1px solid var(--divider-color);
    border-radius: 999px; overflow: hidden; background: var(--card-background-color);
  }
  .hk-seg-btn {
    appearance: none; border: 0; background: transparent; cursor: pointer;
    font: inherit; font-size: 0.85rem; padding: 6px 14px;
    color: var(--primary-text-color); white-space: nowrap;
    border-left: 1px solid var(--divider-color);
  }
  .hk-seg-btn:first-child { border-left: 0; }
  .hk-seg-btn:hover { background: var(--secondary-background-color); }
  .hk-seg-btn.active {
    background: var(--primary-color);
    color: var(--text-primary-color, #fff); font-weight: 500;
  }

  /* Collapsible group sections */
  details.hk-group { margin-bottom: 12px; }
  details.hk-group > summary {
    list-style: none; cursor: pointer; display: flex; align-items: center;
    gap: 8px; padding: 6px 4px; user-select: none;
  }
  details.hk-group > summary::-webkit-details-marker { display: none; }
  details.hk-group > summary::before {
    content: ''; width: 0; height: 0; flex: none;
    border-left: 5px solid var(--secondary-text-color);
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    transition: transform 0.15s ease; transform: rotate(0deg);
  }
  details.hk-group[open] > summary::before { transform: rotate(90deg); }
  .hk-group-title { font-weight: 600; font-size: 0.95rem; }
  .hk-group-count {
    font-size: 0.8rem; color: var(--secondary-text-color);
    background: var(--secondary-background-color);
    border-radius: 999px; padding: 1px 8px;
  }

  /* Detail page */
  .hk-detailbar { display: flex; align-items: center; margin-bottom: 12px; }
  .hk-detail-card { margin-bottom: 12px; }
  .hk-detail-inner { padding: 16px; }
  .hk-detail-title {
    font-size: 1.3rem; font-weight: 500; display: flex; align-items: center;
    gap: 8px; flex-wrap: wrap;
  }
  .hk-detail-card .hk-chips { margin-top: 10px; }
  .hk-detail-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 16px; }
  .hk-detail-row {
    display: flex; gap: 12px; padding: 6px 0; align-items: baseline;
    border-bottom: 1px solid var(--divider-color);
  }
  .hk-detail-row:last-child { border-bottom: none; }
  .hk-detail-row .k {
    flex: 0 0 40%; max-width: 220px; color: var(--secondary-text-color);
    font-size: 0.85rem;
  }
  .hk-detail-row .v { flex: 1; min-width: 0; word-break: break-word; }
  .hk-detail-row .v a { color: var(--primary-color); }
  .hk-muted { color: var(--secondary-text-color); }
  .hk-rel {
    display: flex; align-items: center; gap: 12px; padding: 8px 0;
    border-bottom: 1px solid var(--divider-color); cursor: pointer;
  }
  .hk-rel:last-child { border-bottom: none; }
  .hk-rel .grow { flex: 1; min-width: 0; }
  .hk-rel .hk-name { font-weight: 500; }

  .hk-hist-group { margin-bottom: 18px; }
  .hk-hist-group:last-child { margin-bottom: 0; }
  .hk-hist-head {
    display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;
    font-weight: 500; margin-bottom: 6px;
  }
  .hk-hist-sub { color: var(--secondary-text-color); font-size: 0.85rem; font-weight: 400; }
  .hk-hist-archived {
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--secondary-text-color); border: 1px solid var(--divider-color);
    border-radius: 10px; padding: 1px 8px;
  }
  ul.hk-hist-list { list-style: none; margin: 0; padding: 0; }
  ul.hk-hist-list li {
    padding: 2px 0; border-bottom: 1px solid var(--divider-color);
  }
  ul.hk-hist-list li:last-child { border-bottom: none; }
  .hk-hist-row { display: flex; align-items: center; gap: 12px; }
  ul.hk-hist-list .date { flex: 1; min-width: 0; }
  ul.hk-hist-list .when { color: var(--secondary-text-color); font-size: 0.85rem; white-space: nowrap; }
  .hk-hist-actions { display: flex; align-items: center; }
  ha-icon-button.hk-hist-del, ha-icon-button.hk-hist-edit {
    --mdc-icon-button-size: 36px; color: var(--secondary-text-color);
  }
  .hk-hist-meta {
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
    margin: 0 0 6px 2px;
  }
  .hk-hist-chips { color: var(--secondary-text-color); font-size: 0.85rem; }
  .hk-hist-note { font-size: 0.9rem; white-space: pre-wrap; }
  .hk-hist-photo {
    height: 56px; width: 56px; object-fit: cover; border-radius: 8px;
    border: 1px solid var(--divider-color);
  }
  /* Completion-details dialog */
  .hk-completion-body { display: flex; flex-direction: column; gap: 12px; min-width: 320px; }
  .hk-completion-photo-label { font-weight: 500; font-size: 0.9rem; }
`;

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
/**
 * The completion-details dialog state. Open either to *log* a new completion
 * (`ts` absent) or to *edit* a recorded one (`ts` set). `data` holds the in-progress
 * metadata; `required` is the set of fields that must be filled before saving.
 */
interface CompletionDialogState {
  open: boolean;
  task: Task | null;
  ts?: string;
  data: { note?: string; cost?: number; photo?: string; who?: string };
  required: string[];
  error?: string;
}
/** One task's completion list within a history dialog (live or archived). */
interface HistoryGroup {
  name: string;
  completions: Completion[];
  archived?: boolean;
  // Deletion context for the per-completion trash button: a live task carries
  // `taskId`; an archived (removed-task) group carries `assetId` + `archivedTaskId`.
  taskId?: string;
  assetId?: string;
  archivedTaskId?: string;
}
/** How the list view buckets rows; `status`/`device`/`integration` apply to tasks only. */
type GroupBy = 'none' | 'status' | 'area' | 'device' | 'integration';
/** Task-list quick filter. */
type TaskFilter = 'all' | 'overdue' | 'soon';
/** One bucket of rows rendered under a collapsible section header. */
interface Group<T> {
  /** Stable key for remembering collapse state, e.g. "status:overdue". */
  key: string;
  /** Section header text; empty string renders the rows ungrouped. */
  label: string;
  items: T[];
}
/** Tasks due within this many days (and not overdue) count as "due soon". */
const SOON_DAYS = 7;
const LS_GROUP = 'home-keeper.groupBy';
const LS_FILTER = 'home-keeper.filter';

export class HomeKeeperPanel extends HTMLElement {
  private _hass?: Hass;
  public panel?: PanelInfo;
  public narrow = false;
  private _tasks: Task[] = [];
  private _assets: Asset[] = [];
  private _completion: CompletionDialogState = {
    open: false,
    task: null,
    data: {},
    required: [],
  };
  // config entry id -> integration domain, for resolving device brand logos.
  private _entryDomains: Record<string, string> = {};
  // config entry ids that are currently loaded, for managed-task orphan detection.
  private _loadedEntryIds: Set<string> = new Set();
  private _edit: EditState = { open: false, task: null };
  private _assetEdit: AssetEditState = { open: false, asset: null };
  private _view: 'tasks' | 'appliances' | 'settings' = 'tasks';
  // Integration options for the Settings tab (loaded lazily with the rest).
  private _options: HomeKeeperOptions | null = null;
  // Companion integrations shown on the Settings tab (loaded with the rest).
  private _companions: Companion[] = [];
  // List controls (persisted in localStorage).
  private _groupBy: GroupBy = 'status';
  private _filter: TaskFilter = 'all';
  // Group sections collapsed by the user, keyed by "<group>:<bucket>".
  // Group sections the user collapsed this session (open is the default). The
  // "monitored" status bucket — dormant condition-driven tasks like healthy
  // batteries — starts collapsed so it stays out of the way but one click to browse.
  private _collapsed = new Set<string>(['status:monitored', 'status:completed']);
  // The object whose full detail page is open, or null for the list view.
  private _detail: { kind: 'task' | 'asset'; id: string } | null = null;
  // The panel's URL prefix (e.g. `/home-keeper`), supplied by HA via `route`.
  // Navigation builds absolute paths from it; falls back until the first route.
  private _routePrefix = '/home-keeper';
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

  /**
   * HA sets `route = { prefix, path }` on the panel element for every in-panel
   * URL change, including browser Back/Forward. We treat it as the single source
   * of truth: derive the view/detail from the path and render. This is what makes
   * deep links resolve and Back move within the panel instead of ejecting from it.
   */
  set route(route: { prefix?: string; path?: string } | undefined) {
    if (route?.prefix) this._routePrefix = route.prefix;
    this._applyLocation(parseRoute(route?.path));
  }

  /** Adopt a parsed location into view/detail state, rendering only on change. */
  private _applyLocation(loc: PanelLocation): void {
    const changed =
      loc.view !== this._view ||
      loc.detail?.kind !== this._detail?.kind ||
      loc.detail?.id !== this._detail?.id;
    if (!changed) return;
    this._view = loc.view;
    this._detail = loc.detail;
    // Leaving a list/detail closes any open form (forms are ephemeral overlays).
    this._edit = { open: false, task: null };
    this._assetEdit = { open: false, asset: null };
    this._render();
  }

  /**
   * Navigate the panel by changing the URL — never by mutating view/detail
   * directly. HA's `location-changed` listener re-sets our `route`, which flows
   * back through `set route` so there is exactly one path into a state change.
   * Drill-in steps push (Back-able); lateral moves (tab switch) replace.
   */
  private _navigate(loc: PanelLocation, replace = false): void {
    const url = this._routePrefix + buildPath(loc);
    history[replace ? 'replaceState' : 'pushState'](null, '', url);
    this.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace },
        bubbles: true,
        composed: true,
      }),
    );
  }

  connectedCallback(): void {
    if (!this.shadowRoot) this.attachShadow({ mode: 'open' });
    this._loadPrefs();
    void this._init();
  }

  /** Restore the persisted group-by / filter choices (best-effort). */
  private _loadPrefs(): void {
    try {
      const g = localStorage.getItem(LS_GROUP);
      if (g === 'none' || g === 'status' || g === 'area' || g === 'device' || g === 'integration')
        this._groupBy = g;
      const f = localStorage.getItem(LS_FILTER);
      if (f === 'all' || f === 'overdue' || f === 'soon') this._filter = f;
    } catch {
      // localStorage unavailable (e.g. private mode) — fall back to defaults.
    }
  }

  private _setGroupBy(value: GroupBy): void {
    if (this._groupBy === value) return;
    this._groupBy = value;
    try {
      localStorage.setItem(LS_GROUP, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  private _setFilter(value: TaskFilter): void {
    if (this._filter === value) return;
    this._filter = value;
    try {
      localStorage.setItem(LS_FILTER, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  // ── detail page lifecycle ───────────────────────────────────────────────────
  private _openDetail(kind: 'task' | 'asset', id: string): void {
    // Drilling in is a Back-able step: push.
    this._navigate({ view: kind === 'asset' ? 'appliances' : 'tasks', detail: { kind, id } });
  }
  private _closeDetail(): void {
    // Return to the list this detail belongs to, collapsing the detail entry so
    // browser Back from the list continues past it rather than re-opening it.
    this._navigate({ view: this._view, detail: null }, true);
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

  /** Fetch tasks/assets/domains into state (no render). */
  private async _reload(): Promise<void> {
    if (!this._hass) return;
    try {
      const [tasks, assets, entryDomains, loadedEntryIds, options, companions] =
        await Promise.all([
          api.getTasks(this._hass),
          api.getAssets(this._hass),
          api.getEntryDomains(this._hass).catch(() => ({})),
          api.getLoadedEntryIds(this._hass).catch(() => new Set<string>()),
          api.getOptions(this._hass).catch(() => null),
          api.getCompanions(this._hass).catch(() => [] as Companion[]),
        ]);
      this._tasks = tasks;
      this._assets = assets;
      this._entryDomains = entryDomains;
      this._loadedEntryIds = loadedEntryIds;
      this._options = options;
      this._companions = companions ?? [];
      this._loaded = true;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load data', err);
    }
  }

  private async _refresh(): Promise<void> {
    await this._reload();
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
    // Editing happens in the list view's form host; leave any open detail page.
    this._detail = null;
    this._view = 'tasks';
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

  private async _complete(task: Task): Promise<void> {
    if (!this._hass) return;
    // Tasks set to capture detail open a dialog first; the default one-taps.
    const mode = task.completion_detail || 'none';
    if (mode === 'optional' || mode === 'required') {
      this._openCompletionDialog(task);
      return;
    }
    await api.completeTask(this._hass, task.id);
    await this._refresh();
  }

  /** Open the completion-details dialog to log a new completion for *task*. */
  private _openCompletionDialog(task: Task): void {
    this._completion = {
      open: true,
      task,
      data: {},
      required:
        task.completion_detail === 'required' ? task.completion_required_fields || ['note'] : [],
    };
    this._render();
  }

  /** Open the dialog to edit an already-recorded completion's metadata. */
  private _openCompletionEdit(task: Task, c: Completion): void {
    this._completion = {
      open: true,
      task,
      ts: c.ts,
      data: { note: c.note, cost: c.cost, photo: c.photo, who: c.who },
      required: [],
    };
    this._render();
  }

  private _closeCompletionDialog(): void {
    this._completion = { open: false, task: null, data: {}, required: [] };
    this._render();
  }

  /** True when every required field of the in-progress completion is filled. */
  private _completionMissing(): string[] {
    const d = this._completion.data;
    return this._completion.required.filter((f) => {
      const v = (d as Record<string, unknown>)[f];
      return v == null || v === '' || (typeof v === 'number' && Number.isNaN(v));
    });
  }

  /** Save the dialog: a new completion (with metadata) or an edit of a past one. */
  private async _submitCompletion(): Promise<void> {
    const c = this._completion;
    if (!this._hass || !c.task) return;
    if (c.ts == null && this._completionMissing().length) {
      c.error = t('completion.required');
      this._render();
      return;
    }
    try {
      if (c.ts != null) {
        await api.updateCompletion(this._hass, c.task.id, c.ts, c.data);
      } else {
        await api.completeTask(this._hass, c.task.id, c.data);
      }
      this._closeCompletionDialog();
      await this._refresh();
    } catch (err) {
      c.error = String((err as { message?: string })?.message || err);
      this._render();
    }
  }

  /** A completion-blocked task (e.g. a synced problem sensor) can't be marked done
   *  here — its owning integration clears it. Explain why instead of completing. */
  private _notifyBlocked(task: Task): void {
    this._toast(task.managed_by?.completion_prompt || t('done.blocked'));
  }

  /** Render a *disabled* Done for a completion-blocked task, wrapped in a clickable
   *  span (the native `disabled` greys the button correctly across HA button
   *  versions, but swallows clicks — so the span carries the tap → explanation and a
   *  hover tooltip). ``raised`` matches the prominent detail-page button. */
  private _blockedDone(wrapClass: string, task: Task, raised = false): string {
    const reason = task.managed_by?.completion_prompt || t('done.blocked');
    return `<span class="${wrapClass} done-blocked-wrap" data-id="${escapeHTML(task.id)}" role="button" tabindex="0" title="${escapeHTML(reason)}"><ha-button ${raised ? 'raised ' : ''}disabled>${escapeHTML(t('btn.done'))}</ha-button></span>`;
  }
  private async _delete(task: Task): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteTask(this._hass, task.id);
      await this._refresh();
    } catch (err) {
      const msg = String((err as { message?: string })?.message || err);
      this._toast(msg);
      await this._refresh();
    }
  }

  // ── asset form lifecycle ────────────────────────────────────────────────────
  private _openCreateAsset(): void {
    this._assetEdit = { open: true, asset: { kind: 'virtual', parts: [] } };
    this._render();
  }
  private _openEditAsset(asset: Asset): void {
    this._detail = null;
    this._view = 'appliances';
    this._assetEdit = {
      open: true,
      asset: {
        ...asset,
        parts: [...(asset.parts || [])],
        metadata: (asset.metadata || []).map((m) => ({ ...m })),
      },
    };
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
    // Drop half-finished metadata rows (no label) so they don't fail validation.
    const metadata = (a.metadata || []).filter((m) => m.label && m.label.trim());
    const payload: Partial<Asset> = { ...a, parts, metadata };
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

  /**
   * Build the home-inventory report server-side and save it as a CSV — a
   * grab-and-go record for an insurance claim (make/model/serial, purchase +
   * warranty dates, replacement cost, on-hand spares value).
   */
  private async _exportInventory(): Promise<void> {
    if (!this._hass) return;
    try {
      const { csv } = await api.exportInventory(this._hass);
      const stamp = new Date().toISOString().slice(0, 10);
      this._downloadFile(`home-keeper-inventory-${stamp}.csv`, csv, 'text/csv');
    } catch (err) {
      console.error('home-keeper: inventory export failed', err);
      this._toast(t('error.exportFailed'));
    }
  }

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

  /** Trigger a client-side file download (no server round-trip for the blob). */
  private _downloadFile(filename: string, contents: string, mime: string): void {
    const blob = new Blob([contents], { type: `${mime};charset=utf-8` });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Defer revoke a tick so the download isn't cancelled in browsers that read the
    // blob URL asynchronously after click().
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  // ── completion history ──────────────────────────────────────────────────────
  /**
   * Completion groups for the detail page's history section. For a task: its own
   * completions. For an appliance: every completion tied to it — live related
   * tasks (part-derived or device-attached) plus the history archived from tasks
   * deleted while still assigned to it — newest activity first.
   */
  private _completionGroupsFor(kind: 'task' | 'asset', id: string): HistoryGroup[] {
    if (kind === 'task') {
      const task = this._tasks.find((t) => t.id === id);
      if (!task) return [];
      return [{ name: task.name, completions: task.completions || [], taskId: task.id }];
    }
    const asset = this._assets.find((a) => a.id === id);
    if (!asset) return [];
    const groups: HistoryGroup[] = tasksForAsset(asset, this._tasks).map((task) => ({
      name: task.name,
      completions: task.completions || [],
      taskId: task.id,
    }));
    for (const entry of asset.task_history || []) {
      groups.push({
        name: entry.task_name,
        completions: entry.completions || [],
        archived: true,
        assetId: asset.id,
        archivedTaskId: entry.task_id,
      });
    }
    const lastTs = (g: HistoryGroup): number =>
      g.completions.reduce((m, c) => Math.max(m, new Date(c.ts).getTime() || 0), 0);
    groups.sort((a, b) => lastTs(b) - lastTs(a));
    return groups;
  }

  private async _deleteCompletion(taskId: string, ts: string): Promise<void> {
    if (!this._hass) return;
    await api.deleteCompletion(this._hass, taskId, ts);
    await this._refresh();
  }

  private async _deleteArchivedCompletion(
    assetId: string,
    archivedTaskId: string,
    ts: string,
  ): Promise<void> {
    if (!this._hass) return;
    await api.deleteArchivedCompletion(this._hass, assetId, archivedTaskId, ts);
    await this._refresh();
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  private _render(): void {
    if (!this.shadowRoot) return;
    this._liveHassEls = [];
    const onTasks = this._view === 'tasks';

    let inner: string;
    if (!this._loaded) {
      inner = `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`;
    } else if (this._detail) {
      inner = `
        <div class="hk-detailbar">
          <ha-button id="back-btn">‹ ${escapeHTML(t('btn.back'))}</ha-button>
        </div>
        ${this._detailView()}`;
    } else if (this._view === 'settings') {
      inner = `${this._tabs()}<div id="hk-settings-host"></div><div id="hk-companions-host"></div>`;
    } else {
      const addLabel = onTasks ? t('btn.addTask') : t('btn.addAppliance');
      inner = `
        ${this._tabs()}
        <div class="hk-actionbar">
          <ha-button raised id="add-btn">${escapeHTML(addLabel)}</ha-button>
          ${onTasks ? '' : `<ha-button id="export-btn">${escapeHTML(t('btn.exportInventory'))}</ha-button>`}
        </div>
        <div id="hk-form-host"></div>
        ${this._controls()}
        <div id="hk-list">${onTasks ? this._tasksList() : this._assetsList()}</div>`;
    }

    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-toolbar">
        <span id="menu-host"></span>
        <div class="hk-toolbar-title">${escapeHTML(t('app.title'))}</div>
      </div>
      <div class="hk-wrap">
        ${inner}
        <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
      </div>
      <div id="hk-dialog-host"></div>
    `;
    this._hydrate();
  }

  /** The top tab bar (Tasks / Appliances / Settings), with the active tab marked. */
  private _tabs(): string {
    const v = this._view;
    return `
      <ha-tab-group>
        <ha-tab-group-tab id="tab-tasks" panel="tasks" ${v === 'tasks' ? 'active' : ''}>${escapeHTML(t('tab.tasks'))}</ha-tab-group-tab>
        <ha-tab-group-tab id="tab-appliances" panel="appliances" ${v === 'appliances' ? 'active' : ''}>${escapeHTML(t('tab.appliances'))}</ha-tab-group-tab>
        <ha-tab-group-tab id="tab-settings" panel="settings" ${v === 'settings' ? 'active' : ''}>${escapeHTML(t('tab.settings'))}</ha-tab-group-tab>
      </ha-tab-group>`;
  }

  // ── list controls (filter + group-by) ───────────────────────────────────────
  /** Group-by resolved for the active view (appliances only support area/none). */
  private _effectiveGroup(): GroupBy {
    const taskOnlyGroups: GroupBy[] = ['status', 'device', 'integration'];
    if (this._view === 'appliances' && taskOnlyGroups.includes(this._groupBy)) {
      return 'none';
    }
    return this._groupBy;
  }

  private _controls(): string {
    const onTasks = this._view === 'tasks';
    const groupOpts: { value: GroupBy; label: string }[] = onTasks
      ? [
          { value: 'status', label: t('group.status') },
          { value: 'area', label: t('group.area') },
          { value: 'device', label: t('group.device') },
          { value: 'integration', label: t('group.integration') },
          { value: 'none', label: t('group.none') },
        ]
      : [
          { value: 'area', label: t('group.area') },
          { value: 'none', label: t('group.none') },
        ];
    const groupControl = `
      <div class="hk-control">
        <span class="hk-seg-label">${escapeHTML(t('group.by'))}</span>
        ${this._seg('group', this._effectiveGroup(), groupOpts)}
      </div>`;
    const filterControl = onTasks
      ? `<div class="hk-control">${this._seg('filter', this._filter, [
          { value: 'all', label: t('filter.all') },
          { value: 'overdue', label: t('filter.overdue') },
          { value: 'soon', label: t('filter.soon') },
        ])}</div>`
      : '';
    return `<div class="hk-controls">${filterControl}${groupControl}</div>`;
  }

  /** A pill-style segmented toggle; the active option carries the `active` class. */
  private _seg(name: string, current: string, options: { value: string; label: string }[]): string {
    const btns = options
      .map(
        (o) =>
          `<button class="hk-seg-btn${o.value === current ? ' active' : ''}" data-seg-val="${escapeHTML(
            o.value,
          )}">${escapeHTML(o.label)}</button>`,
      )
      .join('');
    return `<div class="hk-seg" data-seg="${escapeHTML(name)}">${btns}</div>`;
  }

  // ── list bucketing ──────────────────────────────────────────────────────────
  /** Which status section a task belongs to. */
  private _statusBucket(
    task: Task,
    now = Date.now(),
  ): 'overdue' | 'soon' | 'later' | 'monitored' | 'completed' | 'none' {
    // A dormant triggered task is "monitored" — armed-but-not-due — and lands in its
    // own (default-collapsed) section rather than the generic no-schedule bucket. An
    // armed one (next_due set) flows through the normal overdue/soon/later logic.
    if (task.recurrence_type === 'triggered' && !task.next_due) return 'monitored';
    // A completed one-off (do-once, now dormant) goes to its own collapsed section so
    // it leaves the active list without cluttering the generic no-schedule bucket.
    if (task.recurrence_type === 'one-off' && !task.next_due && task.last_completed)
      return 'completed';
    if (!task.next_due) return 'none';
    const due = new Date(task.next_due).getTime();
    if (due <= now) return 'overdue';
    if (due - now <= SOON_DAYS * 86_400_000) return 'soon';
    return 'later';
  }

  /** A task's area: its own, else its attached device's. */
  private _taskAreaId(task: Task): string | undefined {
    if (task.area_id) return task.area_id;
    const dev = task.device_id ? this._hass?.devices?.[task.device_id] : undefined;
    return dev?.area_id ?? undefined;
  }

  private _groupTasks(tasks: Task[], now = Date.now()): Group<Task>[] {
    const group = this._effectiveGroup();
    if (group === 'status') {
      const order: {
        bucket: 'overdue' | 'soon' | 'later' | 'monitored' | 'completed' | 'none';
        label: string;
      }[] = [
        { bucket: 'overdue', label: t('chip.overdue') },
        { bucket: 'soon', label: t('filter.soon') },
        { bucket: 'later', label: t('section.later') },
        { bucket: 'monitored', label: t('section.monitored') },
        { bucket: 'none', label: t('section.noSchedule') },
        { bucket: 'completed', label: t('section.completed') },
      ];
      return order
        .map(({ bucket, label }) => ({
          key: `status:${bucket}`,
          label,
          items: tasks.filter((task) => this._statusBucket(task, now) === bucket),
        }))
        .filter((g) => g.items.length);
    }
    if (group === 'area') {
      return this._groupByKey(
        tasks,
        (task) => this._taskAreaId(task),
        (id) => areaName(this._hass?.areas, id),
        t('section.unassigned'),
        'area',
      );
    }
    if (group === 'device') {
      return this._groupByKey(
        tasks,
        (task) => task.device_id ?? undefined,
        (id) => deviceName(this._hass?.devices, id),
        t('section.noDevice'),
        'device',
      );
    }
    if (group === 'integration') {
      return this._groupByKey(
        tasks,
        (task) => task.managed_by?.display_name ?? undefined,
        (name) => name,
        t('section.standalone'),
        'integration',
      );
    }
    return [{ key: '', label: '', items: tasks }];
  }

  private _groupAssets(assets: Asset[]): Group<Asset>[] {
    if (this._effectiveGroup() === 'area') {
      return this._groupByKey(
        assets,
        (a) => a.area_id ?? undefined,
        (id) => areaName(this._hass?.areas, id),
        t('section.unassigned'),
        'area',
      );
    }
    return [{ key: '', label: '', items: assets }];
  }

  /**
   * Bucket items by a key, label each section, sort sections alphabetically and
   * sink the "no key" fallback bucket to the bottom. Keys are namespaced so
   * collapse state never collides between grouping modes.
   */
  private _groupByKey<T>(
    items: T[],
    keyOf: (item: T) => string | undefined,
    labelOf: (key: string) => string,
    fallbackLabel: string,
    prefix: string,
  ): Group<T>[] {
    const buckets = new Map<string, T[]>();
    for (const item of items) {
      const k = keyOf(item) || '';
      const arr = buckets.get(k);
      if (arr) arr.push(item);
      else buckets.set(k, [item]);
    }
    const fallbackKey = `${prefix}:none`;
    const groups: Group<T>[] = [];
    for (const [k, arr] of buckets) {
      groups.push({
        key: k ? `${prefix}:${k}` : fallbackKey,
        label: k ? labelOf(k) : fallbackLabel,
        items: arr,
      });
    }
    groups.sort((a, b) => {
      const af = a.key === fallbackKey;
      const bf = b.key === fallbackKey;
      if (af !== bf) return af ? 1 : -1;
      return a.label.localeCompare(b.label);
    });
    return groups;
  }

  /** Render groups as collapsible sections, or bare items when ungrouped. */
  private _renderGroups<T>(groups: Group<T>[], renderItem: (item: T) => string): string {
    if (groups.length === 1 && !groups[0].label) {
      return groups[0].items.map(renderItem).join('');
    }
    return groups
      .map((g) => {
        const open = this._collapsed.has(g.key) ? '' : 'open';
        return `
        <details class="hk-group" data-group-key="${escapeHTML(g.key)}" ${open}>
          <summary class="hk-group-head">
            <span class="hk-group-title">${escapeHTML(g.label)}</span>
            <span class="hk-group-count">${g.items.length}</span>
          </summary>
          <div class="hk-group-body">${g.items.map(renderItem).join('')}</div>
        </details>`;
      })
      .join('');
  }

  private _tasksList(): string {
    if (!this._tasks.length) {
      const addTask = `<b>${escapeHTML(t('btn.addTask'))}</b>`;
      return `<ha-alert alert-type="info">${t('tasks.empty', { addTask })}</ha-alert>`;
    }
    const now = Date.now();
    let tasks = [...this._tasks];
    if (this._filter === 'overdue') tasks = tasks.filter((task) => isOverdue(task));
    else if (this._filter === 'soon')
      tasks = tasks.filter((task) => this._statusBucket(task, now) === 'soon');
    tasks.sort((a, b) => {
      const ad = a.next_due ? new Date(a.next_due).getTime() : Infinity;
      const bd = b.next_due ? new Date(b.next_due).getTime() : Infinity;
      return ad - bd;
    });
    if (!tasks.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('tasks.noMatch'))}</ha-alert>`;
    }
    return `${this._orphanBanner()}${this._renderGroups(
      this._groupTasks(tasks, now),
      (task) => this._taskCard(task),
    )}`;
  }

  /**
   * A dismissable-style warning shown above the task list when one or more managed
   * tasks have been orphaned (their integration was uninstalled/disabled). Offers a
   * one-click "Remove orphaned tasks" cleanup so the user isn't stuck with tasks no
   * integration owns any more.
   */
  private _orphanBanner(): string {
    const n = this._tasks.filter((task) => this._isManagedOrphan(task)).length;
    if (!n) return '';
    return `
      <ha-alert alert-type="warning" class="hk-orphan-banner">
        ${escapeHTML(tn('managed.orphanBanner', n))}
        <ha-button slot="action" id="cleanup-orphans-btn">${escapeHTML(
          t('btn.removeOrphaned'),
        )}</ha-button>
      </ha-alert>`;
  }

  /** Delete every orphaned managed task (the bulk cleanup action). */
  private async _cleanupOrphans(): Promise<void> {
    if (!this._hass) return;
    const orphans = this._tasks.filter((task) => this._isManagedOrphan(task));
    if (!orphans.length) return;
    try {
      for (const task of orphans) await api.deleteTask(this._hass, task.id);
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
    await this._refresh();
  }

  private _assetsList(): string {
    if (!this._assets.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('appliances.empty'))}</ha-alert>`;
    }
    const assets = [...this._assets].sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    return this._renderGroups(this._groupAssets(assets), (asset) => this._assetCard(asset));
  }

  private _taskCard(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task))}"></ha-assist-chip>`;
    const dev = task.device_id ? this._deviceChip(task.device_id) : '';
    const managedChip = this._managedChip(task);
    // A completed one-off (do-once, now dormant) shows when it was done instead of a
    // due date.
    const completedOneOff =
      task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
    const dueText = task.next_due
      ? ` · ${escapeHTML(t('form.task.due', { date: new Date(task.next_due).toLocaleDateString() }))}`
      : completedOneOff
        ? ` · ${escapeHTML(t('form.task.completedOn', { date: new Date(task.last_completed as string).toLocaleDateString() }))}`
        : '';
    const n = task.completions?.length ?? 0;
    // A dormant triggered task (monitored, not due) has nothing to mark done — its
    // owning integration arms it when the condition fires; hide the action. A
    // completed one-off is already done, so it too hides Done. A completion-blocked
    // task (e.g. a synced problem sensor) keeps a *disabled* Done that explains why
    // on click, rather than silently offering no action.
    const dormantTriggered = task.recurrence_type === 'triggered' && !task.next_due;
    const doneAction = dormantTriggered || completedOneOff
      ? ''
      : task.managed_by?.completion_blocked
        ? this._blockedDone('done-blocked-wrap', task)
        : `<ha-button class="done-btn" data-id="${escapeHTML(task.id)}">${escapeHTML(t('btn.done'))}</ha-button>`;
    // The row opens the task's detail page; "Done" stays as a quick action.
    return `
      <ha-card class="hk-card${overdue ? ' overdue' : ''}" data-id="${escapeHTML(task.id)}">
        <div class="hk-card-row">
          <div class="grow clickable detail-open" data-detail-kind="task" data-detail-id="${escapeHTML(task.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(task.name)}</div>
            <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}${dueText}${n ? ` · ${escapeHTML(tn('history.count', n))}` : ''}</div>
            <div class="hk-chips">${statusChip}${dev}${managedChip}</div>
          </div>
          <div class="hk-card-actions">
            ${doneAction}
          </div>
        </div>
      </ha-card>`;
  }

  private _assetCard(x: Asset): string {
    const kindChip =
      x.kind === 'virtual'
        ? `<ha-assist-chip label="${escapeHTML(t('chip.virtualDevice'))}"></ha-assist-chip>`
        : x.device_id
          ? this._deviceChip(x.device_id)
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
          <div class="grow clickable detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(x.id)}" role="button" tabindex="0">
            <div class="hk-name">${escapeHTML(title)}</div>
            <div class="hk-meta">${escapeHTML(assetSummary(x, this._hass?.areas))}</div>
            <div class="hk-chips">${kindChip}${extra}</div>
          </div>
        </div>
      </ha-card>`;
  }

  private _assetName(assetId: string): string {
    return this._assets.find((a) => a.id === assetId)?.name || assetId;
  }

  // ── detail page ─────────────────────────────────────────────────────────────
  private _detailView(): string {
    const d = this._detail;
    if (!d) return '';
    if (d.kind === 'task') {
      const task = this._tasks.find((x) => x.id === d.id);
      if (!task) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
      return this._taskDetail(task);
    }
    const asset = this._assets.find((x) => x.id === d.id);
    if (!asset) return `<ha-alert alert-type="warning">${escapeHTML(t('detail.gone'))}</ha-alert>`;
    return this._assetDetail(asset);
  }

  /** Render a URL as a clickable anchor that opens in the browser (new tab). */
  private _link(url: string): string {
    const safe = escapeHTML(url);
    return `<a href="${safe}" target="_blank" rel="noopener">${safe}</a>`;
  }

  /** One label/value row, omitted entirely when the value is empty. */
  private _row(label: string, value?: string | null, isHtml = false): string {
    if (value == null || value === '') return '';
    return `<div class="hk-detail-row"><span class="k">${escapeHTML(label)}</span><span class="v">${
      isHtml ? value : escapeHTML(value)
    }</span></div>`;
  }

  private _historySection(kind: 'task' | 'asset', id: string): string {
    const groups = this._completionGroupsFor(kind, id);
    return `
      <div class="hk-section">${escapeHTML(t('btn.history'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-hist-body">${this._historyBody(
        groups,
      )}</div></ha-card>`;
  }

  private _taskDetail(task: Task): string {
    const overdue = isOverdue(task);
    const statusChip = overdue
      ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
      : `<ha-assist-chip label="${escapeHTML(dueLabel(task))}"></ha-assist-chip>`;
    const dev = task.device_id ? this._deviceChip(task.device_id) : '';
    const managedChip = this._managedChip(task);
    const mb = task.managed_by;

    // Source-owned tasks (wear parts, synced problem sensors) are managed by their
    // source; the panel offers no edit/delete for them.
    const sourceOwned = Boolean(task.source?.part) || Boolean(task.source?.problem_sensor);
    const orphaned = this._isManagedOrphan(task);
    let manage = '';
    if (!sourceOwned) {
      const editBtn = `<ha-button class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>`;
      // Deletion protection only holds while the owner is present. Once orphaned
      // (owner uninstalled/disabled), the Delete button returns so the user can
      // clean the task up — otherwise "delete it from X instead" points nowhere.
      const deleteBtn =
        mb?.deletion_protected && !orphaned
          ? `<span class="hk-managed-info">${escapeHTML(t('managed.deleteBlocked', { name: mb.display_name }))}</span>`
          : `<ha-button class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>`;
      // "Edit in X" deep link when config_entry_id resolves to a loaded domain.
      const domain = mb?.config_entry_id ? this._entryDomains[mb.config_entry_id] : null;
      const openInBtn = domain && !orphaned
        ? `<ha-button class="d-open-in" data-domain="${escapeHTML(domain)}">${escapeHTML(t('btn.openInIntegration', { name: mb!.display_name }))}</ha-button>`
        : '';
      manage = `${editBtn}${deleteBtn}${openInBtn}`;
    }

    // When orphaned, explain why deletion is now allowed; otherwise show the
    // managing integration's optional completion hint.
    const completionHint =
      orphaned && mb
        ? `<div class="hk-managed-prompt">${escapeHTML(t('managed.orphanCleanup', { name: mb.display_name }))}</div>`
        : mb?.completion_prompt
          ? `<div class="hk-managed-prompt">${escapeHTML(mb.completion_prompt)}</div>`
          : '';

    const dormantTriggered = task.recurrence_type === 'triggered' && !task.next_due;
    const completedOneOff =
      task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
    const due = dormantTriggered
      ? t('due.monitored')
      : completedOneOff
        ? t('form.task.completedOn', { date: new Date(task.last_completed as string).toLocaleString() })
        : task.next_due
          ? new Date(task.next_due).toLocaleString()
          : t('due.none');
    // Nothing to mark done while dormant — the integration arms it when the
    // monitored condition fires (e.g. a battery goes low) — or once a one-off is
    // already completed. A completion-blocked task (a synced problem sensor) keeps a
    // *disabled* Done that, on click, explains its source clears it (the managed
    // completion prompt also shows below).
    const doneBtn = dormantTriggered || completedOneOff
      ? ''
      : mb?.completion_blocked
        ? this._blockedDone('d-done-blocked-wrap', task, true)
        : `<ha-button raised class="d-done">${escapeHTML(t('btn.done'))}</ha-button>`;
    const notes = task.notes
      ? escapeHTML(task.notes)
      : `<span class="hk-muted">${escapeHTML(t('detail.noNotes'))}</span>`;
    return `
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(task.name)}</div>
        <div class="hk-chips">${statusChip}${dev}${managedChip}</div>
        <div class="hk-detail-actions">
          ${doneBtn}
          ${manage}
        </div>
        ${completionHint}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('detail.schedule'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        ${this._row(t('field.recurrence_type'), recurrenceSummary(task))}
        ${this._row(t('detail.nextDue'), due)}
      </div></ha-card>
      <div class="hk-section">${escapeHTML(t('field.notes'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${notes}</div></ha-card>
      ${this._historySection('task', task.id)}`;
  }

  private _assetDetail(asset: Asset): string {
    const kindChip =
      asset.kind === 'virtual'
        ? `<ha-assist-chip label="${escapeHTML(t('chip.virtualDevice'))}"></ha-assist-chip>`
        : asset.device_id
          ? this._deviceChip(asset.device_id)
          : '';
    const parentChip = asset.parent_asset_id
      ? `<ha-assist-chip label="${escapeHTML(
          t('chip.subdeviceOf', { name: this._assetName(asset.parent_asset_id) }),
        )}"></ha-assist-chip>`
      : '';
    const title =
      asset.name || deviceName(this._hass?.devices, asset.device_id) || t('appliance.fallbackName');
    const manual = asset.manual_url ? this._link(asset.manual_url) : '';
    const cost = asset.cost != null ? String(asset.cost) : '';
    // Structured (HA-wired) fields first, then the free-form metadata entries.
    const meta = (asset.metadata || [])
      .map((m) =>
        m.value
          ? this._row(m.label, m.type === 'link' ? this._link(m.value) : m.value, m.type === 'link')
          : '',
      )
      .join('');
    const details = [
      this._row(t('field.manufacturer'), asset.manufacturer),
      this._row(t('field.model'), asset.model),
      this._row(t('field.area_id'), areaName(this._hass?.areas, asset.area_id)),
      this._row(t('field.cost'), cost),
      this._row(t('field.manual_url'), manual, true),
      meta,
    ].join('');
    const detailsCard = details
      ? `<div class="hk-section">${escapeHTML(t('detail.about'))}</div>
         <ha-card class="hk-detail-card"><div class="hk-detail-inner">${details}</div></ha-card>`
      : '';
    return `
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">
        <div class="hk-detail-title">${escapeHTML(title)}</div>
        <div class="hk-chips">${kindChip}${parentChip}</div>
        <div class="hk-detail-actions">
          <ha-button raised class="d-edit">${escapeHTML(t('btn.edit'))}</ha-button>
          <ha-button class="d-del">${escapeHTML(t('btn.delete'))}</ha-button>
        </div>
      </div></ha-card>
      ${detailsCard}
      ${this._partsSection(asset)}
      ${this._relatedTasksSection(asset)}
      ${this._subdevicesSection(asset)}
      ${this._historySection('asset', asset.id)}`;
  }

  private _partsSection(asset: Asset): string {
    const parts = asset.parts || [];
    if (!parts.length) return '';
    const chip = (label: string, cls = ''): string =>
      `<ha-assist-chip class="${cls}" label="${escapeHTML(label)}"></ha-assist-chip>`;
    const rows = parts
      .map((p) => {
        const isWear = p.type === 'wear';
        // Subtitle: the descriptive, identity bits (part number, vendor, cost).
        const sub: string[] = [];
        if (p.part_number) sub.push(p.part_number);
        if (p.vendor) sub.push(p.vendor);
        if (p.cost != null) sub.push(String(p.cost));
        const subLine = sub.length
          ? `<div class="hk-part-sub">${escapeHTML(sub.join(' · '))}</div>`
          : '';
        // Chips: the actionable status (cadence, last replaced, stock on hand).
        const chips: string[] = [];
        if (isWear && p.replace_interval && p.replace_unit) {
          chips.push(
            chip(
              t('part.every', {
                n: p.replace_interval,
                unit: t(`opt.unit.${p.replace_unit}`),
              }),
            ),
          );
        }
        if (isWear) {
          chips.push(
            chip(
              p.last_replaced
                ? t('part.replacedOn', { date: p.last_replaced })
                : t('part.neverReplaced'),
            ),
          );
        }
        const low = p.stock != null && p.reorder_at != null && p.stock <= p.reorder_at;
        if (p.stock != null) {
          chips.push(
            low
              ? chip(t('part.lowStock', { n: p.stock }), 'hk-overdue')
              : chip(t('part.inStock', { n: p.stock })),
          );
        }
        const chipRow = chips.length ? `<div class="hk-part-chips">${chips.join('')}</div>` : '';
        const badge = `<span class="hk-part-badge">${escapeHTML(t(`opt.part.${p.type}`))}</span>`;
        return `
          <div class="hk-part-row ${isWear ? 'wear' : 'consumable'}">
            <div class="hk-part-ic">
              <ha-svg-icon data-mdi="${isWear ? 'wear' : 'consumable'}"></ha-svg-icon>
            </div>
            <div class="grow">
              <div class="hk-part-name">${escapeHTML(p.name)}${badge}</div>
              ${subLine}
              ${chipRow}
            </div>
          </div>`;
      })
      .join('');
    return `
      <div class="hk-section">${escapeHTML(t('section.parts'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner hk-parts">${rows}</div></ha-card>`;
  }

  /** Set the mdi `path` on each part-row icon (ha-svg-icon takes a property). */
  private _wirePartIcons(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.hk-part-ic ha-svg-icon').forEach((el) => {
      (el as HTMLElement & { path?: string }).path =
        el.dataset.mdi === 'wear' ? MDI_WEAR : MDI_CONSUMABLE;
    });
  }

  private _relatedTasksSection(asset: Asset): string {
    const tasks = tasksForAsset(asset, this._tasks);
    if (!tasks.length) return '';
    const rows = tasks
      .map((task) => {
        const overdue = isOverdue(task);
        const chip = overdue
          ? `<ha-assist-chip class="hk-overdue" label="${escapeHTML(t('chip.overdue'))}"></ha-assist-chip>`
          : `<ha-assist-chip label="${escapeHTML(dueLabel(task))}"></ha-assist-chip>`;
        return `
          <div class="hk-rel detail-open" data-detail-kind="task" data-detail-id="${escapeHTML(
            task.id,
          )}" role="button" tabindex="0">
            <div class="grow"><div class="hk-name">${escapeHTML(task.name)}</div>
              <div class="hk-meta">${escapeHTML(recurrenceSummary(task))}</div></div>
            <div class="hk-chips">${chip}</div>
          </div>`;
      })
      .join('');
    return `
      <div class="hk-section">${escapeHTML(t('detail.relatedTasks'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
  }

  private _subdevicesSection(asset: Asset): string {
    const subs = this._assets.filter((a) => a.parent_asset_id === asset.id);
    if (!subs.length) return '';
    const rows = subs
      .map((sub) => {
        const title =
          sub.name || deviceName(this._hass?.devices, sub.device_id) || t('appliance.fallbackName');
        return `
          <div class="hk-rel detail-open" data-detail-kind="asset" data-detail-id="${escapeHTML(
            sub.id,
          )}" role="button" tabindex="0">
            <div class="grow"><div class="hk-name">${escapeHTML(title)}</div>
              <div class="hk-meta">${escapeHTML(assetSummary(sub, this._hass?.areas))}</div></div>
          </div>`;
      })
      .join('');
    return `
      <div class="hk-section">${escapeHTML(tn('asset.subdevices', subs.length))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${rows}</div></ha-card>`;
  }

  /**
   * Whether a managed task's owning integration is no longer loaded. A task is
   * orphaned when its `config_entry_id` is set but absent from the loaded-entry
   * set (uninstalled, disabled, or failing to set up). Without a recorded
   * `config_entry_id` we can't prove the owner is gone, so it isn't treated as
   * orphaned (the `force` service is the escape hatch for that edge case).
   */
  private _isManagedOrphan(task: Task): boolean {
    const id = task.managed_by?.config_entry_id;
    return Boolean(id) && !this._loadedEntryIds.has(id as string);
  }

  /** Renders a "Managed by X" chip (or "Integration offline" if orphaned). */
  private _managedChip(task: Task): string {
    const mb = task.managed_by;
    if (!mb) return '';
    if (this._isManagedOrphan(task)) {
      return `<ha-assist-chip class="hk-orphaned" label="${escapeHTML(t('chip.orphaned'))}"></ha-assist-chip>`;
    }
    return `<ha-assist-chip class="hk-managed" label="${escapeHTML(t('chip.managed', { name: mb.display_name }))}"></ha-assist-chip>`;
  }

  /**
   * A device chip that links to the device's HA config page and shows the
   * integration's brand logo (falling back to a generic device icon).
   */
  private _deviceChip(deviceId: string): string {
    const name = deviceName(this._hass?.devices, deviceId);
    const domain = deviceDomain(this._hass?.devices?.[deviceId], this._entryDomains);
    const icon = domain
      ? `<img slot="icon" class="hk-dev-img" alt="" src="${escapeHTML(
          brandLogoUrl(domain),
        )}" data-domain="${escapeHTML(domain)}" />`
      : `<ha-svg-icon slot="icon" class="hk-dev-img"></ha-svg-icon>`;
    return `<ha-assist-chip class="hk-device-chip" role="link" tabindex="0" data-device-id="${escapeHTML(
      deviceId,
    )}" label="${escapeHTML(name)}">${icon}</ha-assist-chip>`;
  }

  private _navigateToDevice(deviceId: string): void {
    history.pushState(null, '', `/config/devices/device/${deviceId}`);
    window.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Wire navigation + brand-logo fallback for every device chip in the tree. */
  private _wireDeviceChips(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.hk-device-chip').forEach((chip) => {
      const id = chip.dataset.deviceId;
      const go = (): void => {
        if (id) this._navigateToDevice(id);
      };
      chip.addEventListener('click', go);
      chip.addEventListener('keydown', (e) => {
        const key = (e as KeyboardEvent).key;
        if (key === 'Enter' || key === ' ') {
          e.preventDefault();
          go();
        }
      });
      const fallbackIcon = (): void => {
        const el = chip.querySelector('.hk-dev-img');
        if (!el) return;
        const svg = document.createElement('ha-svg-icon');
        (svg as HTMLElement & { path?: string }).path = MDI_DEVICES;
        svg.setAttribute('slot', 'icon');
        svg.className = 'hk-dev-img';
        el.replaceWith(svg);
      };
      const img = chip.querySelector<HTMLImageElement>('img.hk-dev-img');
      if (img) {
        img.addEventListener('error', () => {
          // First failure: retry the generic `_/` brand path; then give up.
          const domain = img.dataset.domain;
          if (domain && !img.dataset.retried) {
            img.dataset.retried = '1';
            img.src = brandLogoUrl(domain, true);
          } else {
            fallbackIcon();
          }
        });
      } else {
        fallbackIcon();
      }
    });
  }

  // ── ha-form schemas ─────────────────────────────────────────────────────────
  // The task form schema/data/payload helpers are shared with the dashboard card
  // (see `forms.ts`). Asset/part schemas below stay panel-only.

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

  /** Structured fields that wire into HA: the manual link and replacement cost. */
  private _structuredDetailsSchema(): FormField[] {
    return [
      { name: 'manual_url', selector: selText() },
      { name: 'cost', selector: selNumber(0) },
    ];
  }

  /** Schema for one free-form metadata entry. The value control swaps by type, and
   *  a `date` entry adds a "track as sensor" toggle (opt-in automation). */
  private _metadataSchema(m: MetadataEntry): FormField[] {
    const valueSelector = m.type === 'date' ? selDate() : selText();
    const fields: FormField[] = [
      {
        name: '',
        type: 'grid',
        schema: [
          {
            name: 'type',
            selector: selSelect([
              { value: 'text', label: t('opt.meta.text') },
              { value: 'link', label: t('opt.meta.link') },
              { value: 'date', label: t('opt.meta.date') },
            ]),
          },
          { name: 'label', selector: selText() },
        ],
      },
      { name: 'value', selector: valueSelector },
    ];
    if (m.type === 'date') fields.push({ name: 'track', selector: selBool() });
    return fields;
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
      {
        name: '',
        type: 'grid',
        schema: [
          { name: 'stock', selector: selNumber(0) },
          { name: 'reorder_at', selector: selNumber(0) },
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
      // Let the user record when the part was last replaced so the derived
      // maintenance task's clock starts from the real date instead of "now".
      base.push({ name: 'last_replaced', selector: selDate() });
    }
    return base;
  }

  // ── hydration: build/configure live HA components ───────────────────────────
  private _hydrate(): void {
    const root = this.shadowRoot;
    if (!root) return;

    // The completion-details dialog overlays any view, so build it first.
    const dialogHost = root.getElementById('hk-dialog-host');
    if (dialogHost && this._completion.open) this._renderCompletionDialog(dialogHost);

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

    // Detail page: just the back button, the detail's own action buttons, and
    // any device chips / completion-delete buttons it renders.
    if (this._detail) {
      root.getElementById('back-btn')?.addEventListener('click', () => this._closeDetail());
      this._wireDetailActions(root);
      this._wireDetailOpeners(root);
      this._wireDeviceChips(root);
      this._wirePartIcons(root);
      this._wireHistoryDeletes(root);
      return;
    }

    // Tab navigation. Listen on each tab (click) and on the group's shoelace
    // `sl-tab-show` event (whichever fires) — both funnel through _switchView,
    // which is a no-op when the view is unchanged.
    root.getElementById('tab-tasks')?.addEventListener('click', () => this._switchView('tasks'));
    root
      .getElementById('tab-appliances')
      ?.addEventListener('click', () => this._switchView('appliances'));
    root
      .getElementById('tab-settings')
      ?.addEventListener('click', () => this._switchView('settings'));
    root.querySelector('ha-tab-group')?.addEventListener('sl-tab-show', (e: Event) => {
      const name = (e as CustomEvent<{ name?: string }>).detail?.name;
      if (name === 'tasks' || name === 'appliances' || name === 'settings') this._switchView(name);
    });

    root.getElementById('add-btn')?.addEventListener('click', () => {
      if (this._view === 'tasks') this._openCreate();
      else this._openCreateAsset();
    });

    root.getElementById('export-btn')?.addEventListener('click', () => this._exportInventory());

    root
      .getElementById('cleanup-orphans-btn')
      ?.addEventListener('click', () => void this._cleanupOrphans());

    // Filter / group-by segmented controls.
    root.querySelectorAll<HTMLElement>('.hk-seg-btn').forEach((b) =>
      b.addEventListener('click', () => {
        const seg = (b.closest('.hk-seg') as HTMLElement | null)?.dataset.seg;
        const val = b.dataset.segVal;
        if (!val) return;
        if (seg === 'group') this._setGroupBy(val as GroupBy);
        else if (seg === 'filter') this._setFilter(val as TaskFilter);
      }),
    );
    // Remember which group sections the user collapsed (no re-render needed).
    root.querySelectorAll<HTMLDetailsElement>('details.hk-group').forEach((d) =>
      d.addEventListener('toggle', () => {
        const key = d.dataset.groupKey || '';
        if (d.open) this._collapsed.delete(key);
        else this._collapsed.add(key);
      }),
    );

    // Forms.
    const host = root.getElementById('hk-form-host');
    if (host) {
      if (this._view === 'tasks' && this._edit.open) this._renderTaskForm(host);
      else if (this._view === 'appliances' && this._assetEdit.open) this._renderAssetForm(host);
    }
    const settingsHost = root.getElementById('hk-settings-host');
    if (settingsHost) this._renderSettingsForm(settingsHost);
    const companionsHost = root.getElementById('hk-companions-host');
    if (companionsHost) this._renderCompanions(companionsHost);

    // Card actions: the row opens the detail page; tasks keep a quick "Done".
    this._wireDetailOpeners(root);
    if (this._view === 'tasks') {
      root.querySelectorAll<HTMLElement>('.done-btn').forEach((b) =>
        b.addEventListener('click', () => {
          const task = this._tasks.find((x) => x.id === b.dataset.id);
          if (task) void this._complete(task);
        }),
      );
    }
    // A completion-blocked Done (card row or detail) explains why on click rather
    // than completing — its source clears it.
    root.querySelectorAll<HTMLElement>('.done-blocked-wrap').forEach((b) =>
      b.addEventListener('click', () => {
        const task = this._tasks.find((x) => x.id === b.dataset.id);
        if (task) this._notifyBlocked(task);
      }),
    );
    this._wireDeviceChips(root);
  }

  /** Wire every `.detail-open` row to open its object's detail page. */
  private _wireDetailOpeners(root: ShadowRoot): void {
    root.querySelectorAll<HTMLElement>('.detail-open').forEach((el) => {
      const go = (): void => {
        const kind = el.dataset.detailKind;
        const id = el.dataset.detailId;
        if ((kind === 'task' || kind === 'asset') && id) this._openDetail(kind, id);
      };
      el.addEventListener('click', go);
      el.addEventListener('keydown', (e) => {
        const key = (e as KeyboardEvent).key;
        if (key === 'Enter' || key === ' ') {
          e.preventDefault();
          go();
        }
      });
    });
  }

  /** Wire the detail page's Done / Edit / Delete / Open-in buttons. */
  private _wireDetailActions(root: ShadowRoot): void {
    const d = this._detail;
    if (!d) return;
    if (d.kind === 'task') {
      const task = this._tasks.find((x) => x.id === d.id);
      if (!task) return;
      root.querySelector('.d-done')?.addEventListener('click', () => void this._complete(task));
      root
        .querySelector('.d-done-blocked-wrap')
        ?.addEventListener('click', () => this._notifyBlocked(task));
      root.querySelector('.d-edit')?.addEventListener('click', () => this._openEdit(task));
      root.querySelector('.d-del')?.addEventListener('click', () => {
        // The detail is about to vanish: replace it with its list so Forward
        // can't return to a deleted task.
        this._navigate({ view: 'tasks', detail: null }, true);
        void this._delete(task);
      });
      // "Edit in X" deep link: navigate to the managing integration's config page
      // (same helper the Companions "Configure" button uses).
      root.querySelectorAll<HTMLElement>('.d-open-in').forEach((btn) => {
        btn.addEventListener('click', () => {
          const domain = btn.dataset.domain;
          if (domain) this._navigateToIntegration(domain);
        });
      });
      return;
    }
    const asset = this._assets.find((x) => x.id === d.id);
    if (!asset) return;
    root.querySelector('.d-edit')?.addEventListener('click', () => this._openEditAsset(asset));
    root.querySelector('.d-del')?.addEventListener('click', () => {
      // The detail is about to vanish: replace it with its list so Forward
      // can't return to a deleted appliance.
      this._navigate({ view: 'appliances', detail: null }, true);
      void this._deleteAsset(asset);
    });
  }

  private _switchView(view: 'tasks' | 'appliances' | 'settings'): void {
    if (this._view === view) return;
    // Switching tabs is a lateral move, not a drill-in: replace so Back doesn't
    // retrace every tab toggle.
    this._navigate({ view, detail: null }, true);
  }

  /** Render the Settings tab — an `ha-form` mirror of the options flow that
   *  autosaves each change (the backend reloads + re-runs the problem sync). */
  private _renderSettingsForm(host: HTMLElement): void {
    const opts: HomeKeeperOptions = this._options ?? {
      sync_problem_sensors: false,
      problem_sensor_exclude_entities: [],
      problem_sensor_exclude_areas: [],
      problem_sensor_exclude_labels: [],
      one_off_retention_days: 0,
    };
    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-settings';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';
    inner.innerHTML = `
      <div class="hk-form-title">${escapeHTML(t('settings.heading'))}</div>
      <div class="hk-settings-intro">${escapeHTML(t('settings.help'))}</div>`;
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = settingsSchema();
    form.data = { ...opts };
    form.computeLabel = (s: { name: string }): string => (s.name ? t('settings.' + s.name) : '');
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      void this._saveOptions(value as Partial<HomeKeeperOptions>);
    });
    this._liveHassEls.push(form);
    inner.appendChild(form);
    card.appendChild(inner);
    host.appendChild(card);
  }

  private async _saveOptions(value: Partial<HomeKeeperOptions>): Promise<void> {
    if (!this._hass) return;
    // Keep local state in sync optimistically so the form doesn't flicker; the
    // backend persists, reloads the entry and re-runs the problem-sensor sync.
    this._options = { ...(this._options as HomeKeeperOptions), ...value };
    try {
      await api.setOptions(this._hass, value);
      // setOptions resolves only once the backend has reloaded and reconciled the
      // synced problem-sensor tasks for the new exclusions. Refresh our cached
      // tasks (without re-rendering — that would tear down the form the user is
      // still editing) so the change is reflected the moment they return to the
      // Tasks tab, rather than lingering until the next refresh.
      await this._reload();
      this._toast(t('settings.saved'));
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
  }

  /** Render the Settings → Companions section: integrations that work with
   *  Home Keeper. *Connected* rows (self-registered, or a detected glue) deep-link
   *  to the companion's own options page; *Suggested* rows (a popular upstream is
   *  installed but its glue isn't) offer an install link and can be dismissed. */
  private _renderCompanions(host: HTMLElement): void {
    const all = this._companions ?? [];
    const connected = all.filter((c) => c.status === 'connected');
    const suggested = all.filter((c) => c.status === 'suggested');

    const card = document.createElement('ha-card');
    card.className = 'hk-form-card';
    card.id = 'hk-companions';
    const inner = document.createElement('div');
    inner.className = 'hk-form-inner';

    const sections: string[] = [
      `<div class="hk-form-title">${escapeHTML(t('companions.heading'))}</div>`,
      `<div class="hk-settings-intro">${escapeHTML(t('companions.help'))}</div>`,
    ];
    if (!connected.length && !suggested.length) {
      sections.push(`<ha-alert alert-type="info">${escapeHTML(t('companions.empty'))}</ha-alert>`);
    }
    if (connected.length) {
      sections.push(
        `<div class="hk-companion-group">${escapeHTML(t('companions.connected'))}</div>`,
        ...connected.map((c) => this._companionRow(c)),
      );
    }
    if (suggested.length) {
      sections.push(
        `<div class="hk-companion-group">${escapeHTML(t('companions.suggested'))}</div>`,
        ...suggested.map((c) => this._companionRow(c)),
      );
    }
    inner.innerHTML = sections.join('');
    card.appendChild(inner);
    host.appendChild(card);
    this._wireCompanions(inner);
  }

  /** One companion row's HTML (icon, name + status chip, description, actions). */
  private _companionRow(c: Companion): string {
    const icon = escapeHTML(c.icon || 'mdi:puzzle');
    const chipLabel = c.status === 'connected' ? t('companions.chip.connected') : t('companions.chip.suggested');
    const chipClass = c.status === 'connected' ? 'hk-comp-connected' : 'hk-comp-suggested';
    const actions: string[] =
      c.status === 'connected'
        ? [
            `<ha-button class="hk-comp-configure" data-domain="${escapeHTML(c.configure_domain || c.domain)}">${escapeHTML(t('companions.configure'))}</ha-button>`,
          ]
        : [
            `<ha-button raised class="hk-comp-install" data-url="${escapeHTML(c.install_url || '')}">${escapeHTML(t('companions.install'))}</ha-button>`,
            `<ha-button class="hk-comp-dismiss" data-domain="${escapeHTML(c.domain)}">${escapeHTML(t('companions.dismiss'))}</ha-button>`,
          ];
    if (c.docs_url) {
      actions.push(
        `<ha-button class="hk-comp-docs" data-url="${escapeHTML(c.docs_url)}">${escapeHTML(t('companions.docs'))}</ha-button>`,
      );
    }
    const desc = c.description
      ? `<div class="hk-companion-desc">${escapeHTML(c.description)}</div>`
      : '';
    return `
      <div class="hk-companion">
        <ha-icon class="hk-companion-ic" icon="${icon}"></ha-icon>
        <div class="hk-companion-body">
          <div class="hk-companion-name">
            ${escapeHTML(c.name)}
            <ha-assist-chip class="${chipClass}" label="${escapeHTML(chipLabel)}"></ha-assist-chip>
          </div>
          ${desc}
        </div>
        <div class="hk-companion-actions">${actions.join('')}</div>
      </div>`;
  }

  /** Wire a companion section's Configure / Install / Docs / Dismiss buttons. */
  private _wireCompanions(root: HTMLElement): void {
    root.querySelectorAll<HTMLElement>('.hk-comp-configure').forEach((b) =>
      b.addEventListener('click', () => {
        const domain = b.dataset.domain;
        if (domain) this._navigateToIntegration(domain);
      }),
    );
    root.querySelectorAll<HTMLElement>('.hk-comp-install, .hk-comp-docs').forEach((b) =>
      b.addEventListener('click', () => {
        const url = b.dataset.url;
        // Defense in depth: the backend already restricts docs_url to http(s), but
        // only open externally-supplied links with a safe scheme regardless.
        if (url && /^https?:\/\//i.test(url)) window.open(url, '_blank', 'noopener');
      }),
    );
    root.querySelectorAll<HTMLElement>('.hk-comp-dismiss').forEach((b) =>
      b.addEventListener('click', () => {
        const domain = b.dataset.domain;
        if (domain) void this._dismissCompanion(domain);
      }),
    );
  }

  /** Deep-link to an integration's config page (same pattern as "Edit in X"). */
  private _navigateToIntegration(domain: string): void {
    history.pushState(null, '', `/config/integrations/integration/${domain}`);
    window.dispatchEvent(
      new CustomEvent('location-changed', {
        detail: { replace: false },
        bubbles: true,
        composed: true,
      }),
    );
  }

  /** Hide a suggested companion by persisting its domain to dismissed_companions. */
  private async _dismissCompanion(domain: string): Promise<void> {
    if (!this._hass) return;
    const current = this._options?.dismissed_companions ?? [];
    if (current.includes(domain)) return;
    const dismissed_companions = [...current, domain];
    try {
      await api.setOptions(this._hass, { dismissed_companions });
      await this._refresh();
    } catch (err) {
      this._toast(String((err as { message?: string })?.message || err));
    }
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

    const form = this._makeForm(taskSchema(task), taskFormData(task), (value) => {
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

  /** Build the completion-details dialog (log a new completion, or edit a past one). */
  private _renderCompletionDialog(host: HTMLElement): void {
    const c = this._completion;
    if (!c.task) return;
    const editing = c.ts != null;
    const dialog = document.createElement('ha-dialog') as HTMLElement & {
      heading?: string;
    };
    dialog.setAttribute('open', '');
    dialog.setAttribute(
      'heading',
      editing ? t('completion.edit') : t('completion.title', { name: c.task.name }),
    );
    dialog.addEventListener('closed', () => {
      if (this._completion.open) this._closeCompletionDialog();
    });

    const body = document.createElement('div');
    body.className = 'hk-completion-body';

    // note / cost / who via ha-form; required fields get the asterisk cue.
    const req = new Set(c.required);
    const schema: FormField[] = [
      { name: 'note', required: req.has('note'), selector: selText(true) },
      { name: 'cost', required: req.has('cost'), selector: selNumber(0) },
      { name: 'who', required: req.has('who'), selector: selEntity({ domain: 'person' }) },
    ];
    const form = this._makeForm(
      schema,
      { note: c.data.note ?? '', cost: c.data.cost ?? undefined, who: c.data.who ?? undefined },
      (value) => {
        this._completion.data = {
          ...this._completion.data,
          note: (value.note as string) || undefined,
          cost: value.cost == null || value.cost === '' ? undefined : Number(value.cost),
          who: (value.who as string) || undefined,
        };
        this._completion.error = undefined;
      },
    );
    body.appendChild(form);

    // Photo upload via HA's native picture-upload, if the element is available in
    // this frontend build (degrade gracefully if not — the rest still works).
    if (customElements.get('ha-picture-upload')) {
      const label = document.createElement('div');
      label.className = 'hk-completion-photo-label';
      label.textContent = t('completion.photo');
      const upload = document.createElement('ha-picture-upload') as HTMLElement & {
        hass?: Hass;
        value?: string | null;
      };
      upload.hass = this._hass;
      upload.value = c.data.photo ?? null;
      this._liveHassEls.push(upload);
      const onPhoto = (): void => {
        this._completion.data = { ...this._completion.data, photo: upload.value || undefined };
      };
      upload.addEventListener('change', onPhoto);
      upload.addEventListener('value-changed', onPhoto);
      body.append(label, upload);
    }

    if (c.error) {
      const err = document.createElement('ha-alert');
      err.setAttribute('alert-type', 'error');
      err.textContent = c.error;
      body.appendChild(err);
    }
    dialog.appendChild(body);

    // Primary action: log (or save edit). Optional-mode logging also offers "skip
    // details" to complete with nothing recorded.
    const primary = document.createElement('ha-button');
    primary.setAttribute('slot', 'primaryAction');
    primary.setAttribute('raised', '');
    primary.textContent = editing ? t('btn.save') : t('completion.markDone');
    primary.addEventListener('click', () => void this._submitCompletion());
    dialog.appendChild(primary);

    if (!editing && c.task.completion_detail === 'optional') {
      const skip = document.createElement('ha-button');
      skip.setAttribute('slot', 'secondaryAction');
      skip.textContent = t('completion.skip');
      skip.addEventListener('click', () => {
        this._completion.data = {};
        void this._submitCompletion();
      });
      dialog.appendChild(skip);
    }
    const cancel = document.createElement('ha-button');
    cancel.setAttribute('slot', 'secondaryAction');
    cancel.textContent = t('btn.cancel');
    cancel.addEventListener('click', () => this._closeCompletionDialog());
    dialog.appendChild(cancel);

    host.appendChild(dialog);
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

    inner.appendChild(this._section(t('section.reference')));
    inner.appendChild(
      this._makeForm(
        this._structuredDetailsSchema(),
        { manual_url: x.manual_url ?? '', cost: x.cost ?? undefined },
        mergeAsset,
      ),
    );

    this._renderMetadataEditor(inner);

    this._renderPartsEditor(inner);

    inner.appendChild(this._section(t('section.related')));
    inner.appendChild(
      this._makeForm(
        [{ name: 'related_device_ids', selector: selDevice(true) }],
        { related_device_ids: x.related_device_ids ?? [] },
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

  private _renderMetadataEditor(inner: HTMLElement): void {
    inner.appendChild(this._section(t('section.metadata')));
    const entries = this._assetEdit.asset?.metadata || [];
    entries.forEach((m, i) => {
      const box = document.createElement('div');
      box.className = 'hk-part';
      box.dataset.idx = String(i);
      const head = document.createElement('div');
      head.className = 'hk-part-head';
      head.innerHTML = `<span class="label">${escapeHTML(t('section.meta_n', { n: i + 1 }))}</span>`;
      const del = document.createElement('ha-icon-button');
      del.className = 'part-del';
      del.setAttribute('label', t('btn.removeField'));
      del.addEventListener('click', () => {
        const list = this._assetEdit.asset?.metadata || [];
        this._assetEdit.asset!.metadata = list.filter((_, j) => j !== i);
        this._render();
      });
      head.appendChild(del);
      box.appendChild(head);

      const form = this._makeForm(
        this._metadataSchema(m),
        {
          type: m.type ?? 'text',
          label: m.label ?? '',
          value: m.value ?? '',
          track: Boolean(m.track),
        },
        (value) => {
          const prevType = this._assetEdit.asset?.metadata?.[i]?.type;
          const newType = (value.type as MetadataType) ?? 'text';
          const updated: MetadataEntry = {
            id: m.id,
            type: newType,
            label: String(value.label ?? ''),
            // A date control emits selector-shaped strings; text/link emit text.
            value: value.value != null ? String(value.value) : '',
            // `track` only applies to dates — drop it otherwise so it can't strand.
            track: newType === 'date' ? Boolean(value.track) : undefined,
          };
          const list = [...(this._assetEdit.asset?.metadata || [])];
          list[i] = updated;
          this._assetEdit.asset!.metadata = list;
          // Re-render when the type changes so the value control (and the date
          // "track" toggle) swaps to match.
          if (newType !== prevType) this._render();
        },
      );
      box.appendChild(form);

      if (m.type === 'date') {
        const note = document.createElement('div');
        note.className = 'hk-meta';
        note.textContent = t('meta.trackHint');
        box.appendChild(note);
      }
      inner.appendChild(box);
    });

    // Quick-add seeds for the common fields (each prelabeled, right type), plus a
    // generic blank entry — they're all just entries in the list.
    const seeds: { label: string; type: MetadataType }[] = [
      { label: t('meta.seed.serial'), type: 'text' },
      { label: t('meta.seed.warranty_expiry'), type: 'date' },
      { label: t('meta.seed.purchase_date'), type: 'date' },
      { label: t('meta.seed.install_date'), type: 'date' },
      { label: t('meta.seed.warranty_provider'), type: 'text' },
      { label: t('meta.seed.vendor'), type: 'text' },
      { label: t('meta.seed.notes'), type: 'text' },
    ];
    const addEntry = (entry: MetadataEntry): void => {
      const list = [...(this._assetEdit.asset?.metadata || [])];
      list.push(entry);
      this._assetEdit.asset!.metadata = list;
      this._render();
    };
    const seedRow = document.createElement('div');
    seedRow.className = 'hk-meta-seeds';
    for (const s of seeds) {
      const b = document.createElement('ha-button');
      b.textContent = s.label;
      b.addEventListener('click', () => addEntry({ type: s.type, label: s.label, value: '' }));
      seedRow.appendChild(b);
    }
    const custom = document.createElement('ha-button');
    custom.textContent = t('btn.addField');
    custom.addEventListener('click', () => addEntry({ type: 'text', label: '', value: '' }));
    seedRow.appendChild(custom);
    inner.appendChild(seedRow);
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
          stock: p.stock ?? undefined,
          reorder_at: p.reorder_at ?? undefined,
          replace_interval: p.replace_interval ?? undefined,
          replace_unit: p.replace_unit ?? 'months',
          last_replaced: p.last_replaced ?? undefined,
        },
        (value) => {
          const prevType = this._assetEdit.asset?.parts?.[i]?.type;
          const updated: Part = {
            id: p.id,
            // The last-replaced date is only editable for wear items; preserve any
            // existing value when the part is a consumable (no field shown).
            last_replaced:
              value.type === 'wear'
                ? value.last_replaced
                  ? String(value.last_replaced)
                  : null
                : (p.last_replaced ?? null),
            name: String(value.part_name ?? ''),
            part_number: String(value.part_number ?? ''),
            type: (value.type as Part['type']) ?? 'consumable',
            vendor: String(value.vendor ?? ''),
            cost: value.cost != null && value.cost !== '' ? Number(value.cost) : null,
            stock: value.stock != null && value.stock !== '' ? Number(value.stock) : null,
            reorder_at:
              value.reorder_at != null && value.reorder_at !== ''
                ? Number(value.reorder_at)
                : null,
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

      if (p.type === 'wear') {
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

  /** Give an ha-icon-button its mdi icon via the native `path` property. */
  private _setIcon(button: HTMLElement, path: string): void {
    (button as HTMLElement & { path?: string }).path = path;
  }

  // ── completion-history rendering (inline in the detail page) ─────────────────
  private _historyBody(groups: HistoryGroup[]): string {
    const withAny = groups.filter((g) => (g.completions?.length ?? 0) > 0);
    if (!withAny.length) {
      return `<ha-alert alert-type="info">${escapeHTML(t('history.empty'))}</ha-alert>`;
    }
    const multi = withAny.length > 1;
    return withAny.map((g) => this._historyGroup(g, multi)).join('');
  }

  private _historyGroup(group: HistoryGroup, showHead: boolean): string {
    // Sort the completion objects (not just Dates) so each row keeps its `ts`
    // string for the per-row delete button.
    const comps = [...(group.completions || [])]
      .filter((c) => !Number.isNaN(new Date(c.ts).getTime()))
      .sort((a, b) => new Date(b.ts).getTime() - new Date(a.ts).getTime());
    const stats = completionStats(group.completions);
    const sub: string[] = [tn('history.count', stats.count)];
    if (stats.avgIntervalDays) sub.push(t('history.cadence', { days: stats.avgIntervalDays }));
    const archived = group.archived
      ? `<span class="hk-hist-archived">${escapeHTML(t('history.archived'))}</span>`
      : '';
    const head = showHead
      ? `<div class="hk-hist-head">${escapeHTML(group.name)}${archived}
           <span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span></div>`
      : `<div class="hk-hist-head"><span class="hk-hist-sub">${escapeHTML(sub.join(' · '))}</span>${archived}</div>`;
    // Encode the deletion target on each trash button: a live task carries
    // `data-del-task`; an archived group carries `data-del-asset` + `data-del-arch`.
    const delAttrs = group.taskId
      ? `data-del-task="${escapeHTML(group.taskId)}"`
      : group.assetId
        ? `data-del-asset="${escapeHTML(group.assetId)}" data-del-arch="${escapeHTML(group.archivedTaskId || '')}"`
        : '';
    // Editing a completion's metadata only applies to a live task (the backend's
    // update_completion works on tasks, not an appliance's archived history).
    const editTask = !group.archived ? group.taskId : undefined;
    const items = comps
      .map((c) => {
        const d = new Date(c.ts);
        const date = d.toLocaleDateString(undefined, {
          year: 'numeric',
          month: 'short',
          day: 'numeric',
        });
        const editBtn = editTask
          ? `<ha-icon-button class="hk-hist-edit" data-edit-task="${escapeHTML(editTask)}" data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.edit'))}"></ha-icon-button>`
          : '';
        return `<li>
            <div class="hk-hist-row">
              <span class="date">${escapeHTML(date)}</span>
              <span class="when">${escapeHTML(this._relativeDay(d))}</span>
              <span class="hk-hist-actions">${editBtn}<ha-icon-button class="hk-hist-del" ${delAttrs} data-ts="${escapeHTML(c.ts)}" label="${escapeHTML(t('btn.delete'))}"></ha-icon-button></span>
            </div>
            ${this._completionMeta(c)}
          </li>`;
      })
      .join('');
    return `<div class="hk-hist-group">${head}<ul class="hk-hist-list">${items}</ul></div>`;
  }

  /** Render a completion's recorded metadata (note / cost / who / photo), if any. */
  private _completionMeta(c: Completion): string {
    const bits: string[] = [];
    if (c.cost != null) bits.push(escapeHTML(this._formatCost(c.cost)));
    if (c.who) bits.push(escapeHTML(t('completion.by', { who: this._personName(c.who) })));
    const line = bits.length
      ? `<span class="hk-hist-chips">${bits.join(' · ')}</span>`
      : '';
    const note = c.note ? `<span class="hk-hist-note">${escapeHTML(c.note)}</span>` : '';
    const photo = c.photo
      ? `<a href="${escapeHTML(c.photo)}" target="_blank" rel="noopener"><img class="hk-hist-photo" src="${escapeHTML(c.photo)}" alt="${escapeHTML(t('completion.photo'))}" /></a>`
      : '';
    if (!line && !note && !photo) return '';
    return `<div class="hk-hist-meta">${line}${note}${photo}</div>`;
  }

  /** Format a cost in the instance's configured currency (falls back to the number). */
  private _formatCost(amount: number): string {
    const currency = this._hass?.config?.currency;
    if (currency) {
      try {
        return new Intl.NumberFormat(this._hass?.language, {
          style: 'currency',
          currency,
        }).format(amount);
      } catch {
        /* fall through to a bare number */
      }
    }
    return String(amount);
  }

  /** Resolve a person entity id to its friendly name (falls back to the id). */
  private _personName(entityId: string): string {
    const friendly = this._hass?.states?.[entityId]?.attributes?.friendly_name;
    return typeof friendly === 'string' && friendly ? friendly : entityId;
  }

  /** Set the trash/pencil icons and wire each per-completion delete/edit button. */
  private _wireHistoryDeletes(root: ParentNode): void {
    root.querySelectorAll<HTMLElement>('.hk-hist-del').forEach((b) => {
      this._setIcon(b, MDI_DELETE);
      b.addEventListener('click', () => {
        const ts = b.dataset.ts;
        if (!ts) return;
        if (b.dataset.delTask) void this._deleteCompletion(b.dataset.delTask, ts);
        else if (b.dataset.delAsset)
          void this._deleteArchivedCompletion(b.dataset.delAsset, b.dataset.delArch || '', ts);
      });
    });
    root.querySelectorAll<HTMLElement>('.hk-hist-edit').forEach((b) => {
      this._setIcon(b, MDI_EDIT);
      b.addEventListener('click', () => {
        const ts = b.dataset.ts;
        const taskId = b.dataset.editTask;
        if (!ts || !taskId) return;
        const task = this._tasks.find((x) => x.id === taskId);
        const comp = task?.completions?.find((c) => c.ts === ts);
        if (task && comp) this._openCompletionEdit(task, comp);
      });
    });
  }

  /** "today" / "yesterday" / "N days ago" for a past completion date. */
  private _relativeDay(d: Date, now: Date = new Date()): string {
    const days = Math.round((now.getTime() - d.getTime()) / 86_400_000);
    if (days <= 0) return t('due.today');
    if (days === 1) return t('due.yesterday');
    return tn('due.days_ago', days);
  }
}
