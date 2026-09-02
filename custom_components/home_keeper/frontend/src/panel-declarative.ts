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
 *   one draft, and beneath them a live preview of what the recipe would match.
 *
 * Both dialogs are state-driven (`p._declDialog`) and built through `makeDialog`, so
 * they open, title and close the way the completion dialogs do and pick up the next
 * `ha-dialog` fix with them. The draft is edited **in place** (every section's form
 * writes into the same object), which is what lets a trigger-mode change re-render
 * the dialog with a different schema without losing what was typed.
 */

import * as api from './api';
import { selBool, selNumber, selSelect, selSelectCustom, selText, type FormField } from './forms';
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
type Trigger = Record<string, unknown> & { mode?: string };

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
    trigger: {
      mode: 'state',
      state: 'on',
      clear_on_recover: true,
    } as unknown as DeclarativeCompanion['trigger'],
    task_template: { name_template: '{{ friendly_name }}', notes_template: '', labels: [] },
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
  const schedulePreview = (): void =>
    p._debounce('decl-preview', () => void refreshPreview(p, draft, preview), PREVIEW_DEBOUNCE_MS);

  // Every field is labelled from its own key rather than `field.<name>`, and the
  // one helper is the template vocabulary under the notes template.
  const labelling = {
    computeLabel: (s: { name: string }): string =>
      s.name ? t('declarative.companions.field_' + s.name) : '',
    computeHelper: (s: { name: string }): string =>
      s.name === 'notes_template' ? t('declarative.companions.template_help') : '',
  };
  const section = (
    titleKey: string,
    schema: FormField[],
    data: Record<string, unknown>,
    onChange: (value: Record<string, unknown>) => void,
  ): void => {
    const title = document.createElement('div');
    title.className = 'hk-decl-section-title';
    title.textContent = t(titleKey);
    body.appendChild(title);
    body.appendChild(
      p._makeForm(
        schema,
        data,
        (value) => {
          onChange(value);
          schedulePreview();
        },
        labelling,
      ),
    );
  };
  const str = (v: unknown): string | undefined => {
    const s = String(v ?? '').trim();
    return s || undefined;
  };
  const num = (v: unknown): number | undefined =>
    v == null || v === '' || Number.isNaN(Number(v)) ? undefined : Number(v);

  // 1. Identity.
  section(
    'declarative.companions.section_identity',
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
    'declarative.companions.section_selection',
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
  triggerSchema.push(
    { name: 'for_seconds', selector: selNumber(0) },
    { name: 'clear_on_recover', selector: selBool() },
  );
  if (mode !== 'availability') triggerSchema.push({ name: 'attribute', selector: selText() });
  section(
    'declarative.companions.section_trigger',
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
      const next = typeof v.mode === 'string' ? v.mode : mode;
      trig.mode = next;
      if ('state' in v) trig.state = String(v.state ?? '');
      if ('comparison' in v) trig.comparison = String(v.comparison ?? '>=');
      if ('value' in v) trig.value = num(v.value);
      if ('target' in v) trig.target = num(v.target);
      trig.for_seconds = num(v.for_seconds) ?? 0;
      trig.clear_on_recover = v.clear_on_recover !== false;
      const attribute = str(v.attribute);
      if (attribute) trig.attribute = attribute;
      else delete trig.attribute;
      if (next !== mode) p._render();
    },
  );

  // 4. Task template.
  section(
    'declarative.companions.section_template',
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
    host.innerHTML = previewHtml(await api.previewDeclarativeCompanion(p._hass, draft));
  } catch (err) {
    host.innerHTML = `<ha-alert alert-type="error">${escapeHTML(errorMessage(err))}</ha-alert>`;
  }
}

/** The preview's HTML: the count line, a warning when it is a lot, and the sample. */
function previewHtml(result: DeclarativeCompanionPreviewResult): string {
  if (result.over_cap) {
    return `<ha-alert alert-type="error">${escapeHTML(t('declarative.companions.preview_over_cap'))}</ha-alert>`;
  }
  const count = result.count ?? 0;
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
      ${warning}
      ${rows || `<div class="hk-decl-preview-empty">${escapeHTML(t('declarative.companions.preview_empty'))}</div>`}`;
}
