/**
 * Settings → Companions → **Declarative companions**: specs that materialize one
 * managed sensor task per matching entity, with no glue integration in between.
 *
 * Three surfaces, all free functions over a `PanelHost` (see `panel-host.ts`):
 *
 * - the subsection at the foot of the Companions card — `declarativeSection` renders
 *   it and `wireDeclarativeSection` wires Add / Add from preset / Edit / Delete;
 * - the preset picker: one card per bundled preset, disabled when the integration it
 *   needs has no config entry;
 * - the add/edit dialog: `ha-form`s (identity, selection, trigger, template) over
 *   one draft, and beneath them a live preview of what the companion would match. The
 *   selection section shows integration and domain; a **More filters** row opens the
 *   other filters and the four exclusion lists (#373). Each preview row has an
 *   Exclude button, and an excluded entity is listed under the rows with Include.
 *   The preview also warns when another stored companion already covers those entities.
 *   `declarativeOverlap` works that out from the tasks the panel already holds, so
 *   the warning costs no extra backend call.
 *
 * Both dialogs are state-driven (`p._declDialog`) and built through `makeDialog`, so
 * they open, title and close the way the completion dialogs do and pick up the next
 * `ha-dialog` fix with them. The draft is edited **in place** (every section's form
 * writes into the same object), which is what lets a trigger-mode change re-render
 * the dialog with a different schema without losing what was typed. The one part the
 * mode change replaces is the trigger block itself: see `triggerForMode`, which drops
 * the keys the new mode does not accept.
 */

import * as api from './api';
import {
  applyKeyRows,
  EXCLUSION_FIELDS,
  exclusionsSchema,
  hasMoreFilters,
  idList,
  keyOptions,
  keyRows,
  moreFiltersSchema,
  moreFiltersSummary,
  toggleId,
  toggleKeyRow,
  type KeyRow,
} from './declarative-filters';
import {
  pickFormData,
  selBool,
  selLabel,
  selNumber,
  selSelect,
  selSelectCustom,
  selText,
  type FormField,
} from './forms';
import { t, tn } from './i18n';
import { makeDialog, openConfirmDialog } from './panel-dialogs';
import type { PanelHost } from './panel-host';
import { indentGroup } from './panel-indent';
import { groupPresets, presetTaskNames } from './preset-picker';
import { wireBrandImage } from './panel-chips';
import {
  changedSections,
  companionOrigin,
  limitProgress,
  presetFor,
  resetToPreset,
} from './preset-summary';
import type {
  DeclarativeCompanion,
  DeclarativeCompanionPreset,
  DeclarativeCompanionPreviewMatch,
  DeclarativeCompanionPreviewResult,
  EntityKeyList,
  PresetLimit,
  Task,
} from './types';
import {
  brandLogoUrl,
  btnAttrs,
  escapeHTML,
  formatReading,
  setBtnWeight,
  toast,
} from './utils';

/** The trigger modes the form offers, in the order the dropdown lists them. */
// `template` goes last on purpose. The four above it each answer one plain question,
// and a user who wants one of those must not have to read past Jinja to find it.
const TRIGGER_MODES = ['state', 'threshold', 'usage', 'availability', 'template'] as const;
const COMPARISONS = ['>=', '<=', '>', '<', '==', '!='] as const;
/** The domains the entity-domain picker suggests; any other value can be typed. */
const DOMAINS = ['binary_sensor', 'sensor', 'update', 'switch', 'number'] as const;
/** How long the form has to be quiet before the preview is fetched again. */
const PREVIEW_DEBOUNCE_MS = 350;
/** Above this many matches the preview warns. Mirrors `const.MAX_DECLARATIVE_MATCH_WARN`. */
const MATCH_WARN = 50;

/** The trigger block read loosely: which keys it carries depends on the mode. */
export type Trigger = Record<string, unknown> & { mode?: string };

/**
 * The trigger keys each mode keeps, mirroring `models.normalize_sensor`.
 *
 * The backend does not ignore a key that belongs to another mode — `_reject_fields`
 * raises on it — so a mode change must drop them. A companion seeded from the Device
 * Pulse preset carries `comparison` and `value`; switching it to *state* kept both,
 * and the save came back "sensor.comparison is not valid for a state-mode sensor
 * task" (issues #230 / #231).
 *
 * `usage` drops `for_seconds` and `clear_on_recover`: a meter has no condition to
 * hold or to recover from, and `normalize_sensor` reads neither in that mode.
 * `availability` drops `attribute`, because the form offers no attribute box there,
 * and a carried-over one would be a setting nobody can see or clear. `template` drops
 * it for a stronger reason: `normalize_sensor` rejects an attribute in that mode,
 * because a template reads `attributes.<key>` itself and a second, invisible hop
 * would change what `{{ state }}` means inside it.
 */
const TRIGGER_KEYS_BY_MODE: Record<string, readonly string[]> = {
  usage: ['attribute', 'target', 'baseline', 'unit', 'also_every', 'combinator'],
  threshold: ['attribute', 'comparison', 'value', 'for_seconds', 'clear_on_recover'],
  state: ['attribute', 'state', 'for_seconds', 'clear_on_recover'],
  availability: ['for_seconds', 'clear_on_recover'],
  template: ['template', 'for_seconds', 'clear_on_recover'],
};

/** Kept whatever the mode is. A spec's trigger normally omits `entity_id` — the
 *  reconciler stamps it per match — but where it appears it is mode-independent.
 *  `mode` is not listed: the rewrite always stamps the new one itself. */
const TRIGGER_KEYS_EVERY_MODE = ['entity_id'];

/** What a mode's form shows for a key it defaults rather than leaves empty. Seed the
 *  draft with the same values, or the two disagree: the State box read "on" while the
 *  draft carried no `state`, and the save failed as "sensor.state is required".
 *  `value` and `target` are left out on purpose — they are genuinely the user's to
 *  type, and an empty required box says so. */
const TRIGGER_DEFAULTS: Record<string, Record<string, unknown>> = {
  usage: {},
  threshold: { comparison: '>=', clear_on_recover: true },
  state: { state: 'on', clear_on_recover: true },
  availability: { clear_on_recover: true },
  // No default `template`: it is genuinely the user's to write, and an empty
  // required box says so. `clear_on_recover` follows the other edge modes, so a
  // companion's tasks close themselves when the condition goes away.
  template: { clear_on_recover: true },
};

/**
 * *trigger* rewritten for *nextMode*: the keys that mode accepts, plus the defaults
 * its form shows. Pure — the caller assigns the result over `draft.trigger`.
 */
export function triggerForMode(trigger: Trigger, nextMode: string): Trigger {
  const keep = new Set([...TRIGGER_KEYS_EVERY_MODE, ...(TRIGGER_KEYS_BY_MODE[nextMode] ?? [])]);
  const next: Trigger = {};
  for (const [key, value] of Object.entries(trigger)) {
    if (keep.has(key)) next[key] = value;
  }
  for (const [key, value] of Object.entries(TRIGGER_DEFAULTS[nextMode] ?? {})) {
    if (next[key] === undefined) next[key] = value;
  }
  next.mode = nextMode;
  return next;
}

/** A blank declarative companion, for the Add-from-scratch path. */
export function emptyDeclarativeCompanion(): DeclarativeCompanion {
  return {
    id: '',
    name: '',
    description: '',
    enabled: true,
    preset_id: null,
    selection: {
      area_ids: [],
      label_ids: [],
      exclude_entity_ids: [],
      exclude_device_ids: [],
      exclude_area_ids: [],
      exclude_label_ids: [],
    },
    // The same rule that rewrites the trigger on a mode change builds the first one,
    // so a blank draft and a switched one can never carry different keys.
    trigger: triggerForMode({}, 'state') as unknown as DeclarativeCompanion['trigger'],
    // The device part of the Device Pulse preset's name template. `friendly_name` on its own
    // repeats the device name Home Assistant already prefixes, so a hand-written
    // companion produced "Replace Roborock S7 Main brush time left" and the entity id
    // `sensor.roborock_s7_replace_roborock_s7_main_brush_time_left_next_due`.
    task_template: {
      name_template: '{{ device_name or friendly_name }}',
      notes_template: '',
      labels: [],
    },
    per_entity_overrides: {},
  };
}

