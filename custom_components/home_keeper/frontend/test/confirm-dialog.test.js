import { afterEach, describe, expect, it, vi } from 'vitest';
import { mountConfirm } from '../src/confirm-dialog.ts';

const content = { title: 'Delete "x"?', body: 'Line 1\nLine 2', confirmLabel: 'Delete task' };

const open = [];

function mount(over = {}, handlers = {}) {
  const calls = { cancel: 0, confirm: 0 };
  const handle = mountConfirm(
    { ...content, ...over },
    {
      onCancel: () => (calls.cancel += 1),
      onConfirm: () => (calls.confirm += 1),
      ...handlers,
    },
  );
  open.push(handle);
  return { handle, calls };
}
const scrim = () => document.querySelector('.hk-confirm-scrim');
const buttons = () => [...document.querySelectorAll('.hk-confirm-scrim ha-button')];

afterEach(() => {
  // A scrim that stays leaves its keydown listener on the document.
  open.splice(0).forEach((h) => h.close());
  document.body.innerHTML = '';
  document.head.querySelector('#hk-confirm-style')?.remove();
});

describe('mountConfirm', () => {
  it('is an alertdialog that names itself and reads its body', () => {
    mount();
    const modal = document.querySelector('.hk-confirm-modal');
    expect(modal.getAttribute('role')).toBe('alertdialog');
    expect(modal.getAttribute('aria-modal')).toBe('true');
    expect(document.getElementById(modal.getAttribute('aria-labelledby')).textContent).toBe(
      content.title,
    );
    expect(document.getElementById(modal.getAttribute('aria-describedby')).textContent).toBe(
      content.body,
    );
  });

  it('puts the action word on the red button, and Cancel first', () => {
    mount();
    const [cancel, confirm] = buttons();
    expect(cancel.textContent).toBe('Cancel');
    expect(confirm.textContent).toBe('Delete task');
    expect(confirm.getAttribute('data-hk-weight')).toBe('danger-primary');
  });

  it('uses the plain primary button for a choice that loses nothing', () => {
    mount({ tone: 'primary', confirmLabel: 'Done' });
    expect(buttons()[1].getAttribute('data-hk-weight')).toBe('primary');
  });

  it('gives Cancel the keyboard', () => {
    const spy = vi.spyOn(HTMLElement.prototype, 'focus');
    mount();
    expect(spy.mock.contexts.some((el) => el === buttons()[0])).toBe(true);
    spy.mockRestore();
  });

  it('cancels on Cancel, on Escape and on a tap outside, and never confirms', () => {
    const { calls } = mount();
    buttons()[0].click();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    scrim().click();
    expect(calls).toEqual({ cancel: 3, confirm: 0 });
  });

  it('does not cancel on a tap inside the dialog', () => {
    const { calls } = mount();
    document.querySelector('.hk-confirm-modal').click();
    expect(calls.cancel).toBe(0);
  });

  it('confirms only from the confirm button', () => {
    const { calls } = mount();
    buttons()[1].click();
    expect(calls).toEqual({ cancel: 0, confirm: 1 });
  });

  it('keeps Tab inside the 2 buttons', () => {
    mount();
    const [cancel, confirm] = buttons();
    cancel.focus = () => cancel.setAttribute('data-f', '1');
    const focused = [];
    cancel.focus = () => focused.push('cancel');
    confirm.focus = () => focused.push('confirm');
    Object.defineProperty(document, 'activeElement', { value: cancel, configurable: true });
    const tab = new KeyboardEvent('keydown', { key: 'Tab', cancelable: true });
    document.dispatchEvent(tab);
    expect(tab.defaultPrevented).toBe(true);
    expect(focused).toEqual(['confirm']);
    const back = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, cancelable: true });
    document.dispatchEvent(back);
    expect(focused).toEqual(['confirm', 'confirm']);
    delete document.activeElement;
  });

  it('is a notice with only Close when there is no confirm label', () => {
    mount({ confirmLabel: null });
    expect(buttons().map((b) => b.textContent)).toEqual(['Close']);
  });

  it('takes the scrim and the key listener down on close, and close twice is safe', () => {
    const { handle, calls } = mount();
    handle.close();
    handle.close();
    expect(scrim()).toBeNull();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    expect(calls.cancel).toBe(0);
  });

  it('stops an Escape from reaching a listener below it', () => {
    mount();
    const below = vi.fn();
    document.addEventListener('keydown', below);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    document.removeEventListener('keydown', below);
    expect(below).not.toHaveBeenCalled();
  });

  it('adds its stylesheet once, with every rule on a token and no inline style', () => {
    mount();
    mount();
    const sheets = document.head.querySelectorAll('#hk-confirm-style');
    expect(sheets).toHaveLength(1);
    expect(document.querySelector('.hk-confirm-scrim').getAttribute('style')).toBeNull();
    expect(document.querySelector('.hk-confirm-modal').getAttribute('style')).toBeNull();
    // A literal color may appear only where a token is defined (a `--hk-confirm-*` line).
    const css = sheets[0].textContent;
    const literal = css
      .split('\n')
      .filter((l) => /#[0-9a-f]{3,6}\b|rgba?\(/i.test(l) && !/^\s*--hk-confirm-/.test(l));
    expect(literal).toEqual([]);
  });

  it('breaks a long body at its own line ends', () => {
    mount();
    expect(document.querySelector('.hk-confirm-body').textContent).toContain('\n');
    expect(document.head.querySelector('#hk-confirm-style').textContent).toContain('pre-line');
  });
});
