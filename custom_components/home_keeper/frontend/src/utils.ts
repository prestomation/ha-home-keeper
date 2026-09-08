import { t, tn } from './i18n';
import type { Asset, Hass, HassArea, HassLabel, Part, Task } from './types';

/** Home Keeper's own integration domain (`const.DOMAIN`). A task Home Keeper syncs
 *  or materializes itself carries it in `managed_by.integration`, which is how the
 *  panel tells "another integration owns this" from "we do". */
export const HK_DOMAIN = 'home_keeper';

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
 * Clamp a value to a stored `mdi:<name>` icon, or to `''`. Mirrors
 * `notifications.normalize_icon` in the backend, which is the authority — this copy
 * keeps the panel from writing a value the store would only throw away, and keeps a
 * name with a quote or an angle bracket out of an `ha-icon` attribute.
 */
export function normalizeIcon(value: unknown): string {
  const icon = String(value ?? '')
    .trim()
    .toLowerCase();
  return /^mdi:[a-z0-9-]+$/.test(icon) ? icon : '';
}

/**
 * The Settings row badge for a notification: the accent as the fill, the glyph in
 * white. Returns `''` without an icon, so a row that has none stays as it was.
 *
 * Filled rather than a bare tinted glyph because the fill is the only treatment that
 * survives every color the picker offers — a pale glyph on the panel's white card is
 * invisible, while white on a pale fill is not. It is also what an iPhone draws, so the
 * chip and the phone agree.
 */
