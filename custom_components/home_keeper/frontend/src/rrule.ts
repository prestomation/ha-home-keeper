/**
 * The simple view of a fixed schedule's RRULE.
 *
 * A fixed task stores one thing, its RFC 5545 rule (`FREQ=WEEKLY;BYDAY=TU,FR`). The
 * form shows most rules as plain controls — Repeats, Every and 7 day buttons — and
 * keeps the rule text beside them for anything those controls cannot say ("the first
 * Tuesday of each month"). This module is the translation in both directions:
 *
 * - {@link parseSimple} reads a rule back into the controls, or answers `null` when the
 *   rule says more than they can. The form then grays the controls out and offers
 *   {@link resetToSimple}.
 * - {@link buildSimple} and the edit helpers write the controls back into a rule.
 *
 * The backend (`recurrence.normalize_rule`) is what validates and expands a rule; this
 * module never decides whether a rule is *valid*, only whether it is *simple*.
 */

/** The weekday codes RFC 5545 uses, Monday first as `WKST` defaults to. */
export const WEEKDAYS = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU'] as const;
export type Weekday = (typeof WEEKDAYS)[number];

/** The frequencies the simple controls offer. A sub-daily rule is not storable. */
export const SIMPLE_FREQS = ['DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'] as const;
export type SimpleFreq = (typeof SIMPLE_FREQS)[number];

export interface SimpleRule {
  freq: SimpleFreq;
  interval: number;
  /** Only for WEEKLY. Empty means "the start date's weekday". */
  byday: Weekday[];
}

/**
 * Split a rule into `{PART: value}`, upper-cased. `null` when it does not even have
 * the `KEY=VALUE;…` shape. An `RRULE:` prefix is allowed, as the backend allows it.
 */
export function ruleParts(rule: string): Record<string, string> | null {
  let text = rule.trim();
  if (text.toUpperCase().startsWith('RRULE:')) text = text.slice('RRULE:'.length);
  const parts: Record<string, string> = {};
  for (const raw of text.split(';')) {
    const chunk = raw.trim();
    if (!chunk) continue;
    const eq = chunk.indexOf('=');
    if (eq <= 0 || eq === chunk.length - 1) return null;
    parts[chunk.slice(0, eq).trim().toUpperCase()] = chunk.slice(eq + 1).trim().toUpperCase();
  }
  return Object.keys(parts).length ? parts : null;
}

/**
 * The simple controls for *rule*, or `null` when the rule says more than they can.
 *
 * Simple means: a FREQ the Repeats menu offers, an optional whole INTERVAL, and — for a
 * weekly rule only — a BYDAY of plain weekdays (`TU,FR`, never `1TU`). A `WKST=MO` is
 * the default and changes nothing, so it does not make a rule custom.
 */
export function parseSimple(rule: string | null | undefined): SimpleRule | null {
  if (!rule) return null;
  const parts = ruleParts(rule);
  if (!parts) return null;
  const freq = parts.FREQ as SimpleFreq;
  if (!SIMPLE_FREQS.includes(freq)) return null;
  for (const key of Object.keys(parts)) {
    if (key === 'FREQ' || key === 'INTERVAL') continue;
    if (key === 'WKST' && parts.WKST === 'MO') continue;
    if (key === 'BYDAY' && freq === 'WEEKLY') continue;
    return null;
  }
  let interval = 1;
  if ('INTERVAL' in parts) {
    if (!/^\d+$/.test(parts.INTERVAL)) return null;
    interval = Number(parts.INTERVAL);
    if (interval < 1) return null;
  }
  let byday: Weekday[] = [];
  if ('BYDAY' in parts) {
    const days = parts.BYDAY.split(',').map((d) => d.trim());
    if (!days.every((d) => (WEEKDAYS as readonly string[]).includes(d))) return null;
    byday = sortDays(days as Weekday[]);
  }
  return { freq, interval, byday };
}

/** *days* without repeats, in week order. */
export function sortDays(days: Weekday[]): Weekday[] {
  return WEEKDAYS.filter((d) => days.includes(d));
}

