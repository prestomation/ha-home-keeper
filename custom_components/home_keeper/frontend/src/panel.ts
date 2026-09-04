import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import { SIGNED_URL_REFRESH_MS, SignedUrlCache, assetFileRefs } from './documents';
import {
  buildTaskPayload,
  consumableLinkToken,
  duplicateTaskSeed,
  type FormField,
  type HaFormElement,
} from './forms';
import { setLanguage, t } from './i18n';
import {
  createPreview,
  ensureMarkdown,
  markdownBlock,
  markdownReady,
  wireMarkdown,
  type MarkdownPreview,
} from './markdown';
import { renderAssetForm } from './panel-asset-form';
import { sourceOwnedTask, wireDeviceChips } from './panel-chips';
import { controls, wireControls } from './panel-controls';
import { detailView, wireDetail, wireDetailOpeners } from './panel-detail';
import {
  openCompletionDialog,
  renderCompletionDialog,
  renderMoveCompletionDialog,
  teardownOverlay,
} from './panel-dialogs';
import type { PanelHost } from './panel-host';
import { REQUIRED_COMPONENTS } from './panel-icons';
import { assetsList, tasksList, wireLists } from './panel-lists';
import {
  settingsBackbar,
  settingsIndex,
  settingsRail,
  settingsSectionList,
  switchView,
  wireSettings,
} from './panel-settings';
import { STYLES } from './panel-styles';
import { renderTaskForm } from './panel-task-form';
import {
  LS_ASSET_FILTER,
  LS_ASSET_VIEW,
  LS_FILTER,
  LS_GROUP,
  LS_PROFILE,
  LS_TREE_COLLAPSED,
  type AssetEditState,
  type AssetFilter,
  type AssetView,
  type CompletionDialogState,
  type EditState,
  type GroupBy,
  type MoveCompletionDialogState,
  type NoteTarget,
  type TaskFilter,
} from './panel-types';
import { setAssetError } from './panel-upload';
import type {
  Asset,
  AssetKind,
  Companion,
  Hass,
  HomeKeeperOptions,
  ManagedBy,
  PanelInfo,
  Profile,
  Task,
} from './types';
import {
  toast,
  btnAttrs,
  type BtnWeight,
  buildPath,
  escapeHTML,
  parseRoute,
  scanRequired,
  type PanelLocation,
  type PanelView,
  type AssetTab,
  DEFAULT_ASSET_TAB,
  type SettingsSection,
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
export class HomeKeeperPanel extends HTMLElement implements PanelHost {
  _hass?: Hass;
  public panel?: PanelInfo;
  public narrow = false;
  _tasks: Task[] = [];
  _assets: Asset[] = [];
  _completion: CompletionDialogState = {
    open: false,
    task: null,
    data: {},
    required: [],
  };
  _moveCompletion: MoveCompletionDialogState = {
    open: false,
    task: null,
    ts: '',
  };
  _confirmDelete: { open: boolean; label: string; onConfirm: (() => void) | null } = {
    open: false,
    label: '',
    onConfirm: null,
  };
  // Body-level scrim for the delete confirmation overlay.
  _confirmScrim: HTMLElement | null = null;
  // The document keydown (Escape) handler bound while the confirm dialog is open, held
  // as a field so disconnectedCallback can remove it if we unmount mid-dialog.
  _confirmOnKey: ((e: KeyboardEvent) => void) | null = null;
  // config entry id -> integration domain, for resolving device brand logos.
  _entryDomains: Record<string, string> = {};
  // config entry ids that are currently loaded, for managed-task orphan detection.
  _loadedEntryIds: Set<string> = new Set();
  _edit: EditState = { open: false, task: null };
  // On `PanelHost`, so `panel-history.collapsibleSection` can remember which advanced
  // sections the user left open. Hazard for anything else that reaches it: `.asset` is
  // mutated **in place** by the appliance editors (each field handler merges into the
  // same object) and read back by `_submitAssetForm` — so a region must not replace the
  // object or hold a copy of it, or the save writes stale values.
  _assetEdit: AssetEditState = { open: false, asset: null };
  // Cancels the in-flight upload (see `_runUpload`); undefined when none is running.
  _uploadAbort?: AbortController;
  _uploadShowTimer?: ReturnType<typeof setTimeout>;
  // One-shot: the upload-error key to scroll to on the next render.
  _scrollToError?: string;
  _view: 'tasks' | 'appliances' | 'settings' = 'tasks';
  // Integration options for the Settings tab (loaded lazily with the rest).
  _options: HomeKeeperOptions | null = null;
  // Available mobile_app_* notify services (for the Notifications profile editor).
  _notifyTargets: string[] = [];
  // Home Keeper's own todo entities, kept out of the shopping-list picker.
  _ownTodoEntities: string[] = [];
  // Companion integrations shown on the Settings tab (loaded with the rest).
  _companions: Companion[] = [];
  // HA tag-registry entries as picker options, for the task form's tag field and
  // the tag chip. Best-effort: an empty list still leaves a typable combo box.
  _tags: { value: string; label: string }[] = [];
  // List controls (persisted in localStorage).
  _groupBy: GroupBy = 'status';
  _filter: TaskFilter = 'all';
  _assetFilter: AssetFilter = 'active';
  _assetView: AssetView = 'flat';
  _treeCollapsed = new Set<string>();
  // Selected saved Profile id to filter the task list by ('' = no profile).
  _profile = '';
  // Group sections collapsed by the user, keyed by "<group>:<bucket>".
  // Group sections the user collapsed this session (open is the default). The
  // "monitored" status bucket — dormant condition-driven tasks like healthy
  // batteries — starts collapsed so it stays out of the way but one click to browse.
  _collapsed = new Set<string>(['status:monitored', 'status:completed']);
  // Settings sections (profiles, notifications) the user has collapsed this session.
  _settingsSectionCollapsed = new Set<string>();
  // Individual profile/notification items the user has expanded (default: collapsed).
  _itemExpanded = new Set<string>();
  // Task rows whose chip overflow the user unfolded, so the chips past the second are
  // reachable in the list rather than only on the detail page.
  _chipsExpanded = new Set<string>();
  // The object whose full detail page is open, or null for the list view.
  _detail: PanelLocation['detail'] = null;
  // Which Settings section the URL names, or null for the section index. Both are
  // rendered at every width and CSS decides which one shows: a desktop has room for
  // all six sections beside the rail, a phone shows the index or one section.
  _settingsSection: SettingsSection | null = null;
  // Short-lived signed URLs for the uploaded files on screen, minted ahead of the click
  // so every file is opened by a native anchor tap rather than a JS `window.open` the
  // iOS app's WKWebView would swallow (issue #164). Filled by `_signFiles`.
  _signedFiles = new SignedUrlCache();
  // Pending re-sign of the on-screen files' URLs before they expire; see `_armResign`.
  private _resignTimer: ReturnType<typeof setTimeout> | null = null;
  // The panel's URL prefix (e.g. `/home-keeper`), supplied by HA via `route`.
  // Navigation builds absolute paths from it; falls back until the first route.
  private _routePrefix = '/home-keeper';
  private _loaded = false;
  private _loadError = false;
  // Whether the current user has dismissed the first-run intro banner — loaded from
  // HA's per-user frontend data store in `_reload` (see `_introCard`).
  _introDismissed = false;
  // In-flight refresh, shared by overlapping callers. Both `set hass` (first update)
  // and `_init` gate on `!this._loaded`, and `_loaded` only flips true after the awaited
  // reload — so without coalescing they can pass the check and run two concurrent full
  // loads. Callers await the same promise, so none no-ops and all see a completed render.
  private _refreshing: Promise<void> | null = null;
  // Debounce timers for per-keystroke option saves (profiles / notifications), so a
  // text edit doesn't fire a config-entry reload on every character (and a slow
  // earlier response can't clobber a later one — only the trailing save runs).
  private _persistTimers: Record<string, ReturnType<typeof setTimeout>> = {};
  // A form to open once the pending navigation settles in `_applyLocation` (opening
  // an edit form from a detail page changes the URL, which would otherwise clear it).
  private _pendingEdit: Partial<Task> | null = null;
  private _pendingAssetEdit: Partial<Asset> | null = null;
  // What is being note-edited inline on a detail page, or null. Notes are long-form
  // prose that renders as Markdown, so both tasks and appliances get a dedicated
  // full-width editor on their detail page rather than a cramped row in the edit form
  // (parts keep theirs in the appliance's parts editor, alongside their other fields).
  // The textarea is uncontrolled: its value is read on Save, so typing doesn't trigger
  // a re-render (which would drop focus) — only the live preview updates, in place.
  private _noteEdit: NoteTarget | null = null;
  // Every live Markdown preview on screen — the inline note editors and the notes
  // fields in the edit forms/dialogs. All are built by `_attachNotePreview` (the only
  // constructor) and torn down together: they're rebuilt each render pass, and each
  // holds a debounce timer that must not outlive its DOM. `_attachNotePreview` stays in
  // this file for that reason: a region module that built its own preview would create
  // one `_disposeAllPreviews` never sees, leaking a timer onto detached DOM.
  private _previews: MarkdownPreview[] = [];
  // The task form's notes preview, so that form's value-changed handler can feed it.
  // Owned by `_previews` for disposal — this is only a reference.
  _taskNotePreview: MarkdownPreview | null = null;
  // Live HA components that need `.hass` refreshed when hass updates. Push-only for
  // anything that registers one: the list is emptied in `_render`, at the point the
  // shadow tree those elements live in is replaced. A region module that reset it would
  // drop the elements an earlier pass registered and stop feeding them `hass`.
  _liveHassEls: Array<{ hass?: Hass }> = [];

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
    const section = loc.section ?? null;
    const changed =
      loc.view !== this._view ||
      loc.detail?.kind !== this._detail?.kind ||
      loc.detail?.id !== this._detail?.id ||
      loc.detail?.tab !== this._detail?.tab ||
      section !== this._settingsSection;
    if (!changed) return;
    // A move between Settings sections is a lateral step along one page: which section
    // is marked changes, what is on the page does not. Decided before the state below
    // is adopted, because it is a statement about the move, not about where it lands.
    const sectionOnly =
      loc.view === 'settings' &&
      this._view === 'settings' &&
      !loc.detail &&
      !this._detail &&
      !this._edit.open &&
      !this._assetEdit.open &&
      !this._noteEdit &&
      !this._pendingEdit &&
      !this._pendingAssetEdit;
    this._view = loc.view;
    this._detail = loc.detail;
    this._settingsSection = section;
    if (sectionOnly && this._patchSettingsSection()) return;
    // Leaving a list/detail closes any open form (forms are ephemeral overlays)...
    this._edit = { open: false, task: null };
    this._assetEdit = { open: false, asset: null };
    this._noteEdit = null;
    // ...unless this navigation was initiated to open a form (edit from a detail
    // page): re-open it now that the location has settled.
    if (this._pendingEdit) {
      this._edit = { open: true, task: this._pendingEdit };
      this._pendingEdit = null;
    }
    if (this._pendingAssetEdit) {
      this._assetEdit = { open: true, asset: this._pendingAssetEdit };
      this._pendingAssetEdit = null;
    }
    this._render();
  }

  /**
   * Move the open Settings page to another section without rebuilding it.
   *
   * A section change touches four things: the rail entry that is current, the card the
   * URL names (`.hk-sec-current`), the layout's `data-section` (all the narrow rules
   * key off it), and the narrow back bar. A full render for that is the difference
   * between a smooth scroll and a jump to the top of the page: `_render` replaces the
   * whole shadow tree — including the card the scroll was aimed at — and every
   * `ha-form` in the replacement renders after the swap, so the scroll runs against a
   * page whose height is still settling and can be clamped to the top on the way.
   * Patching leaves the page standing, so the card being scrolled to is the one that
   * was already there and the scroll starts from where the reader was.
   *
   * Returns false when there is no rendered Settings page to patch — first paint, or a
   * deep link straight into a section — leaving the caller to render normally.
   */
  private _patchSettingsSection(): boolean {
    const root = this.shadowRoot;
    const layout = root?.querySelector<HTMLElement>('.hk-settings-layout');
    const col = root?.querySelector<HTMLElement>('.hk-settings-col');
    if (!root || !layout || !col) return false;
    const section = this._settingsSection;
    if (section) layout.dataset.section = section;
    else delete layout.dataset.section;
    const current = settingsSectionList(this).find((s) => s.key === section);
    root.querySelectorAll<HTMLElement>('.hk-rail-link').forEach((link) => {
      if (section && link.dataset.section === section) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    });
    root.querySelectorAll('.hk-settings-col ha-card').forEach((card) => {
      card.classList.toggle('hk-sec-current', !!current && card.id === current.card);
    });
    // The back bar belongs to the section that is open, so it is rebuilt rather than
    // retitled — and rewired, since the button it carries is a new element.
    col.querySelector('.hk-settings-backbar')?.remove();
    if (current) {
      col.insertAdjacentHTML('afterbegin', settingsBackbar(this));
      root
        .getElementById('settings-back')
        ?.addEventListener('click', () => this._closeSettingsSection());
    }
    return true;
  }

  /**
   * Mount whichever form the drawer is holding.
   *
   * The pairing is by view, not by page: the task form mounts wherever the tasks view
   * is showing — its list or one task's page — and the appliance form likewise. Which
   * of those the reader is on is `_openEdit`'s business, not this one's.
   */
  private _mountDrawerForm(root: ShadowRoot): void {
    const host = root.getElementById('hk-form-host');
    if (!host) return;
    if (this._view === 'tasks' && this._edit.open) renderTaskForm(this, host);
    else if (this._view === 'appliances' && this._assetEdit.open) renderAssetForm(this, host);
    // Bring the row being edited on screen. Editing beside the list rather than on
    // top of it only buys anything if the row is visible — open the twentieth task
    // and the highlighted row is below the fold, which is a modal with a hole in it.
    // (On a detail page there is no such row: the page itself is the subject.)
    // Guarded because jsdom does not implement scrollIntoView.
    const edited = root.querySelector<HTMLElement>('ha-card.hk-editing');
    if (edited && typeof edited.scrollIntoView === 'function') {
      edited.scrollIntoView({ block: 'center' });
    }
  }

  /**
   * How a scroll this panel starts itself should move: smoothly, unless the reader has
   * asked their system for less motion.
   *
   * The stylesheet's reduced-motion block cannot speak for these: a `behavior` passed
   * to `scrollIntoView` overrides the CSS `scroll-behavior` it sets, so the choice has
   * to be made here too.
   */
  _scrollBehavior(): ScrollBehavior {
    return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
  }

  /**
   * Navigate the panel by changing the URL — never by mutating view/detail
   * directly. HA's `location-changed` listener re-sets our `route`, which flows
   * back through `set route` so there is exactly one path into a state change.
   * Drill-in steps push (Back-able); lateral moves (tab switch) replace.
   */
  // Set to true the first time _navigate pushes a history entry, so _closeDetail
  // knows whether history.back() has a panel URL to return to.
  private _hasHistory = false;

  _navigate(loc: PanelLocation, replace = false): void {
    const url = this._routePrefix + buildPath(loc);
    history[replace ? 'replaceState' : 'pushState'](null, '', url);
    if (!replace) this._hasHistory = true;
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

  disconnectedCallback(): void {
    // Tear down anything appended outside our shadow DOM so it can't leak on unmount:
    // the body-level confirm scrim and its document keydown listener (both live past
    // the element otherwise), plus any pending per-keystroke persist timers.
    teardownOverlay(this);
    // The sheet-threshold media query outlives the element, so its listener has to
    // come off too — it closes over `this` and would otherwise keep the whole
    // detached shadow tree reachable, and re-render it on every crossing.
    // Both fields are cleared, not just the handler: `_syncDrawerModality` only binds
    // a listener when `_sheetQuery` is unset, so leaving the query behind would make a
    // re-attached panel skip the rebind and stop noticing the threshold entirely.
    if (this._sheetQuery && this._sheetOnChange) {
      this._sheetQuery.removeEventListener?.('change', this._sheetOnChange);
    }
    this._sheetOnChange = null;
    this._sheetQuery = null;
    for (const id of Object.values(this._persistTimers)) clearTimeout(id);
    this._persistTimers = {};
    // Markdown previews hold a debounce timer that would otherwise fire against a
    // detached subtree after unmount.
    this._disposeAllPreviews();
    this._armResign(false);
  }

  /**
   * Tear down every live Markdown preview and drop the references to them.
   *
   * `_attachNotePreview` is the only constructor and registers each preview in
   * `_previews`, so this covers all of them — including `_taskNotePreview`, which is
   * only ever a second reference to one of them. Called from both the render reset and
   * `disconnectedCallback`; keep it the single teardown path so a future third caller
   * can't half-clean and leave a reference dangling.
   */
  private _disposeAllPreviews(): void {
    this._previews.forEach((p) => p.dispose());
    this._previews = [];
    this._taskNotePreview = null;
  }

  /** Restore the persisted group-by / filter choices (best-effort). */
  private _loadPrefs(): void {
    try {
      const g = localStorage.getItem(LS_GROUP);
      if (g === 'none' || g === 'status' || g === 'area' || g === 'device' || g === 'integration')
        this._groupBy = g;
      const f = localStorage.getItem(LS_FILTER);
      if (f === 'all' || f === 'overdue' || f === 'soon' || f === 'shopping')
        this._filter = f;
      const af = localStorage.getItem(LS_ASSET_FILTER);
      if (af === 'active' || af === 'archived') this._assetFilter = af;
      const av = localStorage.getItem(LS_ASSET_VIEW);
      if (av === 'flat' || av === 'tree') this._assetView = av;
      const tc = localStorage.getItem(LS_TREE_COLLAPSED);
      if (tc) {
        try {
          const arr = JSON.parse(tc);
          if (Array.isArray(arr)) this._treeCollapsed = new Set(arr.filter((x: unknown) => typeof x === 'string'));
        } catch { /* ignore malformed */ }
      }
      this._profile = localStorage.getItem(LS_PROFILE) ?? '';
    } catch {
      // localStorage unavailable (e.g. private mode) — fall back to defaults.
    }
  }

  _setGroupBy(value: GroupBy): void {
    if (this._groupBy === value) return;
    this._groupBy = value;
    try {
      localStorage.setItem(LS_GROUP, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  _setFilter(value: TaskFilter): void {
    if (this._filter === value) return;
    this._filter = value;
    try {
      localStorage.setItem(LS_FILTER, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  _setAssetFilter(value: AssetFilter): void {
    if (this._assetFilter === value) return;
    this._assetFilter = value;
    try {
      localStorage.setItem(LS_ASSET_FILTER, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  _setAssetView(value: AssetView): void {
    if (this._assetView === value) return;
    this._assetView = value;
    try {
      localStorage.setItem(LS_ASSET_VIEW, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  /** Pick a saved Profile to drive the task-list filter (''/none clears it). */
  _setProfile(value: string): void {
    if (this._profile === value) return;
    this._profile = value;
    try {
      localStorage.setItem(LS_PROFILE, value);
    } catch {
      /* ignore */
    }
    this._render();
  }

  // ── detail page lifecycle ───────────────────────────────────────────────────
  _openDetail(kind: 'task' | 'asset', id: string): void {
    // Drilling in is a Back-able step: push. An appliance opens on its default
    // sub-tab; `buildPath` leaves that one out of the URL.
    const detail =
      kind === 'asset' ? { kind, id, tab: DEFAULT_ASSET_TAB } : { kind, id };
    this._navigate({ view: kind === 'asset' ? 'appliances' : 'tasks', detail });
  }

  /** Which sub-tab the open appliance detail is showing. */
  _assetTab(): AssetTab {
    return this._detail?.tab ?? DEFAULT_ASSET_TAB;
  }

  /**
   * Switch the open appliance's sub-tab. A lateral move within one appliance, so it
   * *replaces* rather than pushes: Back should leave the appliance, not retrace every
   * tab you looked at on the way through it — the same rule the top-level tabs follow.
   */
  _setAssetTab(tab: AssetTab): void {
    const detail = this._detail;
    if (!detail || detail.kind !== 'asset' || this._assetTab() === tab) return;
    this._navigate({ view: 'appliances', detail: { ...detail, tab } }, true);
  }
  /**
   * Leave an open Settings section for the section index — the phone's back arrow.
   *
   * Same two cases as `_closeDetail`: pop the pushed index entry when there is one,
   * and otherwise (a deep link straight to `/settings/notifications`) navigate to the
   * index outright, since there is nothing behind us to pop.
   */
  _closeSettingsSection(): void {
    if (this._hasHistory) history.back();
    else this._navigate({ view: 'settings', detail: null }, true);
  }

  _closeDetail(): void {
    if (this._hasHistory) {
      // A pushState has occurred in this session: history.back() correctly pops
      // to whatever was before the current detail — even when the detail was
      // opened cross-view (e.g. a task opened from inside an appliance detail).
      history.back();
    } else {
      // No panel navigation has been pushed yet (user deep-linked directly to
      // this detail URL). Fall back to an explicit navigate to the owning list.
      this._navigate({ view: this._view, detail: null }, true);
    }
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
  async _reload(): Promise<void> {
    if (!this._hass) return;
    try {
      const [
        tasks,
        assets,
        entryDomains,
        loadedEntryIds,
        options,
        companions,
        introDismissed,
        tags,
      ] = await Promise.all([
        api.getTasks(this._hass),
        api.getAssets(this._hass),
        api.getEntryDomains(this._hass).catch(() => ({})),
        api.getLoadedEntryIds(this._hass).catch(() => new Set<string>()),
        api.getOptions(this._hass).catch(() => null),
        api.getCompanions(this._hass).catch(() => [] as Companion[]),
        api.getIntroDismissed(this._hass).catch(() => false),
        // Best-effort: the tag registry is a convenience for the picker and the
        // chip label, never a precondition for the panel loading.
        api.getTags(this._hass).catch(() => [] as { value: string; label: string }[]),
      ]);
      this._tasks = tasks;
      this._assets = assets;
      this._entryDomains = entryDomains;
      this._loadedEntryIds = loadedEntryIds;
      this._options = options?.options ?? null;
      this._notifyTargets = options?.notifyTargets ?? [];
      this._ownTodoEntities = options?.ownTodoEntities ?? [];
      this._companions = companions ?? [];
      this._introDismissed = introDismissed;
      this._tags = tags;
      // Drop a remembered Profile filter that no longer exists (deleted since), so the
      // Tasks-tab dropdown and the stored id can't disagree.
      if (this._profile && !(this._options?.profiles ?? []).some((p) => p.id === this._profile)) {
        this._profile = '';
        try {
          localStorage.removeItem(LS_PROFILE);
        } catch {
          /* ignore */
        }
      }
      this._loaded = true;
      this._loadError = false;
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('home-keeper: failed to load data', err);
      // Surface a retry instead of spinning forever (the only auto-retry was on the
      // first `set hass`, so a transient WS failure at startup bricked the panel).
      this._loadError = true;
    }
  }

  _refresh(): Promise<void> {
    // Coalesce overlapping refreshes onto one in-flight load so `set hass` and `_init`
    // can't run two concurrent full loads, while every `await this._refresh()` caller
    // still waits for a completed reload + render (a blanket early-return would let a
    // caller proceed against an unrendered view).
    if (this._refreshing) return this._refreshing;
    this._refreshing = (async () => {
      try {
        await this._reload();
        this._render();
      } finally {
        this._refreshing = null;
      }
    })();
    return this._refreshing;
  }

  // ── task form lifecycle ─────────────────────────────────────────────────────
  _openCreate(): void {
    this._rememberDrawerOpener();
    this._edit = {
      open: true,
      task: {
        recurrence_type: 'floating',
        interval: 1,
        unit: 'months',
        consumable_link: '',
      } as Partial<Task>,
    };
    this._render();
  }
  _openEdit(task: Task): void {
    this._rememberDrawerOpener();
    // Seed the flat consumable_link so the picker reflects the current link and a
    // plain save (no edit) round-trips it unchanged.
    const seeded = { ...task, consumable_link: consumableLinkToken(task) } as Partial<Task>;
    // The form opens beside whatever you were reading, and the location does not move:
    // on the list that is the list, and on the task's own page it is that page — the
    // history, the notes and the schedule that explain the values being edited. Edit
    // used to leave the page it was pressed on, which threw all of that away to show a
    // list nobody asked for.
    //
    // A *cross-view* edit is still a navigation (editing a task from an appliance's
    // page, say): the task form only mounts on the tasks view. That one goes through
    // the URL rather than mutating view/detail directly, and stashes the target as a
    // pending edit, because `_applyLocation` clears ephemeral forms on the way — see
    // `_pendingEdit`, which re-opens it once the location has settled.
    if (this._view === 'tasks' && this._editsThisPage('task', task.id)) {
      this._edit = { open: true, task: seeded };
      this._render();
    } else {
      this._pendingEdit = seeded;
      this._navigate({ view: 'tasks', detail: null });
    }
  }

  /**
   * Open the **create** drawer on a copy of *task* (#279).
   *
   * Deliberately not a save: this is the create form, prefilled, and nothing exists
   * until Create is pressed — `_submitForm` routes an id-less task to `addTask`,
   * which is the entire mechanism. So a duplicate that is abandoned costs nothing.
   *
   * No cross-view dance, unlike `_openEdit`: the only Duplicate button lives on a
   * task's own detail page, which is by construction the `tasks` view, so the form
   * already mounts where we are.
   */
  _openDuplicate(task: Task): void {
    this._rememberDrawerOpener();
    this._edit = { open: true, task: duplicateTaskSeed(task) };
    this._render();
  }

  /**
   * Whether the form for the object named by *kind* and *id* belongs on the page that
   * is open right now.
   *
   * True on the matching list (no detail), and on that object's own detail page. False
   * on anyone else's page — editing a task listed on an appliance's page still has to
   * go to the tasks view, because that is where the task form mounts.
   */
  private _editsThisPage(kind: 'task' | 'asset', id: string | undefined): boolean {
    if (!this._detail) return true;
    return this._detail.kind === kind && !!id && this._detail.id === id;
  }
  _closeForm(): void {
    this._edit = { open: false, task: null };
    this._render();
  }

  async _submitForm(): Promise<void> {
    if (!this._hass || !this._edit.task) return;
    const task = this._edit.task;
    if (!task.name || !String(task.name).trim()) {
      this._edit.error = t('error.nameRequired');
      this._render();
      return;
    }
    const payload = buildTaskPayload(task);
    try {
      const saved = task.id
        ? await api.updateTask(this._hass, task.id, payload)
        : await api.addTask(this._hass, payload);
      // Record the id immediately: if the link step below throws, the form stays open
      // and a retry must *update* this task, not create a second one.
      this._edit.task = { ...this._edit.task, id: saved.id };
      // The consumable link rides its own service (it sets the task's source, which
      // update_task doesn't touch). Only call when it actually changed: the desired
      // token vs. the saved task's current link.
      const desired = String((task as Record<string, unknown>).consumable_link ?? '');
      if (desired !== consumableLinkToken(saved)) {
        const [assetId, partId] = desired ? desired.split(':') : ['', ''];
        await api.setTaskConsumable(this._hass, saved.id, assetId || null, partId || null);
      }
      this._closeForm();
      await this._refresh();
    } catch (err) {
      this._edit.error = String((err as { message?: string })?.message || err);
      this._render();
    }
  }

  /** True when the inline notes editor is open on *target*. */
  private _editingNote(target: NoteTarget): boolean {
    return this._noteEdit?.kind === target.kind && this._noteEdit.id === target.id;
  }

  /** Open the inline notes editor on *target* (closing any other one). */
  private _openNoteEditor(target: NoteTarget): void {
    this._noteEdit = target;
    this._render();
  }

  /** Close the inline notes editor, discarding whatever was typed. */
  private _closeNoteEditor(): void {
    this._noteEdit = null;
    this._render();
  }

  /**
   * Persist an inline-edited note.
   *
   * Both kinds reuse the ordinary partial-update path — `update_task` for a task
   * (the store also mirrors a problem-sensor task's note into the durable,
   * entity-keyed side-store so it outlives the mirror) and `update_asset` for an
   * appliance (`merge_update` carries every unmentioned field through). On failure
   * the editor stays open with the typed text so the user can retry.
   */
  private async _saveNote(target: NoteTarget, notes: string): Promise<void> {
    if (!this._hass) return;
    try {
      if (target.kind === 'task') {
        await api.updateTask(this._hass, target.id, { notes });
      } else {
        await api.updateAsset(this._hass, target.id, { notes });
      }
      this._noteEdit = null;
      await this._refresh();
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Home Keeper: failed to save note', err);
      toast(this, t('error.actionFailed'));
    }
  }

  /**
   * The body of a detail page's Notes card: rendered Markdown plus an Edit button,
   * or — when this target is the one being edited — a textarea with a live preview.
   *
   * *editable* is false for a note the panel doesn't own (a source-managed task whose
   * `notes` field is locked by its integration), which keeps the read-only rendering.
   * *placeholder* lets a problem-sensor task keep its more pointed prompt.
   */
  _notesCardBody(
    target: NoteTarget,
    text: string,
    editable: boolean,
    placeholder: string = t('note.placeholderMd'),
  ): string {
    const rendered = text
      ? markdownBlock(text)
      : `<span class="hk-muted">${escapeHTML(t('detail.noNotes'))}</span>`;
    if (!editable) return rendered;
    if (this._editingNote(target)) {
      // The preview is appended into `.d-note-preview` by `_wireNoteEditor` — it is a
      // live element driven by `input`, so it can't be part of this HTML string.
      return `
        <textarea class="hk-note-input d-note-input" rows="5"
          placeholder="${escapeHTML(placeholder)}">${escapeHTML(text)}</textarea>
        <div class="d-note-preview"></div>
        <div class="hk-detail-actions">
          <ha-button ${btnAttrs('primary')} class="d-note-save">${escapeHTML(t('btn.save'))}</ha-button>
          <ha-button ${btnAttrs('tertiary')} class="d-note-cancel">${escapeHTML(t('btn.cancel'))}</ha-button>
        </div>`;
    }
    const label = text ? t('note.edit') : t('note.add');
    return `${rendered}
      <div class="hk-detail-actions">
        <ha-button ${btnAttrs('secondary')} class="d-note-edit">${escapeHTML(label)}</ha-button>
      </div>`;
  }

  /** A whole Notes section (heading + card) for a detail page. */
  private _notesSection(target: NoteTarget, text: string, editable: boolean): string {
    return `<div class="hk-section">${escapeHTML(t('field.notes'))}</div>
      <ha-card class="hk-detail-card"><div class="hk-detail-inner">${this._notesCardBody(
        target,
        text,
        editable,
      )}</div></ha-card>`;
  }

  /**
   * Append a live Markdown preview for a notes field to *host*, seeded with *initial*.
   *
   * The caller feeds it from its form's existing `value-changed` handler — updating the
   * preview in place rather than re-rendering, so the field keeps focus while typing
   * (the same technique `_updateFormHints` uses for the sensor primer).
   *
   * **This is the only way to build a preview.** Every one is registered in
   * `_previews`, which `_render` and `disconnectedCallback` dispose wholesale, so a
   * preview can never outlive its DOM with a debounce timer still armed. Constructing
   * one directly with `createPreview` would leak — don't.
   */
  _attachNotePreview(host: HTMLElement, initial: string): MarkdownPreview {
    const preview = createPreview(t('note.preview'));
    this._previews.push(preview);
    host.appendChild(preview.el);
    preview.update(initial);
    return preview;
  }

  /** Wire the inline notes editor's buttons and its live preview. */
  _wireNoteEditor(root: ShadowRoot, target: NoteTarget): void {
    root
      .querySelector('.d-note-edit')
      ?.addEventListener('click', () => this._openNoteEditor(target));
    root
      .querySelector('.d-note-cancel')
      ?.addEventListener('click', () => this._closeNoteEditor());
    const input = root.querySelector<HTMLTextAreaElement>('.d-note-input');
    root.querySelector('.d-note-save')?.addEventListener('click', () => {
      void this._saveNote(target, input?.value ?? '');
    });
    const host = root.querySelector<HTMLElement>('.d-note-preview');
    if (!input || !host) return;
    // A fresh preview per render pass — `_render` disposed the previous one and its
    // DOM is already gone. This runs from `_hydrate`, i.e. after that reset.
    const preview = this._attachNotePreview(host, input.value);
    input.addEventListener('input', () => preview.update(input.value));
  }

  async _complete(task: Task): Promise<void> {
    if (!this._hass) return;
    // A scan-locked task is completed by its tag, not by this button. The backend
    // rejects the call outright, so say why here rather than surfacing its error.
    if (scanRequired(task)) {
      toast(this, t('done.needsScan'));
      return;
    }
    // Tasks set to capture detail open a dialog first; the default one-taps.
    const mode = task.completion_detail || 'none';
    if (mode === 'optional' || mode === 'required') {
      openCompletionDialog(this, task);
      return;
    }
    try {
      await api.completeTask(this._hass, task.id);
    } catch (err) {
      console.error('home-keeper: complete failed', err);
      toast(this, t('error.actionFailed'));
    }
    await this._refresh();
  }

  /** A completion-blocked task (e.g. a synced problem sensor) can't be marked done
   *  here — its owning integration clears it. Explain why instead of completing.
   *  A scan-locked task is blocked for a different reason, so it says so instead. */
  _notifyBlocked(task: Task): void {
    toast(this, this._blockedReason(task));
  }

  /** Why *task*'s Done action is unavailable, in the words the user needs: a
   *  scan-locked task wants its tag scanned, a source-owned one clears itself. */
  private _blockedReason(task: Task): string {
    if (scanRequired(task)) return t('done.needsScan');
    return task.managed_by?.completion_prompt || t('done.blocked');
  }

  /** A *disabled* `ha-button` wrapped in a clickable span. The native `disabled`
   *  greys the button correctly across HA button versions but swallows clicks, so the
   *  span carries the tap → explanation and the hover tooltip. Every action the panel
   *  greys out rather than hides renders through here, so a dead button always has a
   *  reason attached to it. */
  private _blockedButton(
    classes: string,
    id: string,
    label: string,
    reason: string,
    weight: BtnWeight,
  ): string {
    const cls = [classes, 'hk-blocked-wrap'].filter(Boolean).join(' ');
    return `<span class="${cls}" data-id="${escapeHTML(id)}" role="button" tabindex="0" title="${escapeHTML(reason)}"><ha-button ${btnAttrs(weight)} disabled>${escapeHTML(label)}</ha-button></span>`;
  }

  /** Render a *disabled* Done for a completion-blocked task. *weight* matches
   *  whichever live Done it stands in for: the detail page's primary, or the list
   *  row's tonal one.
   *
   *  Keeps its own `done-blocked-wrap` class: `panel-lists.ts` wires every element
   *  carrying it to `_notifyBlocked`, which is the *Done* reason specifically. A
   *  blocked action of another kind must not borrow it. */
  _blockedDone(wrapClass: string, task: Task, weight: BtnWeight = 'secondary'): string {
    const cls = [wrapClass, 'done-blocked-wrap'].filter(Boolean).join(' ');
    return this._blockedButton(cls, task.id, t('btn.done'), this._blockedReason(task), weight);
  }

  /** Whether *task*'s configuration can be copied into a new task (#279).
   *
   *  A source-owned task (a reconciler wear part, a synced problem sensor) and an
   *  integration-managed one are both authored elsewhere: a copy would be an unowned
   *  lookalike of a row its owner still reconciles.
   *
   *  A *triggered* task is blocked for a harder reason than ownership. Its payload
   *  carries only descriptive fields — sending a cadence would re-arm a dormant task
   *  — so a copy would reach the backend with no schedule at all and be inferred as a
   *  one-off due today. Guarding on the recurrence type rather than on `managed_by`
   *  keeps that true even for a triggered task an integration pushed without
   *  declaring ownership. */
  _canDuplicate(task: Task): boolean {
    if (task.recurrence_type === 'triggered') return false;
    if (task.managed_by) return false;
    return !sourceOwnedTask(task);
  }

  /** Why *task* can't be duplicated, naming the owning integration when there is one
   *  so the answer points somewhere rather than just refusing. */
  private _duplicateBlockedReason(task: Task): string {
    const name = task.managed_by?.display_name;
    return name ? t('duplicate.blockedManaged', { name }) : t('duplicate.blockedSource');
  }

  /** The greyed Duplicate a task Home Keeper doesn't own keeps, instead of silently
   *  missing one. Secondary, matching the live button it stands in for: greying a
   *  *tonal* button reads as "this button is off", where greying bare text just reads
   *  as text. */
  _blockedDuplicate(task: Task): string {
    return this._blockedButton(
      'd-dup-blocked',
      task.id,
      t('btn.duplicate'),
      this._duplicateBlockedReason(task),
      'secondary',
    );
  }

  /** Explain why *task* offers no Duplicate, rather than a button that does nothing. */
  _notifyNoDuplicate(task: Task): void {
    toast(this, this._duplicateBlockedReason(task));
  }
  /** A muted "Clears automatically" caption for a completion-blocked task in the list
   *  card — self-explanatory inline (no hover needed), unlike a dead greyed button. It's
   *  a *status*, not an action, so it carries no button role: the visible label conveys
   *  the gist, `aria-label` gives assistive tech the full reason, `title` shows it on
   *  hover, and a pointer tap still surfaces it as a toast (via `.done-blocked-wrap`). */
  _blockedDoneInline(task: Task): string {
    const reason = task.managed_by?.completion_prompt || t('done.blocked');
    const label = t('done.autoClears');
    return `<span class="hk-auto-clear done-blocked-wrap" data-id="${escapeHTML(task.id)}" title="${escapeHTML(reason)}" aria-label="${escapeHTML(`${label}: ${reason}`)}"><ha-icon icon="mdi:autorenew" class="hk-chip-ic"></ha-icon>${escapeHTML(label)}</span>`;
  }
  async _delete(task: Task): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteTask(this._hass, task.id);
      await this._refresh();
    } catch (err) {
      const msg = String((err as { message?: string })?.message || err);
      toast(this, msg);
      await this._refresh();
    }
  }

  // ── asset form lifecycle ────────────────────────────────────────────────────
  _openCreateAsset(): void {
    this._rememberDrawerOpener();
    this._assetEdit = { open: true, asset: { kind: 'virtual', parts: [] } };
    this._render();
  }
  _openEditAsset(asset: Asset): void {
    this._rememberDrawerOpener();
    // Opens beside the page it was pressed on — the appliance's own page keeps its
    // parts, documents and history in view while the form is up. See `_openEdit` for
    // the cross-view case and the pending-edit dance that survives `_applyLocation`
    // clearing ephemeral forms on a route change.
    const seeded: Partial<Asset> = {
      ...asset,
      parts: [...(asset.parts || [])],
      metadata: (asset.metadata || []).map((m) => ({ ...m })),
    };
    if (this._view === 'appliances' && this._editsThisPage('asset', asset.id)) {
      this._assetEdit = { open: true, asset: seeded };
      this._render();
    } else {
      this._pendingAssetEdit = seeded;
      this._navigate({ view: 'appliances', detail: null });
    }
  }
  _closeAssetForm(): void {
    this._assetEdit = { open: false, asset: null };
    this._render();
  }

  async _submitAssetForm(): Promise<void> {
    if (!this._hass || !this._assetEdit.asset) return;
    const a = this._assetEdit.asset;
    if (a.kind === 'virtual' && !String(a.name || '').trim()) {
      setAssetError(this, t('error.nameRequiredAppliance'));
      this._render();
      return;
    }
    if (a.kind === 'existing' && !a.device_id) {
      setAssetError(this, t('error.pickDevice'));
      this._render();
      return;
    }
    const parts = (a.parts || []).filter((p) => p.name && p.name.trim());
    // Drop half-finished metadata rows (no label) so they don't fail validation.
    const metadata = (a.metadata || []).filter((m) => m.label && m.label.trim());
    // For a saved appliance, documents are managed live (their own backend calls), so
    // they're excluded from the batch save — omitting them preserves the server's list
    // (merge_update). A brand-new appliance has no live id yet, so its collected link
    // documents ride along in the create payload (the backend seeds links on create).
    const { documents, ...rest } = a;
    const payload: Partial<Asset> = { ...rest, parts, metadata };
    if (!a.id) payload.documents = (documents || []).filter((d) => d.kind === 'link' && d.url);
    try {
      if (a.id) await api.updateAsset(this._hass, a.id, payload);
      else await api.addAsset(this._hass, payload);
      this._closeAssetForm();
      await this._refresh();
    } catch (err) {
      setAssetError(this, String((err as { message?: string })?.message || err));
      this._render();
    }
  }

  async _deleteAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.deleteAsset(this._hass, asset.id);
    } catch (err) {
      console.error('home-keeper: delete appliance failed', err);
      toast(this, t('error.actionFailed'));
    }
    await this._refresh();
  }

  /** Hide an appliance from the default list without deleting its data;
   *  reversible via {@link _restoreAsset}. */
  async _archiveAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.archiveAsset(this._hass, asset.id);
      await this._refresh();
    } catch (err) {
      console.error('home-keeper: archive appliance failed', err);
      toast(this, t('error.actionFailed'));
    }
  }

  async _restoreAsset(asset: Asset): Promise<void> {
    if (!this._hass) return;
    try {
      await api.restoreAsset(this._hass, asset.id);
      await this._refresh();
    } catch (err) {
      console.error('home-keeper: restore appliance failed', err);
      toast(this, t('error.actionFailed'));
    }
  }

  /**
   * Build the home-inventory report server-side and save it as a CSV — a
   * grab-and-go record for an insurance claim (make/model/serial, purchase +
   * warranty dates, replacement cost, on-hand spares value).
   */
  async _exportInventory(): Promise<void> {
    if (!this._hass) return;
    try {
      const { csv } = await api.exportInventory(this._hass);
      const stamp = new Date().toISOString().slice(0, 10);
      this._downloadFile(`home-keeper-inventory-${stamp}.csv`, csv, 'text/csv');
    } catch (err) {
      console.error('home-keeper: inventory export failed', err);
      toast(this, t('error.exportFailed'));
    }
  }

  /** Coalesce rapid calls under *key*, running only the trailing one after *ms*. */
  _debounce(key: string, fn: () => void, ms = 600): void {
    const prev = this._persistTimers[key];
    if (prev) clearTimeout(prev);
    this._persistTimers[key] = setTimeout(() => {
      delete this._persistTimers[key];
      fn();
    }, ms);
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

  /**
   * Keep trying to register HA's lazy `<ha-markdown>` until it sticks, re-rendering
   * once it does so notes upgrade from the escaped-text fallback to real Markdown.
   *
   * The retry matters for a cold deep-link to `/home-keeper`: `window.loadCardHelpers`
   * is installed by HA's Lovelace chunk, so it can be absent at first paint and appear
   * later once the user has visited a dashboard. Each attempt is a cheap no-op when
   * the helper is still missing, and `markdownReady()` short-circuits it forever after
   * the element registers — so this cannot loop.
   *
   * The registration attempt outlives a single render (it awaits a lazy chunk load), so
   * the callback checks `isConnected` before re-rendering: without that, unmounting
   * while one is in flight would rebuild the whole panel — forms, previews and their
   * debounce timers — onto a detached element that nothing will ever tear down again.
   */
  private _ensureMarkdown(): void {
    if (markdownReady()) return;
    void ensureMarkdown().then((ok) => {
      if (!ok || !this.isConnected) return;
      // Never mid-edit: this resolves a lazy chunk load later, so a user who opened a
      // form and started typing would have the field replaced under them — focus falls
      // back to `<body>` and HA's global one-letter shortcuts start eating the word.
      // Nothing is lost by waiting: each live preview re-checks `markdownReady()` when
      // it paints, so the open form upgrades on the next keystroke, and the panel-wide
      // upgrade lands on the next render.
      if (this._editingOpen()) return;
      this._render();
    });
  }

  /**
   * Whether the user is editing something that a re-render would destroy — a form or a
   * dialog with fields in it. Background refreshes that only improve the rendering
   * (never the data the user is looking at) stand down while this is true.
   */
  private _editingOpen(): boolean {
    return Boolean(
      this._edit.open ||
        this._assetEdit.open ||
        this._noteEdit ||
        this._completion.open ||
        this._moveCompletion.open,
    );
  }

  /** Whether the side drawer holds a form right now. Narrower than `_editingOpen`:
   *  the note editor and the completion dialogs are their own surfaces, and neither
   *  belongs in — or should dim the list behind — the drawer. Mirrors the condition
   *  `_hydrate` uses to decide which form to mount into the drawer host. */
  private _drawerOpen(): boolean {
    return (
      (this._view === 'tasks' && this._edit.open) ||
      (this._view === 'appliances' && this._assetEdit.open)
    );
  }

  // ── rendering ───────────────────────────────────────────────────────────────
  _render(): void {
    if (!this.shadowRoot) return;
    // Whatever had focus is about to be destroyed; note it so `_restoreFocus` can put
    // the keyboard back on the same control in the rebuilt tree.
    const focused = this._focusKey();
    this._ensureMarkdown();
    this._liveHassEls = [];
    // Everything below is rebuilt from scratch, so every preview on screen is about to
    // be detached — cancel its pending debounce rather than leaking a timer.
    this._disposeAllPreviews();
    const onTasks = this._view === 'tasks';

    let inner: string;
    if (!this._loaded && this._loadError) {
      // A transient WS failure at startup used to leave the panel spinning forever
      // (only the very first `set hass` retried). Show a retry instead.
      inner = `<div class="hk-loading"><ha-alert alert-type="error">${escapeHTML(
        t('error.loadFailed'),
      )}</ha-alert><ha-button id="hk-retry" ${btnAttrs('primary')}>${escapeHTML(
        t('btn.retry'),
      )}</ha-button></div>`;
    } else if (!this._loaded) {
      inner = `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`;
    } else if (this._detail?.kind === 'asset') {
      // An appliance is read next to the list it came from: the master pane stays,
      // the detail fills the rest, and the top tabs stay reachable. Below the
      // breakpoint the pane steps aside and the back button carries the return trip.
      // Back lives above both columns, not inside the master pane: the pane is hidden
      // on a narrow screen, and that is exactly where Back is the only way out.
      // The controls row filters the master pane, so it is marked as belonging to it:
      // where the pane steps aside, a row of controls for a list nobody can see is
      // just chrome in front of the appliance you asked for.
      inner = `
        ${this._tabs()}
        <div class="hk-detailbar">
          <ha-button id="back-btn" ${btnAttrs('tertiary')}>‹ ${escapeHTML(t('btn.back'))}</ha-button>
        </div>
        <div class="hk-master-controls">${controls(this)}</div>
        <div class="hk-master-detail">
          <div class="hk-master">
            <div id="hk-list">${assetsList(this)}</div>
          </div>
          <div class="hk-detail-pane">${detailView(this)}</div>
        </div>`;
    } else if (this._detail) {
      inner = `
        <div class="hk-detailbar">
          <ha-button id="back-btn" ${btnAttrs('tertiary')}>‹ ${escapeHTML(t('btn.back'))}</ha-button>
        </div>
        ${detailView(this)}`;
    } else if (this._view === 'settings') {
      // Three things, all rendered at every width, with CSS choosing between them: an
      // anchor rail naming every section and what it is set to, a section index for a
      // screen with no room for the rail, and the sections themselves. Which section
      // the URL names is on the layout as `data-section`, so the phone rules can show
      // the index or one section without any JS knowing the viewport size. The four
      // host ids are unchanged — only where they sit on the page moved.
      inner = `
        ${this._tabs()}
        <div class="hk-settings-layout"${
          this._settingsSection
            ? ` data-section="${escapeHTML(this._settingsSection)}"`
            : ''
        }>
          ${settingsRail(this)}
          ${settingsIndex(this)}
          <div class="hk-settings-col">
            ${settingsBackbar(this)}
            <div id="hk-settings-host"></div>
            <div id="hk-profiles-host"></div>
            <div id="hk-notifications-host"></div>
            <div id="hk-companions-host"></div>
          </div>
        </div>`;
    } else {
      // Add / Export now live at the end of the controls row (one primary action per
      // surface), so the old full-width action bar above the list is gone.
      inner = `
        ${this._tabs()}
        ${controls(this)}
        <div id="hk-list">${onTasks ? tasksList(this) : assetsList(this)}</div>`;
    }

    // Editing happens in a side drawer beside the list rather than in a card above
    // it: the list keeps its place, and the row being edited stays on screen. The
    // drawer is a sibling of the content column, so it is laid out by the shell's
    // flex row instead of overlaying the page.
    const drawerOpen = this._drawerOpen();
    this.shadowRoot.innerHTML = `
      <style>${STYLES}</style>
      <div class="hk-toolbar">
        <span id="menu-host"></span>
        <div class="hk-toolbar-title">${escapeHTML(t('app.title'))}</div>
      </div>
      <div class="hk-shell${drawerOpen ? ' hk-shell-drawer' : ''}">
        <div class="hk-wrap" data-view="${escapeHTML(this._view)}"${
          this._detail ? ` data-detail="${escapeHTML(this._detail.kind)}"` : ''
        }>
          ${inner}
          <div class="ver">v${escapeHTML(PANEL_VERSION)}</div>
        </div>
        <aside class="hk-drawer"${
          drawerOpen
            ? ` data-open role="dialog" aria-modal="true" tabindex="-1" aria-label="${escapeHTML(t('btn.edit'))}"`
            : ''
        }>
          <div id="hk-form-host" class="hk-drawer-sticky"></div>
        </aside>
      </div>
      ${this._loaded ? this._bottomTabs() : ''}
      <div id="hk-dialog-host"></div>
    `;
    this._hydrate();
    this._restoreFocus(focused);
    this._syncDrawerModality();
  }

  /**
   * Identify the focused control well enough to find its replacement after a render.
   *
   * `_render()` replaces the whole shadow tree, so the element the user was on stops
   * existing and focus falls to `<body>`. For a mouse that is invisible; for a keyboard
   * it means every filter click, every sub-tab and every rail entry throws you back to
   * the top of the document. These controls all already carry a stable data attribute,
   * which is enough to find the same control in the new tree.
   */
  private _focusKey(): string | null {
    const el = this.shadowRoot?.activeElement as HTMLElement | null;
    if (!el) return null;
    for (const attr of ['data-seg-val', 'data-seg-select', 'data-section', 'data-rail', 'data-tab']) {
      const v = el.getAttribute(attr);
      // Two segments can share a value ("active" appears in more than one), so the
      // key carries the group as well as the option.
      if (v !== null) {
        const group = el.closest('[data-seg]')?.getAttribute('data-seg') ?? '';
        return `[${attr}="${CSS.escape(v)}"]${group ? `:is([data-seg="${CSS.escape(group)}"] *)` : ''}`;
      }
    }
    return el.id ? `#${CSS.escape(el.id)}` : null;
  }

  private _restoreFocus(key: string | null): void {
    if (!key) return;
    this._focus(this.shadowRoot?.querySelector<HTMLElement>(key) ?? null);
  }

  /**
   * Focus an element without letting it take the render down with it.
   *
   * A Home Assistant custom element is focused through its own `focus()`, which
   * dereferences its shadow root — and immediately after an `innerHTML` assignment
   * that root may not exist yet, so it throws. Unguarded, that propagated out of
   * `_render()` and every step after the focus call was skipped.
   *
   * Swallowing it is not enough on its own, though: an `ha-button` mounted by the
   * render we are standing in is *always* still upgrading, so the throw was the
   * normal path and the keyboard was dropped on `<body>` every time. Try again on
   * the next frame, by which time the element has its shadow root — and only while
   * nothing else has claimed focus in the meantime, so a deferred restore can never
   * steal the caret from wherever the reader has since moved.
   */
  private _focus(el: HTMLElement | null): void {
    if (!el || typeof el.focus !== 'function') return;
    try {
      el.focus({ preventScroll: true });
      if (this.shadowRoot?.activeElement !== el) this._focusNextFrame(el);
    } catch {
      // Not ready to take focus yet; the retry below is the one that lands, and
      // leaving focus where it is beats aborting the render.
      this._focusNextFrame(el);
    }
  }

  /**
   * The second attempt at a focus the render was too early for.
   *
   * Bails when the element has left the tree (another render replaced it) or when
   * focus is no longer sitting on `<body>` — by then the reader, or a component
   * finishing its own upgrade, has put the caret somewhere deliberate and moving it
   * would be the more surprising of the two failures.
   */
  private _focusNextFrame(el: HTMLElement): void {
    const raf = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : null;
    if (!raf) return;
    raf(() => {
      if (!el.isConnected) return;
      const active = this.shadowRoot?.activeElement;
      if (active && active !== el) return;
      try {
        el.focus({ preventScroll: true });
      } catch {
        // Still not ready. Two frames is where this stops being worth chasing.
      }
    });
  }

  /**
   * A selector for the control that opened the drawer, so closing it can hand the
   * keyboard back.
   *
   * Deliberately a selector rather than the element: opening the drawer renders, and
   * `_render()` replaces the whole shadow tree, so the element captured on the way in
   * is detached by the time the drawer closes. Holding it meant `isConnected` was
   * always false and focus was never returned — every Escape, Cancel and close button
   * dropped the keyboard on `<body>`. A selector is resolved against the tree that is
   * actually on screen at close time, and holds no reference to a dead node.
   */
  private _drawerOpenerKey: string | null = null;
  // Escape closes the sheet; held at document level because the sheet is fixed and a
  // keydown inside it would not otherwise reach us once focus is on a form field.
  _drawerOnKey: ((e: KeyboardEvent) => void) | null = null;
  private _sheetQuery: MediaQueryList | null = null;
  // The `change` handler bound to `_sheetQuery`, held so unmounting can remove it.
  private _sheetOnChange: (() => void) | null = null;

  /**
   * Keep the drawer's *modality* — not its layout — in step with what it currently is.
   *
   * Beside the list it is a panel: the list stays live in every modality, exactly as it
   * was when the form rendered inline above it. Covering the list it is a sheet, and a
   * sheet that leaves 30 tabbable controls underneath an opaque overlay is a trap: the
   * keyboard walks a list nobody can see and Enter discards the open form.
   *
   * `inert` is an attribute, not a style, so this is the one place that reads the
   * viewport — and it reads it for modality, not for layout. `_render()` stays
   * viewport-agnostic; the media query below simply says which thing the drawer is.
   */
  _syncDrawerModality(): void {
    const root = this.shadowRoot;
    if (!root) return;
    const drawer = root.querySelector<HTMLElement>('.hk-drawer[data-open]');
    const wrap = root.querySelector<HTMLElement>('.hk-wrap');
    if (!this._sheetQuery && typeof window.matchMedia === 'function') {
      this._sheetQuery = window.matchMedia('(max-width: 1150px)');
      // Held as a field so `disconnectedCallback` can take it off again: the listener
      // closes over `this`, so leaving it attached to a live MediaQueryList keeps a
      // detached panel (and its whole shadow tree) reachable for as long as the tab
      // lives, and re-renders it on every resize across the threshold.
      this._sheetOnChange = (): void => this._syncDrawerModality();
      this._sheetQuery.addEventListener?.('change', this._sheetOnChange);
    }
    const isSheet = !!this._sheetQuery?.matches;
    // The bottom tab bar is a sibling of `.hk-wrap`, not a child, so making the wrap
    // inert left it live under an `aria-modal="true"` sheet — the one thing still
    // tappable behind the overlay, and a tap on it silently discarded the open form.
    // A modal that leaves a navigation control reachable is not one.
    const bar = root.querySelector<HTMLElement>('.hk-bottombar');
    for (const el of [wrap, bar]) {
      if (!el) continue;
      if (drawer && isSheet) el.setAttribute('inert', '');
      else el.removeAttribute('inert');
    }
    if (drawer) {
      if (!this._drawerOnKey) {
        this._drawerOnKey = (e: KeyboardEvent): void => {
          if (e.key === 'Escape' && this.shadowRoot?.querySelector('.hk-drawer[data-open]')) {
            e.stopPropagation();
            // Close only the one that is open. Closing both ran two renders back to
            // back, and the second replaced the tree the first had just handed the
            // keyboard back to — so Escape, alone among the three ways out, left
            // focus on `<body>`.
            if (this._edit.open) this._closeForm();
            else if (this._assetEdit.open) this._closeAssetForm();
          }
        };
        document.addEventListener('keydown', this._drawerOnKey);
      }
      // Land inside the drawer rather than leaving focus on a control the render just
      // destroyed — but only on the way in, so a re-render mid-edit does not yank the
      // caret out of the field being typed into.
      if (!drawer.contains(root.activeElement)) {
        // The dialog itself, not its first control: a Home Assistant custom element
        // may not be upgraded yet (and its focus() throws when it is not), while
        // focusing the container is what makes a screen reader read the dialog's
        // label before its contents.
        this._focus(drawer);
      }
    } else if (this._drawerOnKey) {
      document.removeEventListener('keydown', this._drawerOnKey);
      this._drawerOnKey = null;
      const key = this._drawerOpenerKey;
      this._drawerOpenerKey = null;
      if (key) this._focus(root.querySelector<HTMLElement>(key));
    }
  }

  /**
   * A selector that will find *this* control again in the tree a later render builds.
   *
   * The drawer's openers are an id (`#add-btn`) or a detail page's action class
   * (`.d-edit`), both of which survive a rebuild. Anything else returns null and the
   * keyboard simply stays where the browser left it, which is what happened before.
   */
  private _openerKeyFor(el: HTMLElement | null): string | null {
    if (!el) return null;
    if (el.id) return `#${CSS.escape(el.id)}`;
    const cls = Array.from(el.classList).find((c) => c.startsWith('d-'));
    return cls ? `.${CSS.escape(cls)}` : null;
  }

  /** Remember what to hand the keyboard back to when the drawer closes. */
  private _rememberDrawerOpener(): void {
    this._drawerOpenerKey = this._openerKeyFor(
      (this.shadowRoot?.activeElement as HTMLElement) ?? null,
    );
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

  /**
   * The phone-width tab bar, pinned to the bottom of the viewport where a thumb can
   * reach it. Rendered alongside `ha-tab-group` rather than replacing it: that
   * component is Shoelace-based, so turning it into a bottom bar would mean styling
   * a shadow root we don't own. Exactly one of the two is visible at any width (see
   * the tab-bar rules in STYLES), and both drive the same `switchView`.
   *
   * Its ids are `mtab-*`, not `tab-*`: two elements cannot share an id, and the
   * desktop tabs' ids are what deep links and the test suite navigate by.
   */
  private _bottomTabs(): string {
    const v = this._view;
    const tab = (view: PanelView, id: string, label: string): string =>
      `<button class="hk-bottomtab${v === view ? ' active' : ''}" id="${id}" data-view="${view}"
         ${v === view ? 'aria-current="page"' : ''}><span class="hk-bottomtab-mark"></span>${escapeHTML(label)}</button>`;
    return `
      <nav class="hk-bottombar" aria-label="${escapeHTML(t('app.title'))}">
        ${tab('tasks', 'mtab-tasks', t('tab.tasks'))}
        ${tab('appliances', 'mtab-appliances', t('tab.appliances'))}
        ${tab('settings', 'mtab-settings', t('tab.settings'))}
      </nav>`;
  }

  /** Appliance notes — always present (even when empty) so the Edit affordance is
   *  discoverable, matching the task detail page. */
  _assetNotesSection(asset: Asset): string {
    return this._notesSection({ kind: 'asset', id: asset.id }, asset.notes || '', true);
  }

  // ── hydration: build/configure live HA components ───────────────────────────
  private _hydrate(): void {
    const root = this.shadowRoot;
    if (!root) return;

    // `markdownBlock` carries its text in `data-md`; `content` is a property, so it
    // has to be assigned after the markup lands in the DOM.
    wireMarkdown(root);

    // Mint/refresh the signed URLs for any uploaded file this render put on screen and
    // fill them into their anchors. Async, but it lands within a round-trip — long
    // before a user can reach for a link — and the anchors carry a JS fallback until
    // it does.
    void this._signFiles();

    // The completion-details dialog overlays any view, so build it first.
    const dialogHost = root.getElementById('hk-dialog-host');
    if (dialogHost && this._completion.open) renderCompletionDialog(this, dialogHost);
    if (dialogHost && this._moveCompletion.open) renderMoveCompletionDialog(this, dialogHost);
    // renderConfirmDeleteDialog appends directly to document.body (not shadow root).

    // The drawer is a sibling of the whole content column, so it belongs to every
    // page that can open it — including a task's own page, which returns out of this
    // method further down. Mounted here, before that return, or Edit on a task page
    // would open an empty drawer.
    this._mountDrawerForm(root);

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

    // Load-error retry (shown instead of the infinite spinner on a startup failure).
    root.getElementById('hk-retry')?.addEventListener('click', () => {
      this._loadError = false;
      this._render();
      void this._refresh();
    });

    // The phone-width tab bar is rendered on every route, detail pages included, so
    // it is wired before the detail-page early return below.
    root.querySelectorAll<HTMLElement>('.hk-bottomtab').forEach((b) =>
      b.addEventListener('click', () => {
        const view = b.dataset.view;
        if (view === 'tasks' || view === 'appliances' || view === 'settings') {
          switchView(this, view);
        }
      }),
    );

    // A detail page's own controls: back, its action buttons, device chips and
    // completion-delete buttons. A task detail is a page of its own and stops here
    // (`wireDetail` says so), because the wiring it shares with the list views has
    // already happened inside it; an appliance detail is rendered beside the
    // appliance list and carries on into the list wiring below.
    if (wireDetail(this, root)) return;

    // Tab navigation. Listen on each tab (click) and on the group's shoelace
    // `sl-tab-show` event (whichever fires) — both funnel through switchView,
    // which is a no-op when the view is unchanged.
    root.getElementById('tab-tasks')?.addEventListener('click', () => switchView(this, 'tasks'));
    root
      .getElementById('tab-appliances')
      ?.addEventListener('click', () => switchView(this, 'appliances'));
    root
      .getElementById('tab-settings')
      ?.addEventListener('click', () => switchView(this, 'settings'));
    root.querySelector('ha-tab-group')?.addEventListener('sl-tab-show', (e: Event) => {
      const name = (e as CustomEvent<{ name?: string }>).detail?.name;
      if (name === 'tasks' || name === 'appliances' || name === 'settings') switchView(this, name);
    });

    // The control row (Add/Export, the scope pills and their dropdown twins, the
    // saved-Profile picker, the group-collapse memory) and the list surfaces (orphan
    // cleanup, the empty state's way out, the tree toggles, a row's quick Done, the
    // intro dismiss and the "+n" chip unfold). Both wire disjoint selectors, none of
    // which the settings forms below emit, so the two passes sit together here.
    wireControls(this, root);
    wireLists(this, root);

    // The Settings tab: its four hosts built into, the card the URL names marked,
    // and the rail / index / back-bar wired.
    wireSettings(this, root);

    // Card actions: the row opens the detail page; tasks keep a quick "Done".
    wireDetailOpeners(this, root);
    wireDeviceChips(root);
  }

  /**
   * Mint the signed URLs for every uploaded file the current screen shows and fill them
   * into the anchors that are waiting for one (`data-sign` carries the cache key).
   *
   * The single signing chokepoint for the panel, run after every render: a file must be
   * openable by a *native* anchor tap, because a `window.open` issued after the async
   * sign is swallowed by the iOS app's WKWebView (issue #164). Because `ensure` also
   * evicts what isn't passed, this collects the whole set the panel currently renders —
   * the appliance detail page or the appliance edit form, which are never both up.
   */
  private async _signFiles(): Promise<void> {
    const hass = this._hass;
    if (!hass) return;
    const detailAsset =
      this._detail?.kind === 'asset'
        ? this._assets.find((a) => a.id === this._detail?.id)
        : undefined;
    const refs = [
      ...assetFileRefs(detailAsset ?? {}),
      ...assetFileRefs(this._assetEdit.asset ?? {}),
    ];
    // A screen with no uploaded files still calls through, so the cache drops the URLs
    // of whatever was on the previous one.
    await this._signedFiles.ensure(hass, refs);
    this._applySignedHrefs();
    this._armResign(refs.length > 0);
  }

  /**
   * Keep a long-lived screen's hrefs valid. Unlike the dashboard card — which re-signs
   * on every data refresh — the panel only renders on navigation and data changes, so
   * an appliance page left open (a wall tablet, a forgotten tab) would sail past the
   * backend's 1h URL TTL and every document link would 403 on click. A single timer
   * re-runs the signing pass on the same clock the cache re-mints on, updating the live
   * anchors in place. Disarmed as soon as the screen has no files, and on unmount.
   */
  private _armResign(needed: boolean): void {
    if (this._resignTimer) {
      clearTimeout(this._resignTimer);
      this._resignTimer = null;
    }
    if (!needed) return;
    this._resignTimer = setTimeout(() => {
      this._resignTimer = null;
      void this._signFiles();
    }, SIGNED_URL_REFRESH_MS);
  }

  /** Point every `data-sign` anchor at its freshly-minted URL. Anchors are matched by
   *  cache key, so this is safe to run against whatever the DOM currently holds (a
   *  re-render mid-sign just means the new nodes get the hrefs). */
  private _applySignedHrefs(): void {
    const root = this.shadowRoot;
    if (!root) return;
    root.querySelectorAll<HTMLAnchorElement>('a[data-sign]').forEach((el) => {
      const url = this._signedFiles.getByKey(el.dataset.sign || '');
      if (url && el.getAttribute('href') !== url) el.setAttribute('href', url);
    });
  }

  /**
   * Build one live `ha-form` and register it for `hass` updates.
   *
   * The only constructor for an `ha-form` in the panel: being registered in
   * `_liveHassEls` is what keeps a form's pickers current, and one built by hand
   * elsewhere would quietly go stale.
   *
   * *labelling* is for the forms that don't name their fields from `field.<name>` —
   * a Settings card reads `settings.<name>`, a profile `notify.<name>`, a sync group
   * `todo_sync.<name>`. Omit it for the `field.`/`help.` default; supply it and the
   * form gets exactly what is given. A *labelling* with no `computeHelper` leaves the
   * form without one rather than falling back to the `help.<name>` lookup: a stray
   * helper is a line of prose appearing under a field that never had one.
   */
  _makeForm(
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
    labelling?: {
      computeLabel: (s: { name: string }) => string;
      computeHelper?: (s: { name: string }) => string;
    },
  ): HaFormElement {
    const form = document.createElement('ha-form') as HaFormElement;
    form.hass = this._hass;
    form.schema = schema;
    form.data = data;
    if (labelling) {
      form.computeLabel = labelling.computeLabel;
      if (labelling.computeHelper) form.computeHelper = labelling.computeHelper;
    } else {
      form.computeLabel = (s: { name: string }): string => (s.name ? t('field.' + s.name) : '');
      // Muted per-field helper text under each field (keyed `help.<field>`); returns ''
      // where no string is authored, so helpers appear only where we wrote them.
      form.computeHelper = (s: { name: string }): string => {
        if (!s.name) return '';
        const h = t('help.' + s.name);
        return h === 'help.' + s.name ? '' : h;
      };
    }
    form.addEventListener('value-changed', (e: Event) => {
      const value = (e as CustomEvent<{ value: Record<string, unknown> }>).detail.value;
      onChange(value);
    });
    this._liveHassEls.push(form);
    return form;
  }

  /** The language to format dates, times and numbers in — Home Assistant's, not the
   *  browser's, so the panel's dates read the same way as the rest of HA. */
  _lang(): string | undefined {
    return this._hass?.language;
  }
}