export function notifyRowChip(icon: unknown, color: unknown): string {
  const name = normalizeIcon(icon);
  if (!name) return '';
  const hex = String(color ?? '')
    .trim()
    .toLowerCase();
  // The color reaches a `style` attribute, so accept only the one shape the backend
  // stores rather than escaping an arbitrary string into CSS.
  const fill = /^#[0-9a-f]{6}$/.test(hex) ? hex : 'var(--secondary-text-color)';
  return (
    `<span class="hk-notify-chip" style="background:${fill}">` +
    `<ha-icon icon="${escapeHTML(name)}"></ha-icon></span>`
  );
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
 * paints the label in the accent color, which is 3.26:1 on a card and makes Cancel
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
 * the symptom is a button that keeps a color from the weight it used to have.
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

/**
 * Surface a transient message through Home Assistant's own toast.
 *
 * `composed` so the event escapes the shadow root it is fired in, `bubbles` so HA's
 * listener further up the tree receives it. The panel and the card both need this and
 * had a byte-identical copy each.
 */
export function toast(el: EventTarget, message: string): void {
  el.dispatchEvent(
    new CustomEvent('hass-notification', {
      detail: { message },
      bubbles: true,
      composed: true,
    }),
  );
}

/**
 * Send Home Assistant's SPA router to *path* — a device page, an integration page, the
 * Home Keeper panel — without a full page load.
 *
 * Always a push (Back returns to where the user pressed) and always fired on `window`,
 * because these are the navigations that *leave* the element behind: it may be
 * unmounted by the time HA re-renders. The panel's own in-panel `_navigate` is a
 * different thing — it fires from the panel element and can replace instead of push —
 * so it stays there.
 */
export function navigateTo(path: string): void {
  history.pushState(null, '', path);
  window.dispatchEvent(
    new CustomEvent('location-changed', {
      detail: { replace: false },
      bubbles: true,
      composed: true,
    }),
  );
}

/** True when a triggered task is currently armed (due-now) vs dormant. */
export function isArmedTriggered(task: Task): boolean {
  return task.recurrence_type === 'triggered' && !!task.next_due;
}

/** The sensor modes that watch a *condition* rather than count a meter — the panel's
 *  twin of `sensor_tasks.holds_edge_state`. Listed rather than derived by excluding
 *  `usage`, so a mode added later does not silently join them. */
const EDGE_SENSOR_MODES: readonly string[] = ['state', 'threshold', 'availability'];

/**
 * True when a task is watching a condition that has **not** fired — the state every
 * surface labels "Monitored".
 *
 * Two shapes reach it. A dormant `triggered` task, which its owning integration arms.
 * And a dormant `sensor` task in an edge mode (state / threshold / availability),
 * which the watcher arms on the next crossing. Neither has work waiting, so neither
 * offers Done: pressing it wrote a completion and changed nothing else, because
 * `next_due_after_completion` leaves a sensor task dormant. That is #231 — a Device
 * Pulse task sat under the Monitored heading with a live Done button.
 *
 * A dormant **usage** meter is deliberately not monitored-dormant. It is counting up
 * to its target, the panel shows that countdown ("in 7000 miles"), and completing it
 * early is real work that re-anchors the meter (`store._reset_usage_baseline`) — so
 * the oil change done at 4,500 miles keeps its button.
 */
export function isMonitoredDormant(task: Task): boolean {
  if (task.next_due) return false;
  if (task.recurrence_type === 'triggered') return true;
  // The recurrence type decides, not the presence of a binding: a task edited away
  // from `sensor` can keep a stale `sensor` block, and it is no longer condition-driven.
  if (task.recurrence_type !== 'sensor') return false;
  // An absent mode reads as `usage` everywhere else (`models.normalize_sensor`), so
  // it reads as a meter here too.
  // Stryker disable next-line StringLiteral: the fallback only has to be a mode that
  // is not an edge mode, so every string this literal could become answers the same.
  return EDGE_SENSOR_MODES.includes(task.sensor?.mode ?? 'usage');
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
 * A meter reading as text, in the viewer's language, with the meter's unit appended.
 *
 * An odometer is the case that matters: `163900` is hard to read and `163,900 km` is
 * not, and the grouping separator is a comma in English and a point in German, so the
 * language has to reach the formatter. One decimal at most, the same resolution
 * `round1` keeps, because a maintenance interval does not need more.
 */
export function formatReading(value: number, unit?: string | null, lang?: string): string {
  const text = new Intl.NumberFormat(lang || undefined, {
    maximumFractionDigits: 1,
  }).format(value);
  const label = (unit || '').trim();
  return label ? `${text} ${label}` : text;
}

/**
 * The step a part's stock moves in: a whole spare, or a fine step once the part
 * deals in fractions — it has a unit, or any of its quantities is fractional. The
 * same rule as the device page's `number` entity (`number.py` `native_step`), so
 * the two controls accept the same values.
 */
export function partStockStep(part: Part): number {
  if ((part.stock_unit || '').trim()) return 0.001;
  const quantities = [part.stock, part.reorder_at, part.consume_quantity, part.restock_quantity];
  return quantities.some((q) => q != null && !Number.isInteger(q)) ? 0.001 : 1;
}

/**
 * How far one tap of the stepper's − or + moves the stock: one spare for a part
 * counted in spares, and one completion's worth for a measured part (a thousandth
 * of a millilitre is a step nobody wants to tap through).
 */
export function partStockButtonStep(part: Part): number {
  return partStockStep(part) === 1 ? 1 : (part.consume_quantity ?? 1);
}

/** A typed stock value snapped to *step* and floored at zero, at the stored
 *  three-decimal precision. */
export function snapStock(value: number, step: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.max(0, Math.round(Math.round(value / step) * step * 1000) / 1000);
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
 * Whether `task`'s history reports the usage between its completions.
 *
 * A usage meter only, and narrower than `taskRecordsReading` on purpose: a `threshold`
 * task logs a reading too, but that reading is a measurement (airflow at 58%) and not a
 * meter that only climbs, so the difference between two of them is not usage. Lives
 * here beside the other mode predicates rather than in the renderer, so the panel and
 * its tests ask the same question.
 */
export function showsUsageIntervals(task: Partial<Task> | null | undefined): boolean {
  return task?.recurrence_type === 'sensor' && task.sensor?.mode === 'usage';
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

/** "today" / "yesterday" / "N days ago" for a past date, counted in whole days. */
export function relativeDay(d: Date, now: Date = new Date()): string {
  const days = Math.round((now.getTime() - d.getTime()) / 86_400_000);
  if (days <= 0) return t('due.today');
  if (days === 1) return t('due.yesterday');
  return tn('due.days_ago', days);
}

/**
 * Format a cost in the instance's configured currency, falling back to the bare
 * number when Home Assistant has no currency set — or names one `Intl` refuses.
 */
export function formatCost(hass: Hass | undefined, amount: number): string {
  const currency = hass?.config?.currency;
  const lang = hass?.language;
  // Stryker disable next-line ConditionalExpression: equivalent — with no currency
  // configured, `Intl.NumberFormat` with `style: 'currency'` throws, and the catch
  // below returns the very bare number this guard skips ahead to.
  if (currency) {
    try {
      return new Intl.NumberFormat(lang, { style: 'currency', currency }).format(amount);
    } catch {
      /* an unknown currency code — fall through to a bare number */
    }
  }
  return String(amount);
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
    // Availability has no reading to describe — the condition *is* the entity being
    // gone. Without its own case it fell through to the meter below and read "Every
    // of use", because a mode with no `target` renders the usage string empty.
    if (s.mode === 'availability') return t('recurrence.sensorAvailability');
    const target = s.unit ? `${s.target ?? ''} ${s.unit}` : (s.target ?? '');
    const summary = t('recurrence.sensorUsage', { target });
    if (!s.also_every) return summary;
    const every = `${s.also_every.interval} ${t(`opt.unit.${s.also_every.unit}`)}`;
    return s.combinator === 'all'
      ? t('recurrence.sensorUsageAll', { summary, every })
      : t('recurrence.sensorUsageAny', { summary, every });
  }
  const n = task.interval || 1;
  let summary: string;
  if (task.recurrence_type === 'floating') {
    const base = (task.unit || 'days').replace(/s$/, ''); // day / week / month
    const unit = tn(`recurrence.unit.${base}`, n);
    summary = tn('recurrence.floating', n, { unit });
  } else {
    const freqBase: Record<string, string> = {
      DAILY: 'day',
      WEEKLY: 'week',
      MONTHLY: 'month',
    };
    const base = freqBase[task.freq || 'DAILY'] || 'day';
    const unit = tn(`recurrence.unit.${base}`, n);
    summary = tn('recurrence.fixed', n, { unit });
  }
  if (task.active_season) {
    const windows = Array.isArray(task.active_season)
      ? task.active_season
      : [task.active_season];
    const range = windows
      .map((w) => {
        const s = t(`opt.month.${parseInt(w.start, 10)}`);
        const sDay = parseInt(w.start.split('-')[1], 10);
        const e = t(`opt.month.${parseInt(w.end, 10)}`);
        const eDay = parseInt(w.end.split('-')[1], 10);
        return `${s} ${sDay}–${e} ${eDay}`;
      })
      .join(' & ');
    summary = t('recurrence.season', { summary, range });
  }
  return summary;
}

/** True when the task's next due date is at or before now. */
export function isOverdue(task: Task, now: Date = new Date()): boolean {
  if (!task.next_due) return false;
  return new Date(task.next_due).getTime() <= now.getTime();
}

/**
 * Whether *task* is one of Home Keeper's auto-created "Buy {part}" reminders.
 *
 * Both ids are required, mirroring the backend's `reconcile.buy_source`: the pair is
 * what identifies the part being bought, and half of it identifies nothing. The two
 * have to agree, because a Profile carrying `exclude_shopping` is matched in the
 * browser for the panel and the card, and in Python for a notification — and
 * `tests/fixtures/profile_filter_cases.json` holds them to it.
 *
 * The agreement is on a *missing* id, which is what the fixture pins and what the
 * reconciler can actually produce. On an id present but **empty** the two part
 * company: this asks for truthy, `buy_source` only for the key. Left alone rather
 * than papered over, because nothing can reach it — the reconciler mints real uuids,
 * and `models.build_task` is the only other way in. Worth knowing if that ever stops
 * being true, since the divergence would show as a task one surface excludes and
 * another does not.
 *
 * Lives here beside `isOverdue` because the two are read together: a buy reminder is
 * *also* overdue, and every surface that draws a status has to know which of the two
 * to say. `statusChipHtml` is that answer, and `card-filter.ts` re-exports this for
 * the pure list-shaping code.
 */
export function isBuyTask(task: Task): boolean {
  const buy = task.source?.buy;
  return Boolean(buy && buy.asset_id && buy.part_id);
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
 * The right-hand status pill for *task*, as it reads on every surface that draws one:
 * the panel's list row and its detail page, an appliance's related-tasks list, and the
 * dashboard card's row.
 *
 * One function on purpose. An auto-created buy reminder is minted as a one-off with no
 * due date, and a dateless one-off is due *now* — so it is technically overdue from the
 * moment a part goes low, and reading it as late work is what put "Overdue" beside
 * genuinely late maintenance. Saying "Low stock" instead was written into two of the
 * four renderers and missed in the other two, which left one task showing two different
 * statuses depending on where you looked at it. A copy per surface is free to disagree,
 * so there is no longer a copy per surface.
 *
 * Only the wording and the color move. A buy reminder is still overdue to every filter
 * pill, count, binary sensor and Profile, so no number changes.
 *
 * *elapsed* appends how overdue the task is ("3 days overdue") instead of a bare
 * "Overdue". The panel's list row asks for it, where urgency has to read at a glance
 * down a long list; the detail page and the card do not, having the date in view
 * already. Whole elapsed days only, and only past a full day — a task overdue by hours
 * reading "1 day overdue" would overstate it.
 */
export function statusChipHtml(
  task: Task,
  hass?: Hass,
  opts: { elapsed?: boolean; now?: Date } = {},
): string {
  const now = opts.now ?? new Date();
  const chip = (label: string, cls = '') =>
    `<ha-assist-chip${cls ? ` class="${cls}"` : ''} label="${escapeHTML(label)}"></ha-assist-chip>`;
  // "Low stock" answers an *open* reminder. A reminder that was bought while the part
  // stayed under its reorder point keeps its row — the reconciler only retires it once
  // the stock is back up — and that row belongs to the Completed section, which is
  // where `statusBucket` puts it by running its `completed` check ahead of its buy
  // check. The pill runs them in the same order for the same reason: a row filed under
  // Completed must not carry a chip arguing it is still outstanding.
  const boughtAlready =
    task.recurrence_type === 'one-off' && !task.next_due && !!task.last_completed;
  if (isBuyTask(task) && !boughtAlready) return chip(t('chip.lowStock'), 'hk-shopping');
  if (!isOverdue(task, now)) return chip(dueLabel(task, now, hass));
  const days = task.next_due
    ? Math.floor((now.getTime() - new Date(task.next_due).getTime()) / 86_400_000)
    : 0;
  const label = opts.elapsed && days >= 1 ? tn('due.overdue_by', days) : t('chip.overdue');
  return chip(label, 'hk-overdue');
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
 * Resolve a `person` entity id to its friendly name, falling back to the id itself.
 * Unlike `deviceName`, the fallback is deliberate: a completion's "who" is a name the
 * history line is built around, so `person.sam` still says more there than a blank.
 */
export function personName(hass: Hass | undefined, entityId: string): string {
  const friendly = hass?.states?.[entityId]?.attributes?.friendly_name;
  return typeof friendly === 'string' && friendly ? friendly : entityId;
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
 * The sub-tabs a task's detail page is divided into, mirroring the appliance page so
 * the two read the same way. `schedule` is the default: what a task is and when it
 * is next due is the page's first question; its notes and its history are the
 * second and third.
 */
export const TASK_TABS = ['schedule', 'notes', 'history'] as const;
export type TaskTab = (typeof TASK_TABS)[number];
export const DEFAULT_TASK_TAB: TaskTab = 'schedule';

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
  'transfer',
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
  detail: { kind: 'task' | 'asset'; id: string; tab?: AssetTab | TaskTab } | null;
  section?: SettingsSection;
}

/**
 * Parse the panel's route path (the part after the `/home-keeper` prefix that HA
 * hands the panel) into a {@link PanelLocation}. Unknown/empty paths fall back to
 * the tasks list. The asset detail lives under the `appliances` segment but keeps
 * the internal `asset` kind.
 *
 * A third segment names an appliance sub-tab (`/appliances/<id>/documents`) or a
 * task sub-tab (`/tasks/<id>/history`). An unrecognised one falls back to the
 * default rather than 404-ing, and a bare `/appliances/<id>` — every link minted
 * before sub-tabs existed, including the `configuration_url` on already-registered
 * devices — keeps resolving. A bare `/tasks/<id>` likewise.
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
    // A task page has sub-tabs of its own, resolved the same way.
    const raw = parts[2] && decodeURIComponent(parts[2]);
    const tab =
      raw && (TASK_TABS as readonly string[]).includes(raw) ? (raw as TaskTab) : DEFAULT_TASK_TAB;
    return { view, detail: { kind, id: decodeURIComponent(parts[1]), tab } };
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
  const dflt = loc.detail.kind === 'asset' ? DEFAULT_ASSET_TAB : DEFAULT_TASK_TAB;
  return tab && tab !== dflt ? `${base}/${tab}` : base;
}

// ── completion history ───────────────────────────────────────────────────────

/** Parsed, valid completion timestamps sorted newest-first. */
export function sortedCompletions(completions?: { ts: string }[]): Date[] {
  return (completions || [])
    .map((c) => new Date(c.ts))
    .filter((d) => !Number.isNaN(d.getTime()))
    .sort((a, b) => b.getTime() - a.getTime());
}

/**
 * The durations the snooze dialog offers, in order, plus the custom escape hatch.
 *
 * One home for the list so the dialog, its labels and any future "editable presets"
 * option all read the same definition. `custom` carries no offset — it reveals a
 * date-time field instead.
 */
export const SNOOZE_PRESETS = [
  { id: '1h', hours: 1 },
  { id: '1d', days: 1 },
  { id: '1w', days: 7 },
  { id: '1mo', months: 1 },
  { id: 'custom' },
] as const;

export type SnoozePresetId = (typeof SNOOZE_PRESETS)[number]['id'];

/** The preset the dialog opens on. A week is the middle of the range and the one a
 *  "not this time" deferral most often means. */
export const DEFAULT_SNOOZE_PRESET: SnoozePresetId = '1w';

/**
 * Resolve a snooze preset to a real instant, measured from *from*.
 *
 * Month arithmetic clamps a day the target month does not have (Jan 31 + 1 month is
 * Feb 28), matching what the backend's `recurrence.add_months` does — so the date the
 * dialog previews is the date the task ends up with. Returns `null` for `custom`,
 * which has no offset of its own.
 */
export function resolveSnoozePreset(id: SnoozePresetId, from: Date): Date | null {
  const preset = SNOOZE_PRESETS.find((p) => p.id === id);
  if (!preset || id === 'custom') return null;
  const out = new Date(from.getTime());
  const spec = preset as { hours?: number; days?: number; months?: number };
  if (spec.hours) out.setHours(out.getHours() + spec.hours);
  if (spec.days) out.setDate(out.getDate() + spec.days);
  if (spec.months) {
    const day = out.getDate();
    // Set the day to 1 before shifting the month: `setMonth` on the 31st of a month
    // whose target is shorter rolls *forward* into the next month (Jan 31 -> Mar 3),
    // which is the opposite of clamping.
    out.setDate(1);
    out.setMonth(out.getMonth() + spec.months);
    const lastDay = new Date(out.getFullYear(), out.getMonth() + 1, 0).getDate();
    out.setDate(Math.min(day, lastDay));
  }
  return out;
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
 * How much a meter advanced between completions, per row and in summary.
 *
 * `byTs` holds each completion's own interval, keyed by that completion's `ts`, so a
 * row renderer looks up its own figure without re-deriving the list. The oldest
 * completion has no predecessor and so no entry. The four summary figures are absent
 * until there are two readings to subtract.
 */
export interface UsageIntervalStats {
  byTs: Map<string, number>;
  /** How many intervals the summary is computed over. */
  count: number;
  /** The most recent interval. */
  last?: number;
  average?: number;
  shortest?: number;
  longest?: number;
}

/** A `Z` or a `±HH:MM` / `±HHMM` tail — the shapes Home Assistant writes. */
// Stryker disable next-line Regex: equivalent — dropping the anchor only admits text
// carrying an offset somewhere other than the end, and `new Date` answers NaN for all
// of it, so the parse filter below rejects it either way.
const TS_HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/i;

/**
 * The usage between consecutive completions — "the last oil change ran 15,400 km".
 *
 * Mirrors `sensor_tasks.usage_intervals` / `usage_interval_stats` on the backend, which
 * publishes the same four figures as attributes; both exist so the panel can render the
 * history without a round trip, and both are the one place the rule is written down.
 *
 * Entries are ordered by parsed timestamp, not by position: `completions` keeps
 * insertion order, so a back-dated completion sits at the end of the list. A negative
 * difference is dropped, because the meter was reset or replaced between the two
 * completions and there is no usage figure to report; a zero difference is kept, since
 * two completions at the same reading really are 0 units apart.
 *
 * Skips are not passed in. A skip resets the meter too, but it records work that was
 * *not* done, so an interval spanning one is still a single service interval — the same
 * rule that keeps a skip out of the completion tally and the cadence.
 */
export function usageIntervalStats(
  completions?: { ts: string; reading?: number }[],
): UsageIntervalStats {
  // Stryker disable next-line ArrayDeclaration: equivalent — the stand-in entry the
  // mutator puts in the empty fallback has no numeric `reading`, so the filter below
  // drops it and the result is the same empty list either way.
  const dated = (completions || [])
    // `Number.isFinite` does not coerce, so that one call is the whole reading guard: a
    // string reading, a boolean, `undefined`, `NaN` and `Infinity` all answer false.
    // (The backend needs an explicit `isinstance` beside it, because `float()` there
    // *would* coerce the string and `True` really is an `int`.)
    //
    // The stamp has to carry a UTC offset. `new Date` reads an offset-free stamp as the
    // viewer's own zone, so the same history would order differently in Berlin and in
    // Seattle, and the backend refuses to compare it against an offset-bearing one at
    // all. Neither is an answer, so both sides drop it.
    .filter((c) => Number.isFinite(c.reading) && TS_HAS_OFFSET.test(c.ts))
    .map((c) => ({ ts: c.ts, at: new Date(c.ts).getTime(), reading: c.reading as number }))
    // The offset test above reads the tail, not the whole stamp, so text that merely
    // ends in one still has to be parsed before it can be ordered.
    .filter((c) => !Number.isNaN(c.at))
    .sort((a, b) => a.at - b.at);
  const byTs = new Map<string, number>();
  const gaps: number[] = [];
  for (let i = 1; i < dated.length; i += 1) {
    const gap = dated[i].reading - dated[i - 1].reading;
    if (gap < 0) continue;
    byTs.set(dated[i].ts, gap);
    gaps.push(gap);
  }
  const stats: UsageIntervalStats = { byTs, count: gaps.length };
  if (gaps.length) {
    stats.last = gaps[gaps.length - 1];
    stats.average = gaps.reduce((sum, gap) => sum + gap, 0) / gaps.length;
    stats.shortest = Math.min(...gaps);
    stats.longest = Math.max(...gaps);
  }
  return stats;
}

/**
 * The only two fields that decide which appliance a task belongs to. Narrower than
 * `Task` on purpose, so the task form can ask the same question of a half-filled
 * draft rather than keeping a second copy of the rule.
 */
export type TaskAssociation = Pick<Task, 'device_id' | 'source'>;

/**
 * How strongly a task is associated with an appliance: 1 is the strongest link
 * and 0 means none. `taskRelatesToAsset` is this predicate's boolean face and
 * `assetsForTask` is its ordering, so the two can never disagree about what
 * counts as related.
 */
function assetRank(task: TaskAssociation, asset: Asset): number {
  // The task exists *because* of this appliance's part. Nothing beats that.
  if (task.source?.part?.asset_id === asset.id) return 1;
  const dev = task.device_id;
  if (!dev) return 0;
  if (asset.device_id && dev === asset.device_id) return 2;
  // A related device is a many-to-one link, so it is the weakest claim.
  // Stryker disable next-line ArrayDeclaration: equivalent — the stand-in the mutator
  // puts in the empty fallback is not a device id, so `includes` answers false either
  // way. Only a task whose device_id were that literal string could tell them apart.
  if ((asset.related_device_ids || []).includes(dev)) return 3;
  return 0;
}

/**
 * True when a task is associated with an appliance — mirrors the backend's
 * `assets.task_relates_to_asset` so the panel can group history client-side.
 */
export function taskRelatesToAsset(task: Task, asset: Asset): boolean {
  return assetRank(task, asset) > 0;
}

/** Every loaded task associated with an appliance. */
export function tasksForAsset(asset: Asset, tasks: Task[]): Task[] {
  return tasks.filter((task) => taskRelatesToAsset(task, asset));
}

/**
 * Every appliance a task is associated with, strongest association first — the
 * inverse of `tasksForAsset`. A device can be claimed by more than one appliance
 * (a related device is a many-to-one link), so the order is what decides which
 * one a single-destination surface picks.
 *
 * Ranked, strongest first:
 *   1. the appliance whose *part* the task is (`source.part.asset_id`) — the task
 *      exists because of that appliance, so nothing beats it;
 *   2. the appliance the device belongs to (`asset.device_id`);
 *   3. an appliance that merely lists the device as related.
 * An archived appliance always ranks below a live one at the same strength: it is
 * still the right answer when it is the only one, and never the right answer when
 * a live appliance claims the same device.
 */
export function assetsForTask(task: TaskAssociation, assets: Asset[]): Asset[] {
  // No index tiebreak: `Array.prototype.sort` is stable, so appliances with an equal
  // claim keep the order they were given.
  return assets
    .map((asset) => ({ asset, rank: assetRank(task, asset) }))
    .filter((x) => x.rank > 0)
    .sort(
      (a, b) =>
        Number(Boolean(a.asset.archived_at)) - Number(Boolean(b.asset.archived_at)) ||
        a.rank - b.rank,
    )
    .map((x) => x.asset);
}

/**
 * The one appliance a task is about, or `undefined` when none claims it. What a
 * task's device chip opens, and what the task form scopes its consumable picker
 * to — one ranking, so the two cannot disagree about which appliance a task
 * belongs to.
 */
export function assetForTask(task: TaskAssociation, assets: Asset[]): Asset | undefined {
  return assetsForTask(task, assets)[0];
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