/** The spec id a managed task was materialized from, or undefined for any other task. */
export function declarativeSpecId(task: Task): string | undefined {
  const source = task.source as
    | { declarative_companion?: { spec_id?: string } }
    | null
    | undefined;
  return source?.declarative_companion?.spec_id;
}

/**
 * The stored declarative companion that made *task*, or undefined for any other task.
 *
 * The task page reads it to answer "where are this task's settings?". A declarative
 * companion that is no longer stored returns undefined, so the page falls back to the
 * generic managed-task captions rather than offering an editor for one that is gone.
 */
export function declarativeCompanionFor(
  p: PanelHost,
  task: Task,
): DeclarativeCompanion | undefined {
  const specId = declarativeSpecId(task);
  return specId ? p._declarativeCompanions.find((s) => s.id === specId) : undefined;
}

/** What `declarativeOverlap` found: the companion that already covers the most of the
 *  draft's matches, and how many of those matches it covers. */
export interface DeclarativeOverlap {
  /** The other companion's name, or its id when it is no longer stored. */
  name: string;
  /** How many of the entities in *matched* that companion already has a task for. */
  count: number;
}

/**
 * The companion that already covers part of *matched*, or null when none does.
 *
 * Two companions that select the same entity each materialize their own task for it, so
 * the user gets two identical tasks and the task list says nothing about why. The check
 * runs in the panel: a materialized task carries its spec id in
 * `source.declarative_companion.spec_id` and the entity it watches in
 * `sensor.entity_id`, and the panel already holds every task and every stored
 * companion.
 *
 * *draftId* is the companion under edit and is skipped. Its tasks are the tasks the
 * draft rebuilds, not an overlap with another companion.
 *
 * *matched* is the preview sample, so the count is a count of the matches on screen.
 * The warning names one companion, so only the companion with the most overlap is
 * returned. If two companions cover the same number, the first one found in *tasks*
 * wins.
 */
export function declarativeOverlap(
  matched: readonly { entity_id: string }[],
  tasks: readonly Task[],
  specs: readonly DeclarativeCompanion[],
  draftId: string,
): DeclarativeOverlap | null {
  const wanted = new Set(matched.map((m) => m.entity_id));
  if (!wanted.size) return null;
  const covered = new Map<string, Set<string>>();
  for (const task of tasks) {
    const specId = declarativeSpecId(task);
    if (!specId || specId === draftId) continue;
    const entityId = task.sensor?.entity_id;
    if (!entityId || !wanted.has(entityId)) continue;
    const seen = covered.get(specId) ?? new Set<string>();
    seen.add(entityId);
    covered.set(specId, seen);
  }
  let best: DeclarativeOverlap | null = null;
  for (const [specId, seen] of covered) {
    if (best && seen.size <= best.count) continue;
    best = { name: specs.find((s) => s.id === specId)?.name || specId, count: seen.size };
  }
  return best;
}

export function errorMessage(err: unknown): string {
  return String((err as { message?: string })?.message || err);
}

// ── the subsection inside the Companions card ───────────────────────────────

/** The subsection's HTML: heading, help, the two Add buttons, then a row per companion. */
export function declarativeSection(p: PanelHost): string {
  const rows = p._declarativeCompanions.length
    ? p._declarativeCompanions.map((spec) => declarativeRow(p, spec)).join('')
    : `<div class="hk-decl-empty">${escapeHTML(t('declarative.companions.empty'))}</div>`;
  return `
      <div class="hk-companion-group hk-companion-group-decl">${escapeHTML(t('declarative.companions.heading'))}</div>
      <div class="hk-settings-intro">${escapeHTML(t('declarative.companions.help'))}</div>
      <div class="hk-decl-actions">
        <ha-button ${btnAttrs('primary')} class="hk-decl-add">${escapeHTML(t('declarative.companions.add'))}</ha-button>
        <ha-button ${btnAttrs('secondary')} class="hk-decl-preset">${escapeHTML(t('declarative.companions.add_from_preset'))}</ha-button>
      </div>
      ${rows}`;
}

/** The badge on a companion row's logo for each preset shape: its icon and its name. */
const SHAPE_BADGES: Record<string, { icon: string; key: string }> = {
  percent_low: { icon: 'mdi:trending-down', key: 'declarative.companions.shape.percent_low' },
  life_low: { icon: 'mdi:timer-sand-complete', key: 'declarative.companions.shape.life_low' },
  wear_high: { icon: 'mdi:counter', key: 'declarative.companions.shape.wear_high' },
  reading_low: { icon: 'mdi:arrow-down-bold', key: 'declarative.companions.shape.reading_low' },
  reading_high: { icon: 'mdi:arrow-up-bold', key: 'declarative.companions.shape.reading_high' },
  alert: { icon: 'mdi:alert-outline', key: 'declarative.companions.shape.alert' },
};

/** The icon a companion row shows when it has no integration logo. */
const COMPANION_ICON = 'mdi:puzzle-outline';

/** The name of each entity platform the companion form offers, in the panel language. */
const PLATFORM_NAMES: Record<string, string> = {
  binary_sensor: 'declarative.companions.platform.binary_sensor',
  sensor: 'declarative.companions.platform.sensor',
  update: 'declarative.companions.platform.update',
  switch: 'declarative.companions.platform.switch',
  number: 'declarative.companions.platform.number',
};

/** The name of entity platform *domain*. Home Assistant does not load the titles of
 *  the entity platforms in a panel, so the panel has its own for the common ones. */
function platformName(p: PanelHost, domain: string): string {
  const key = PLATFORM_NAMES[domain];
  return key ? t(key) : integrationTitle(p, domain);
}

/** Home Assistant's title for *domain* (`component.<domain>.title`), else *domain*. */
function integrationTitle(p: PanelHost, domain: string): string {
  return p._hass?.localize?.(`component.${domain}.title`) || domain;
}

/**
 * One companion row: a logo tile, the name with its status chips, the description,
 * and a meta line that says the integration, the platform, the limit and the count.
 */
