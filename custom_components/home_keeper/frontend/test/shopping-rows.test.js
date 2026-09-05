import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, mountPanel, waitFor } from './panel-harness.js';

/**
 * How an auto-created "Buy {part}" reminder reads in the panel's task list.
 *
 * A buy reminder is minted as a one-off with no due date, and a dateless one-off is
 * due *now* — so it has always been technically overdue, from the moment a part goes
 * low until it is restocked. That put it in the Overdue section with a red "Overdue
 * by 3 days" chip, beside maintenance that really was late (#220). It now gets its
 * own Shopping section and says what is actually true: low stock.
 *
 * What must *not* change is any count. The reminder is still overdue to the filter
 * pills, the per-task binary sensors and every saved Profile, so the panel never
 * disagrees with the rest of Home Assistant about how much is outstanding.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
  localStorage.clear();
});

const THREE_DAYS_AGO = new Date(Date.now() - 3 * 86_400_000).toISOString();

function buyTask(overrides = {}) {
  return {
    id: 'buy1',
    name: 'Buy Anode rod',
    recurrence_type: 'one-off',
    next_due: THREE_DAYS_AGO,
    enabled: true,
    completions: [],
    source: { buy: { asset_id: 'a1', part_id: 'p1' } },
    ...overrides,
  };
}

function lateTask(overrides = {}) {
  return {
    id: 'late1',
    name: 'Clean gutters',
    recurrence_type: 'interval',
    interval: 6,
    unit: 'months',
    next_due: THREE_DAYS_AGO,
    enabled: true,
    completions: [],
    ...overrides,
  };
}

/** Every rendered task row, keyed by task id. */
async function rows(panel) {
  await waitFor(() => panel.shadowRoot?.querySelector('ha-card.hk-card[data-id]'));
  const found = {};
  for (const card of panel.shadowRoot.querySelectorAll('ha-card.hk-card[data-id]')) {
    found[card.getAttribute('data-id')] = card;
  }
  return found;
}

describe('a buy reminder in the task list', () => {
  it('reads as low stock, not as overdue work', async () => {
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    const found = await rows(panel);

    const buy = found.buy1;
    expect(buy, 'the buy reminder should render').toBeTruthy();
    // No danger rail: that treatment belongs to work that is actually behind.
    expect(buy.classList.contains('overdue')).toBe(false);
    const buyChip = buy.querySelector('.hk-status ha-assist-chip');
    expect(buyChip.getAttribute('label')).toBe('Low stock');
    expect(buyChip.classList.contains('hk-shopping')).toBe(true);
    expect(buyChip.classList.contains('hk-overdue')).toBe(false);

    // The genuinely late task is untouched — it keeps the rail and the red chip,
    // which is the contrast the whole change exists to draw.
    const late = found.late1;
    expect(late.classList.contains('overdue')).toBe(true);
    const lateChip = late.querySelector('.hk-status ha-assist-chip');
    expect(lateChip.classList.contains('hk-overdue')).toBe(true);
    expect(lateChip.getAttribute('label')).toMatch(/3 days/);
  });

  it('sits under its own Shopping heading, not under Overdue', async () => {
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    await waitFor(() => panel.shadowRoot?.querySelector('details.hk-group'));

    const sections = {};
    for (const group of panel.shadowRoot.querySelectorAll('details.hk-group')) {
      const ids = [...group.querySelectorAll('ha-card.hk-card[data-id]')].map((c) =>
        c.getAttribute('data-id'),
      );
      sections[group.getAttribute('data-bucket')] = ids;
    }
    expect(sections.shopping).toEqual(['buy1']);
    expect(sections.overdue).toEqual(['late1']);
  });

  it('is counted by the Shopping pill, not the Overdue one', async () => {
    // The pill is the panel's word for late work, and a buy reminder is not late work
    // — it is overdue only by the clock. Counting it here put "Overdue 2" above a list
    // whose own headings read Overdue 1 and Shopping 1, and clicking the pill drew a
    // Shopping section under a heading that says Overdue. Shopping has its own pill
    // right beside this one, so nothing goes unseen by leaving it out of this one.
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-seg[data-seg="filter"]'));
    const count = (val) =>
      panel.shadowRoot
        .querySelector(`.hk-seg[data-seg="filter"] .hk-seg-btn[data-seg-val="${val}"] .hk-seg-count`)
        .textContent.trim();
    expect(count('overdue')).toBe('1');
    expect(count('shopping')).toBe('1');
    // All still counts both — it is the one pill that promises everything.
    expect(count('all')).toBe('2');
  });

  it('is not listed when the Overdue pill is chosen', async () => {
    // The count and the list come from one predicate, so this is what the count means.
    localStorage.setItem('home-keeper.filter', 'overdue');
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    const found = await rows(panel);
    expect(Object.keys(found)).toEqual(['late1']);
  });
});

