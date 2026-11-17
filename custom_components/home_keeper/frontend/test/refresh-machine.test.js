import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import {
  INITIAL_REFRESH,
  LOAD_RETRY_MS,
  refreshStep,
  shouldLoad,
} from '../src/refresh-machine.ts';

const ECHO_MS = 2000;
const T = 1_000_000;

/** Apply *events* to *state* in order. */
const run = (state, ...events) => events.reduce(refreshStep, state);

describe('refreshStep', () => {
  it('starts with nothing seen, nothing loading and no wait', () => {
    expect(INITIAL_REFRESH).toEqual({
      sig: '',
      seen: 0,
      shown: 0,
      loading: null,
      echoUntil: 0,
      retryAt: 0,
    });
    expect(LOAD_RETRY_MS).toBe(10_000);
  });

  it('counts a new fingerprint as 1 change, and the same one again as none', () => {
    const a = run(INITIAL_REFRESH, { type: 'signal', sig: 'a', busy: false, now: T });
    expect(a).toMatchObject({ sig: 'a', seen: 1, shown: 0 });
    expect(shouldLoad(a, false, T)).toBe(true);
    const again = refreshStep(a, { type: 'signal', sig: 'a', busy: false, now: T });
    expect(again.seen).toBe(1);
  });

  it('counts a pushed event as 1 change and keeps the fingerprint', () => {
    const s = run(INITIAL_REFRESH, { type: 'start', sig: 'a' }, { type: 'change' });
    expect(s).toMatchObject({ sig: 'a', seen: 1, loading: 0 });
  });

  it('does not load while busy, while a load runs, or when nothing changed', () => {
    const changed = run(INITIAL_REFRESH, { type: 'change' });
    expect(shouldLoad(changed, true, T)).toBe(false);
    expect(shouldLoad(INITIAL_REFRESH, false, T)).toBe(false);
    const loading = refreshStep(changed, { type: 'start', sig: '' });
    expect(shouldLoad(loading, false, T)).toBe(false);
  });

  it('covers the count at the start of a load, so a change during it loads again', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'signal', sig: 'b', busy: false, now: T },
      { type: 'done', ok: true, now: T, echoMs: ECHO_MS },
    );
    expect(s).toMatchObject({ seen: 1, shown: 0, loading: null, echoUntil: 0, retryAt: 0 });
    expect(shouldLoad(s, false, T)).toBe(true);
  });

  it('keeps the first start when a second start comes during a load', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'change' },
      { type: 'start', sig: 'b' },
    );
    expect(s.loading).toBe(0);
    expect(s.sig).toBe('b');
  });

  it('opens the echo window after a clean load, and takes a new fingerprint as the echo', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'done', ok: true, now: T, echoMs: ECHO_MS },
    );
    expect(s.echoUntil).toBe(T + ECHO_MS);
    const echo = refreshStep(s, { type: 'signal', sig: 'b', busy: false, now: T + ECHO_MS - 1 });
    expect(echo).toMatchObject({ seen: 1, shown: 1 });
    expect(shouldLoad(echo, false, T + ECHO_MS - 1)).toBe(false);
  });

  it('loads a change that comes when the echo window has closed', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'done', ok: true, now: T, echoMs: ECHO_MS },
      { type: 'signal', sig: 'b', busy: false, now: T + ECHO_MS },
    );
    expect(s).toMatchObject({ seen: 1, shown: 0 });
    expect(shouldLoad(s, false, T + ECHO_MS)).toBe(true);
  });

  it('does not take a change as the echo while busy or while a load runs', () => {
    const open = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'done', ok: true, now: T, echoMs: ECHO_MS },
    );
    const busy = refreshStep(open, { type: 'signal', sig: 'b', busy: true, now: T + 1 });
    expect(busy.shown).toBe(0);
    const loading = run(
      open,
      { type: 'start', sig: 'a' },
      { type: 'signal', sig: 'b', busy: false, now: T + 1 },
    );
    expect(loading.shown).toBe(0);
  });

  it('keeps a change after a failed load and waits before the next try', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'change' },
      { type: 'start', sig: 'a' },
      { type: 'done', ok: false, now: T, echoMs: ECHO_MS },
    );
    expect(s).toMatchObject({ seen: 1, shown: 0, loading: null, echoUntil: 0 });
    expect(s.retryAt).toBe(T + LOAD_RETRY_MS);
    expect(shouldLoad(s, false, T + LOAD_RETRY_MS - 1)).toBe(false);
    expect(shouldLoad(s, false, T + LOAD_RETRY_MS)).toBe(true);
    // A good load clears the wait.
    const ok = run(
      s,
      { type: 'start', sig: 'a' },
      { type: 'done', ok: true, now: T + 1, echoMs: ECHO_MS },
    );
    expect(ok).toMatchObject({ shown: 1, retryAt: 0 });
  });

  it('loads a new change at once after a failed load', () => {
    const failed = run(
      INITIAL_REFRESH,
      { type: 'start', sig: 'a' },
      { type: 'done', ok: false, now: T, echoMs: ECHO_MS },
    );
    const signal = refreshStep(failed, { type: 'signal', sig: 'b', busy: false, now: T + 1 });
    expect(signal).toMatchObject({ seen: 1, retryAt: 0 });
    expect(shouldLoad(signal, false, T + 1)).toBe(true);
    const pushed = refreshStep(failed, { type: 'change' });
    expect(pushed).toMatchObject({ seen: 1, retryAt: 0 });
    // The same fingerprint again keeps the wait.
    const same = refreshStep(failed, { type: 'signal', sig: 'a', busy: false, now: T + 1 });
    expect(same.retryAt).toBe(T + LOAD_RETRY_MS);
  });

  it('changes nothing on screen when a load ends that did not start', () => {
    const s = run(
      INITIAL_REFRESH,
      { type: 'change' },
      { type: 'done', ok: true, now: T, echoMs: ECHO_MS },
    );
    expect(s).toMatchObject({ seen: 1, shown: 0, echoUntil: 0 });
  });

  it('does not change the input state', () => {
    const s = { ...INITIAL_REFRESH };
    run(s, { type: 'change' }, { type: 'start', sig: 'x' });
    expect(s).toEqual(INITIAL_REFRESH);
  });
});

