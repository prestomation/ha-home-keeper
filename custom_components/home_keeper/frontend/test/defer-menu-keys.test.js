/**
 * X11-5: the deferral menu claims role="menu", so it must act as one. Opening it
 * focuses the first item, the arrow keys and Home/End move focus, and Escape puts
 * focus back on the caret instead of letting it fall to the page body.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { DeferMenus, menuKeyTarget } from '../src/defer-dialogs.ts';
import { deferSplit } from '../src/defer.ts';

const TASK = { id: 't1', name: 'Replace filter', next_due: '2030-01-01T00:00:00Z' };

function mount() {
  const root = document.createElement('div');
  root.innerHTML = deferSplit(TASK, '<button class="done">Done</button>', {
    snooze: true,
    skip: true,
    dueToday: true,
  });
  document.body.appendChild(root);
  const host = { taskById: () => TASK, onSnooze: vi.fn(), onSkip: vi.fn(), onDueToday: vi.fn() };
  const menus = new DeferMenus(host);
  menus.wire(root);
  const caret = root.querySelector('.hk-split-caret');
  // jsdom gives an unknown element no focus, so watch the call instead.
  caret.focus = vi.fn();
  const items = [...root.querySelectorAll('[role="menuitem"]')];
  return { root, menus, caret, items, host };
}

function key(target, k) {
  const e = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true });
  target.dispatchEvent(e);
  return e;
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('X11-5: deferral menu keyboard', () => {
  it('X11-5: focuses the first item when the menu opens', () => {
    const { caret, items } = mount();
    caret.click();
    expect(caret.getAttribute('aria-expanded')).toBe('true');
    expect(document.activeElement).toBe(items[0]);
  });

  it('X11-5: moves focus with the arrow keys, Home and End', () => {
    const { caret, items } = mount();
    caret.click();
    const down = key(items[0], 'ArrowDown');
    expect(down.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(items[1]);
    key(items[1], 'ArrowDown');
    key(items[2], 'ArrowDown');
    expect(document.activeElement).toBe(items[0]);
    key(items[0], 'ArrowUp');
    expect(document.activeElement).toBe(items[2]);
    key(items[2], 'Home');
    expect(document.activeElement).toBe(items[0]);
    key(items[0], 'End');
    expect(document.activeElement).toBe(items[2]);
    const other = key(items[2], 'a');
    expect(other.defaultPrevented).toBe(false);
    expect(document.activeElement).toBe(items[2]);
  });

  it('X11-5: Escape closes the menu and focuses the caret', () => {
    const { root, caret, items } = mount();
    caret.click();
    key(items[1], 'Escape');
    expect(root.querySelector('.hk-defer-menu').hidden).toBe(true);
    expect(caret.getAttribute('aria-expanded')).toBe('false');
    expect(caret.focus).toHaveBeenCalledTimes(1);
  });

  it('X11-5: a key after the menu closed does nothing', () => {
    const { caret, items } = mount();
    caret.click();
    key(items[0], 'Escape');
    items[2].focus();
    key(items[2], 'Home');
    expect(document.activeElement).toBe(items[2]);
    expect(caret.focus).toHaveBeenCalledTimes(1);
  });
});

describe('menuKeyTarget', () => {
  it('X11-5: gives the next index for each key, and wraps', () => {
    expect(menuKeyTarget('ArrowDown', 0, 3)).toBe(1);
    expect(menuKeyTarget('ArrowDown', 2, 3)).toBe(0);
    expect(menuKeyTarget('ArrowDown', -1, 3)).toBe(0);
    expect(menuKeyTarget('ArrowUp', 1, 3)).toBe(0);
    expect(menuKeyTarget('ArrowUp', 0, 3)).toBe(2);
    expect(menuKeyTarget('ArrowUp', -1, 3)).toBe(2);
    expect(menuKeyTarget('Home', 2, 3)).toBe(0);
    expect(menuKeyTarget('End', 0, 3)).toBe(2);
    expect(menuKeyTarget('Tab', 0, 3)).toBeNull();
    expect(menuKeyTarget('ArrowDown', 0, 0)).toBeNull();
  });
});
