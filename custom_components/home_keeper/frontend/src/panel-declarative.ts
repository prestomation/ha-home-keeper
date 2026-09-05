/**
 * Settings → Companions → **Declarative companions**: recipes that materialize one
 * managed sensor task per matching entity, with no glue integration in between.
 *
 * Three surfaces, all free functions over a `PanelHost` (see `panel-host.ts`):
 *
 * - the subsection at the foot of the Companions card — `declarativeSection` renders
 *   it and `wireDeclarativeSection` wires Add / Add from preset / Edit / Delete;
 * - the preset picker: one card per bundled recipe, disabled when the integration it
 *   needs has no config entry;
 * - the add/edit dialog: four `ha-form`s (identity, selection, trigger, template) over
 *   one draft, and beneath them a live preview of what the recipe would match. The
 *   preview also warns when another stored recipe already covers those entities.
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
  pickFormData,
  selBool,
  selNumber,
  selSelect,
  selSelectCustom,
  selText,
  type FormField,
} from './forms';
import { t } from './i18n';
import { makeDialog, openConfirmDialog } from './panel-dialogs';
import type { PanelHost } from './panel-host';
import type {
  DeclarativeCompanion,
  DeclarativeCompanionPreset,
  DeclarativeCompanionPreviewResult,
  Task,
} from './types';
import { btnAttrs, escapeHTML, setBtnWeight, toast } from './utils';

/** The trigger modes the form offers, in the order the dropdown lists them. */
const TRIGGER_MODES = ['state', 'threshold', 'usage', 'availability'] as const;
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
 * raises on it — so a mode change must drop them. A recipe seeded from the Device
 * Pulse preset carries `comparison` and `value`; switching it to *state* kept both,
 * and the save came back "sensor.comparison is not valid for a state-mode sensor
 * task" (issues #230 / #231).
 *
 * `usage` drops `for_seconds` and `clear_on_recover`: a meter has no condition to
 * hold or to recover from, and `normalize_sensor` reads neither in that mode.
 * `availability` drops `attribute`, because the form offers no attribute box there,
 * and a carried-over one would be a setting nobody can see or clear.
 */
const TRIGGER_KEYS_BY_MODE: Record<string, readonly string[]> = {
  usage: ['attribute', 'target', 'baseline', 'unit', 'also_every', 'combinator'],
  threshold: ['attribute', 'comparison', 'value', 'for_seconds', 'clear_on_recover'],
  state: ['attribute', 'state', 'for_seconds', 'clear_on_recover'],
  availability: ['for_seconds', 'clear_on_recover'],
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

/** A blank recipe, for the Add-from-scratch path. */
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
    // The same name template every bundled preset uses. `friendly_name` on its own
    // repeats the device name Home Assistant already prefixes, so a hand-written
    // recipe produced "Replace Roborock S7 Main brush time left" and the entity id
    // `sensor.roborock_s7_replace_roborock_s7_main_brush_time_left_next_due`.
    task_template: {
      name_template: '{{ device_name or friendly_name }}',
      notes_template: '',
      labels: [],
    },
    per_entity_overrides: {},
  };
}

/** The recipe id a managed task was materialized from, or undefined for any other task. */
export function declarativeSpecId(task: Task): string | undefined {
  const source = task.source as
    | { declarative_companion?: { spec_id?: string } }
    | null
    | undefined;
  return source?.declarative_companion?.spec_id;
}

/** What `declarativeOverlap` found: the recipe that already covers the most of the
 *  draft's matches, and how many of those matches it covers. */
export interface DeclarativeOverlap {
  /** The other recipe's name, or its id when the recipe is no longer stored. */
  name: string;
  /** How many of the entities in *matched* that recipe already has a task for. */
  count: number;
}

/**
 * The recipe that already covers part of *matched*, or null when none does.
 *
 * Two recipes that select the same entity each materialize their own task for it, so
 * the user gets two identical tasks and the task list says nothing about why. The
 * check runs in the panel: a materialized task carries its recipe id in
 * `source.declarative_companion.spec_id` and the entity it watches in
 * `sensor.entity_id`, and the panel already holds every task and every stored recipe.
 *
 * *draftId* is the recipe under edit and is skipped. Its tasks are the tasks the draft
 * rebuilds, not an overlap with another recipe.
 *
 * *matched* is the preview sample, so the count is a count of the matches on screen.
 * The warning names one recipe, so only the recipe with the most overlap is returned.
 * If two recipes cover the same number, the first one found in *tasks* wins.
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

function errorMessage(err: unknown): string {
  return String((err as { message?: string })?.message || err);
}

// ── the subsection inside the Companions card ───────────────────────────────

/** The subsection's HTML: heading, help, the two Add buttons, then one row per recipe. */
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

