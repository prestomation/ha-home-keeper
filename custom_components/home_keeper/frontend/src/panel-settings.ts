/**
 * The Settings tab: the rail and phone index that name every section, the autosaving
 * option cards, the Profiles and Notifications editors, and the Companions list.
 *
 * Three scaffolds carry the whole tab, and each exists once here rather than per
 * caller:
 *
 * - `settingsListSection` — the collapsible `ha-card` that Profiles and Notifications
 *   are both rendered into (header, count, remembered collapse, intro, body).
 * - `itemCard` — the collapsible row a single profile, a single notification, and a
 *   profile's sync group are all built from (header, chevron, remembered expansion,
 *   optional Delete).
 * - `persistOptionList` — the save both option lists run through (optimistic local
 *   write, `setOptions`, expand-the-new-one, toast, error toast), with the options key
 *   and the debounce key threaded through as one value.
 *
 * Every `ha-form` here is built by the panel's own `_makeForm`, which is what keeps
 * each one registered in `_liveHassEls` (see `panel-host.ts`). The four forms this
 * region needs label their fields from four different key spaces, so they pass their
 * own `computeLabel` — that is the whole reason `_makeForm` takes one.
 */

import { PANEL_VERSION } from 'panel-version';
import * as api from './api';
import {
  generalSchema,
  notificationSchema,
  notifyFormData,
  notifyFormToNotification,
  problemSyncExclusionsSchema,
  problemSyncToggleSchema,
  profileFormData,
  profileFormToProfile,
  profileSchema,
  profileSyncSchema,
  shoppingSchema,
  toProfileSync,
  type FormField,
} from './forms';
import { t, tn } from './i18n';
import type { PanelHost } from './panel-host';
import { COMPANIONS_DOCS_URL, DOCS_URL } from './panel-icons';
import type {
  Companion,
  HomeKeeperOptions,
  Notification,
  Profile,
  ProfileSync,
} from './types';
import {
  btnAttrs,
  escapeHTML,
  navigateTo,
  setBtnWeight,
  toast,
  type SettingsSection,
} from './utils';

export function switchView(p: PanelHost, view: 'tasks' | 'appliances' | 'settings'): void {
  // Tapping the tab you are already on returns to its list when a detail page is
  // open — the standard "tab bar pops to root" gesture, and the only way back out of
  // a detail from the phone tab bar, whose Appliances tab is *already* the current
  // view while an appliance detail is showing. An open Settings section is the same
  // gesture: the tab pops back to the section index.
  if (p._view === view && !p._detail && !p._settingsSection) return;
  // Switching tabs is a lateral move, not a drill-in: replace so Back doesn't
  // retrace every tab toggle.
  p._navigate({ view, detail: null }, true);
}

/**
 * Every Settings section in display order, with the heading, the mark saying what
 * state it is in, and the line saying what it is set to.
 *
 * The anchor rail and the phone index are two renderings of this one list, so they
 * cannot come to disagree about what exists or what it says. Every label reuses the
 * heading its section already carries, so neither surface adds translated prose to
 * keep in sync with the cards it points at.
 */
export function settingsSectionList(p: PanelHost): {
  key: SettingsSection;
  card: string;
  label: string;
  mark: string;
  summary: string;
}[] {
  const opts = p._options;
  // The dot was the rail's only indicator and it said everything in hue: green for
  // on, amber for "configured but with nothing to deliver to". A screen reader got
  // an empty span, and so did anyone who cannot separate the two colours.
  const dot = (state: 'on' | 'warn' | 'off'): string =>
    state === 'off'
      ? ''
      : `<span class="hk-rail-dot ${state}" role="img" aria-label="${escapeHTML(
          t(state === 'warn' ? 'settings.state_warn' : 'settings.state_on'),
        )}" title="${escapeHTML(
          t(state === 'warn' ? 'settings.state_warn' : 'settings.state_on'),
        )}"></span>`;
  const count = (n: number): string =>
    n ? `<span class="hk-rail-count">${escapeHTML(String(n))}</span>` : '';
  const companionsOn = p._companions.filter((c) => c.status === 'connected').length;
  const sections: { key: SettingsSection; card: string; label: string; mark: string }[] = [
    { key: 'general', card: 'hk-settings-general', label: t('settings.general_heading'), mark: '' },
    {
      key: 'shopping',
      card: 'hk-settings-shopping',
      label: t('settings.shopping_heading'),
      mark: dot(opts?.shopping_list_entity ? 'on' : 'off'),
    },
    {
      key: 'problem',
      card: 'hk-settings',
      label: t('settings.heading'),
      mark: dot(opts?.sync_problem_sensors ? 'on' : 'off'),
    },
    {
      key: 'profiles',
      card: 'hk-profiles',
      label: t('notify.profiles_heading'),
      mark: count(opts?.profiles?.length ?? 0),
    },
    {
      key: 'notifications',
      card: 'hk-notifications',
      label: t('notify.heading'),
      // Amber rather than green when notifications are configured but there is no
      // mobile app to deliver them to — the one state that looks fine on the card
      // and silently does nothing.
      mark: p._notifyTargets.length ? count(opts?.notifications?.length ?? 0) : dot('warn'),
    },
    { key: 'companions', card: 'hk-companions', label: t('companions.heading'), mark: count(companionsOn) },
  ];
  // Every section says what it holds, not just how much. A bare "2" beside Profiles
  // is not enough to decide whether to open it, and those three sections are exactly
  // the ones whose state is least guessable from the heading. Naming what is inside
  // costs no new translated prose — the names are the user's own.
  const forSummary = (opts ?? {}) as HomeKeeperOptions;
  const names = (list: { name?: string }[] | undefined): string =>
    (list ?? [])
      .map((x) => x.name)
      .filter((n): n is string => !!n)
      .join(', ');
  const listed: Partial<Record<SettingsSection, string>> = {
    profiles: names(opts?.profiles),
    notifications: names(opts?.notifications),
    companions: names(p._companions.filter((c) => c.status === 'connected')),
  };
  return sections.map((s) => ({
    ...s,
    summary: listed[s.key] || settingsSummary(p, s.card, forSummary),
  }));
}

