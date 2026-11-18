import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * The Appliances list beside an open appliance keeps its scroll position (#586).
 *
 * A press on a row navigates by URL. The panel then builds a new tree, and the new
 * `.hk-master` pane starts at scrollTop 0. jsdom has no layout, so these tests give the
 * pane a model of its own: a scrollTop that sticks, a 300px window, and rows that are
 * 100px high. The model reads `scrollTop` for each row, as a real layout does.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const ROW = 100;
const WINDOW = 300;
const ASSETS = Array.from({ length: 12 }, (_, i) => ({
  id: `a${i}`,
  name: `Appliance ${String(i).padStart(2, '0')}`,
  kind: 'virtual',
  parts: [],
  metadata: [],
}));

// jsdom keeps no scroll state, so a pane remembers the value that was set on it.
const tops = new WeakMap();
function installScrollModel() {
  const proto = HTMLElement.prototype;
  const saved = {
    top: Object.getOwnPropertyDescriptor(proto, 'scrollTop') ?? Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop'),
    rect: proto.getBoundingClientRect,
  };
  const isPane = (el) => el.classList?.contains('hk-master');
  Object.defineProperty(proto, 'scrollTop', {
    configurable: true,
    get() {
      return tops.get(this) ?? 0;
    },
    set(v) {
      tops.set(this, Math.max(0, Math.min(v, ASSETS.length * ROW - WINDOW)));
    },
  });
  proto.getBoundingClientRect = function () {
    const rect = (top, height) => ({ top, height, bottom: top + height, left: 0, right: 0, width: 0, x: 0, y: top });
    if (isPane(this)) return rect(0, WINDOW);
    const pane = this.closest?.('.hk-master');
    if (pane && this.matches('ha-card.hk-card')) {
      const index = [...pane.querySelectorAll('ha-card.hk-card')].indexOf(this);
      return rect(index * ROW - (tops.get(pane) ?? 0), ROW);
    }
    return rect(0, 0);
  };
  Object.defineProperty(proto, 'clientHeight', {
    configurable: true,
    get() {
      return isPane(this) ? WINDOW : 0;
    },
  });
  return () => {
    if (saved.top) Object.defineProperty(proto, 'scrollTop', saved.top);
    else delete proto.scrollTop;
    proto.getBoundingClientRect = saved.rect;
    delete proto.clientHeight;
  };
}

async function mountAt(path) {
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path };
  document.body.appendChild(panel);
  panel.hass = makeHass({ assets: ASSETS });
  const pane = await waitFor(() => panel.shadowRoot?.querySelector('.hk-master ha-card.hk-card'));
  expect(pane, `${path} should draw the list beside the appliance`).toBeTruthy();
  return panel;
}

// The pane is put back on the next frame, so a test waits for frames before it reads.
const frames = async (n = 4) => {
  for (let i = 0; i < n; i++) await new Promise((r) => requestAnimationFrame(r));
};

const master = (panel) => panel.shadowRoot.querySelector('.hk-master');

describe('Appliance list scroll', () => {
  it('keeps the scroll position when another appliance opens', async () => {
    const restore = installScrollModel();
    try {
      const panel = await mountAt('/appliances/a0');
      master(panel).scrollTop = 800;
      panel.route = { prefix: '/home-keeper', path: '/appliances/a9' };
      const open = await waitFor(() => panel.shadowRoot.querySelector('.hk-master .hk-selected')?.dataset.id === 'a9');
      expect(open, 'the pane should mark a9 as open').toBe(true);
      await frames();
      expect(master(panel).scrollTop).toBe(800);
    } finally {
      restore();
    }
  });

  it('scrolls the open appliance into view when it is outside the pane', async () => {
    const restore = installScrollModel();
    try {
      const panel = await mountAt('/appliances/a0');
      master(panel).scrollTop = 0;
      // a9 sits at 900px. The window shows 0 to 300px, so a9 is out of sight.
      panel.route = { prefix: '/home-keeper', path: '/appliances/a9' };
      await waitFor(() => panel.shadowRoot.querySelector('.hk-master .hk-selected')?.dataset.id === 'a9');
      // The row ends at 1000px, so the window must end there: it starts at 700px.
      await frames();
      expect(master(panel).scrollTop).toBe(ROW * 10 - WINDOW);
    } finally {
      restore();
    }
  });

  it('does not move a pane whose open appliance is already in view', async () => {
    const restore = installScrollModel();
    try {
      const panel = await mountAt('/appliances/a0');
      master(panel).scrollTop = 600;
      // a7 sits at 700px, and the window shows 600 to 900px.
      panel.route = { prefix: '/home-keeper', path: '/appliances/a7' };
      await waitFor(() => panel.shadowRoot.querySelector('.hk-master .hk-selected')?.dataset.id === 'a7');
      await frames();
      expect(master(panel).scrollTop).toBe(600);
    } finally {
      restore();
    }
  });

  it('scrolls up to an open appliance that sits above the window', async () => {
    const restore = installScrollModel();
    try {
      const panel = await mountAt('/appliances/a9');
      master(panel).scrollTop = 800;
      panel.route = { prefix: '/home-keeper', path: '/appliances/a1' };
      await waitFor(() => panel.shadowRoot.querySelector('.hk-master .hk-selected')?.dataset.id === 'a1');
      // a1 sits at 100px, above the window that starts at 800px.
      await frames();
      expect(master(panel).scrollTop).toBe(ROW);
    } finally {
      restore();
    }
  });
});