/*
 * Model test. The world holds the store's version (`server`), the version that
 * Home Assistant shows in its entity states (`ha`), and the version on screen. A
 * driver does what the panel does: it sends each event to the machine and starts a
 * load when `shouldLoad` says so. The model knows the truth from the fake store, not
 * from the machine's own fields.
 *
 * A change from another device comes after the echo window when no load runs. The
 * window drops such a change inside it, and the panel accepts that.
 */

function makeWorld() {
  return {
    server: 0,
    ha: 0,
    screen: 0,
    reading: null,
    busy: false,
    now: T,
    loads: 0,
    m: INITIAL_REFRESH,
  };
}

function startLoad(w) {
  w.m = refreshStep(w.m, { type: 'start', sig: `v${w.ha}` });
  w.reading = w.server;
  w.loads++;
}

function maybeLoad(w) {
  if (shouldLoad(w.m, w.busy, w.now)) startLoad(w);
}

function push(w) {
  w.m = refreshStep(w.m, { type: 'signal', sig: `v${w.ha}`, busy: w.busy, now: w.now });
  maybeLoad(w);
}

function finish(w, ok) {
  if (ok) w.screen = w.reading;
  w.reading = null;
  w.m = refreshStep(w.m, { type: 'done', ok, now: w.now, echoMs: ECHO_MS });
  maybeLoad(w);
}

const idle = (w) => w.reading === null;

class Refresh {
  check(w) {
    return idle(w);
  }
  run(w) {
    startLoad(w);
  }
  toString() {
    return 'Refresh';
  }
}

class LoadEnds {
  constructor(ok) {
    this.ok = ok;
  }
  check(w) {
    return !idle(w);
  }
  run(w) {
    w.now += 50;
    finish(w, this.ok);
  }
  toString() {
    return this.ok ? 'LoadOk' : 'LoadFail';
  }
}

class OtherDevice {
  check() {
    return true;
  }
  run(w) {
    w.server++;
    w.ha = w.server;
    w.now += idle(w) ? ECHO_MS + 1 : 1;
    push(w);
  }
  toString() {
    return 'OtherDevice';
  }
}

/** The panel's own action: it writes, then it loads. Its echo comes later. */
class OwnWrite {
  check(w) {
    return idle(w);
  }
  run(w) {
    w.server++;
    startLoad(w);
  }
  toString() {
    return 'OwnWrite';
  }
}

class Echo {
  check(w) {
    return w.ha < w.server;
  }
  run(w) {
    w.ha = w.server;
    w.now += 1;
    push(w);
  }
  toString() {
    return 'Echo';
  }
}

class Busy {
  constructor(busy) {
    this.busy = busy;
  }
  check() {
    return true;
  }
  run(w) {
    w.busy = this.busy;
  }
  toString() {
    return `Busy(${this.busy})`;
  }
}

/** Time passes, and Home Assistant pushes a state that is not ours. */
class Wait {
  constructor(ms) {
    this.ms = ms;
  }
  check() {
    return true;
  }
  run(w) {
    w.now += this.ms;
    push(w);
  }
  toString() {
    return `Wait(${this.ms})`;
  }
}

const commands = [
  fc.constant(new Refresh()),
  fc.boolean().map((ok) => new LoadEnds(ok)),
  fc.constant(new OtherDevice()),
  fc.constant(new OwnWrite()),
  fc.constant(new Echo()),
  fc.boolean().map((b) => new Busy(b)),
  fc.integer({ min: 0, max: 15_000 }).map((ms) => new Wait(ms)),
];

/** The user goes idle, all waits end, and each load succeeds. */
function settle(w) {
  w.busy = false;
  w.now += LOAD_RETRY_MS + ECHO_MS;
  w.ha = w.server;
  push(w);
  for (let i = 0; i < 5 && !idle(w); i++) finish(w, true);
}

describe('refresh machine model', () => {
  it('after any sequence, a pending change is always followed by a load', () => {
    fc.assert(
      fc.property(fc.commands(commands, { maxCommands: 40 }), (cmds) => {
        const w = makeWorld();
        fc.modelRun(() => ({ model: w, real: w }), cmds);
        // At most 1 load runs, and the machine agrees with the driver.
        expect(w.m.loading === null).toBe(idle(w));
        const before = w.loads;
        settle(w);
        expect(idle(w), 'the loads should end').toBe(true);
        expect(w.screen, 'the screen should show the newest data').toBe(w.server);
        // Settling starts at most 2 loads: the pending one and 1 for a change during it.
        expect(w.loads - before).toBeLessThanOrEqual(2);
      }),
    );
  });

  it('starts no load while the user is busy', () => {
    fc.assert(
      fc.property(fc.commands(commands, { maxCommands: 40 }), (cmds) => {
        const w = makeWorld();
        fc.modelRun(() => ({ model: w, real: w }), cmds);
        // A change from another device while a form is open waits for the user.
        w.busy = true;
        if (!idle(w)) finish(w, true);
        const before = w.loads;
        new OtherDevice().run(w);
        new Wait(LOAD_RETRY_MS).run(w);
        expect(w.loads).toBe(before);
        expect(shouldLoad(w.m, false, w.now)).toBe(true);
      }),
    );
  });
});