/**
 * The Settings tab's anchor rail: every section, in order, with a dot or a count
 * saying what state it is in.
 *
 * Settings is one long page of cards, and the thing people actually want from it is
 * "is the mirror on, do I have notifications set up" — questions the rail answers
 * without scrolling. Clicking an entry opens that section's URL, which on a wide
 * screen scrolls its card into view.
 */
export function settingsRail(p: PanelHost): string {
  const entry = (s: { key: SettingsSection; card: string; label: string; mark: string }): string =>
    `<button class="hk-rail-link" data-rail="${escapeHTML(s.card)}" data-section="${escapeHTML(
      s.key,
    )}"${s.key === p._settingsSection ? ' aria-current="page"' : ''}>
         <span class="hk-rail-label">${escapeHTML(s.label)}</span>${s.mark}
       </button>`;
  return `
      <nav class="hk-settings-rail" aria-label="${escapeHTML(t('tab.settings'))}">
        ${settingsSectionList(p).map(entry).join('')}
        ${settingsFoot()}
      </nav>`;
}

/** The version and documentation link that close the Settings tab, on whichever of
 *  the rail or the phone index is the one showing. */
function settingsFoot(): string {
  return `
      <div class="hk-rail-foot">
        <span class="hk-rail-ver">v${escapeHTML(PANEL_VERSION)}</span>
        <a href="${DOCS_URL}" target="_blank" rel="noopener noreferrer">${escapeHTML(
          t('help.docsLink'),
        )}</a>
      </div>`;
}

/**
 * The Settings tab's section index — the phone's way in.
 *
 * A phone has no room for a rail beside six expanded sections, and no room for the
 * six sections either. So it gets the list first: every section as a row naming it,
 * what it is set to, and its mark, opening that section's own URL. It is rendered
 * at every width and hidden by CSS on a wide screen, so nothing here has to know
 * how big the viewport is.
 */
export function settingsIndex(p: PanelHost): string {
  const row = (s: {
    key: SettingsSection;
    label: string;
    mark: string;
    summary: string;
  }): string => `
      <button class="hk-index-row" data-section="${escapeHTML(s.key)}">
        <span class="hk-index-text">
          <span class="hk-index-name">${escapeHTML(s.label)}</span>
          ${s.summary ? `<span class="hk-index-sum">${escapeHTML(s.summary)}</span>` : ''}
        </span>
        ${s.mark}
        <span class="hk-index-chev" aria-hidden="true"></span>
      </button>`;
  return `
      <div class="hk-settings-index">
        <ha-card class="hk-index-card">${settingsSectionList(p).map(row).join('')}</ha-card>
        ${settingsFoot()}
      </div>`;
}

/** The phone's header for one open Settings section: the way back to the index, and
 *  the section's own name. Hidden by CSS where the whole page fits. */
export function settingsBackbar(p: PanelHost): string {
  const current = settingsSectionList(p).find((s) => s.key === p._settingsSection);
  if (!current) return '';
  return `
      <div class="hk-settings-backbar">
        <ha-button id="settings-back" ${btnAttrs('tertiary')}>‹ ${escapeHTML(t('btn.back'))}</ha-button>
        <span class="hk-settings-backtitle">${escapeHTML(current.label)}</span>
      </div>`;
}

/** Render the Settings tab — `ha-form` mirrors of the options flow that autosave
 *  each change (the backend reloads + re-runs the problem sync). Three cards: a
 *  **General** card for settings (like one-off retention) that aren't tied to any
 *  single feature, the **Shopping list** mirror, and problem-sensor sync. The two
 *  feature cards each carry a paragraph, because both do something to the user's
 *  data they should read about before switching it on. */
function renderSettingsForm(p: PanelHost, host: HTMLElement): void {
  const opts: HomeKeeperOptions = p._options ?? {
    sync_problem_sensors: false,
    problem_sensor_exclude_entities: [],
    problem_sensor_exclude_devices: [],
    problem_sensor_exclude_areas: [],
    problem_sensor_exclude_labels: [],
    one_off_retention_days: 0,
    shopping_list_entity: '',
    profiles: [],
    notifications: [],
  };
  // General — settings independent of any single feature (e.g. one-off retention).
  host.appendChild(
    settingsCard(
      p,
      'hk-settings-general',
      'settings.general_heading',
      'settings.general_help',
      generalSchema(),
      opts,
    ),
  );
  // Shopping list — where auto-buy reminders are mirrored.
  host.appendChild(
    settingsCard(
      p,
      'hk-settings-shopping',
      'settings.shopping_heading',
      'settings.shopping_help',
      shoppingSchema(p._ownTodoEntities),
      opts,
      // Clearing an entity picker emits `undefined`, which JSON drops on the way
      // to the backend — so the key never reaches the partial-update merge and
      // "turn the mirror off" silently wouldn't stick. Send the empty string the
      // backend reads as off. (The other settings are multi-selects, which emit
      // `[]`, which is why nothing has needed this before.)
      (value) => ({ ...value, shopping_list_entity: String(value.shopping_list_entity ?? '') }),
    ),
  );
  // Problem-sensor sync. Keeps id `hk-settings` (deep-link/e2e/test anchor). The
  // exclusions are split out so they can be indented behind the switch that decides
  // whether they apply at all.
  host.appendChild(
    settingsCard(
      p,
      'hk-settings',
      'settings.heading',
      'settings.help',
      problemSyncToggleSchema(),
      opts,
      undefined,
      {
        schema: problemSyncExclusionsSchema(),
        labelKey: 'settings.exclusions',
        noteKey: 'settings.exclusions_note',
      },
    ),
  );
}

/** Build one autosaving Settings card: a titled `ha-card` wrapping an `ha-form`
 *  for *schema*, seeded with the full *opts* and saving on change. *coerce*, when
 *  given, cleans the emitted value before it is saved. */
