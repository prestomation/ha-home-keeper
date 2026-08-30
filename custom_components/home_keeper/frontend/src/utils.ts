import { t, tn } from './i18n';
import type { Asset, Hass, HassArea, HassLabel, Task } from './types';

/** Escape user-provided text before injecting into innerHTML. */
export function escapeHTML(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * True when *url* is a plain http(s) URL — the only schemes safe to place in an
 * `href`. `escapeHTML` cannot neutralise a `javascript:`/`data:` URI in an href
 * context (it only encodes markup characters), so any link built from stored or
 * user-supplied data must pass through this guard first.
 */
export function isHttpUrl(url: unknown): boolean {
  return typeof url === 'string' && /^https?:\/\//i.test(url);
}

/**
 * Escaped, scheme-checked value for an `href` attribute. Returns the escaped URL when
 * it is http(s), otherwise an empty string so the anchor is inert (defence-in-depth:
 * the backend also rejects non-http(s), but the frontend must not depend on that).
 */
export function safeHref(url: unknown): string {
  return isHttpUrl(url) ? escapeHTML(url) : '';
}

/**
 * True when *url* is safe to place in an image `src`/`href`: either a plain http(s)
 * URL or a **site-relative** path (single leading `/`, e.g. HA's
 * `/api/image/serve/<id>/original` from `ha-picture-upload`). Rejects
 * `javascript:`/`data:`/`vbscript:` and protocol-relative `//host` URLs. The
 * completion `photo` field is caller-supplied via `home_keeper.complete_task`, so it
 * must be validated before it reaches an href/src.
 */
export function isSafeImageUrl(url: unknown): boolean {
  return typeof url === 'string' && (isHttpUrl(url) || /^\/[^/]/.test(url));
}

/**
 * Escaped, scheme-checked value for an `href` that may hold **either** an external
 * link **or** a server-minted signed file URL. Signed URLs are site-relative
 * (`/api/home_keeper/document/…?authSig=…`), which `safeHref` rejects, so document
 * and part-file anchors need this variant rather than escaping the value raw:
 * `escapeHTML` alone leaves a `javascript:` URI intact in href position, and these
 * values reach the DOM from stored data and from other integrations' `task_chips`.
 */
export function safeFileHref(url: unknown): string {
  return isSafeImageUrl(url) ? escapeHTML(url) : '';
}

// ── Button weights ──────────────────────────────────────────────────────────
/**
 * The panel's four button weights, expressed in Home Assistant's own vocabulary.
 *
 * `ha-button` extends Web Awesome's `Button`, whose reactive attributes are
 * `appearance` (`accent`/`filled`/`outlined`/`plain`) and `variant`
 * (`brand`/`neutral`/`success`/`warning`/`danger`). **`raised` and `destructive` are
 * not among them** — they are Material leftovers the element never reads, so a button
 * carrying either renders at the default accent fill, exactly as a bare one does.
 * That is why Done, Edit, Cancel and Delete all arrived at the same weight (#262):
 * three quarters of the panel was asking for a weight in a language the button had
 * stopped speaking. Ask in this one instead, and never re-introduce those two.
 *
 * Measured against the rendered pixels in the e2e container, on the default light
 * theme's white card:
 *
 * | weight           | attributes                              | label vs its fill |
 * | ---------------- | --------------------------------------- | ----------------- |
 * | `primary`        | *(none — HA's default)*                 | 3.26:1 †          |
 * | `secondary`      | `appearance=filled`                     | 6.02:1 ‡          |
 * | `tertiary`       | `appearance=plain variant=neutral`      | 6.49:1            |
 * | `danger`         | `appearance=plain variant=danger`       | 7.04:1            |
 * | `danger-primary` | `variant=danger`                        | 4.59:1            |
 *
 * † Home Assistant's own filled-button pairing, used unchanged across HA itself.
 * ‡ Only with the `[data-hk-weight="secondary"]::part(base)` ink override in `STYLES`
 *   — HA's tonal label on its own tonal fill measures 2.85:1, which is what the
 *   `.done-btn` rule was already working around one button at a time.
 *
 * `tertiary` is deliberately `neutral` rather than brand: `appearance="plain"` alone
 * paints the label in the accent colour, which is 3.26:1 on a card and makes Cancel
 * compete with the action beside it.
 */
export type BtnWeight = 'primary' | 'secondary' | 'tertiary' | 'danger' | 'danger-primary';

/** Attribute set per weight. `primary` is the element's own default, so it adds none. */
const BTN_ATTRS: Record<BtnWeight, Record<string, string>> = {
  primary: {},
  secondary: { appearance: 'filled' },
  tertiary: { appearance: 'plain', variant: 'neutral' },
  danger: { appearance: 'plain', variant: 'danger' },
  'danger-primary': { variant: 'danger' },
};

/**
 * Every attribute any weight can set, so re-weighting clears the previous one.
 *
 * Derived from the table rather than restated beside it: a hand-written list silently
 * stops clearing an attribute the moment a weight adds one the list does not name, and
 * the symptom is a button that keeps a colour from the weight it used to have.
 */
const BTN_ATTR_NAMES: readonly string[] = [
  ...new Set(Object.values(BTN_ATTRS).flatMap((attrs) => Object.keys(attrs))),
];

/**
 * The attributes for *weight*, as markup — `btnAttrs('tertiary')` →
 * `appearance="plain" variant="neutral" data-hk-weight="tertiary"`.
 *
 * `data-hk-weight` is not decoration. It is what the tonal ink rule and the
 * `button-weights` e2e guard select on, and it is the difference between "this button
 * was given the primary weight" and "nobody thought about this button" — which, with
 * `primary` spelled as the absence of attributes, are otherwise the same markup.
 */
export function btnAttrs(weight: BtnWeight): string {
  const attrs = Object.entries(BTN_ATTRS[weight]).map(([k, v]) => `${k}="${v}"`);
  attrs.push(`data-hk-weight="${weight}"`);
  return attrs.join(' ');
}

/**
 * Apply *weight* to an already-created `ha-button`, for the call sites that build
 * their buttons with `createElement` rather than a template string. Idempotent:
 * clears the attributes the new weight does not set, so a button can be re-weighted.
 */
export function setBtnWeight(el: Element, weight: BtnWeight): void {
  const attrs = BTN_ATTRS[weight];
  for (const name of BTN_ATTR_NAMES) {
    if (name in attrs) el.setAttribute(name, attrs[name]);
    else el.removeAttribute(name);
  }
  el.setAttribute('data-hk-weight', weight);
}

/**
 * A random UUID-v4 string for client-minted ids (document ids, working-copy entries).
 *
 * `crypto.randomUUID()` only exists in a **secure context** — HTTPS or `localhost`. Over
 * a plain-HTTP LAN address (e.g. `http://192.168.1.x:8123`) it is `undefined`, so calling
 * it directly throws and silently breaks file uploads / link-adds for users on their LAN.
 * Prefer it when present, otherwise build a v4 from `crypto.getRandomValues` (always
 * available), falling back to `Math.random` only if even that is missing.
 */
export function randomId(): string {
  const c: Crypto | undefined = globalThis.crypto;
  if (c?.randomUUID) return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c?.getRandomValues) c.getRandomValues(bytes);
  else for (let i = 0; i < 16; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'));
  return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
    .slice(6, 8)
    .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`;
}

/**
 * Put *value* on the clipboard, resolving to whether it actually landed.
 *
 * `navigator.clipboard` is a **secure-context** API — the same trap as
 * `crypto.randomUUID` above. Over a plain-HTTP LAN address, which is how plenty of
 * people reach Home Assistant, it is simply absent, so the copy button beside an id
 * would do nothing at all. Fall back to an off-screen textarea and the legacy
 * `execCommand`, and report `false` when neither path works so the caller can say so
 * rather than claiming a copy that never happened.
 */
export async function copyText(value: string): Promise<boolean> {
  try {
    // No `?.` guard: a missing `navigator.clipboard` throws here and lands in the
    // same catch as a denied write, and one mechanism is better than two.
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    // Absent (the plain-HTTP case), denied, or the document is not focused.
  }
  const area = document.createElement('textarea');
  area.value = value;
  // Off-screen rather than `display:none`: a hidden element cannot be selected.
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.top = '-9999px';
  document.body.appendChild(area);
  try {
    area.select();
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

/** True when a triggered task is currently armed (due-now) vs dormant. */
export function isArmedTriggered(task: Task): boolean {
  return task.recurrence_type === 'triggered' && !!task.next_due;
}

/** Round to at most one decimal, dropping a trailing ".0".
 *
 * Meter readings are floats (`661.4166666`); shown raw they swamp the figure that
 * matters. One decimal is enough resolution for a maintenance interval. */
export function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/**
 * A spare quantity as text, with the part's unit appended when it has one.
 *
 * Stock is decimal (a part can be measured in millilitres or in thirds of a bottle),
 * but the ordinary count-the-filters case must still read "3", not "3.000" — so
 * trailing zeros go, and the unit only appears when the part actually set one.
 */
export function formatQuantity(value: number, unit?: string | null): string {
  // parseFloat on the fixed form drops trailing zeros without exposing float noise
  // (0.1 + 0.2 would otherwise render as 0.30000000000000004).
  const text = String(parseFloat(value.toFixed(3)));
  const label = (unit || '').trim();
  return label ? `${text} ${label}` : text;
}

/**
 * Whether completing `task` records the bound sensor's reading.
 *
 * True for a sensor task in a *numeric* mode — `usage` or `threshold`. A `state`
 * binding compares a string (`on`, `docked`), so there is no number to log. Mirrors
 * `models.task_records_reading` on the backend; both exist so the panel can decide
 * whether to offer the field without a round trip, and both are the single place the
 * scope is written down, so widening it later is one line on each side.
 */
export function taskRecordsReading(task: Partial<Task> | null | undefined): boolean {
  if (!task || task.recurrence_type !== 'sensor') return false;
  // An absent binding has nothing to read, so check for it before applying
  // `normalize_sensor`'s default of `usage` to a binding that merely omits `mode`.
  if (!task.sensor) return false;
  const mode = task.sensor.mode ?? 'usage';
  return mode === 'usage' || mode === 'threshold';
}

/**
 * The unit label to show beside a meter reading for `task`.
 *
 * A usage binding carries its own `unit` (the label the user typed, e.g. "h"), which
 * wins. A threshold binding has no `unit` field at all — it is usage-only in the
 * backend model — so fall back to the bound entity's `unit_of_measurement`. An
 * `attribute` binding reads an arbitrary attribute whose unit the entity does not
 * describe, so that falls through to no label rather than borrowing a wrong one.
 */
export function readingUnit(
  task: Partial<Task> | null | undefined,
  hass?: Hass,
): string {
  const s = task?.sensor;
  if (!s) return '';
  if (s.unit) return s.unit;
  if (s.attribute) return '';
  const state = s.entity_id ? hass?.states?.[s.entity_id] : undefined;
  return (state?.attributes?.unit_of_measurement as string | undefined) || '';
}

// ── Dates and times, as a person would write them ───────────────────────────
/**
 * A date, in the viewer's language — "1 Jul 2026", not "7/1/2026".
 *
 * Absolute dates used to be formatted at each call site with a bare
 * `toLocaleDateString()`/`toLocaleString()`, which gave the panel three different
 * shapes on three surfaces, and none of them passed the language Home Assistant
 * already knows, so a German user reading a German panel got US formatting.
 */
export function formatDate(value: string | Date | null | undefined, lang?: string): string {
  const d = value instanceof Date ? value : value ? new Date(value) : null;
  if (!d || Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(lang || undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * A date and time, to the minute — "1 Jul 2026, 13:00".
 *
 * Deliberately no seconds. `toLocaleString()` renders "7/1/2026, 1:00:00 PM", and a
 * completion is a thing a person did on an afternoon, not an event log line: the
 * ":00" at the end is precision the panel does not have and nobody asked for.
 */
export function formatDateTime(value: string | Date | null | undefined, lang?: string): string {
  const d = value instanceof Date ? value : value ? new Date(value) : null;
  if (!d || Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(lang || undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

/**
 * Sentence-case *text*, leaving everything after the first character alone.
 *
 * Scripts without letter case (Chinese) are unaffected: `toUpperCase` is a no-op on
 * a character that has no upper-case mapping.
 */
function sentenceCase(text: string): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/**
 * Human-readable summary of a task's recurrence rule, in sentence case.
 *
 * The strings underneath it are inconsistent by history rather than by design: the
 * clock ones were written as embeddable fragments ("every 12 months after
 * completion") and the sensor and status ones as standalone labels ("Every 300 h of
 * use", "Monitored"). Every caller renders the result as the first words of a line —
 * a task row's meta, the detail page's Recurrence row, the form's live preview — so
 * the case is fixed here rather than in sixteen locale files, where it would have to
 * be re-decided per language and could not be enforced.
 */
export function recurrenceSummary(task: Task): string {
  return sentenceCase(recurrenceText(task));
}

function recurrenceText(task: Task): string {
  // A triggered task has no schedule — it is "monitored" and only due when its
  // owning integration arms it (e.g. Battery Notes when a battery goes low).
  if (task.recurrence_type === 'triggered') return t('recurrence.triggered');
  // A one-off (do-once) task has no cadence — just a single due date.
  if (task.recurrence_type === 'one-off') return t('recurrence.oneOff');
  // A sensor task is described by its bound condition, not a clock.
  if (task.recurrence_type === 'sensor') {
    const s = task.sensor;
    if (!s) return t('recurrence.sensor');
    if (s.mode === 'state') {
      return t('recurrence.sensorState', { state: s.state ?? '' });
    }
    if (s.mode === 'threshold') {
      return t('recurrence.sensorThreshold', {
        comparison: s.comparison ?? '',
        value: s.value ?? '',
      });
    }
    const target = s.unit ? `${s.target ?? ''} ${s.unit}` : (s.target ?? '');
    const summary = t('recurrence.sensorUsage', { target });
    if (!s.also_every) return summary;
    const every = `${s.also_every.interval} ${t(`opt.unit.${s.also_every.unit}`)}`;
    return s.combinator === 'all'
      ? t('recurrence.sensorUsageAll', { summary, every })
      : t('recurrence.sensorUsageAny', { summary, every });
  }
  const n = task.interval || 1;
  if (task.recurrence_type === 'floating') {
    const base = (task.unit || 'days').replace(/s$/, ''); // day / week / month
    const unit = tn(`recurrence.unit.${base}`, n);
    return tn('recurrence.floating', n, { unit });
  }
  const freqBase: Record<string, string> = {
    DAILY: 'day',
    WEEKLY: 'week',
    MONTHLY: 'month',
  };
  const base = freqBase[task.freq || 'DAILY'] || 'day';
  const unit = tn(`recurrence.unit.${base}`, n);
  return tn('recurrence.fixed', n, { unit });
}

/** True when the task's next due date is at or before now. */
export function isOverdue(task: Task, now: Date = new Date()): boolean {
  if (!task.next_due) return false;
  return new Date(task.next_due).getTime() <= now.getTime();
}

/**
 * Units left before a dormant usage/meter task next comes due, or `null` when there
 * is no live countdown to show.
 *
 * `target - max(0, currentReading - baseline)`, clamped at 0 — the same arithmetic
 * the detail page's meter bar uses (`panel._sensorProgressBar`). Returns `null` for
 * anything that isn't a `usage` sensor task with a numeric `target`/`baseline` and a
 * readable numeric value on the bound entity (a threshold/state task, an un-anchored
 * meter, or an unavailable sensor), so a caller falls back to "Monitored".
 */
export function meterRemaining(
  task: Partial<Task> | null | undefined,
  hass?: Hass,
): number | null {
  const s = task?.sensor;
  if (!s || task?.recurrence_type !== 'sensor' || s.mode !== 'usage') return null;
  if (typeof s.target !== 'number' || typeof s.baseline !== 'number') return null;
  const state = s.entity_id ? hass?.states?.[s.entity_id] : undefined;
  const raw = state
    ? s.attribute
      ? (state.attributes?.[s.attribute] as unknown)
      : state.state
    : undefined;
  if (raw == null || raw === '') return null;
  const reading = Number(raw);
  if (Number.isNaN(reading)) return null;
  const consumed = Math.max(0, reading - s.baseline);
  return Math.max(0, s.target - consumed);
}

/** Compact relative description of a due date, e.g. "in 3 days" / "2 days ago". */
export function dueLabel(task: Task, now: Date = new Date(), hass?: Hass): string {
  // A dormant triggered/sensor task is armed-but-not-due: show "Monitored", not "no
  // date" — Home Keeper is watching the condition / sensor and will arm it.
  if (
    (task.recurrence_type === 'triggered' || task.recurrence_type === 'sensor') &&
    !task.next_due
  ) {
    // A dormant usage/meter task can read as a live countdown ("in 7000 miles") — the
    // meter analogue of a time task's "in 3 days" — when its bound sensor gives one.
    // Every other dormant sensor/triggered task (threshold, state, integration-armed,
    // or a meter with no reading yet) has no number, so it stays "Monitored".
    const remaining = meterRemaining(task, hass);
    if (remaining !== null) {
      const unit = readingUnit(task, hass);
      const value = unit ? `${round1(remaining)} ${unit}` : `${round1(remaining)}`;
      return t('due.in_units', { value });
    }
    return t('due.monitored');
  }
  // A completed one-off (do-once, now dormant) reads as "Completed".
  if (task.recurrence_type === 'one-off' && !task.next_due && task.last_completed) {
    return t('due.completed');
  }
  if (!task.next_due) return t('due.none');
  const due = new Date(task.next_due);
  // Compare calendar days (local midnights), not rolling 24h windows: at 20:00 a
  // task due 08:00 tomorrow should read "tomorrow", not "today".
  const startOfDay = (d: Date) => {
    const x = new Date(d);
    x.setHours(0, 0, 0, 0);
    return x.getTime();
  };
  const days = Math.round((startOfDay(due) - startOfDay(now)) / 86_400_000);
  if (days === 0) return t('due.today');
  if (days > 0) return days === 1 ? t('due.tomorrow') : tn('due.in_days', days);
  const ago = Math.abs(days);
  return ago === 1 ? t('due.yesterday') : tn('due.days_ago', ago);
}

/**
 * Resolve a device id to its display name using `hass.devices`, or `''` when there is
 * no name to show.
 *
 * It used to fall back to the id itself, which meant a task pointing at a device that
 * had left the registry — a removed integration, a deleted device — rendered
 * `5ff1f1bb41a19a763aa4ab750cd37c97` as its chip, cut mid-string by the chip's own
 * border. The id is not a name in any language, and it made things worse than a blank:
 * the four callers that read `asset.name || deviceName(…) || t('appliance.fallbackName')`
 * could never reach the friendly fallback, because a raw id is truthy.
 *
 * Returning `''` puts the decision where the context is. Every caller either already
 * guards on an empty string or now does.
 */
export function deviceName(
  devices: Record<string, { name?: string; name_by_user?: string | null }> | undefined,
  deviceId: string | null | undefined,
): string {
  // Stryker disable next-line ConditionalExpression: equivalent — a falsy id looks up
  // `undefined` in the map, which the `!dev` guard below turns into the same ''. The
  // early return is for readers, not for behaviour.
  if (!deviceId) return '';
  const dev = devices?.[deviceId];
  if (!dev) return '';
  return dev.name_by_user || dev.name || '';
}

/**
 * The device id to group *task* under, or `undefined` for the "No device" bucket.
 *
 * The test is whether the device can be **named**, not whether it is in the registry:
 * a bucket is headed by its label, and a device that is present but nameless resolves
 * to `''`, which would head a section with nothing at all.
 */
export function groupableDeviceId(
  devices: Record<string, { name?: string; name_by_user?: string | null }> | undefined,
  deviceId: string | null | undefined,
): string | undefined {
  return deviceId && deviceName(devices, deviceId) ? deviceId : undefined;
}

/** Resolve a device to its integration domain via the config-entry → domain map. */
export function deviceDomain(
  device: { primary_config_entry?: string | null; config_entries?: string[] } | undefined,
  entryDomains: Record<string, string> | undefined,
): string | undefined {
  if (!device || !entryDomains) return undefined;
  const entryId = device.primary_config_entry || device.config_entries?.[0];
  return entryId ? entryDomains[entryId] : undefined;
}

/**
 * Brand logo URL for an integration domain. The `_/` fallback path serves a
 * generic logo when the integration ships no brand image of its own.
 */
export function brandLogoUrl(domain: string, fallback = false): string {
  return `https://brands.home-assistant.io/${fallback ? '_/' : ''}${domain}/icon.png`;
}

/** Resolve an area id to its name using hass.areas. */
export function areaName(
  areas: Record<string, HassArea> | undefined,
  areaId: string | null | undefined,
): string {
  if (!areaId) return '';
  return areas?.[areaId]?.name || areaId;
}

/** Resolve a label id to its display name using hass.labels (falls back to the id). */
export function labelName(
  labels: Record<string, HassLabel> | undefined,
  labelId: string | null | undefined,
): string {
  if (!labelId) return '';
  return labels?.[labelId]?.name || labelId;
}

/**
 * Resolve a tag id to the name HA's tag registry gives it, falling back to the raw
 * id — an unnamed tag has nothing else to call it by, and showing the id beats
 * showing nothing.
 */
export function tagName(
  tags: { value: string; label: string }[] | undefined,
  tagId: string | null | undefined,
): string {
  if (!tagId) return '';
  return tags?.find((tag) => tag.value === tagId)?.label || tagId;
}

/**
 * Whether *task* can only be completed by scanning its tag. Both halves are
 * required: the flag without a bound tag would describe a task nothing could ever
 * complete, so it reads as "not locked" rather than "locked forever".
 */
export function scanRequired(task: Partial<Task>): boolean {
  return !!task.tag_id && !!task.require_tag_scan;
}

// ── panel routing ────────────────────────────────────────────────────────────

/** The navigable list view; mirrors the panel's two tabs. */
export type PanelView = 'tasks' | 'appliances' | 'settings';

/**
 * The sub-tabs an appliance's detail page is divided into. Each is a URL of its own,
 * so Back leaves a sub-tab the same way it leaves any other destination.
 *
 * `parts` is the default: it is the reason most appliances exist in Home Keeper.
 */
export const ASSET_TABS = [
  'parts',
  'tasks',
  'documents',
  'details',
  'related',
  'history',
] as const;
export type AssetTab = (typeof ASSET_TABS)[number];
export const DEFAULT_ASSET_TAB: AssetTab = 'parts';

/**
 * The Settings tab's sections, in the order they are shown. Each is a URL of its own
 * so a phone, which has no room for six sections at once, can show an index and open
 * one section at a time with Back working normally.
 *
 * Unlike an appliance sub-tab there is no default: `/settings` with no section is the
 * index itself, which is a real destination rather than a redirect.
 */
export const SETTINGS_SECTIONS = [
  'general',
  'shopping',
  'problem',
  'skipsnooze',
  'profiles',
  'notifications',
  'companions',
] as const;
export type SettingsSection = (typeof SETTINGS_SECTIONS)[number];

/**
 * A fully-resolved panel location: which tab is shown and, optionally, the
 * detail page open on top of it. This is the panel's entire navigation state —
 * it round-trips losslessly with the URL via {@link parseRoute} / {@link buildPath}
 * so the URL can be the single source of truth (high-fidelity deep linking).
 *
 * An appliance detail also carries which of its sub-tabs is open, and the Settings
 * tab carries which of its sections is open (none meaning the section index).
 */
export interface PanelLocation {
  view: PanelView;
  detail: { kind: 'task' | 'asset'; id: string; tab?: AssetTab } | null;
  section?: SettingsSection;
}

/**
 * Parse the panel's route path (the part after the `/home-keeper` prefix that HA
 * hands the panel) into a {@link PanelLocation}. Unknown/empty paths fall back to
 * the tasks list. The asset detail lives under the `appliances` segment but keeps
 * the internal `asset` kind.
 *
 * A third segment names an appliance sub-tab (`/appliances/<id>/documents`). An
 * unrecognised one falls back to the default rather than 404-ing, and a bare
 * `/appliances/<id>` — every link minted before sub-tabs existed, including the
 * `configuration_url` on already-registered devices — keeps resolving.
 *
 * Under `settings` the second segment names a section (`/settings/notifications`).
 * An unrecognised one falls back to the section index, not to a default section: a
 * bare `/settings` is the index, and a typo should land there rather than somewhere
 * arbitrary.
 */
export function parseRoute(path: string | undefined | null): PanelLocation {
  // Stryker disable next-line StringLiteral: equivalent — a null path with any other
  // slash-free default parses to the same location, so no test can tell them apart.
  const parts = String(path ?? '')
    .split('/')
    .map((p) => p.trim())
    .filter(Boolean);
  const view: PanelView =
    parts[0] === 'appliances' ? 'appliances' : parts[0] === 'settings' ? 'settings' : 'tasks';
  if (view === 'settings') {
    // Short-circuit rather than falling back to '': an empty-string default is
    // indistinguishable from any other non-section string here, so it would only
    // add a mutant no test could ever kill.
    const raw = parts[1] && decodeURIComponent(parts[1]);
    return raw && (SETTINGS_SECTIONS as readonly string[]).includes(raw)
      ? { view, detail: null, section: raw as SettingsSection }
      : { view, detail: null };
  }
  // Only the tasks/appliances lists drill into a detail page.
  if (parts[1]) {
    const kind = view === 'appliances' ? 'asset' : 'task';
    if (kind === 'asset') {
      // Short-circuit rather than defaulting to '', for the same reason the settings
      // branch does: an empty-string default is indistinguishable from any other
      // non-tab string, so it only adds a mutant no test could ever kill.
      const raw = parts[2] && decodeURIComponent(parts[2]);
      const tab =
        raw && (ASSET_TABS as readonly string[]).includes(raw)
          ? (raw as AssetTab)
          : DEFAULT_ASSET_TAB;
      return { view, detail: { kind, id: decodeURIComponent(parts[1]), tab } };
    }
    return { view, detail: { kind, id: decodeURIComponent(parts[1]) } };
  }
  return { view, detail: null };
}

/**
 * Build the route path (under the panel prefix) for a {@link PanelLocation} —
 * the inverse of {@link parseRoute}. The detail page's URL segment derives from
 * the view, so a task detail is `/tasks/<id>` and an asset detail is
 * `/appliances/<id>`, plus its sub-tab where one is open.
 *
 * The default sub-tab is left off the URL: `/appliances/<id>` and
 * `/appliances/<id>/parts` are the same page, and the shorter one is what a link
 * to an appliance should look like.
 *
 * A Settings section appends itself the same way, and no section means the index.
 */
export function buildPath(loc: PanelLocation): string {
  if (loc.view === 'settings') {
    return loc.section ? `/settings/${loc.section}` : '/settings';
  }
  if (!loc.detail) return `/${loc.view}`;
  const base = `/${loc.view}/${encodeURIComponent(loc.detail.id)}`;
  const tab = loc.detail.tab;
  return tab && tab !== DEFAULT_ASSET_TAB ? `${base}/${tab}` : base;
}

// ── completion history ───────────────────────────────────────────────────────

/** Parsed, valid completion timestamps sorted newest-first. */
export function sortedCompletions(completions?: { ts: string }[]): Date[] {
  return (completions || [])
    .map((c) => new Date(c.ts))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
}

export interface CompletionStats {
  count: number;
  last?: Date;
  /** Mean days between completions (only when there are at least two). */
  avgIntervalDays?: number;
}

/** Count, most-recent completion, and average cadence for a completion list. */
export function completionStats(completions?: { ts: string }[]): CompletionStats {
  const dates = sortedCompletions(completions);
  const stats: CompletionStats = { count: dates.length };
  if (dates.length) stats.last = dates[0];
  if (dates.length >= 2) {
    const spanMs = dates[0].getTime() - dates[dates.length - 1].getTime();
    stats.avgIntervalDays = Math.round(spanMs / (dates.length - 1) / 86_400_000);
  }
  return stats;
}

/**
 * True when a task is associated with an appliance — mirrors the backend's
 * `assets.task_relates_to_asset` so the panel can group history client-side.
 */
export function taskRelatesToAsset(task: Task, asset: Asset): boolean {
  if (task.source?.part?.asset_id === asset.id) return true;
  const dev = task.device_id;
  if (!dev) return false;
  if (asset.device_id && dev === asset.device_id) return true;
  return (asset.related_device_ids || []).includes(dev);
}

/** Every loaded task associated with an appliance. */
export function tasksForAsset(asset: Asset, tasks: Task[]): Task[] {
  return tasks.filter((task) => taskRelatesToAsset(task, asset));
}

/** Compact one-line summary of an asset's notable metadata for the card. */
export function assetSummary(
  asset: Asset,
  areas?: Record<string, HassArea>,
): string {
  const bits: string[] = [];
  const makeModel = [asset.manufacturer, asset.model].filter(Boolean).join(' ');
  if (makeModel) bits.push(makeModel);
  const area = areaName(areas, asset.area_id);
  if (area) bits.push(area);
  const partCount = asset.parts?.length ?? 0;
  if (partCount) bits.push(tn('asset.parts', partCount));
  return bits.length ? bits.join(' · ') : t('asset.noDetails');
}

export interface AssetTreeEntry<T> {
  item: T;
  depth: number;
}

/**
 * Flatten a list of assets into depth-first render order, respecting the
 * parent_asset_id hierarchy. Assets whose parent is absent from the input
 * are promoted to roots (handles cross-filter cases). Siblings at each
 * level are sorted using the caller's comparator.
 */
export function buildAssetTree<
  T extends { id: string; parent_asset_id?: string | null },
>(assets: T[], compare: (a: T, b: T) => number): AssetTreeEntry<T>[] {
  const ids = new Set(assets.map((a) => a.id));
  const children = new Map<string, T[]>();
  const roots: T[] = [];

  for (const a of assets) {
    const pid = a.parent_asset_id;
    if (pid && ids.has(pid)) {
      const arr = children.get(pid);
      if (arr) arr.push(a);
      else children.set(pid, [a]);
    } else {
      roots.push(a);
    }
  }

  roots.sort(compare);
  for (const arr of children.values()) arr.sort(compare);

  const result: AssetTreeEntry<T>[] = [];
  const visited = new Set<string>();

  const walk = (nodes: T[], depth: number): void => {
    for (const node of nodes) {
      if (visited.has(node.id)) continue;
      visited.add(node.id);
      result.push({ item: node, depth });
      const kids = children.get(node.id);
      if (kids) walk(kids, depth + 1);
    }
  };

  walk(roots, 0);

  // Assets trapped in a pure cycle (A→B→A) have no root — promote any
  // un-visited ones so they still appear in the output.
  if (visited.size < assets.length) {
    const remaining = assets.filter((a) => !visited.has(a.id));
    remaining.sort(compare);
    walk(remaining, 0);
  }

  return result;
}
