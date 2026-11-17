import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  MENU_KINDS,
  NO_OVERLAY,
  OVERLAY_KINDS,
  isBusy,
  isOpen,
  overlayStep,
  topOverlay,
} from '../src/overlay-state.ts';

const run = (s, ...events) => events.reduce(overlayStep, s);
const open = (kind, opener = null) => ({ type: 'open', kind, opener });
const close = (kind) => ({ type: 'close', kind });
const FOCUSED = { type: 'focused' };

describe('overlayStep', () => {
  it('starts with no overlay, not busy and no focus move', () => {
    expect(NO_OVERLAY).toEqual({ stack: [], focus: null });
    expect(isBusy(NO_OVERLAY)).toBe(false);
    expect(topOverlay(NO_OVERLAY)).toBeNull();
    expect(MENU_KINDS).toEqual(['deferMenu', 'actionSheet']);
    expect(OVERLAY_KINDS).toHaveLength(14);
  });

  it('is busy while any overlay is open, also a menu or a sheet', () => {
    for (const kind of OVERLAY_KINDS) {
      const s = run(NO_OVERLAY, open(kind, '#b'));
      expect(isBusy(s), kind).toBe(true);
      expect(isOpen(s, kind), kind).toBe(true);
      expect(topOverlay(s)).toBe(kind);
      expect(isBusy(run(s, close(kind))), kind).toBe(false);
    }
  });

  it('gives the keyboard back to the opener of the top overlay that closes', () => {
    const s = run(NO_OVERLAY, open('completion', '#done'));
    expect(s.focus).toBeNull();
    const closed = overlayStep(s, close('completion'));
    expect(closed).toEqual({ stack: [], focus: '#done' });
    expect(overlayStep(closed, FOCUSED)).toEqual(NO_OVERLAY);
  });

  it('leaves the keyboard when an overlay below the top closes', () => {
    const s = run(NO_OVERLAY, open('taskForm', '#add-btn'), open('confirm', '#del'));
    const closed = overlayStep(s, close('taskForm'));
    expect(closed.focus).toBeNull();
    // The opener of the confirmation was in the form, so it takes the form's opener.
    expect(closed.stack).toEqual([{ kind: 'confirm', opener: '#add-btn' }]);
    expect(overlayStep(closed, close('confirm')).focus).toBe('#add-btn');
  });

  it('keeps a focus move that waits when an overlay below closes', () => {
    const s = run(
      NO_OVERLAY,
      open('taskForm', '#add-btn'),
      open('confirm', '#del'),
      open('label', '#lbl'),
      close('label'),
      close('taskForm'),
    );
    expect(s.focus).toBe('#lbl');
    // The next top close moves the keyboard to its own opener.
    expect(overlayStep(s, close('confirm')).focus).toBe('#add-btn');
  });

  it('does nothing for a close of an overlay that is not open', () => {
    const s = run(NO_OVERLAY, open('snooze', '#s'));
    expect(overlayStep(s, close('skip'))).toBe(s);
    expect(overlayStep(NO_OVERLAY, FOCUSED)).toBe(NO_OVERLAY);
  });

  it('hands a menu over to the dialog that it opens', () => {
    for (const menu of MENU_KINDS) {
      const s = run(NO_OVERLAY, open(menu, '.caret'), open('snooze', '.menu-item'));
      expect(s.stack).toEqual([{ kind: 'snooze', opener: '.caret' }]);
      expect(isOpen(s, menu)).toBe(false);
      expect(overlayStep(s, close('snooze')).focus).toBe('.caret');
    }
  });

  it('takes the waiting focus move as the opener after a close and an open', () => {
    const s = run(NO_OVERLAY, open('deferMenu', '.caret'), close('deferMenu'), open('skip', '.item'));
    expect(s).toEqual({ stack: [{ kind: 'skip', opener: '.caret' }], focus: null });
  });

  it('changes nothing for an open of an overlay that is open', () => {
    const s = run(NO_OVERLAY, open('taskForm', '#add'), open('label', '#l'), close('label'));
    expect(overlayStep(s, open('taskForm', '#x'))).toBe(s);
  });

  it('keeps an overlay that is not a menu under the next one', () => {
    const s = run(NO_OVERLAY, open('taskForm', '#add'), open('confirm', '#del'));
    expect(s.stack.map((o) => o.kind)).toEqual(['taskForm', 'confirm']);
  });

  it('keeps a menu opener of null and uses the new opener then', () => {
    const s = run(NO_OVERLAY, open('actionSheet', null), open('snooze', '#x'));
    expect(s.stack).toEqual([{ kind: 'snooze', opener: '#x' }]);
  });
});