function settingsCard(
  p: PanelHost,
  id: string,
  headingKey: string,
  helpKey: string,
  schema: FormField[],
  opts: HomeKeeperOptions,
  coerce?: (value: Record<string, unknown>) => Record<string, unknown>,
  dependent?: { schema: FormField[]; labelKey: string; noteKey: string },
): HTMLElement {
  const card = document.createElement('ha-card');
  card.className = 'hk-form-card hk-settings-card';
  card.id = id;
  const inner = document.createElement('div');
  inner.className = 'hk-form-inner';
  // The card states its current value under its name, so the Settings page can be
  // read for what it is set to without opening anything.
  const summary = settingsSummary(p, id, opts);
  inner.innerHTML = `
      <div class="hk-form-title">${escapeHTML(t(headingKey))}</div>
      ${summary ? `<div class="hk-settings-value">${escapeHTML(summary)}</div>` : ''}
      <div class="hk-settings-intro">${escapeHTML(t(helpKey))}</div>`;

  const build = (fields: FormField[]): HTMLElement =>
    p._makeForm(
      fields,
      { ...opts },
      (raw) => {
        const value = coerce ? coerce(raw) : raw;
        // Each form carries only its own fields, which is exactly what the options
        // endpoint wants: it merges partial updates, so a change to the toggle never
        // has to restate the exclusions to leave them alone.
        void saveOptions(p, value as Partial<HomeKeeperOptions>);
      },
      {
        computeLabel: (s) => (s.name ? t('settings.' + s.name) : ''),
        // Optional per-field note, for a setting whose consequences aren't obvious from
        // its label (the problem-sensor toggle: what clears such a task, and where it
        // shows up). `t()` echoes an unknown key back, which is how a field with no note
        // renders none.
        computeHelper: (s) => {
          if (!s.name) return '';
          const key = `settings.${s.name}_help`;
          const text = t(key);
          return text === key ? '' : text;
        },
      },
    );

  inner.appendChild(build(schema));
  if (dependent) {
    // Fields that only bite while the setting above them is on, indented behind a
    // rule and captioned with that condition — the same treatment the task form
    // gives the fields a recurrence choice reveals.
    const indent = document.createElement('div');
    indent.className = 'hk-indent';
    const body = document.createElement('div');
    body.className = 'hk-indent-body';
    const head = document.createElement('div');
    head.className = 'hk-indent-head';
    head.innerHTML =
      `<span class="hk-eyebrow accent">${escapeHTML(t(dependent.labelKey))}</span>` +
      `<span class="hk-indent-note">${escapeHTML(t(dependent.noteKey))}</span>`;
    body.append(head, build(dependent.schema));
    indent.appendChild(body);
    inner.appendChild(indent);
  }
  card.appendChild(inner);
  return card;
}

/**
 * One line stating what a Settings card is currently set to, shown under its name.
 *
 * Derived from the live options rather than stored, so it can never disagree with
 * the controls below it. Returns '' where a card has nothing worth restating.
 */
function settingsSummary(p: PanelHost, id: string, opts: HomeKeeperOptions): string {
  if (id === 'hk-settings-general') {
    const days = Number(opts.one_off_retention_days) || 0;
    return days > 0 ? tn('settings.retention_summary', days) : t('settings.retention_forever');
  }
  if (id === 'hk-settings-shopping') {
    const entity = String(opts.shopping_list_entity ?? '');
    if (!entity) return t('settings.shopping_off');
    const name = p._hass?.states?.[entity]?.attributes?.friendly_name;
    return t('settings.shopping_on', { list: String(name || entity) });
  }
  if (id === 'hk-settings') {
    if (!opts.sync_problem_sensors) return t('settings.sync_off');
    const excluded =
      (opts.problem_sensor_exclude_entities?.length ?? 0) +
      (opts.problem_sensor_exclude_devices?.length ?? 0) +
      (opts.problem_sensor_exclude_areas?.length ?? 0) +
      (opts.problem_sensor_exclude_labels?.length ?? 0);
    return excluded ? tn('settings.sync_on_excluding', excluded) : t('settings.sync_on');
  }
  // The three sections whose summary is the names of what they hold. When they hold
  // nothing the join is '', and the row fell through to the empty string below —
  // saying nothing at all, in exactly the state a new install is in. The index
  // promises to name every section *and what it is set to*, so "set to nothing" is
  // an answer it owes the reader too.
  if (id === 'hk-profiles') return t('settings.profiles_none');
  if (id === 'hk-notifications') return t('settings.notifications_none');
  if (id === 'hk-companions') return t('settings.companions_none');
  return '';
}

async function saveOptions(p: PanelHost, value: Partial<HomeKeeperOptions>): Promise<void> {
  if (!p._hass) return;
  // Keep local state in sync optimistically so the form doesn't flicker; the
  // backend persists, reloads the entry and re-runs the problem-sensor sync.
  p._options = { ...(p._options as HomeKeeperOptions), ...value };
  try {
    await api.setOptions(p._hass, value);
    // setOptions resolves only once the backend has reloaded and reconciled the
    // synced problem-sensor tasks for the new exclusions. Refresh our cached
    // tasks (without re-rendering — that would tear down the form the user is
    // still editing) so the change is reflected the moment they return to the
    // Tasks tab, rather than lingering until the next refresh.
    await p._reload();
    toast(p, t('settings.saved'));
  } catch (err) {
    toast(p, String((err as { message?: string })?.message || err));
  }
}

// ── the two shared scaffolds ────────────────────────────────────────────────

/**
 * A collapsible Settings card holding a list of editable items — the shape Profiles
 * and Notifications are both rendered into. The header names the section and counts
 * what it holds, the collapse choice is remembered on `_settingsSectionCollapsed`
 * under *key*, and *fill* adds the section's own empty-state alerts, item editors
 * and Add button under the intro line.
 */
