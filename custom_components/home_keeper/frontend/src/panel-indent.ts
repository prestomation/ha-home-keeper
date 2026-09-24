/**
 * Fields that only mean something because of a choice above them, indented behind
 * the accent rule (`.hk-indent`) under a small eyebrow and note. Settings uses it for
 * the problem-sensor exclusions, and the recipe dialog for a recipe's exclusions.
 */

import { escapeHTML } from './utils';

/** An `.hk-indent` block headed by *label* and *note*, holding *content*. */
export function indentGroup(label: string, note: string, content: HTMLElement): HTMLElement {
  const indent = document.createElement('div');
  indent.className = 'hk-indent';
  const body = document.createElement('div');
  body.className = 'hk-indent-body';
  const head = document.createElement('div');
  head.className = 'hk-indent-head';
  head.innerHTML =
    `<span class="hk-eyebrow accent">${escapeHTML(label)}</span>` +
    `<span class="hk-indent-note">${escapeHTML(note)}</span>`;
  body.append(head, content);
  indent.appendChild(body);
  return indent;
}