/** One recipe row: name, enabled chip, preset badge, description, match count, actions. */
function declarativeRow(p: PanelHost, spec: DeclarativeCompanion): string {
  const count = p._tasks.filter((task) => declarativeSpecId(task) === spec.id).length;
  const enabled = spec.enabled
    ? `<ha-assist-chip class="hk-comp-connected" label="${escapeHTML(t('declarative.companions.enabled'))}"></ha-assist-chip>`
    : `<ha-assist-chip class="hk-comp-suggested" label="${escapeHTML(t('declarative.companions.disabled'))}"></ha-assist-chip>`;
  const preset = spec.preset_id
    ? `<ha-assist-chip class="hk-decl-preset-chip" label="${escapeHTML(t('declarative.companions.preset_badge') + spec.preset_id)}"></ha-assist-chip>`
    : '';
  const desc = spec.description
    ? `<div class="hk-companion-desc">${escapeHTML(spec.description)}</div>`
    : '';
  const id = escapeHTML(spec.id);
  return `
      <div class="hk-companion hk-decl-row" data-spec-id="${id}">
        <ha-icon class="hk-companion-ic" icon="mdi:puzzle-outline"></ha-icon>
        <div class="hk-companion-body">
          <div class="hk-companion-name">${escapeHTML(spec.name)} ${enabled} ${preset}</div>
          ${desc}
          <div class="hk-decl-matches">${escapeHTML(t('declarative.companions.matches', { count: String(count) }))}</div>
        </div>
        <div class="hk-companion-actions">
          <ha-button ${btnAttrs('secondary')} class="hk-decl-edit" data-spec-id="${id}">${escapeHTML(t('declarative.companions.edit'))}</ha-button>
          <ha-button ${btnAttrs('danger')} class="hk-decl-delete" data-spec-id="${id}">${escapeHTML(t('declarative.companions.delete'))}</ha-button>
        </div>
      </div>`;
}