function settingsListSection(
  p: PanelHost,
  host: HTMLElement,
  o: { id: string; key: string; headingKey: string; helpKey: string; count: number },
  fill: (body: HTMLElement) => void,
): void {
  const isCollapsed = p._settingsSectionCollapsed.has(o.key);

  const card = document.createElement('ha-card');
  card.className = 'hk-form-card';
  card.id = o.id;
  const inner = document.createElement('div');
  inner.className = 'hk-form-inner';

  // Clickable header (always visible)
  const header = document.createElement('button');
  header.className = 'hk-section-header';
  header.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
  header.innerHTML = `
      <span class="hk-form-title hk-section-title">${escapeHTML(t(o.headingKey))}</span>
      ${o.count ? `<span class="hk-section-count">${o.count}</span>` : ''}
      <ha-icon icon="mdi:chevron-down" class="hk-section-chevron${isCollapsed ? '' : ' open'}"></ha-icon>`;
  inner.appendChild(header);

  // Collapsible body
  const body = document.createElement('div');
  if (isCollapsed) body.style.display = 'none';
  const intro = document.createElement('div');
  intro.className = 'hk-settings-intro';
  intro.textContent = t(o.helpKey);
  body.appendChild(intro);
  fill(body);
  inner.appendChild(body);
  card.appendChild(inner);

  header.addEventListener('click', () => {
    const collapsed = p._settingsSectionCollapsed.has(o.key);
    const chevron = header.querySelector<HTMLElement>('.hk-section-chevron');
    if (collapsed) {
      p._settingsSectionCollapsed.delete(o.key);
      body.style.display = '';
      header.setAttribute('aria-expanded', 'true');
      chevron?.classList.add('open');
    } else {
      p._settingsSectionCollapsed.add(o.key);
      body.style.display = 'none';
      header.setAttribute('aria-expanded', 'false');
      chevron?.classList.remove('open');
    }
  });

  host.appendChild(card);
}

/**
 * One collapsible row inside a Settings section: a profile, a notification, or a
 * profile's sync group. The header carries the row's name (returned to *fill*, so a
 * rename can retitle the collapsed row live), an optional extra element beside it,
 * and the chevron. *isOpen* and *setOpen* say where the expansion state is kept, so
 * the three callers can each use their own; *onDelete*, when given, adds the Delete
 * button under the body.
 */
function itemCard(o: {
  className: string;
  name: string;
  headerExtra?: HTMLElement;
  isOpen: () => boolean;
  setOpen: (open: boolean) => void;
  fill: (body: HTMLElement, nameSpan: HTMLElement) => void;
  /** Returns its promise so the button can hold itself down for the round trip. */
  onTest?: () => Promise<void>;
  onDelete?: () => void;
}): HTMLElement {
  const isExpanded = o.isOpen();

  const card = document.createElement('div');
  card.className = o.className;

  // Clickable header showing the row's name
  const header = document.createElement('button');
  header.className = 'hk-item-header';
  header.setAttribute('aria-expanded', isExpanded ? 'true' : 'false');
  const nameSpan = document.createElement('span');
  nameSpan.className = 'hk-item-name';
  nameSpan.textContent = o.name;
  header.appendChild(nameSpan);
  if (o.headerExtra) header.appendChild(o.headerExtra);
  const chevron = document.createElement('ha-icon');
  (chevron as unknown as Record<string, string>).icon = 'mdi:chevron-down';
  chevron.className = 'hk-section-chevron' + (isExpanded ? ' open' : '');
  header.appendChild(chevron);
  card.appendChild(header);

  // Collapsible body
  const body = document.createElement('div');
  body.className = 'hk-item-body';
  if (!isExpanded) body.style.display = 'none';
  o.fill(body, nameSpan);

  // One right-aligned footer row, so a row that has both actions keeps Delete where it
  // has always been and puts the safe action to its left.
  if (o.onTest || o.onDelete) {
    const actions = document.createElement('div');
    actions.className = 'hk-item-actions';
    if (o.onTest) {
      const test = document.createElement('ha-button');
      test.className = 'hk-notify-test';
      setBtnWeight(test, 'secondary');
      test.textContent = t('notify.test');
      // Held down for the round trip. A save plus a send is slow enough to look
      // unresponsive, and every press delivers a real notification to a real phone,
      // so an impatient double-press would send twice.
      //
      // The flag lives on this button element rather than on the host, which is safe
      // because `set hass` only refreshes on its *first* call — a later hass update
      // (including the config-entry reload this handler's own save triggers) pushes
      // into `_liveHassEls` without re-rendering, so the button survives the send it
      // started. The one case that does defeat it is Home Assistant replacing the
      // whole panel element mid-flight, which remounts every row enabled. That is the
      // same swap `walkthrough.capture.ts` guards its row-opens against, it needs the
      // swap to land inside a ~1s round trip, and it costs one duplicate test
      // notification, so it is not worth hoisting this state onto the host to cover.
      const onTest = o.onTest;
      test.addEventListener('click', () => {
        if (test.hasAttribute('disabled')) return;
        test.setAttribute('disabled', '');
        void onTest().finally(() => test.removeAttribute('disabled'));
      });
      actions.appendChild(test);
    }
    if (o.onDelete) {
      const del = document.createElement('ha-button');
      del.className = 'hk-notify-delete';
      setBtnWeight(del, 'danger');
      del.textContent = t('notify.delete');
      del.addEventListener('click', o.onDelete);
      actions.appendChild(del);
    }
    body.appendChild(actions);
  }
  card.appendChild(body);

  header.addEventListener('click', () => {
    const open = !o.isOpen();
    o.setOpen(open);
    const chev = header.querySelector<HTMLElement>('.hk-section-chevron');
    body.style.display = open ? '' : 'none';
    header.setAttribute('aria-expanded', open ? 'true' : 'false');
    chev?.classList.toggle('open', open);
  });

  return card;
}

// ── persistence ─────────────────────────────────────────────────────────────

/** The two option lists the Settings tab edits. The options key is also the debounce
 *  key, which is what lets one helper serve both. */
type OptionListKey = 'profiles' | 'notifications';

/**
 * How many saves of each list this panel has issued, so a save can tell whether it is
 * still the newest by the time its answer arrives.
 *
 * Per host and weakly held: two panels must not share a counter, and a panel Home
 * Assistant has thrown away must not be kept alive by one.
 */
const saveSeq = new WeakMap<PanelHost, Map<OptionListKey, number>>();