/** The rule text for a set of simple controls. */
export function buildSimple(simple: SimpleRule): string {
  const interval = Math.max(1, Math.floor(simple.interval) || 1);
  let rule = `FREQ=${simple.freq};INTERVAL=${interval}`;
  if (simple.freq === 'WEEKLY' && simple.byday.length) {
    rule += `;BYDAY=${sortDays(simple.byday).join(',')}`;
  }
  return rule;
}

/**
 * A simple rule that keeps what it can of *rule*: its FREQ when the menu offers it,
 * else weekly, and its INTERVAL when it has a usable one. The days are dropped, so the
 * schedule falls back to the start date's weekday until a day button is pressed.
 */
export function resetToSimple(rule: string | null | undefined): string {
  const parts = (rule && ruleParts(rule)) || {};
  const freq = SIMPLE_FREQS.includes(parts.FREQ as SimpleFreq)
    ? (parts.FREQ as SimpleFreq)
    : 'WEEKLY';
  const interval = /^\d+$/.test(parts.INTERVAL ?? '') ? Number(parts.INTERVAL) : 1;
  return buildSimple({ freq, interval, byday: [] });
}

/**
 * The rule after a change to the Repeats or Every control.
 *
 * A custom rule is returned unchanged: the controls are grayed out then, so a change
 * can only arrive from a stale form and must not overwrite what the user typed.
 * Changing the frequency drops the days, because a weekday list means nothing to a
 * monthly rule.
 */
export function withSimpleChange(
  rule: string,
  change: { freq?: string; interval?: number },
): string {
  const simple = parseSimple(rule);
  if (!simple) return rule;
  const freq = SIMPLE_FREQS.includes(change.freq as SimpleFreq)
    ? (change.freq as SimpleFreq)
    : simple.freq;
  return buildSimple({
    freq,
    interval: change.interval ?? simple.interval,
    byday: freq === simple.freq ? simple.byday : [],
  });
}

/** The weekday of a start date, as an RFC 5545 code. */
export function weekdayOf(date: Date): Weekday {
  // getDay() counts from Sunday.
  return WEEKDAYS[(date.getDay() + 6) % 7];
}

/**
 * The days a weekly rule lands on, as the day buttons should show them: its BYDAY, or
 * the start date's weekday when it names none. Empty for a rule that is not a simple
 * weekly one.
 */
export function shownDays(rule: string, anchor: Date | null): Weekday[] {
  const simple = parseSimple(rule);
  if (!simple || simple.freq !== 'WEEKLY') return [];
  if (simple.byday.length) return simple.byday;
  return anchor ? [weekdayOf(anchor)] : [];
}

/**
 * The rule after a day button is pressed.
 *
 * The button shows {@link shownDays}, so toggling acts on that set: pressing Friday on
 * a plain weekly rule anchored on a Tuesday gives Tuesday and Friday. The last day
 * cannot be turned off — a weekly rule with no day would fall back to the start
 * date's day, which is not what pressing it off asked for.
 */
export function toggleDay(rule: string, day: Weekday, anchor: Date | null): string {
  const simple = parseSimple(rule);
  if (!simple || simple.freq !== 'WEEKLY') return rule;
  const current = shownDays(rule, anchor);
  const next = current.includes(day) ? current.filter((d) => d !== day) : [...current, day];
  if (!next.length) return rule;
  return buildSimple({ ...simple, byday: next });
}

/** A weekday's name in *lang*: `short` for a button, `long` for a sentence. */
export function weekdayName(
  day: Weekday,
  lang: string | undefined,
  style: 'narrow' | 'short' | 'long' = 'short',
): string {
  // 2024-01-01 was a Monday, so day *i* of that week is WEEKDAYS[i]. Noon UTC keeps
  // the date the same in every zone.
  const date = new Date(Date.UTC(2024, 0, 1 + WEEKDAYS.indexOf(day), 12));
  return new Intl.DateTimeFormat(lang || undefined, { weekday: style, timeZone: 'UTC' }).format(
    date,
  );
}

/** "Tuesday and Friday" in *lang*. */
export function dayList(days: Weekday[], lang: string | undefined): string {
  const names = sortDays(days).map((d) => weekdayName(d, lang, 'long'));
  return new Intl.ListFormat(lang || undefined, { type: 'conjunction' }).format(names);
}