/*
 * Model test. The fake page has 3 controls, and each open overlay has 1 control of
 * its own. The keyboard is on 1 control. A user opens an overlay from where the
 * keyboard is, the keyboard goes into it, and the user closes overlays in any order.
 * The host moves the keyboard to `focus` when it has rendered. The model keeps its
 * own list of what is open, with the menu rule, and checks the machine against it.
 */
const PAGE = ['#p0', '#p1', '#p2'];
const itemOf = (kind) => `${kind}:item`;

function exists(model, control) {
  return PAGE.includes(control) || model.open.some((k) => itemOf(k) === control);
}

const cmd = (name, check, run) => ({
  check,
  run(m) {
    run(m);
    expect(isBusy(m.s), name).toBe(m.open.length > 0);
    for (const kind of OVERLAY_KINDS) expect(isOpen(m.s, kind), `${name} ${kind}`).toBe(m.open.includes(kind));
    expect(topOverlay(m.s)).toBe(m.open.length ? m.open[m.open.length - 1] : null);
  },
  toString: () => name,
});

const commands = [
  fc.constantFrom(...OVERLAY_KINDS).map((kind) =>
    cmd(`Open(${kind})`, () => true, (m) => {
      m.s = overlayStep(m.s, { type: 'open', kind, opener: m.keyboard });
      if (m.open.includes(kind)) return;
      const top = m.open[m.open.length - 1];
      if (top && top !== kind && (top === 'deferMenu' || top === 'actionSheet')) {
        m.open = m.open.filter((k) => k !== top);
      }
      m.open.push(kind);
      m.keyboard = itemOf(kind);
    }),
  ),
  fc.constantFrom(...OVERLAY_KINDS).map((kind) =>
    cmd(`Close(${kind})`, (m) => m.open.includes(kind), (m) => {
      m.s = overlayStep(m.s, { type: 'close', kind });
      m.open = m.open.filter((k) => k !== kind);
    }),
  ),
  fc.constantFrom(...PAGE).map((control) =>
    cmd(`Click(${control})`, (m) => m.open.length === 0 && m.s.focus === null, (m) => {
      m.keyboard = control;
    }),
  ),
  fc.constant(
    cmd('Render', () => true, (m) => {
      if (m.s.focus !== null) m.keyboard = m.s.focus;
      m.s = overlayStep(m.s, { type: 'focused' });
      expect(m.s.focus).toBeNull();
      // The keyboard is never on a control that is gone after the host moved it.
      expect(exists(m, m.keyboard), `keyboard on ${m.keyboard}`).toBe(true);
    }),
  ),
];

describe('overlay model', () => {
  it('agrees with the model and never leaves the keyboard on a closed overlay', () => {
    fc.assert(
      fc.property(fc.commands(commands, { maxCommands: 30 }), (cmds) => {
        const m = { s: NO_OVERLAY, open: [], keyboard: '#p0' };
        fc.modelRun(() => ({ model: m, real: {} }), cmds);
        // Close all, in order from the top, rendering after each, as a user does.
        if (m.s.focus !== null) m.keyboard = m.s.focus;
        m.s = overlayStep(m.s, { type: 'focused' });
        while (m.open.length) {
          const top = m.open.pop();
          m.s = overlayStep(m.s, { type: 'close', kind: top });
          if (m.s.focus !== null) m.keyboard = m.s.focus;
          m.s = overlayStep(m.s, { type: 'focused' });
        }
        expect(m.s).toEqual(NO_OVERLAY);
        expect(PAGE).toContain(m.keyboard);
      }),
    );
  });
});
