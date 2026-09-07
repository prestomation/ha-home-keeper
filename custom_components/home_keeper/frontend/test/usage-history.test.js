import { beforeAll, afterEach, describe, expect, it } from 'vitest';
import { definePanelStubs, makeHass, waitFor } from './panel-harness.js';

/**
 * The usage between completions, in a metered task's history (issue #305).
 *
 * The readings were already logged and already shown; what was missing was the
 * subtraction. Each row now carries the usage since the completion before it, and the
 * list opens with the last interval, the average and the range.
 *
 * Asserted at the DOM rather than only through `usageIntervalStats`, because the two
 * ways this goes wrong are both in the wiring: a row reading someone else's interval,
 * and the strip appearing on a task whose readings are not a meter. Nothing asserted on
 * `.hk-hist-chips` at all before this file, so the reading itself is covered here too.
 */
beforeAll(() => {
  definePanelStubs();
});

afterEach(() => {
  document.querySelectorAll('home-keeper-panel').forEach((el) => el.remove());
});

const ODOMETER = 'sensor.car_odometer';

/** Four oil changes: 120,000 -> 134,800 -> 150,200 -> 163,900 km. */
const COMPLETIONS = [
  { ts: '2023-03-12T09:00:00Z', reading: 120000 },
  { ts: '2024-02-04T09:00:00Z', reading: 134800 },
  { ts: '2024-11-19T09:00:00Z', reading: 150200 },
  { ts: '2025-08-28T09:00:00Z', reading: 163900 },
];

function meterTask(overrides = {}) {
  return {
    id: 'oil1',
    name: 'Oil change',
    recurrence_type: 'sensor',
    enabled: true,
    sensor: {
      entity_id: ODOMETER,
      mode: 'usage',
      target: 15000,
      baseline: 163900,
      unit: 'km',
    },
    completions: COMPLETIONS,
    ...overrides,
  };
}

/** Mount *task*'s history tab and hand back its shadow root. */
async function history(task) {
  const hass = makeHass({ tasks: [task] });
  hass.states = { [ODOMETER]: { state: '170000', attributes: {} } };
  const panel = document.createElement('home-keeper-panel');
  panel.route = { prefix: '/home-keeper', path: `/tasks/${task.id}/history` };
  document.body.appendChild(panel);
  panel.hass = hass;
  await waitFor(() => panel.shadowRoot?.querySelector('.hk-hist-body'));
  return panel.shadowRoot;
}

/** The `Last / Average / …` figures, as `[label, value]` pairs. */
function stripFigures(root) {
  return [...root.querySelectorAll('.hk-hist-usage > div')].map((cell) => [
    cell.querySelector('.hk-eyebrow').textContent,
    cell.querySelector('.v').textContent,
  ]);
}

describe('history — the usage between completions', () => {
  it('gives every row but the oldest its own interval', async () => {
    const root = await history(meterTask());
    const rows = [...root.querySelectorAll('.hk-hist-list li')];
    expect(rows).toHaveLength(4);
    // Newest first, so the deltas count down the list the readings count down.
    expect(rows[0].querySelector('.hk-hist-delta').textContent).toBe('+13,700 km');
    expect(rows[1].querySelector('.hk-hist-delta').textContent).toBe('+15,400 km');
    expect(rows[2].querySelector('.hk-hist-delta').textContent).toBe('+14,800 km');
    // The oldest completion has nothing before it to subtract.
    expect(rows[3].querySelector('.hk-hist-delta')).toBeNull();
  });

  it('shows the delta beside the reading it is derived from', async () => {
    const root = await history(meterTask());
    const chips = root.querySelector('.hk-hist-list li .hk-hist-chips').textContent;
    expect(chips).toContain('at 163,900 km');
    expect(chips).toContain('+13,700 km');
  });

  it('opens with the last interval, the average and the range', async () => {
    const root = await history(meterTask());
    expect(stripFigures(root)).toEqual([
      ['Last interval', '13,700 km'],
      ['Average interval', '14,633.3 km'],
      ['Shortest interval', '13,700 km'],
      ['Longest interval', '15,400 km'],
    ]);
  });

  it('shows the last interval alone when there is only one', async () => {
    // The average, the shortest and the longest of a single number are all that same
    // number, and printing it four times says less than printing it once.
    const root = await history(meterTask({ completions: COMPLETIONS.slice(2) }));
    expect(stripFigures(root)).toEqual([['Last interval', '13,700 km']]);
  });

  it('shows no strip until two completions carry a reading', async () => {
    const root = await history(meterTask({ completions: COMPLETIONS.slice(3) }));
    expect(root.querySelector('.hk-hist-usage')).toBeNull();
    expect(root.querySelector('.hk-hist-delta')).toBeNull();
    // The reading itself is still there — it always was.
    expect(root.querySelector('.hk-hist-chips').textContent).toContain('at 163,900 km');
  });

  it('leaves a threshold task alone', async () => {
    // A threshold task records a reading too, but that reading is a measurement
    // (airflow at 58%) and not a meter that only climbs, so the difference between two
    // of them is not usage.
    const root = await history(
      meterTask({
        sensor: { entity_id: ODOMETER, mode: 'threshold', comparison: 'lt', value: 60 },
        completions: [
          { ts: '2024-02-04T09:00:00Z', reading: 58 },
          { ts: '2025-08-28T09:00:00Z', reading: 55 },
        ],
      }),
    );
    expect(root.querySelector('.hk-hist-usage')).toBeNull();
    expect(root.querySelector('.hk-hist-delta')).toBeNull();
  });

  it('leaves a time-based task alone', async () => {
    const root = await history({
      id: 'oil1',
      name: 'Change water filter',
      recurrence_type: 'floating',
      interval: 6,
      unit: 'months',
      completions: [{ ts: '2024-02-04T09:00:00Z' }, { ts: '2025-08-28T09:00:00Z' }],
    });
    expect(root.querySelector('.hk-hist-usage')).toBeNull();
    expect(root.querySelector('.hk-hist-delta')).toBeNull();
  });

  it('never reports an interval on a skip', async () => {
    // A skip resets the meter, but it records work that was not done: the interval it
    // sits inside is one service interval, and it belongs to the completion that ends
    // it, not to the skip.
    const root = await history(
      meterTask({
        completions: COMPLETIONS.slice(2),
        skips: [{ ts: '2025-02-01T09:00:00Z', reading: 155000 }],
      }),
    );
    const skip = root.querySelector('.hk-hist-list li.hk-hist-is-skip');
    expect(skip).toBeTruthy();
    expect(skip.querySelector('.hk-hist-delta')).toBeNull();
    // …and the completion after it still measures the whole interval.
    expect(stripFigures(root)).toEqual([['Last interval', '13,700 km']]);
  });

  it('drops the interval a meter reset leaves behind', async () => {
    const root = await history(
      meterTask({
        completions: [
          { ts: '2024-02-04T09:00:00Z', reading: 134800 },
          { ts: '2024-11-19T09:00:00Z', reading: 200 },
          { ts: '2025-08-28T09:00:00Z', reading: 14000 },
        ],
      }),
    );
    const rows = [...root.querySelectorAll('.hk-hist-list li')];
    expect(rows[0].querySelector('.hk-hist-delta').textContent).toBe('+13,800 km');
    // The reading dropped, so there is no usage figure between these two.
    expect(rows[1].querySelector('.hk-hist-delta')).toBeNull();
    expect(stripFigures(root)).toEqual([['Last interval', '13,800 km']]);
  });
});