/** Claim the next sequence number for *key*, and a check for still being the newest. */
function claimSave(p: PanelHost, key: OptionListKey): () => boolean {
  let byKey = saveSeq.get(p);
  if (!byKey) {
    byKey = new Map();
    saveSeq.set(p, byKey);
  }
  const seq = (byKey.get(key) ?? 0) + 1;
  byKey.set(key, seq);
  return () => saveSeq.get(p)?.get(key) === seq;
}

/**
 * Save one of the option lists: write it locally first so the form doesn't flicker,
 * then persist, optionally expand whatever the backend appended (an id is only known
 * after the round-trip), re-render if asked, and say so. A failure toasts the
 * backend's own message and leaves the reload to restore the truth.
 *
 * An answer **only replaces `p._options` when this save is still the newest** for its
 * list. Two rows can have writes in flight at once, and the answers are not guaranteed
 * to arrive in the order they were sent: an earlier one landing last would put
 * `p._options` back to the state before the later row was saved, and the next row to
 * build a list from it would then write that staleness to disk — losing a value the
 * user was told was saved. Nothing is lost by ignoring the out-of-date copy, because
 * the newest write already carries every earlier row's value: each list is built from
 * `p._options` after the earlier save updated it (see `persistDebounced`).
 *
 * Only that assignment is skipped. Being superseded is not a failure, so the save still
 * expands, re-renders and says "Saved" — a person who pressed *Add notification* has to
 * get their row and their toast whether or not another row's autosave happened to land
 * in between.
 */
async function persistOptionList(
  p: PanelHost,
  key: OptionListKey,
  list: Profile[] | Notification[],
  render: boolean,
  expandLast = false,
): Promise<void> {
  if (!p._hass) return;
  const isNewest = claimSave(p, key);
  p._options = { ...(p._options as HomeKeeperOptions), [key]: list };
  try {
    const merged = await api.setOptions(p._hass, {
      [key]: list,
    } as Partial<HomeKeeperOptions>);
    // A later save owns the truth now, and its own answer will set it.
    if (isNewest()) p._options = merged;
    if (expandLast) {
      const saved: { id: string }[] = p._options?.[key] ?? [];
      if (saved.length) p._itemExpanded.add(saved[saved.length - 1].id);
    }
    if (render) p._render();
    toast(p, t('settings.saved'));
  } catch (err) {
    // The optimistic write above stands. The user keeps what they typed and sees the
    // backend's own message, and the next save of this list carries the value again —
    // a retry rather than a silent revert. Rolling back here would take the text out
    // of the field under them, which is worse for the common case (a transient
    // failure) than re-sending it.
    toast(p, String((err as { message?: string })?.message || err));
  }
}

/**
 * The per-keystroke form saves, debounced so a text edit doesn't fire a config-entry
 * reload on every character.
 *
 * Two details here are load-bearing, and getting either wrong silently drops an edit
 * the user was told was saved (#255).
 *
 * The timer is keyed **per row**, not per list. One timer for the whole list means
 * touching a second row inside the 600ms window cancels the first row's pending save,
 * and the first row's edit is never written.
 *
 * *buildList* is called when the timer **fires**, not when it is armed. A list built
 * at keystroke time is a snapshot of `p._options` from before any save that lands in
 * between, so writing it would put every other row back to where it was. Building late
 * composes instead: `persistOptionList` updates `p._options` synchronously before it
 * awaits, so a row saving second already sees the row that saved first.
 */
function persistDebounced(
  p: PanelHost,
  key: OptionListKey,
  itemId: string,
  buildList: () => Profile[] | Notification[],
): void {
  p._debounce(`${key}:${itemId}`, () => void persistOptionList(p, key, buildList(), false));
}

// ── profiles ────────────────────────────────────────────────────────────────

/** Render the Settings → Profiles card: reusable saved filters (status +
 *  labels/areas/devices), each an autosaving `ha-form`. Profiles are consumed by
 *  notifications, the admin task list, and the dashboard card. */
function renderProfiles(p: PanelHost, host: HTMLElement): void {
  const profiles = p._options?.profiles ?? [];
  settingsListSection(
    p,
    host,
    {
      id: 'hk-profiles',
      key: 'profiles',
      headingKey: 'notify.profiles_heading',
      helpKey: 'notify.profiles_help',
      count: profiles.length,
    },
    (body) => {
      if (!profiles.length) {
        const alert = document.createElement('ha-alert');
        alert.setAttribute('alert-type', 'info');
        alert.textContent = t('notify.profiles_empty');
        body.appendChild(alert);
      }
      for (const profile of profiles) body.appendChild(profileEditor(p, profile));
      const add = document.createElement('ha-button');
      add.id = 'hk-profile-add';
      add.className = 'hk-notify-add';
      setBtnWeight(add, 'secondary');
      add.textContent = t('notify.add_profile');
      add.addEventListener('click', () => void addProfile(p));
      body.appendChild(add);
    },
  );
}

function profileEditor(p: PanelHost, profile: Profile): HTMLElement {
  // The row says where it syncs without being opened; the group below is the
  // only place that can change it, so the chip is display-only.
  const syncChip = document.createElement('span');
  paintSyncChip(p, syncChip, profile.sync?.entity_id ?? '');

  return itemCard({
    className: 'hk-item-card',
    name: profile.name,
    headerExtra: syncChip,
    isOpen: () => p._itemExpanded.has(profile.id),
    setOpen: (open) => {
      if (open) p._itemExpanded.add(profile.id);
      else p._itemExpanded.delete(profile.id);
    },
    onDelete: () => void deleteProfile(p, profile.id),
    fill: (body, nameSpan) => {
      // The filter form and the sync group are two `ha-form`s editing one profile, and
      // both save through the same debounce key. Each keeps the other half in a closure
      // so whichever fires last still writes both — and so a rename can't wipe a
      // configured list, which is what saving the filter form alone would do.
      let filter = profileFormData(profile);
      let sync: ProfileSync = toProfileSync(profile.sync);
      const saveProfile = (): void => {
        persistDebounced(p, 'profiles', profile.id, () =>
          (p._options?.profiles ?? []).map((x) =>
            x.id === profile.id ? profileFormToProfile(profile.id, filter, sync) : x,
          ),
        );
      };

      body.appendChild(
        p._makeForm(
          profileSchema(),
          filter,
          (value) => {
            filter = value;
            if (typeof filter.name === 'string') nameSpan.textContent = filter.name;
            saveProfile();
          },
          {
            computeLabel: (s) => {
              if (s.name === 'name') return t('field.name');
              if (s.name === 'labels') return t('field.labels');
              return t('notify.' + s.name);
            },
            // The three status values are nested tiers, not independent buckets —
            // "Overdue and due soon" already covers everything overdue. Nothing in a
            // single-select says so, which read as a missing multi-select (#248), so
            // the helper spells it out.
            computeHelper: (s) => (s.name === 'status' ? t('notify.status_help') : ''),
          },
        ),
      );

      body.appendChild(
        profileSyncGroup(p, profile, sync, (next) => {
          sync = next;
          paintSyncChip(p, syncChip, next.entity_id);
          saveProfile();
        }),
      );
    },
  });
}

