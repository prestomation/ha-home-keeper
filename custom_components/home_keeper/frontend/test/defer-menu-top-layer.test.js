/**
 * #497: a theme that clips or layers every card (`overflow`, `backdrop-filter`) cut
 * the Done menu off or hid it behind the next row. The menu opens in the top layer,
 * and `placeMenu` puts it under its button.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';
import { DeferMenus, placeMenu } from '../src/defer-dialogs.ts';
import { deferSplit } from '../src/defer.ts';

const TASK = { id: 't1', name: 'Replace filter', next_due: '2030-01-01T00:00:00Z' };
const VERBS = { snooze: true, skip: true, dueToday: true };

function rect(left, top, width, height) {
  return { left, top, width, height, right: left + width, bottom: top + height };
}

/** A split button and a menu whose boxes are fixed, as jsdom does no layout. */
function place({ split, menu, inActions = false, viewport = [1000, 800] }) {
  const root = document.createElement('div');
  if (inActions) root.className = 'hk-card-actions';
  const splitEl = document.createElement('span');
  root.appendChild(splitEl);
  const menuEl = document.createElement('div');
  splitEl.appendChild(menuEl);
  splitEl.getBoundingClientRect = () => split;
  menuEl.getBoundingClientRect = () => menu;
  vi.stubGlobal('innerWidth', viewport[0]);
  vi.stubGlobal('innerHeight', viewport[1]);
  placeMenu(splitEl, menuEl);
  return { left: menuEl.style.left, top: menuEl.style.top };
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('#497: Done menu in the top layer', () => {
  it('puts the menu under the left edge of the button', () => {
    const at = place({ split: rect(100, 50, 80, 30), menu: rect(0, 0, 220, 120) });
    expect(at).toEqual({ left: '100px', top: '86px' });
  });

  it('puts the menu under the right edge for a list row action', () => {
    const at = place({
      split: rect(700, 50, 80, 30),
      menu: rect(0, 0, 220, 120),
      inActions: true,
    });
    expect(at).toEqual({ left: '560px', top: '86px' });
  });

  it('keeps the menu inside the viewport on both sides', () => {
    expect(place({ split: rect(900, 50, 80, 30), menu: rect(0, 0, 220, 120) }).left).toBe(
      '768px',
    );
    expect(
      place({ split: rect(2, 50, 40, 30), menu: rect(0, 0, 220, 120), inActions: true }).left,
    ).toBe('12px');
  });

  it('opens above the button when there is no room below', () => {
    const at = place({ split: rect(100, 700, 80, 30), menu: rect(0, 0, 220, 120) });
    expect(at.top).toBe('574px');
  });

  it('opens below when there is no room above either', () => {
    const at = place({
      split: rect(100, 30, 80, 30),
      menu: rect(0, 0, 220, 120),
      viewport: [1000, 150],
    });
    expect(at.top).toBe('66px');
  });

  it('shows and hides the popover with the menu, and moves it on scroll', () => {
    const root = document.createElement('div');
    root.innerHTML = deferSplit(TASK, '<button>Done</button>', VERBS);
    document.body.appendChild(root);
    const menu = root.querySelector('.hk-defer-menu');
    const split = root.querySelector('.hk-split');
    menu.showPopover = vi.fn();
    menu.hidePopover = vi.fn();
    const box = { current: rect(100, 50, 80, 30) };
    split.getBoundingClientRect = () => box.current;
    menu.getBoundingClientRect = () => rect(0, 0, 220, 120);
    const menus = new DeferMenus({
      taskById: () => TASK,
      onSnooze: vi.fn(),
      onSkip: vi.fn(),
      onDueToday: vi.fn(),
    });
    menus.wire(root);
    root.querySelector('.hk-split-caret').click();
    expect(menu.getAttribute('popover')).toBe('manual');
    expect(menu.showPopover).toHaveBeenCalledTimes(1);
    expect(menu.style.top).toBe('86px');
    box.current = rect(100, 20, 80, 30);
    window.dispatchEvent(new Event('scroll'));
    expect(menu.style.top).toBe('56px');
    menus.close();
    expect(menu.hidePopover).toHaveBeenCalledTimes(1);
    expect(menu.hidden).toBe(true);
    box.current = rect(100, 300, 80, 30);
    window.dispatchEvent(new Event('scroll'));
    expect(menu.style.top).toBe('56px');
  });

  it('still opens where the browser has no Popover API', () => {
    const root = document.createElement('div');
    root.innerHTML = deferSplit(TASK, '<button>Done</button>', VERBS);
    document.body.appendChild(root);
    const menu = root.querySelector('.hk-defer-menu');
    const menus = new DeferMenus({
      taskById: () => TASK,
      onSnooze: vi.fn(),
      onSkip: vi.fn(),
      onDueToday: vi.fn(),
    });
    menus.wire(root);
    root.querySelector('.hk-split-caret').click();
    expect(menu.hidden).toBe(false);
    menus.close();
    expect(menu.hidden).toBe(true);
  });
});