export function declarativeRow(p: PanelHost, spec: DeclarativeCompanion): string {
  const count = p._tasks.filter((task) => declarativeSpecId(task) === spec.id).length;
  const origin = companionOrigin(spec, p._declarativePresets);
  const enabled = spec.enabled
    ? `<ha-assist-chip class="hk-comp-connected" label="${escapeHTML(t('declarative.companions.enabled'))}"></ha-assist-chip>`
    : `<ha-assist-chip class="hk-comp-suggested" label="${escapeHTML(t('declarative.companions.disabled'))}"></ha-assist-chip>`;
  const custom = origin.custom
    ? `<span class="hk-decl-custom">${escapeHTML(t('declarative.companions.custom'))}</span>`
    : '';
  const desc = spec.description
    ? `<div class="hk-companion-desc">${escapeHTML(spec.description)}</div>`
    : '';
  const fallbackIcon = escapeHTML(origin.icon || COMPANION_ICON);
  const art = origin.domain
    ? `<img class="hk-decl-logo" alt="" src="${escapeHTML(brandLogoUrl(origin.domain))}" data-domain="${escapeHTML(origin.domain)}" data-fallback-icon="${fallbackIcon}" />`
    : `<ha-icon class="hk-decl-logo" icon="${fallbackIcon}"></ha-icon>`;
  const badge = origin.shape ? SHAPE_BADGES[origin.shape] : undefined;
  const badgeHtml = badge
    ? `<span class="hk-decl-shape" title="${escapeHTML(t(badge.key))}"><ha-icon icon="${badge.icon}"></ha-icon></span>`
    : '';
  const source = origin.domain
    ? origin.brand || integrationTitle(p, origin.domain)
    : t('declarative.companions.any_integration');
  const meta = [
    source,
    origin.platform ? platformName(p, origin.platform) : '',
    origin.limitText ?? '',
    t('declarative.companions.matches', { count: String(count) }),
  ]
    .filter(Boolean)
    .map((part) => `<span>${escapeHTML(part)}</span>`)
    .join('');
  const id = escapeHTML(spec.id);
  return `
      <div class="hk-companion hk-decl-row" data-spec-id="${id}">
        <div class="hk-companion-ic hk-decl-tile">${art}${badgeHtml}</div>
        <div class="hk-companion-body">
          <div class="hk-companion-name">${escapeHTML(spec.name)} ${enabled} ${custom}</div>
          ${desc}
          <div class="hk-decl-meta">${meta}</div>
        </div>
        <div class="hk-companion-actions">
          <ha-button ${btnAttrs('secondary')} class="hk-decl-edit" data-spec-id="${id}">${escapeHTML(t('declarative.companions.edit'))}</ha-button>
          <ha-button ${btnAttrs('danger')} class="hk-decl-delete" data-spec-id="${id}">${escapeHTML(t('declarative.companions.delete'))}</ha-button>
        </div>
      </div>`;
}

/** Make each row's logo fall back to the generic brand image, then to an icon. */
function wireDeclarativeLogos(root: HTMLElement): void {
  root.querySelectorAll<HTMLImageElement>('img.hk-decl-logo').forEach((img) =>
    wireBrandImage(img, () => {
      const icon = document.createElement('ha-icon');
      icon.className = 'hk-decl-logo';
      icon.setAttribute('icon', img.dataset.fallbackIcon || COMPANION_ICON);
      img.replaceWith(icon);
    }),
  );
}

/** Wire the subsection's Add / Add from preset / Edit / Delete buttons. */
export function wireDeclarativeSection(p: PanelHost, root: HTMLElement): void {
  wireDeclarativeLogos(root);
  root
    .querySelector('.hk-decl-add')
    ?.addEventListener('click', () => void openDeclarativeForm(p, null));
  root.querySelector('.hk-decl-preset')?.addEventListener('click', () => void openPresetPicker(p));
  const specFor = (b: HTMLElement): DeclarativeCompanion | undefined =>
    p._declarativeCompanions.find((s) => s.id === b.dataset.specId);
  root.querySelectorAll<HTMLElement>('.hk-decl-edit').forEach((b) =>
    b.addEventListener('click', () => {
      const spec = specFor(b);
      if (spec) void openDeclarativeForm(p, spec);
    }),
  );
  root.querySelectorAll<HTMLElement>('.hk-decl-delete').forEach((b) =>
    b.addEventListener('click', () => {
      const spec = specFor(b);
      if (!spec) return;
      openConfirmDialog(
        p,
        t('declarative.companions.delete_confirm', { name: spec.name }),
        () => void deleteDeclarative(p, spec.id),
      );
    }),
  );
}

async function deleteDeclarative(p: PanelHost, id: string): Promise<void> {
  if (!p._hass) return;
  try {
    await api.deleteDeclarativeCompanion(p._hass, id);
    await p._refresh();
  } catch (err) {
    toast(p, errorMessage(err));
  }
}

// ── opening and closing ─────────────────────────────────────────────────────

/** Fetch the installed-integration list once; the picker's gate and the form's
 *  integration dropdown both read it. Best-effort: an empty list still leaves a
 *  typable box. */
async function ensureIntegrations(p: PanelHost): Promise<void> {
  if (p._installedIntegrations !== null || !p._hass) return;
  try {
    p._installedIntegrations = await api.listInstalledIntegrations(p._hass);
  } catch {
    p._installedIntegrations = [];
  }
}

async function openPresetPicker(p: PanelHost): Promise<void> {
  if (!p._hass) return;
  if (p._declarativePresets === null) {
    try {
      p._declarativePresets = await api.listDeclarativePresets(p._hass);
    } catch (err) {
      toast(p, errorMessage(err));
      return;
    }
  }
  await ensureIntegrations(p);
  p._declDialog = { open: true, kind: 'picker', draft: null };
  p._render();
}

/** Open the form on a copy of *seed* (a stored companion, or a preset's default), or
 *  on a blank one when null. Exported because a task's own page opens the companion
 *  that built it — the dialog host is global, so the form works from any view. */
export async function openDeclarativeForm(
  p: PanelHost,
  seed: DeclarativeCompanion | null,
): Promise<void> {
  if (!p._hass) return;
  await ensureIntegrations(p);
  const draft = seed
    ? (JSON.parse(JSON.stringify(seed)) as DeclarativeCompanion)
    : emptyDeclarativeCompanion();
  p._declDialog = { open: true, kind: 'form', draft };
  p._render();
}

export function seededFrom(preset: DeclarativeCompanionPreset): DeclarativeCompanion {
  return { id: '', ...(preset.default_spec as Omit<DeclarativeCompanion, 'id'>) };
}

function closeDeclarativeDialog(p: PanelHost): void {
  p._declDialog = { open: false, kind: 'picker', draft: null };
  p._render();
}

async function saveDeclarative(p: PanelHost, draft: DeclarativeCompanion): Promise<void> {
  if (!p._hass) return;
  try {
    if (draft.id) {
      await api.updateDeclarativeCompanion(p._hass, draft.id, draft);
    } else {
      // The backend assigns the id.
      const { id: _drop, ...body } = draft;
      void _drop;
      await api.addDeclarativeCompanion(p._hass, body);
    }
    p._declDialog = { open: false, kind: 'picker', draft: null };
    await p._refresh();
  } catch (err) {
    p._declDialog.error = errorMessage(err);
    p._render();
  }
}

// ── the dialogs ─────────────────────────────────────────────────────────────

/** Build whichever declarative dialog is open into *host*; a no-op when none is. */
export function renderDeclarativeDialog(p: PanelHost, host: HTMLElement): void {
  const d = p._declDialog;
  if (!d.open) return;
  if (d.kind === 'picker') renderPresetPicker(p, host);
  else if (d.draft) renderDeclarativeForm(p, host, d.draft);
}