/** The expand/collapse key for a profile's sync group. Namespaced so it can share
 *  the panel's two expansion sets with the profile row itself. */
function syncKey(profileId: string): string {
  return `sync:${profileId}`;
}

/** Whether a profile's sync group starts open. A configured list is worth seeing
 *  at a glance, so it defaults open and an unconfigured one stays folded — but an
 *  explicit expand (`_itemExpanded`) or collapse (`_settingsSectionCollapsed`)
 *  outranks the default, so re-rendering never undoes what the user just did. */
function syncGroupExpanded(p: PanelHost, profile: Profile): boolean {
  const key = syncKey(profile.id);
  if (p._itemExpanded.has(key)) return true;
  if (p._settingsSectionCollapsed.has(key)) return false;
  return Boolean(profile.sync?.entity_id);
}

function setSyncGroupExpanded(p: PanelHost, profileId: string, expanded: boolean): void {
  const key = syncKey(profileId);
  if (expanded) {
    p._itemExpanded.add(key);
    p._settingsSectionCollapsed.delete(key);
  } else {
    p._settingsSectionCollapsed.add(key);
    p._itemExpanded.delete(key);
  }
}

/** The synced list's friendly name, falling back to the raw entity id for a list
 *  with no state yet (a freshly picked one, or one whose integration is offline). */
function syncListName(p: PanelHost, entityId: string): string {
  const friendly = p._hass?.states?.[entityId]?.attributes?.friendly_name;
  return typeof friendly === 'string' && friendly ? friendly : entityId;
}

/** Paint (or clear) the chip on a collapsed profile row that names the to-do list
 *  the profile syncs to. An unsynced profile shows nothing rather than an empty
 *  pill, so the chip's presence is itself the signal. */
function paintSyncChip(p: PanelHost, chip: HTMLElement, entityId: string): void {
  if (!entityId) {
    chip.className = '';
    chip.removeAttribute('title');
    chip.removeAttribute('aria-label');
    chip.innerHTML = '';
    return;
  }
  const name = syncListName(p, entityId);
  const label = t('todo_sync.chip', { name });
  chip.className = 'hk-sync-chip';
  chip.setAttribute('title', label);
  chip.setAttribute('aria-label', label);
  // A plain span, not an `ha-assist-chip`: the row header is a <button>, and HA's
  // chip renders a button of its own, which would nest one inside the other.
  chip.innerHTML = `<ha-icon icon="mdi:swap-horizontal" class="hk-chip-ic"></ha-icon>${escapeHTML(name)}`;
}

/** A profile's collapsible **Sync to a to-do list** group: the list to sync the
 *  profile's tasks onto, plus what a change over there means here. There is no
 *  delete button — clearing the picker is the off switch, which is why the schema
 *  round-trips a cleared value to `''` rather than dropping the key. */
function profileSyncGroup(
  p: PanelHost,
  profile: Profile,
  initial: ProfileSync,
  onChange: (sync: ProfileSync) => void,
): HTMLElement {
  return itemCard({
    className: 'hk-sync-group',
    name: t('todo_sync.group'),
    isOpen: () => syncGroupExpanded(p, profile),
    setOpen: (open) => setSyncGroupExpanded(p, profile.id, open),
    fill: (body) => {
      const intro = document.createElement('div');
      intro.className = 'hk-settings-intro';
      intro.textContent = t('todo_sync.group_help');
      body.appendChild(intro);

      body.appendChild(
        p._makeForm(
          profileSyncSchema(p._ownTodoEntities),
          { ...initial },
          // Clearing the picker emits `undefined`, which JSON drops on the way to the
          // backend; normalizing to '' is what makes "switch the sync off" stick.
          (value) => onChange(toProfileSync(value)),
          { computeLabel: (s) => (s.name ? t('todo_sync.' + s.name) : '') },
        ),
      );
    },
  });
}

function addProfile(p: PanelHost): Promise<void> {
  const blank: Profile = {
    id: '',
    name: t('notify.new_profile'),
    filter: {
      status: 'overdue',
      labels: [],
      areas: [],
      devices: [],
      exclude_labels: [],
      exclude_areas: [],
      exclude_devices: [],
    },
    // No list picked: the sync does nothing until one is, and both switches
    // carry the defaults the backend normalizer would fill in.
    sync: { entity_id: '', two_way: true, vanish_as_completed: true },
  };
  return persistOptionList(p, 'profiles', [...(p._options?.profiles ?? []), blank], true, true);
}

function deleteProfile(p: PanelHost, id: string): Promise<void> {
  p._itemExpanded.delete(id);
  p._itemExpanded.delete(syncKey(id));
  p._settingsSectionCollapsed.delete(syncKey(id));
  const next = (p._options?.profiles ?? []).filter((x) => x.id !== id);
  return persistOptionList(p, 'profiles', next, true);
}

// ── notifications ───────────────────────────────────────────────────────────

/** Render the Settings → Notifications card: delivery bindings that each reference
 *  a profile and add targets/buttons/style — see the backend `notifier.py`. */