/** Wire the subsection's Add / Add from preset / Edit / Delete buttons. */
export function wireDeclarativeSection(p: PanelHost, root: HTMLElement): void {
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

/** Open the form on a copy of *seed* (a stored recipe, or a preset's default), or
 *  on a blank recipe when null. */
async function openDeclarativeForm(
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

function seededFrom(preset: DeclarativeCompanionPreset): DeclarativeCompanion {
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
  const list = document.createElement('div');
  list.className = 'hk-decl-preset-list';
  for (const preset of p._declarativePresets ?? []) {
    const missing =
      preset.requires_integration !== null && !installed.has(preset.requires_integration);
    // A real button, so the picker is keyboard-reachable like the rest of the panel.
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'hk-decl-preset-card' + (missing ? ' hk-decl-preset-disabled' : '');
    card.dataset.presetId = preset.id;
    card.disabled = missing;
    const requires = missing
      ? `<span class="hk-decl-preset-req">${escapeHTML(
          t('declarative.companions.requires_integration', {
            integration: preset.requires_integration ?? '',
          }),
        )}</span>`
      : '';
    card.innerHTML = `
        <ha-icon icon="${escapeHTML(preset.icon)}"></ha-icon>
        <span class="hk-decl-preset-text">
          <span class="hk-decl-preset-name">${escapeHTML(preset.name)}</span>
          <span class="hk-decl-preset-desc">${escapeHTML(preset.description)}</span>
          ${requires}
        </span>`;
    if (!missing) {
      card.addEventListener('click', () => void openDeclarativeForm(p, seededFrom(preset)));
    }
    list.appendChild(card);
  }
  body.appendChild(list);

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

  const preview = document.createElement('div');
  preview.className = 'hk-decl-preview';
  preview.textContent = t('declarative.companions.preview_loading');
  const schedulePreview = (): void => {
    // Only the dialog that is still on screen may own the pending preview. A trigger
    // mode change re-renders the dialog from *inside* the section's change handler,
    // so by the time the handler's own `schedulePreview()` runs, the new dialog has
    // already scheduled one against its own node. Both share the `decl-preview`
    // debounce key, so scheduling here would replace that live timer with one
    // pointing at this render's node — which the re-render has just detached — and
    // `refreshPreview` would return early, leaving "Loading preview…" on screen for
    // good. Switching the mode is exactly the flow #230 reported.
    if (!preview.isConnected) return;
    p._debounce('decl-preview', () => void refreshPreview(p, draft, preview), PREVIEW_DEBOUNCE_MS);
  };

  // Every field is labelled from its own key rather than `field.<name>`, and the
  // one helper is the template vocabulary under the notes template.
  const labelling = {
    computeLabel: (s: { name: string }): string =>
      s.name ? t('declarative.companions.field_' + s.name) : '',
    computeHelper: (s: { name: string }): string =>
      s.name === 'notes_template' ? t('declarative.companions.template_help') : '',
  };
  // Each section is its own `ha-form` (one heading between two fields is only
  // reachable by splitting the schema) and carries `data-decl-section` so a test can
  // address the form that owns a field rather than counting elements.
  const section = (
    key: string,
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
  ): void => {
    const title = document.createElement('div');
    title.className = 'hk-decl-section-title';
    title.textContent = t('declarative.companions.section_' + key);
    body.appendChild(title);
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
    body.appendChild(form);
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
      { name: 'device_class', selector: selText() },
      { name: 'entity_regex', selector: selText() },
    ],
    {
      integration: sel.target_integration,
      domain: sel.domain,
      device_class: sel.device_class,
      entity_regex: sel.entity_regex,
    },
    (v) => {
      sel.target_integration = str(v.integration);
      sel.domain = str(v.domain);
      sel.device_class = str(v.device_class);
      sel.entity_regex = str(v.entity_regex);
    },
  );

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
  // A hold and an auto-clear belong to the edge-driven modes only; a usage meter has
  // no condition to hold or recover from, and `normalize_sensor` reads neither there.
  if (mode !== 'usage') {
    triggerSchema.push(
      { name: 'for_seconds', selector: selNumber(0) },
      { name: 'clear_on_recover', selector: selBool() },
    );
  }
  if (mode !== 'availability') triggerSchema.push({ name: 'attribute', selector: selText() });
  section(
    'trigger',
    triggerSchema,
    {
      mode,
      state: trig.state ?? 'on',
      comparison: trig.comparison ?? '>=',
      value: trig.value,
      target: trig.target,
      for_seconds: trig.for_seconds ?? 0,
      clear_on_recover: trig.clear_on_recover !== false,
      attribute: trig.attribute,
    },
    (v) => {
      // Each read is guarded: the section carries only the current mode's fields, so
      // an unguarded read would write `undefined` over a key another mode owns.
      if ('state' in v) trig.state = String(v.state ?? '');
      if ('comparison' in v) trig.comparison = String(v.comparison ?? '>=');
      if ('value' in v) trig.value = num(v.value);
      if ('target' in v) trig.target = num(v.target);
      if ('for_seconds' in v) trig.for_seconds = num(v.for_seconds) ?? 0;
      if ('clear_on_recover' in v) trig.clear_on_recover = v.clear_on_recover !== false;
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

  // 4. Task template.
  section(
    'template',
    [
      { name: 'name_template', required: true, selector: selText() },
      { name: 'notes_template', selector: selText(true) },
    ],
    {
      name_template: draft.task_template.name_template,
      notes_template: draft.task_template.notes_template,
    },
    (v) => {
      draft.task_template.name_template = String(v.name_template ?? '');
      draft.task_template.notes_template = String(v.notes_template ?? '');
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
  save.addEventListener('click', () => void saveDeclarative(p, draft));
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

// ── the live preview ────────────────────────────────────────────────────────

async function refreshPreview(
  p: PanelHost,
  draft: DeclarativeCompanion,
  host: HTMLElement,
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
    host.innerHTML = previewHtml(result, overlap);
  } catch (err) {
    host.innerHTML = `<ha-alert alert-type="error">${escapeHTML(errorMessage(err))}</ha-alert>`;
  }
}

/** The preview's HTML: the count line, the warnings, and the sample. */
function previewHtml(
  result: DeclarativeCompanionPreviewResult,
  overlap: DeclarativeOverlap | null,
): string {
  if (result.over_cap) {
    return `<ha-alert alert-type="error">${escapeHTML(t('declarative.companions.preview_over_cap'))}</ha-alert>`;
  }
  const count = result.count ?? 0;
  // A `warning`, the same type as the count warning below it. A second recipe over
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
  const rows = result.matched
    .map(
      (m) => `
        <div class="hk-decl-preview-row">
          <div class="hk-decl-preview-name">${escapeHTML(m.rendered_name)}</div>
          <div class="hk-decl-preview-eid">${escapeHTML(m.entity_id)}</div>
        </div>`,
    )
    .join('');
  const summary = escapeHTML(
    t('declarative.companions.preview_summary', {
      shown: String(result.matched.length),
      total: String(count),
    }),
  );
  return `
      <div class="hk-decl-preview-header">${summary}</div>
      ${duplicate}
      ${warning}
      ${rows || `<div class="hk-decl-preview-empty">${escapeHTML(t('declarative.companions.preview_empty'))}</div>`}`;
}