function renderPresetPicker(p: PanelHost, host: HTMLElement): void {
  const { dialog, body, footer, mount } = makeDialog(
    t('declarative.companions.preset_picker_title'),
    () => {
      if (p._declDialog.open && p._declDialog.kind === 'picker') closeDeclarativeDialog(p);
    },
  );
  dialog.classList.add('hk-decl-picker');
  // A preset that needs an integration is offered only when that integration has a
  // config entry. The entry-domain map the panel already holds is the fallback for a
  // list that failed to load.
  const installed = new Set([
    ...(p._installedIntegrations ?? []),
    ...Object.values(p._entryDomains),
  ]);

  // The search box stays put while the list under it is drawn again on each key, so
  // typing never loses focus.
  const search = document.createElement('div');
  search.className = 'hk-decl-preset-search';
  search.innerHTML = `<ha-icon icon="mdi:magnify"></ha-icon>`;
  const input = document.createElement('input');
  input.type = 'search';
  input.id = 'hk-decl-preset-q';
  input.className = 'hk-decl-preset-q';
  input.autocomplete = 'off';
  input.placeholder = t('declarative.companions.preset_search');
  input.setAttribute('aria-label', t('declarative.companions.preset_search'));
  input.value = p._declDialog.presetQuery ?? '';
  search.appendChild(input);
  const list = document.createElement('div');
  list.className = 'hk-decl-preset-groups';
  body.append(search, list);

  const card = (preset: DeclarativeCompanionPreset): HTMLElement => {
    const missing =
      preset.requires_integration !== null && !installed.has(preset.requires_integration);
    // A real button, so the picker is keyboard-reachable like the rest of the panel.
    const el = document.createElement('button');
    el.type = 'button';
    el.className = 'hk-decl-preset-card' + (missing ? ' hk-decl-preset-disabled' : '');
    el.dataset.presetId = preset.id;
    el.disabled = missing;
    const requires = missing
      ? `<span class="hk-decl-preset-req">${escapeHTML(
          t('declarative.companions.requires_integration', {
            integration: preset.requires_integration ?? '',
          }),
        )}</span>`
      : '';
    // How many entities the preset would match now, so a user sees why it is first.
    const count =
      typeof preset.matches === 'number' && preset.matches > 0
        ? `<span class="hk-decl-preset-count">${escapeHTML(
            tn('declarative.companions.keys_entities', preset.matches),
          )}</span>`
        : '';
    const tasks = presetTaskNames(preset);
    const chips = tasks.length
      ? `<span class="hk-decl-preset-tasks">${tasks
          .map((name) => `<span class="hk-decl-preset-task">${escapeHTML(name)}</span>`)
          .join('')}</span>`
      : '';
    el.innerHTML = `
        <ha-icon icon="${escapeHTML(preset.icon)}"></ha-icon>
        <span class="hk-decl-preset-text">
          <span class="hk-decl-preset-name">${escapeHTML(preset.name)}${count}</span>
          <span class="hk-decl-preset-desc">${escapeHTML(preset.description)}</span>
          ${chips}
          ${requires}
        </span>`;
    if (!missing) {
      el.addEventListener('click', () => void openDeclarativeForm(p, seededFrom(preset)));
    }
    return el;
  };

  const draw = (): void => {
    const query = p._declDialog.presetQuery ?? '';
    const groups = groupPresets(
      p._declarativePresets ?? [],
      installed,
      query,
      p._declDialog.presetShowAll ?? false,
    );
    list.innerHTML = '';
    const section = (key: string, presets: DeclarativeCompanionPreset[]): void => {
      if (!presets.length) return;
      const head = document.createElement('div');
      head.className = 'hk-decl-preset-group';
      head.dataset.group = key;
      head.textContent = t('declarative.companions.preset_group_' + key);
      const grid = document.createElement('div');
      grid.className = 'hk-decl-preset-list';
      grid.dataset.group = key;
      for (const preset of presets) grid.appendChild(card(preset));
      list.append(head, grid);
    };
    section('mine', groups.mine);
    section('general', groups.general);
    section('other', groups.other);
    if (!groups.mine.length && !groups.general.length && !groups.other.length) {
      const empty = document.createElement('div');
      empty.className = 'hk-decl-preset-empty';
      empty.textContent = t('declarative.companions.preset_none');
      list.appendChild(empty);
    }
    if (!query.trim() && (groups.hidden || p._declDialog.presetShowAll)) {
      const toggle = document.createElement('ha-button');
      toggle.className = 'hk-decl-preset-all';
      setBtnWeight(toggle, 'tertiary');
      toggle.textContent = groups.hidden
        ? tn('declarative.companions.preset_show_all', groups.hidden)
        : t('declarative.companions.preset_hide_other');
      toggle.addEventListener('click', () => {
        p._declDialog.presetShowAll = !p._declDialog.presetShowAll;
        draw();
      });
      list.appendChild(toggle);
    }
  };
  input.addEventListener('input', () => {
    p._declDialog.presetQuery = input.value;
    draw();
  });
  draw();

  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  cancel.classList.add('hk-decl-cancel');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => closeDeclarativeDialog(p));
  footer.appendChild(cancel);

  mount();
  host.appendChild(dialog);
}