function renderNotifications(p: PanelHost, host: HTMLElement): void {
  const profiles = p._options?.profiles ?? [];
  const notifications = p._options?.notifications ?? [];
  settingsListSection(
    p,
    host,
    {
      id: 'hk-notifications',
      key: 'notifications',
      headingKey: 'notify.heading',
      helpKey: 'notify.help',
      count: notifications.length,
    },
    (body) => {
      if (!p._notifyTargets.length) {
        const alert = document.createElement('ha-alert');
        alert.setAttribute('alert-type', 'info');
        alert.textContent = t('notify.no_targets');
        body.appendChild(alert);
      }
      if (!profiles.length) {
        const alert = document.createElement('ha-alert');
        alert.setAttribute('alert-type', 'info');
        alert.textContent = t('notify.need_profile');
        body.appendChild(alert);
      }
      if (!notifications.length) {
        const alert = document.createElement('ha-alert');
        alert.setAttribute('alert-type', 'info');
        alert.textContent = t('notify.empty');
        body.appendChild(alert);
      }
      for (const notification of notifications) {
        body.appendChild(notificationEditor(p, notification, profiles));
      }
      const add = document.createElement('ha-button');
      add.id = 'hk-notify-add';
      add.className = 'hk-notify-add';
      setBtnWeight(add, 'secondary');
      add.textContent = t('notify.add');
      if (!profiles.length) add.setAttribute('disabled', '');
      add.addEventListener('click', () => void addNotification(p));
      body.appendChild(add);
    },
  );
}

function notificationEditor(
  p: PanelHost,
  notification: Notification,
  profiles: Profile[],
): HTMLElement {
  // The row's live value. Test must send what the form shows, so it saves this rather
  // than trusting whatever the last debounced write happened to catch.
  let current: Notification = notification;
  const listWith = (n: Notification): Notification[] =>
    (p._options?.notifications ?? []).map((x) => (x.id === notification.id ? n : x));

  return itemCard({
    className: 'hk-item-card',
    name: notification.name,
    isOpen: () => p._itemExpanded.has(notification.id),
    setOpen: (open) => {
      if (open) p._itemExpanded.add(notification.id);
      else p._itemExpanded.delete(notification.id);
    },
    onTest: () => testNotification(p, () => current, listWith),
    onDelete: () => void deleteNotification(p, notification.id),
    fill: (body, nameSpan) => {
      body.appendChild(
        p._makeForm(
          notificationSchema(p._notifyTargets, profiles),
          notifyFormData(notification),
          (value) => {
            if (typeof value.name === 'string') nameSpan.textContent = value.name;
            current = notifyFormToNotification(notification.id, value);
            persistDebounced(p, 'notifications', notification.id, () => listWith(current));
          },
          {
            computeLabel: (s) => {
              if (s.name === 'name') return t('field.name');
              if (s.name === 'profile_id') return t('notify.profile');
              return t('notify.' + s.name);
            },
            // Both fields do something the field name cannot say. A channel is
            // Android's word and means nothing on an iPhone. Its sound and Do Not
            // Disturb settings belong to the phone once the channel exists, so a later
            // urgency change does not move a channel that already exists. Critical
            // needs a permission on iOS.
            computeHelper: (s) => {
              if (s.name === 'channel') return t('notify.channel_help');
              if (s.name === 'urgency') return t('notify.urgency_help');
              return '';
            },
          },
        ),
      );
    },
  });
}

/**
 * Send this notification now, so the delivery just configured can be checked on the
 * phone without waiting for a task to come due.
 *
 * Pending edits are saved first: `home_keeper.notify` resolves the notification out of
 * stored options, so an unsaved channel or urgency would test the previous delivery
 * and quietly report success. A run that matched nothing is a real outcome rather than
 * an error, and says the filter found nothing due, so it gets its own message.
 *
 * `matched` is what says a notification went out, not `sent`: `sent` is the *task id*
 * a walk surfaced, and a digest that delivered answers `null` for it. Reading `sent`
 * as a count made every real delivery report "no task is due" (#255).
 */
async function testNotification(
  p: PanelHost,
  current: () => Notification,
  listWith: (n: Notification) => Notification[],
): Promise<void> {
  const hass = p._hass;
  if (!hass) return;
  try {
    p._options = await api.setOptions(hass, { notifications: listWith(current()) });
    const { matched } = await api.runNotification(hass, current().id);
    toast(p, matched > 0 ? t('notify.test_sent') : t('notify.test_none'));
  } catch (err) {
    toast(p, String((err as { message?: string })?.message || err));
  }
}

function addNotification(p: PanelHost): Promise<void> {
  const profiles = p._options?.profiles ?? [];
  if (!profiles.length) return Promise.resolve();
  const blank: Notification = {
    id: '',
    name: t('notify.new_name'),
    profile_id: profiles[0].id,
    targets: p._notifyTargets.length ? [p._notifyTargets[0]] : [],
    actions: ['complete', 'snooze', 'open'],
    snooze_hours: 24,
    style: 'walk',
    channel: '',
    urgency: 'normal',
    auto: { overdue: false, due_soon: false },
  };
  return persistOptionList(
    p,
    'notifications',
    [...(p._options?.notifications ?? []), blank],
    true,
    true,
  );
}

function deleteNotification(p: PanelHost, id: string): Promise<void> {
  p._itemExpanded.delete(id);
  const next = (p._options?.notifications ?? []).filter((n) => n.id !== id);
  return persistOptionList(p, 'notifications', next, true);
}

// ── companions ──────────────────────────────────────────────────────────────

/** Render the Settings → Companions section: integrations that work with
 *  Home Keeper. *Connected* rows (self-registered, or a detected glue) deep-link
 *  to the companion's own options page; *Suggested* rows (a popular upstream is
 *  installed but its glue isn't) offer an install link and can be dismissed. */
