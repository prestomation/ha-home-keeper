import { t } from './i18n';
import type { Asset, Part, Task } from './types';
import { formatQuantity, isBuyTask } from './utils';

/**
 * The lines the Settings → Shopping list preview shows: what the synced list will
 * hold, written the way the shopping-list sync writes it.
 *
 * This is the panel's copy of `shopping.buy_tasks_by_part` and `shopping.line_for`
 * on the backend. It has to read the same, so each rule here names its twin.
 */

/** How a line is titled on the list. The values are the `shopping_line_style` option. */
export type LineStyle = 'with_verb' | 'product_only';

/** One line on the list: its title, and the description under it (or ''). */
export interface PreviewLine {
  title: string;
  description: string;
}

/** `TodoListEntityFeature.SET_DESCRIPTION_ON_ITEM`. */
export const SET_DESCRIPTION_ON_ITEM = 64;

/** Whether a to-do entity's `supported_features` let an item hold a description. */
export function supportsDescription(features: unknown): boolean {
  return (Number(features) & SET_DESCRIPTION_ON_ITEM) !== 0;
}

/** Anything unknown reads as the default, like `shopping.normalize_line_style`. */
export function normalizeLineStyle(value: unknown): LineStyle {
  return value === 'product_only' ? 'product_only' : 'with_verb';
}

/**
 * How much a buy reminder asks for, or '' — the twin of `assets.part_restock_label`.
 *
 * A part measured in something reads "500 ml", a part that restocks several spares
 * reads "×2", and the ordinary one-spare part reads nothing.
 */
export function restockLabel(part: Part, lang?: string): string {
  const raw = Number(part.restock_quantity);
  const quantity = Number.isFinite(raw) && raw > 0 ? raw : 1;
  const unit = (part.stock_unit || '').trim();
  if (unit) return formatQuantity(quantity, unit, lang);
  if (quantity > 1) return `×${formatQuantity(quantity, '', lang)}`;
  return '';
}

/** The title and the amount, placed as the list can hold them — `shopping.line_for`. */
export function lineFor(
  name: string,
  amount: string,
  withDescription: boolean,
): PreviewLine {
  if (withDescription) return { title: name, description: amount };
  return { title: amount ? `${name} (${amount})` : name, description: '' };
}

function isOpen(task: Task): boolean {
  // A completed one-off is dormant: no due date, and a completion on record.
  return !(task.recurrence_type === 'one-off' && !task.next_due && task.last_completed);
}

function partFor(task: Task, assets: Asset[]): Part | undefined {
  const buy = task.source?.buy;
  const asset = assets.find((a) => a.id === buy?.asset_id);
  return asset?.parts?.find((p) => p.id === buy?.part_id);
}

/**
 * The preview for the household's open buy reminders, sorted by title.
 *
 * With no open reminders there is nothing real to show, so two example parts stand
 * in. They are built from the same rules, so the example still changes with the style
 * and with what the list can hold.
 */
export function previewLines(
  tasks: Task[],
  assets: Asset[],
  style: LineStyle,
  withDescription: boolean,
  lang?: string,
): PreviewLine[] {
  const lines: PreviewLine[] = [];
  for (const task of tasks) {
    if (!isBuyTask(task) || !isOpen(task)) continue;
    const name = (task.name || '').trim();
    if (!name) continue;
    const part = partFor(task, assets);
    const partName = (part?.name || '').trim();
    const title = style === 'product_only' && partName ? partName : name;
    lines.push(lineFor(title, part ? restockLabel(part, lang) : '', withDescription));
  }
  if (lines.length) return lines.sort((a, b) => a.title.localeCompare(b.title, lang));
  return exampleLines(style, withDescription, lang);
}

function exampleLines(style: LineStyle, withDescription: boolean, lang?: string): PreviewLine[] {
  const examples: [string, Part][] = [
    [t('settings.shopping_preview_example_a'), { name: '', type: 'consumable', restock_quantity: 2 }],
    [
      t('settings.shopping_preview_example_b'),
      { name: '', type: 'consumable', restock_quantity: 1.5, stock_unit: 'kg' },
    ],
  ];
  return examples.map(([part, spec]) => {
    const title = style === 'product_only' ? part : t('settings.shopping_preview_buy', { part });
    return lineFor(title, restockLabel(spec, lang), withDescription);
  });
}