function renderDeclarativeForm(p: PanelHost, host: HTMLElement, draft: DeclarativeCompanion): void {
  const editing = Boolean(draft.id);
  const { dialog, body, footer, mount } = makeDialog(
    editing
      ? t('declarative.companions.edit_title', { name: draft.name })
      : t('declarative.companions.add_title'),
    () => {
      if (p._declDialog.open && p._declDialog.kind === 'form') closeDeclarativeDialog(p);
    },
  );
  dialog.classList.add('hk-decl-dialog');
  body.classList.add('hk-decl-dialog-body');

  // The preset this draft came from, and the box that says what it does. The box
  // checks for changes on each edit, from the same hook the preview uses.
  const preset = presetFor(draft, p._declarativePresets);
  const presetBox = preset
    ? presetSummaryBox(preset, draft, () => {
        p._declDialog.draft = resetToPreset(draft, preset.default_spec);
        p._render();
      })
    : null;
  if (presetBox) body.appendChild(presetBox.el);

  const preview = document.createElement('div');
  preview.className = 'hk-decl-preview';
  preview.textContent = t('declarative.companions.preview_loading');
  const schedulePreview = (): void => {
    presetBox?.refresh();
    // Only the dialog that is still on screen may own the pending preview. A trigger
    // mode change re-renders the dialog from *inside* the section's change handler,
    // so by the time the handler's own `schedulePreview()` runs, the new dialog has
    // already scheduled one against its own node. Both share the `decl-preview`
    // debounce key, so scheduling here would replace that live timer with one
    // pointing at this render's node — which the re-render has just detached — and
    // `refreshPreview` would return early, leaving "Loading preview…" on screen for
    // good. Switching the mode is exactly the flow #230 reported.
    if (!preview.isConnected) return;
    p._debounce(
      'decl-preview',
      () =>
        void refreshPreview(
          p,
          draft,
          preview,
          (id) => toggleExcluded(id),
          // A reading is drawn against the preset's limit only while the trigger is
          // still the preset's: an edited trigger has a limit of its own.
          preset && !presetBox?.changed().includes('trigger') ? (preset.limit ?? null) : null,
        ),
      PREVIEW_DEBOUNCE_MS,
    );
  };

  // Every field is labelled from its own key rather than `field.<name>`. Three fields
  // carry a helper. Two say what a template can read: the notes template, and the
  // trigger template, which sees the same vocabulary. The third says what the task
  // labels do to the tasks that already exist.
  const HELPERS: Record<string, string> = {
    notes_template: 'declarative.companions.template_help',
    template: 'declarative.companions.template_trigger_help',
    labels: 'declarative.companions.labels_help',
  };
  const labelling = {
    computeLabel: (s: { name: string }): string =>
      s.name ? t('declarative.companions.field_' + s.name) : '',
    computeHelper: (s: { name: string }): string =>
      s.name in HELPERS ? t(HELPERS[s.name]) : '',
  };
  // Each section is its own `ha-form` (one heading between two fields is only
  // reachable by splitting the schema) and carries `data-decl-section` so a test can
  // address the form that owns a field rather than counting elements.
  // *parent* and *titled* let a section sit inside **More filters** without a heading
  // of its own: the row above it, or the indent head, already names it.
  const section = (
    key: string,
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
    parent: HTMLElement = body,
    titled = true,
  ): HTMLElement & { data?: Record<string, unknown> } => {
    if (titled) {
      const title = document.createElement('div');
      title.className = 'hk-decl-section-title';
      title.textContent = t('declarative.companions.section_' + key);
      parent.appendChild(title);
    }
    const form = p._makeForm(
      schema,
      // `ha-form` echoes its whole `data` back on every change, so seed it with this
      // section's own fields only. Seeded with the rest, a state trigger kept handing
      // back the threshold's comparison and value and re-wrote them into the draft.
      pickFormData(data, schema),
      (value) => {
        onChange(value);
        schedulePreview();
      },
      labelling,
    );
    form.classList.add('hk-decl-form');
    form.dataset.declSection = key;
    parent.appendChild(form);
    return form;
  };
  const str = (v: unknown): string | undefined => {
    const s = String(v ?? '').trim();
    return s || undefined;
  };
  const num = (v: unknown): number | undefined =>
    v == null || v === '' || Number.isNaN(Number(v)) ? undefined : Number(v);

  // 1. Identity.
  section(
    'identity',
    [
      { name: 'name', required: true, selector: selText() },
      { name: 'description', selector: selText() },
      { name: 'enabled', selector: selBool() },
    ],
    { name: draft.name, description: draft.description, enabled: draft.enabled },
    (v) => {
      draft.name = String(v.name ?? '');
      draft.description = String(v.description ?? '');
      draft.enabled = v.enabled !== false;
    },
  );

  // 2. Which entities. The integration and domain boxes offer what is installed and
  //    the common domains, and accept anything typed.
  const integrations = (p._installedIntegrations ?? []).map((d) => ({ value: d, label: d }));
  const sel = draft.selection;
  section(
    'selection',
    [
      { name: 'integration', selector: selSelectCustom(integrations) },
      { name: 'domain', selector: selSelectCustom(DOMAINS.map((d) => ({ value: d, label: d }))) },
    ],
    { integration: sel.target_integration, domain: sel.domain },
    (v) => {
      const before = `${sel.target_integration}|${sel.domain}`;
      sel.target_integration = str(v.integration);
      sel.domain = str(v.domain);
      // Load the key list again only when the query changes. The form can report a
      // change with the same values, and each load reads the entity registry.
      if (`${sel.target_integration}|${sel.domain}` !== before) refreshKeys();
    },
  );
  // Assigned once the key editor below exists; the integration box above can change
  // before that, so it starts as a no-op.
  let refreshKeys = (): void => {};

  // 2b. More filters: the rarer filters and the exclusions, behind one row whose
  //     summary says what is set, so a closed row never hides a filter unseen. It
  //     opens by default when something in it is set; after a toggle, the choice is
  //     kept in the dialog state so a trigger-mode re-render does not close it.
  const open = p._declDialog.moreOpen ?? hasMoreFilters(sel);
  const more = document.createElement('button');
  more.type = 'button';
  more.className = 'hk-decl-more';
  more.setAttribute('aria-expanded', String(open));
  more.setAttribute('aria-controls', 'hk-decl-more-body');
  more.innerHTML = `
      <span class="hk-decl-more-text">
        <span class="hk-decl-more-title">${escapeHTML(t('declarative.companions.more_filters'))}</span>
        <span class="hk-decl-more-summary"></span>
      </span>
      <ha-icon class="hk-decl-more-chevron" icon="mdi:chevron-down"></ha-icon>`;
  const summary = more.querySelector('.hk-decl-more-summary') as HTMLElement;
  const updateSummary = (): void => {
    summary.textContent = moreFiltersSummary(sel);
  };
  updateSummary();
  const moreBody = document.createElement('div');
  moreBody.id = 'hk-decl-more-body';
  moreBody.className = 'hk-decl-more-body';
  moreBody.hidden = !open;
  more.addEventListener('click', () => {
    const next = more.getAttribute('aria-expanded') !== 'true';
    moreBody.hidden = !next;
    more.setAttribute('aria-expanded', String(next));
    p._declDialog.moreOpen = next;
  });
  body.append(more, moreBody);

  // ha-form does not keep its own value, so each change is written back. Without
  // it the area and label pickers build the next pick from the seed and drop the
  // earlier ones.
  const filtersData = (): Record<string, unknown> => ({
    device_class: sel.device_class,
    device_ids: sel.device_ids ?? [],
    area_ids: sel.area_ids ?? [],
    label_ids: sel.label_ids ?? [],
    entity_regex: sel.entity_regex,
  });
  const filtersForm = section(
    'filters',
    moreFiltersSchema(),
    filtersData(),
    (v) => {
      sel.device_class = str(v.device_class);
      sel.device_ids = idList(v.device_ids);
      sel.area_ids = idList(v.area_ids);
      sel.label_ids = idList(v.label_ids);
      sel.entity_regex = str(v.entity_regex);
      filtersForm.data = filtersData();
      updateSummary();
    },
    moreBody,
    false,
  );

  // The entity keys, each with the task name its tasks read as `{{ task_name }}`.
  // Native inputs rather than an `ha-form`: a list of key and name pairs has no
  // selector. The rows live here, so a row still being filled in (no key yet) stays
  // on screen while the draft only ever holds complete keys.
  const keysHost = document.createElement('div');
  keysHost.className = 'hk-decl-keys';
  moreBody.appendChild(
    indentGroup(
      t('declarative.companions.section_keys'),
      t('declarative.companions.keys_note'),
      keysHost,
    ),
  );
  // The name table as the editor opened it. A spec made through the service can
  // name keys that are not in its key list, and the rows do not show those (F06-4).
  const storedNames = { ...draft.task_template.task_names };
  refreshKeys = renderKeyEditor(
    keysHost,
    keyRows(sel.translation_keys, draft.task_template.task_names),
    (rows) => {
      const applied = applyKeyRows(rows, storedNames);
      sel.translation_keys = applied.translation_keys;
      draft.task_template.task_names = applied.task_names;
      updateSummary();
      schedulePreview();
    },
    {
      integration: () => sel.target_integration,
      load: async () =>
        p._hass && sel.target_integration
          ? api.listEntityKeys(p._hass, sel.target_integration, sel.domain)
          : null,
      names: storedNames,
    },
  );

  // The exclusions, indented under the same head Problem sensor sync uses.
  const exclusionsHost = document.createElement('div');
  const exclusionsData = (): Record<string, unknown> =>
    Object.fromEntries(EXCLUSION_FIELDS.map((f) => [f, sel[f] ?? []]));
  const exclusionsForm = section(
    'exclusions',
    exclusionsSchema(),
    exclusionsData(),
    (v) => {
      for (const f of EXCLUSION_FIELDS) if (f in v) sel[f] = idList(v[f]);
      exclusionsForm.data = exclusionsData();
      updateSummary();
    },
    exclusionsHost,
    false,
  );
  moreBody.appendChild(
    indentGroup(
      t('declarative.companions.section_exclusions'),
      t('declarative.companions.exclusions_note'),
      exclusionsHost,
    ),
  );

  // The preview's Exclude and Include buttons edit the same list the entity picker
  // above shows, so the two can never disagree.
  const toggleExcluded = (id: string): void => {
    sel.exclude_entity_ids = toggleId(sel.exclude_entity_ids, id);
    exclusionsForm.data = exclusionsData();
    updateSummary();
    schedulePreview();
  };

  // 3. Trigger. The schema follows the mode, so a mode change re-renders the dialog:
  //    the draft is edited in place, so nothing typed elsewhere is lost.
  const trig = draft.trigger as Trigger;
  const mode = typeof trig.mode === 'string' ? trig.mode : 'state';
  const triggerSchema: FormField[] = [
    {
      name: 'mode',
      required: true,
      selector: selSelect(
        TRIGGER_MODES.map((m) => ({
          value: m,
          label: t('declarative.companions.trigger_mode.' + m),
        })),
      ),
    },
  ];
  if (mode === 'state') triggerSchema.push({ name: 'state', required: true, selector: selText() });
  if (mode === 'threshold') {
    triggerSchema.push(
      {
        name: 'comparison',
        required: true,
        selector: selSelect(COMPARISONS.map((c) => ({ value: c, label: c }))),
      },
      // A bare number box: a threshold can be 0 or negative.
      { name: 'value', required: true, selector: { number: { mode: 'box', step: 'any' } } },
    );
  }
  if (mode === 'usage') {
    triggerSchema.push({ name: 'target', required: true, selector: selNumber(0, 'any') });
  }
  // Multiline, like the notes template: a trigger template is one expression, but it
  // runs long, and a single-line box hides its own tail.
  if (mode === 'template') {
    triggerSchema.push({ name: 'template', required: true, selector: selText(true) });
  }
  // A hold and an auto-clear belong to the edge-driven modes only; a usage meter has
  // no condition to hold or recover from, and `normalize_sensor` reads neither there.
  if (mode !== 'usage') {
    triggerSchema.push(
      { name: 'for_seconds', selector: selNumber(0) },
      { name: 'clear_on_recover', selector: selBool() },
    );
  }
  // `template` joins `availability` in offering no attribute box: the backend rejects
  // one there, and a template reads `attributes.<key>` itself.
  if (mode !== 'availability' && mode !== 'template') {
    triggerSchema.push({ name: 'attribute', selector: selText() });
  }
  section(
    'trigger',
    triggerSchema,
    {
      mode,
      state: trig.state ?? 'on',
      comparison: trig.comparison ?? '>=',
      value: trig.value,
      target: trig.target,
      template: trig.template,
      for_seconds: trig.for_seconds ?? 0,
      // The backend stores this flag only when on in the edge modes, so a missing key
      // means off there. Availability defaults it on (F06-1), as the task form does.
      clear_on_recover: trig.clear_on_recover ?? mode === 'availability',
      attribute: trig.attribute,
    },
    (v) => {
      // Each read is guarded: the section carries only the current mode's fields, so
      // an unguarded read would write `undefined` over a key another mode owns.
      if ('state' in v) trig.state = String(v.state ?? '');
      if ('comparison' in v) trig.comparison = String(v.comparison ?? '>=');
      if ('value' in v) trig.value = num(v.value);
      if ('target' in v) trig.target = num(v.target);
      if ('template' in v) trig.template = String(v.template ?? '');
      if ('for_seconds' in v) trig.for_seconds = num(v.for_seconds) ?? 0;
      if ('clear_on_recover' in v) trig.clear_on_recover = v.clear_on_recover === true;
      if ('attribute' in v) {
        const attribute = str(v.attribute);
        if (attribute) trig.attribute = attribute;
        else delete trig.attribute;
      }
      const next = typeof v.mode === 'string' ? v.mode : mode;
      trig.mode = next;
      if (next === mode) return;
      // The mode owns which keys are legal, and the backend rejects the others rather
      // than ignoring them. Rewrite the trigger for the new mode, then rebuild the
      // dialog on the new schema — the draft is edited in place, so the rest survives.
      draft.trigger = triggerForMode(trig, next) as unknown as DeclarativeCompanion['trigger'];
      p._render();
    },
  );

  // 4. Task template. The label picker builds each pick from the form's data, so the
  // data is written back on every change, as the filters above do.
  const templateData = (): Record<string, unknown> => ({
    name_template: draft.task_template.name_template,
    notes_template: draft.task_template.notes_template,
    labels: draft.task_template.labels ?? [],
  });
  const templateForm = section(
    'template',
    [
      { name: 'name_template', required: true, selector: selText() },
      { name: 'notes_template', selector: selText(true) },
      { name: 'labels', selector: selLabel(true) },
    ],
    templateData(),
    (v) => {
      draft.task_template.name_template = String(v.name_template ?? '');
      draft.task_template.notes_template = String(v.notes_template ?? '');
      draft.task_template.labels = idList(v.labels);
      templateForm.data = templateData();
    },
  );

  body.appendChild(preview);
  if (p._declDialog.error) {
    const err = document.createElement('ha-alert');
    err.setAttribute('alert-type', 'error');
    err.textContent = p._declDialog.error;
    body.appendChild(err);
  }

  const save = document.createElement('ha-button');
  save.setAttribute('slot', 'primaryAction');
  save.classList.add('hk-decl-save');
  setBtnWeight(save, 'primary');
  save.textContent = t('btn.save');
  save.addEventListener('click', () => {
    // The dialog stays on screen until the panel has re-read the store, and that
    // read waits out the entry reload the save itself can trigger — a second or
    // two. Say so on the button rather than leave it looking dead, and stop a
    // second click from adding the companion twice.
    save.setAttribute('disabled', '');
    save.textContent = t('settings.status_saving');
    void saveDeclarative(p, draft);
  });
  footer.appendChild(save);
  const cancel = document.createElement('ha-button');
  cancel.setAttribute('slot', 'secondaryAction');
  cancel.classList.add('hk-decl-cancel');
  setBtnWeight(cancel, 'tertiary');
  cancel.textContent = t('btn.cancel');
  cancel.addEventListener('click', () => closeDeclarativeDialog(p));
  footer.appendChild(cancel);

  mount();
  host.appendChild(dialog);
  schedulePreview();
}