function renderCompanions(p: PanelHost, host: HTMLElement): void {
  const all = p._companions ?? [];
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
    // Static link to the docs catalog of known companions/glue. Only the
    // template's `<a>` is trusted here — the URL is a constant, no user content.
    `<div class="hk-settings-intro">${t('companions.discover', { url: COMPANIONS_DOCS_URL })}</div>`,
  ];
  if (!connected.length && !suggested.length) {
    sections.push(`<ha-alert alert-type="info">${escapeHTML(t('companions.empty'))}</ha-alert>`);
  }
  if (connected.length) {
    sections.push(
      `<div class="hk-companion-group">${escapeHTML(t('companions.connected'))}</div>`,
      ...connected.map((c) => companionRow(c)),
    );
  }
  if (suggested.length) {
    sections.push(
      `<div class="hk-companion-group">${escapeHTML(t('companions.suggested'))}</div>`,
      ...suggested.map((c) => companionRow(c)),
    );
  }
  inner.innerHTML = sections.join('');
  card.appendChild(inner);
  host.appendChild(card);
  wireCompanions(p, inner);
}

/** One companion row's HTML (icon, name + status chip, description, actions). Takes
 *  no `PanelHost`: a row is a pure function of the companion it describes. */
function companionRow(c: Companion): string {
  const icon = escapeHTML(c.icon || 'mdi:puzzle');
  const chipLabel = c.status === 'connected' ? t('companions.chip.connected') : t('companions.chip.suggested');
  const chipClass = c.status === 'connected' ? 'hk-comp-connected' : 'hk-comp-suggested';
  const actions: string[] =
    c.status === 'connected'
      ? [
          `<ha-button ${btnAttrs('secondary')} class="hk-comp-configure" data-domain="${escapeHTML(c.configure_domain || c.domain)}">${escapeHTML(t('companions.configure'))}</ha-button>`,
        ]
      : [
          `<ha-button ${btnAttrs('secondary')} class="hk-comp-install" data-url="${escapeHTML(c.install_url || '')}">${escapeHTML(t('companions.install'))}</ha-button>`,
          `<ha-button ${btnAttrs('tertiary')} class="hk-comp-dismiss" data-domain="${escapeHTML(c.domain)}">${escapeHTML(t('companions.dismiss'))}</ha-button>`,
        ];
  if (c.docs_url) {
    actions.push(
      `<ha-button ${btnAttrs('tertiary')} class="hk-comp-docs" data-url="${escapeHTML(c.docs_url)}">${escapeHTML(t('companions.docs'))}</ha-button>`,
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
function wireCompanions(p: PanelHost, root: HTMLElement): void {
  root.querySelectorAll<HTMLElement>('.hk-comp-configure').forEach((b) =>
    b.addEventListener('click', () => {
      const domain = b.dataset.domain;
      if (domain) navigateTo(`/config/integrations/integration/${domain}`);
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
      if (domain) void dismissCompanion(p, domain);
    }),
  );
}

/** Hide a suggested companion by persisting its domain to dismissed_companions. */
async function dismissCompanion(p: PanelHost, domain: string): Promise<void> {
  if (!p._hass) return;
  const current = p._options?.dismissed_companions ?? [];
  if (current.includes(domain)) return;
  const dismissed_companions = [...current, domain];
  try {
    await api.setOptions(p._hass, { dismissed_companions });
    await p._refresh();
  } catch (err) {
    toast(p, String((err as { message?: string })?.message || err));
  }
}

// ── hydration ───────────────────────────────────────────────────────────────

/**
 * Build the Settings tab's live components into their four hosts, mark the card the
 * URL names, and wire the two ways into a section plus the phone's way back out.
 */
export function wireSettings(p: PanelHost, root: ShadowRoot): void {
  // Forms.
  const settingsHost = root.getElementById('hk-settings-host');
  if (settingsHost) renderSettingsForm(p, settingsHost);
  const profilesHost = root.getElementById('hk-profiles-host');
  if (profilesHost) renderProfiles(p, profilesHost);
  const notificationsHost = root.getElementById('hk-notifications-host');
  if (notificationsHost) renderNotifications(p, notificationsHost);
  const companionsHost = root.getElementById('hk-companions-host');
  if (companionsHost) renderCompanions(p, companionsHost);

  // Mark the card the URL names, so the phone rules can show that one and hide its
  // five siblings without CSS having to compare two attribute values. This is a
  // fact about the route, not about the viewport, so it is set at every width.
  if (p._view === 'settings') {
    const current = settingsSectionList(p).find((s) => s.key === p._settingsSection);
    root.querySelectorAll('.hk-settings-col ha-card').forEach((card) => {
      card.classList.toggle('hk-sec-current', !!current && card.id === current.card);
    });
  }

  // Both ways into a section navigate, so the URL always says which one is open.
  // The rail is a lateral move along one page, so it replaces; an index row is a
  // drill-in from a list, so it pushes and Back returns to the list. On a wide
  // screen the whole page is showing, so a rail click also scrolls its card into
  // view — guarded because jsdom does not implement `scrollIntoView`.
  root.querySelectorAll<HTMLElement>('.hk-rail-link').forEach((link) =>
    link.addEventListener('click', () => {
      const section = link.dataset.section as SettingsSection | undefined;
      if (section) p._navigate({ view: 'settings', detail: null, section }, true);
      const card = link.dataset.rail ? root.getElementById(link.dataset.rail) : null;
      if (card && typeof card.scrollIntoView === 'function') {
        card.scrollIntoView({ block: 'start', behavior: p._scrollBehavior() });
      }
    }),
  );
  root.querySelectorAll<HTMLElement>('.hk-index-row').forEach((row) =>
    row.addEventListener('click', () => {
      const section = row.dataset.section as SettingsSection | undefined;
      if (section) p._navigate({ view: 'settings', detail: null, section });
      // A drill-in opens a screen, so it opens at the top of one. Worth saying out
      // loud now that the page is patched rather than rebuilt: nothing else moves
      // the scroll, so an index read halfway down would open a section halfway down.
      const top = root.querySelector<HTMLElement>('.hk-toolbar');
      if (top && typeof top.scrollIntoView === 'function') {
        top.scrollIntoView({ block: 'start' });
      }
    }),
  );
  root.getElementById('settings-back')?.addEventListener('click', () => p._closeSettingsSection());
}