describe('a buy reminder away from the task list', () => {
  /** Boot straight onto a task's detail page. `mountPanel` waits for the list's Add
   *  button, which a detail page does not have. */
  async function openTask(id, hass) {
    const panel = document.createElement('home-keeper-panel');
    panel.route = { prefix: '/home-keeper', path: `/tasks/${id}` };
    document.body.appendChild(panel);
    panel.hass = hass;
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-detail-actions'));
    return panel;
  }

  it('reads as low stock on its own detail page', async () => {
    // The list row and the card row were taught to say "Low stock"; the detail page
    // was not, so opening the very same reminder turned it back into red "Overdue".
    // One task cannot have two statuses depending on where it is looked at.
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const panel = await openTask('buy1', hass);

    const chip = panel.shadowRoot.querySelector('.hk-chips ha-assist-chip');
    expect(chip.getAttribute('label')).toBe('Low stock');
    expect(chip.classList.contains('hk-shopping')).toBe(true);
    expect(chip.classList.contains('hk-overdue')).toBe(false);
  });

  it('keeps Overdue on a genuinely late task’s detail page', async () => {
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const panel = await openTask('late1', hass);

    const chip = panel.shadowRoot.querySelector('.hk-chips ha-assist-chip');
    expect(chip.getAttribute('label')).toBe('Overdue');
    expect(chip.classList.contains('hk-overdue')).toBe(true);
  });

  it('reads as low stock in an appliance’s related tasks', async () => {
    // The worst of the two misses: this list sits directly beneath the parts panel
    // that already says the part is low, so it read "Low stock: 1" and "Overdue"
    // about the same part, inches apart.
    const asset = {
      id: 'a1',
      name: 'Garage water heater',
      device_id: 'dev-wh',
      parts: [{ id: 'p1', name: 'Anode rod', stock: 1, reorder_at: 3 }],
    };
    const hass = makeHass({
      tasks: [buyTask({ device_id: 'dev-wh' }), lateTask({ device_id: 'dev-wh' })],
      assets: [asset],
    });
    const { panel } = await mountPanel('/appliances/a1/tasks', hass);
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-rel'));

    const byId = {};
    for (const row of panel.shadowRoot.querySelectorAll('.hk-rel')) {
      byId[row.getAttribute('data-detail-id')] = row.querySelector('ha-assist-chip');
    }
    expect(byId.buy1.getAttribute('label')).toBe('Low stock');
    expect(byId.buy1.classList.contains('hk-shopping')).toBe(true);
    expect(byId.late1.getAttribute('label')).toBe('Overdue');
    expect(byId.late1.classList.contains('hk-overdue')).toBe(true);
  });
});

describe('the remembered filter', () => {
  it('restores a Shopping selection across a reload', async () => {
    // _setFilter has always written this; only the reader was missing 'shopping',
    // so the pill silently reset to All on every reload.
    localStorage.setItem('home-keeper.filter', 'shopping');
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-seg[data-seg="filter"]'));

    const active = panel.shadowRoot.querySelector(
      '.hk-seg[data-seg="filter"] .hk-seg-btn[aria-pressed="true"]',
    );
    expect(active.getAttribute('data-seg-val')).toBe('shopping');
    const found = await rows(panel);
    expect(Object.keys(found)).toEqual(['buy1']);
  });

  it('still ignores a value that is not a filter at all', async () => {
    localStorage.setItem('home-keeper.filter', 'not-a-filter');
    const hass = makeHass({ tasks: [buyTask(), lateTask()] });
    const { panel } = await mountPanel('/', hass);
    await waitFor(() => panel.shadowRoot?.querySelector('.hk-seg[data-seg="filter"]'));
    const active = panel.shadowRoot.querySelector(
      '.hk-seg[data-seg="filter"] .hk-seg-btn[aria-pressed="true"]',
    );
    expect(active.getAttribute('data-seg-val')).toBe('all');
  });
});