/** Where the key editor gets the key list of the target integration. */
interface KeySource {
  integration: () => string | undefined;
  load: () => Promise<EntityKeyList | null>;
  /** The stored name table, so a key picked from the list keeps its name. */
  names?: Readonly<Record<string, string>>;
}

/**
 * The entity-key editor: one row per key, with its task name and a remove button,
 * and an Add key button under them. Under those, the key list: every key the target
 * integration's entities have, to add with a click, because Home Assistant shows a
 * `translation_key` on no screen. *onChange* gets every row on each edit.
 *
 * Returns the function that loads the key list again, which the dialog calls when
 * the integration or the domain changes.
 */
function renderKeyEditor(
  host: HTMLElement,
  initial: KeyRow[],
  onChange: (rows: KeyRow[]) => void,
  source: KeySource,
): () => void {
  let rows = initial.map((r) => ({ ...r }));
  const editor = document.createElement('div');
  editor.className = 'hk-decl-keys-rows';
  const list = document.createElement('div');
  list.className = 'hk-decl-keylist';
  host.append(editor, list);

  let keys: EntityKeyList | null = null;
  let query = '';
  let loading = 0;

  const draw = (focusLast = false): void => {
    editor.innerHTML = '';
    if (rows.length) {
      const head = document.createElement('div');
      head.className = 'hk-decl-key-row hk-decl-key-head';
      head.innerHTML =
        `<span>${escapeHTML(t('declarative.companions.key_header'))}</span>` +
        `<span>${escapeHTML(t('declarative.companions.task_name_header'))}</span>`;
      editor.appendChild(head);
    }
    rows.forEach((row, i) => {
      const line = document.createElement('div');
      line.className = 'hk-decl-key-row';
      const key = document.createElement('input');
      key.className = 'hk-decl-key-input hk-decl-key';
      key.value = row.key;
      key.placeholder = t('declarative.companions.key_header');
      key.spellcheck = false;
      key.autocomplete = 'off';
      key.setAttribute('aria-label', t('declarative.companions.key_header'));
      key.addEventListener('input', () => {
        row.key = key.value;
        onChange(rows);
      });
      // A typed key can match one in the list, so the list marks it on leaving.
      key.addEventListener('change', () => drawList());
      const name = document.createElement('input');
      name.className = 'hk-decl-key-input hk-decl-key-name';
      name.value = row.name;
      name.placeholder = t('declarative.companions.task_name_placeholder');
      name.setAttribute('aria-label', t('declarative.companions.task_name_header'));
      name.addEventListener('input', () => {
        row.name = name.value;
        onChange(rows);
      });
      const remove = document.createElement('ha-icon-button');
      remove.className = 'hk-decl-key-remove';
      remove.setAttribute('label', t('declarative.companions.remove_key'));
      remove.innerHTML = '<ha-icon icon="mdi:close"></ha-icon>';
      remove.addEventListener('click', () => {
        rows.splice(i, 1);
        onChange(rows);
        draw();
        drawList();
      });
      line.append(key, name, remove);
      editor.appendChild(line);
      if (focusLast && i === rows.length - 1) queueMicrotask(() => key.focus());
    });
    const add = document.createElement('ha-button');
    add.className = 'hk-decl-key-add';
    setBtnWeight(add, 'tertiary');
    add.textContent = t('declarative.companions.add_key');
    add.addEventListener('click', () => {
      rows.push({ key: '', name: '' });
      draw(true);
    });
    editor.appendChild(add);
  };

  // The list's search box is kept across a redraw of the rows under it, so typing
  // in it never loses focus.
  const search = document.createElement('input');
  search.type = 'search';
  search.className = 'hk-decl-keylist-q';
  search.autocomplete = 'off';
  search.placeholder = t('declarative.companions.keys_search');
  search.setAttribute('aria-label', t('declarative.companions.keys_search'));
  search.addEventListener('input', () => {
    query = search.value;
    drawOptions();
  });
  const head = document.createElement('div');
  head.className = 'hk-decl-keylist-head';
  const options = document.createElement('div');
  options.className = 'hk-decl-keylist-options';

  const drawOptions = (): void => {
    options.innerHTML = '';
    if (!keys) return;
    const picked = rows.map((r) => r.key.trim());
    const found = keyOptions(keys.keys, picked, query);
    for (const opt of found) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'hk-decl-keyopt';
      b.dataset.key = opt.key;
      b.setAttribute('aria-pressed', String(opt.picked));
      b.innerHTML = `
          <ha-icon icon="${opt.picked ? 'mdi:check-circle' : 'mdi:plus-circle-outline'}"></ha-icon>
          <span class="hk-decl-keyopt-text">
            <span class="hk-decl-keyopt-key">${escapeHTML(opt.key)}</span>
            <span class="hk-decl-keyopt-ex">${escapeHTML(opt.example_name || opt.example_entity_id)}</span>
          </span>
          <span class="hk-decl-keyopt-count">${escapeHTML(
            tn('declarative.companions.keys_entities', opt.count),
          )}</span>`;
      b.addEventListener('click', () => {
        rows = toggleKeyRow(rows, opt.key, source.names);
        onChange(rows);
        draw();
        drawOptions();
      });
      options.appendChild(b);
    }
    if (!found.length && keys.keys.length) {
      const none = document.createElement('div');
      none.className = 'hk-decl-keylist-note';
      none.textContent = t('declarative.companions.keys_none');
      options.appendChild(none);
    }
  };

  const drawList = (): void => {
    const integration = source.integration();
    list.hidden = !integration;
    if (!integration) return;
    list.innerHTML = '';
    head.innerHTML = `<span class="hk-decl-keylist-title">${escapeHTML(
      t('declarative.companions.keys_list_title', { integration }),
    )}</span>`;
    if (keys && keys.without_key) {
      head.innerHTML += `<span class="hk-decl-keylist-note">${escapeHTML(
        t('declarative.companions.keys_without', { n: String(keys.without_key) }),
      )}</span>`;
    }
    list.appendChild(head);
    if (keys === null) {
      const wait = document.createElement('div');
      wait.className = 'hk-decl-keylist-note';
      wait.textContent = t('declarative.companions.preview_loading');
      list.appendChild(wait);
      return;
    }
    if (!keys.keys.length) {
      const empty = document.createElement('div');
      empty.className = 'hk-decl-keylist-note';
      empty.textContent = t('declarative.companions.keys_empty');
      list.appendChild(empty);
      return;
    }
    list.append(search, options);
    drawOptions();
  };

  const refresh = (): void => {
    const mine = ++loading;
    keys = null;
    drawList();
    if (!source.integration()) return;
    void source
      .load()
      .catch(() => null)
      .then((found) => {
        // A later refresh (the integration changed again) owns the list now.
        if (mine !== loading) return;
        keys = found ?? { keys: [], without_key: 0 };
        drawList();
      });
  };

  draw();
  refresh();
  return refresh;
}

