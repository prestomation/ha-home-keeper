import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  expectAbsentFromActiveSurfaces,
  expectOnTodoList,
  listTasks,
  todoSummaries,
} from './helpers';

/**
 * The dormancy contract, asserted once per recurrence type.
 *
 * `recurrence.apply_completion` sets `next_due = None` for `one-off`, `triggered`
 * and `sensor` alike — "all go dormant (every time surface drops them)" — while a
 * recurring task advances instead. Every surface has to agree about that, and
 * before #221 only some did: the to-do list carried the skip for `triggered` and
 * `sensor` but not `one-off`, so a finished do-once task sat there undated forever.
 *
 * That bug was one cell of this matrix. The others were untested by construction,
 * which is why this file walks all of them rather than re-testing the one that
 * broke.
 */

interface Case {
  kind: string;
  /** Fields for `home_keeper.add_task`. */
  fields: Record<string, unknown>;
  /** Is it armed (on the active surfaces) the moment it's created? */
  bornArmed: boolean;
  /** After a completion: dormant (off every surface) or re-armed? */
  dormantAfterCompletion: boolean;
}

const CASES: Case[] = [
  {
    kind: 'one-off',
    fields: { recurrence_type: 'one-off', due: '2026-07-15T09:00:00-04:00' },
    bornArmed: true,
    dormantAfterCompletion: true,
  },
  {
    kind: 'triggered',
    // Condition-driven and owned by another integration: born armed (due now),
    // and a completion clears the condition rather than rescheduling.
    fields: { recurrence_type: 'triggered' },
    bornArmed: true,
    dormantAfterCompletion: true,
  },
  {
    kind: 'floating',
    // The control: a recurring task is never dormant, it just moves.
    fields: { recurrence_type: 'floating', interval: 1, unit: 'months' },
    bornArmed: true,
    dormantAfterCompletion: false,
  },
];

test.describe('Home Keeper — dormancy across surfaces', () => {
  let created: string[] = [];

  test.afterEach(async () => {
    await Promise.all(created.map(deleteTask));
    created = [];
  });

  for (const c of CASES) {
    test(`a ${c.kind} task ${c.dormantAfterCompletion ? 'leaves' : 'stays on'} the active surfaces when completed`, async ({
      page,
    }) => {
      const NAME = `E2E dormancy ${c.kind} probe`;
      const id = await createTask({ name: NAME, ...c.fields });
      created.push(id);

      // Born armed -> on the to-do list before anything happens.
      expect(c.bornArmed, 'every case here starts armed').toBe(true);
      await expectOnTodoList(page, NAME);

      await callService('home_keeper', 'complete_task', { task_id: id });

      const task = () => listTasks().then((ts) => ts.find((t) => t.id === id)!);
      if (c.dormantAfterCompletion) {
        await expectAbsentFromActiveSurfaces(page, NAME);
        expect((await task()).next_due, `a completed ${c.kind} goes dormant`).toBeNull();
      } else {
        await expect
          .poll(async () => (await task()).next_due, { timeout: 20_000 })
          .not.toBeNull();
        expect(await todoSummaries(), `a completed ${c.kind} re-arms`).toContain(NAME);
      }
      expect((await task()).completions).toHaveLength(1);
    });
  }

  test('a sensor task is born dormant and appears on no active surface', async ({ page }) => {
    // Unlike the others, a sensor task starts dormant: the watcher arms it only
    // once the live reading meets its condition (models.build_task). So there is
    // no completion to make here — being absent from the outset is the contract.
    const NAME = 'E2E dormancy sensor probe';
    const id = await createTask({
      name: NAME,
      recurrence_type: 'sensor',
      // The container's seeded demo meter, so the watcher has a real reading to
      // baseline against (a fresh target it hasn't advanced past = still dormant).
      sensor: { entity_id: 'sensor.demo_printer_hours', mode: 'usage', target: 100_000 },
    });
    created.push(id);

    expect((await listTasks()).find((t) => t.id === id)!.next_due).toBeNull();
    await expectAbsentFromActiveSurfaces(page, NAME);
  });
});