// ── the live preview ────────────────────────────────────────────────────────

async function refreshPreview(
  p: PanelHost,
  draft: DeclarativeCompanion,
  host: HTMLElement,
  onToggle: (entityId: string) => void,
  limit: PresetLimit | null = null,
): Promise<void> {
  // A re-render (a mode change) replaces the dialog; the old preview node is gone
  // and the new dialog schedules its own.
  if (!p._hass || !host.isConnected) return;
  try {
    const result = await api.previewDeclarativeCompanion(p._hass, draft);
    // The overlap is computed from what the panel already holds, so the preview
    // needs no second round trip to report it.
    const overlap = declarativeOverlap(
      result.matched,
      p._tasks,
      p._declarativeCompanions,
      draft.id,
    );
    const trig = (draft.trigger ?? {}) as Trigger;
    const pendingTemplate =
      trig.mode === 'template' && !String(trig.template ?? '').trim();
    host.innerHTML = previewHtml(
      result,
      overlap,
      draft.selection.exclude_entity_ids ?? [],
      pendingTemplate,
      limit,
    );
    host.querySelectorAll<HTMLElement>('[data-toggle-entity]').forEach((b) =>
      b.addEventListener('click', () => onToggle(b.dataset.toggleEntity ?? '')),
    );
  } catch (err) {
    host.innerHTML = `<ha-alert alert-type="error">${escapeHTML(errorMessage(err))}</ha-alert>`;
  }
}

/** One Exclude or Include button. The label is always there for a screen reader;
 *  on a phone the CSS hides the text and keeps the icon. */
function toggleButton(entityId: string, include: boolean): string {
  const label = t(include ? 'declarative.companions.include' : 'declarative.companions.exclude');
  const icon = include ? 'mdi:restore' : 'mdi:minus-circle-outline';
  return `<button type="button" class="hk-decl-toggle ${include ? 'hk-decl-include' : 'hk-decl-exclude'}"
      data-toggle-entity="${escapeHTML(entityId)}" aria-label="${escapeHTML(label)}">
      <ha-icon icon="${icon}"></ha-icon><span class="hk-decl-toggle-text">${escapeHTML(label)}</span>
    </button>`;
}

/** The entities excluded one by one, each with Include. Empty when there are none. */
function excludedHtml(excluded: readonly string[]): string {
  if (!excluded.length) return '';
  const rows = excluded
    .map(
      (id) => `
        <div class="hk-decl-preview-row hk-decl-excluded-row">
          <div class="hk-decl-preview-text"><div class="hk-decl-preview-eid">${escapeHTML(id)}</div></div>
          ${toggleButton(id, true)}
        </div>`,
    )
    .join('');
  return `
      <div class="hk-decl-excluded">
        <div class="hk-decl-excluded-head">${escapeHTML(
          tn('declarative.companions.excluded_heading', excluded.length),
        )}</div>
        ${rows}
      </div>`;
}

/** A preview row's reading now, with a bar toward the preset's limit when the
 *  reading must rise past it. Empty when the backend sent no state. */
function readingHtml(m: DeclarativeCompanionPreviewMatch, limit: PresetLimit | null): string {
  if (m.state == null || m.state === '') return '';
  const number = Number(m.state);
  const reading = Number.isFinite(number) ? formatReading(number, m.unit) : m.state;
  const progress = limitProgress(m.state, m.unit, limit);
  const pct = progress === null ? 0 : Math.round(progress * 100);
  // The text beside the bar says the same number, so the bar is hidden from a screen
  // reader.
  const bar =
    progress === null
      ? ''
      : `<span class="hk-decl-reading-bar" aria-hidden="true"><span style="width:${pct}%"></span></span>
         <span class="hk-decl-reading-pct">${escapeHTML(
           t('declarative.companions.preview_of_limit', { pct }),
         )}</span>`;
  return `<div class="hk-decl-reading">
      <span>${escapeHTML(t('declarative.companions.preview_now', { value: reading }))}</span>${bar}
    </div>`;
}

/**
 * The box at the top of the form for a draft made from *preset*: what the preset
 * does, its tasks, and a row that names the sections the user changed, with Reset to
 * preset. The text always describes the preset, so the row says when the draft left it.
 */
function presetSummaryBox(
  preset: DeclarativeCompanionPreset,
  draft: DeclarativeCompanion,
  onReset: () => void,
): { el: HTMLElement; refresh: () => void; changed: () => string[] } {
  const el = document.createElement('section');
  el.className = 'hk-preset-summary';
  el.setAttribute('aria-label', t('declarative.companions.summary_from_preset'));
  const tasks = presetTaskNames(preset);
  el.innerHTML = `
      <div class="hk-preset-summary-head">
        <span class="hk-preset-summary-icon"><ha-icon icon="${escapeHTML(preset.icon)}"></ha-icon></span>
        <span class="hk-preset-summary-title">
          <span class="hk-preset-summary-kicker">${escapeHTML(t('declarative.companions.summary_from_preset'))}</span>
          <span class="hk-preset-summary-name">${escapeHTML(preset.name)}</span>
        </span>
      </div>
      <p class="hk-preset-summary-desc">${escapeHTML(preset.description)}</p>
      ${
        tasks.length
          ? `<div class="hk-preset-summary-tasks"><span class="hk-preset-summary-label">${escapeHTML(
              t('declarative.companions.summary_tasks'),
            )}</span>${tasks
              .map((name) => `<span class="hk-decl-preset-task">${escapeHTML(name)}</span>`)
              .join('')}</div>`
          : ''
      }
      <div class="hk-preset-summary-changed" hidden>
        <span class="hk-preset-summary-chip"></span>
        <button type="button" class="hk-preset-summary-reset">${escapeHTML(
          t('declarative.companions.summary_reset'),
        )}</button>
        <span class="hk-preset-summary-note">${escapeHTML(t('declarative.companions.summary_changed_note'))}</span>
      </div>`;
  const row = el.querySelector('.hk-preset-summary-changed') as HTMLElement;
  const chip = el.querySelector('.hk-preset-summary-chip') as HTMLElement;
  el.querySelector('.hk-preset-summary-reset')?.addEventListener('click', onReset);
  let sections: string[] = [];
  const refresh = (): void => {
    sections = changedSections(draft, preset.default_spec);
    row.hidden = sections.length === 0;
    // The chip names each section by the heading the form gives it.
    chip.textContent = t('declarative.companions.summary_changed', {
      sections: sections
        .map((s) => t('declarative.companions.section_' + (s === 'task_template' ? 'template' : s)))
        .join(', '),
    });
  };
  refresh();
  return { el, refresh, changed: () => sections };
}

/** The preview's HTML: the count line, the warnings, the sample, and the entities
 *  excluded one by one.
 *
 * `pendingTemplate` says the draft is on Template mode with an empty box — a form the
 * user has not filled in yet, not a mistake. The backend sends no verdict for those
 * rows, so the sample still says what the companion matches while the hint says what is
 * missing. */
export function previewHtml(
  result: DeclarativeCompanionPreviewResult,
  overlap: DeclarativeOverlap | null,
  excluded: readonly string[] = [],
  pendingTemplate = false,
  limit: PresetLimit | null = null,
): string {
  if (result.over_cap) {
    return (
      `<ha-alert alert-type="error">${escapeHTML(t('declarative.companions.preview_over_cap'))}</ha-alert>` +
      excludedHtml(excluded)
    );
  }
  const count = result.count ?? 0;
  // A `warning`, the same type as the count warning below it. A second companion over
  // the same entities makes a duplicate task for each one. That is a result to
  // prevent, not a fact to read.
  const duplicate = overlap
    ? `<ha-alert alert-type="warning" class="hk-decl-preview-overlap">${escapeHTML(
        t('declarative.companions.preview_overlap', {
          name: overlap.name,
          count: String(overlap.count),
        }),
      )}</ha-alert>`
    : '';
  const warning =
    count > MATCH_WARN
      ? `<ha-alert alert-type="warning">${escapeHTML(
          t('declarative.companions.preview_many', { count: String(count) }),
        )}</ha-alert>`
      : '';
  // A template trigger is the one condition a user cannot check by reading it:
  // `{{ state > 24 }}` against a string state renders false forever and opens
  // nothing. So the backend renders it per sampled entity and each row says what it
  // got. The other modes send `null` for every row and draw no chip at all.
  const verdicts = result.matched.some(
    (m) => m.trigger_now != null || m.trigger_error != null,
  );
  const rows = result.matched
    .map(
      (m) => `
        <div class="hk-decl-preview-row">
          <div class="hk-decl-preview-text">
            <div class="hk-decl-preview-name">${escapeHTML(m.rendered_name)}</div>
            <div class="hk-decl-preview-eid">${escapeHTML(m.entity_id)}</div>
            ${
              m.translation_key
                ? `<div class="hk-decl-preview-key">${escapeHTML(m.translation_key)}</div>`
                : ''
            }
            ${readingHtml(m, limit)}
          </div>
          ${verdicts ? verdictChip(m) : ''}
          ${toggleButton(m.entity_id, false)}
        </div>`,
    )
    .join('');
  // One alert for the whole sample rather than one per row: a broken template is
  // broken for every entity, and ten copies of the same Jinja error is noise.
  const failed = result.matched.find((m) => m.trigger_error);
  const firing = result.matched.filter((m) => m.trigger_now === true).length;
  // A template that did not render decided nothing, so the header must not report a
  // count. "Due now: 0" beside a red Jinja error reads as "nothing is due", which is
  // the one thing the render did not say.
  const summary = escapeHTML(
    failed
      ? t('declarative.companions.preview_summary_undecided', {
          shown: String(result.matched.length),
          total: String(count),
        })
      : verdicts
        ? t('declarative.companions.preview_summary_due', {
            shown: String(result.matched.length),
            total: String(count),
            due: String(firing),
          })
        : t('declarative.companions.preview_summary', {
            shown: String(result.matched.length),
            total: String(count),
          }),
  );
  const templateError = failed
    ? `<ha-alert alert-type="error" class="hk-decl-template-error">${escapeHTML(
        t('declarative.companions.preview_template_error', {
          error: String(failed.trigger_error),
        }),
      )}</ha-alert>`
    : '';
  // An empty box is not an error, so this is `info` and it sits where the red alert
  // would. It cannot collide with one: an empty template renders nothing, so no row
  // carries a `trigger_error` for the backend to report.
  const templateHint =
    pendingTemplate && !failed
      ? `<ha-alert alert-type="info" class="hk-decl-template-hint">${escapeHTML(
          t('declarative.companions.preview_template_empty'),
        )}</ha-alert>`
      : '';
  return `
      <div class="hk-decl-preview-header">${summary}</div>
      ${templateError}
      ${templateHint}
      ${duplicate}
      ${warning}
      ${rows || `<div class="hk-decl-preview-empty">${escapeHTML(t('declarative.companions.preview_empty'))}</div>`}
      ${excludedHtml(excluded)}`;
}

/** The chip that says what a template trigger renders for one sampled entity. */
export function verdictChip(match: DeclarativeCompanionPreviewMatch): string {
  // Error first: a row that did not render has no verdict to report, and saying
  // "Monitored" for it would read as "this is fine".
  if (match.trigger_error) {
    return `<span class="hk-decl-chip bad">${escapeHTML(t('declarative.companions.chip_error'))}</span>`;
  }
  if (match.trigger_now === true) {
    return `<span class="hk-decl-chip due">${escapeHTML(t('declarative.companions.chip_due_now'))}</span>`;
  }
  return `<span class="hk-decl-chip quiet">${escapeHTML(t('declarative.companions.chip_monitored'))}</span>`;
}
