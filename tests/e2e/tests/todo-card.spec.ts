import { test, expect } from '@playwright/test';
import {
  callService,
  createTask,
  deleteTask,
  expectAbsentFromActiveSurfaces,
  expectOnTodoList,
  listTasks,
  openTodoCard,
  todoSummaries,
  TODO_ENTITY,
} from './helpers';

/**
 * E2E coverage for the **native to-do card** — the surface users actually complete
 * tasks from, and the one `todo.py` projects onto.
 *
 * Everything else in this suite drives the panel. The panel is the admin surface
 * and was never wrong about a completed one-off; the to-do list was (#221), and
 * nothing here looked. `async_update_todo_item` in particular had no browser
 * coverage at all: checking an item off in the card is the code path a user takes,
 * and it was only ever exercised indirectly.
 */
test.describe('Home Keeper — native to-do card', () => {
  let created: string[] = [];

  test.afterEach(async () => {
    await Promise.all(created.map(deleteTask));
    created = [];
  });

  test('lists active tasks and omits every dormant one', async ({ page }) => {
    const card = await openTodoCard(page);
    // An upcoming one-off and an overdue recurring task are both actionable.
    await expect(card).toContainText('Renew passport');
    await expect(card).toContainText('Replace water filter');
    // Dormant tasks are not: a completed one-off (#221) and the seeded
    // triggered/sensor tasks that nobody has armed.
    await expect(card).not.toContainText('Renew car registration');
    await expect(card).not.toContainText('Replace battery: Hallway smoke alarm');
  });

  test('checking a recurring task off in the card completes it and re-dates it', async ({
    page,
  }) => {
    const NAME = 'E2E todo-card probe';
    created.push(
      await createTask({
        name: NAME,
        recurrence_type: 'floating',
        interval: 1,
        unit: 'months',
      }),
    );
    await expectOnTodoList(page, NAME);

    // Check it off through the entity the card drives (the card's own checkbox is
    // a shadow-DOM ha-check-list-item; todo.update_item is the same call it makes).
    await callService('todo', 'update_item', {
      entity_id: TODO_ENTITY,
      item: NAME,
      status: 'completed',
    });

    // A recurring task doesn't disappear — it advances and comes back needs_action
    // with a later due date. That distinction is the whole point of the dormancy
    // rule: the skip keys on "dormant", not on "has been completed".
    await expect.poll(async () => (await listTasks()).find((t) => t.name === NAME)?.completions?.length, {
      timeout: 20_000,
    }).toBe(1);
    const task = (await listTasks()).find((t) => t.name === NAME);
    expect(task!.next_due, 'a completed floating task re-arms').toBeTruthy();
    expect(await todoSummaries()).toContain(NAME);
  });

  test('checking a one-off off in the card retires it from the list', async ({ page }) => {
    const NAME = 'E2E todo-card one-off probe';
    created.push(
      await createTask({
        name: NAME,
        recurrence_type: 'one-off',
        due: '2026-07-15T09:00:00-04:00',
      }),
    );
    await expectOnTodoList(page, NAME);

    await callService('todo', 'update_item', {
      entity_id: TODO_ENTITY,
      item: NAME,
      status: 'completed',
    });

    await expectAbsentFromActiveSurfaces(page, NAME);
    const task = (await listTasks()).find((t) => t.name === NAME);
    expect(task!.next_due, 'a completed one-off goes dormant').toBeNull();
    expect(task!.completions).toHaveLength(1);
  });

  test('a completed one-off cannot be checked off twice', async ({ page }) => {
    // The reporter's other symptom: re-completing the stale item appended a second
    // entry to the history of work done exactly once. The item is now off the list,
    // so HA can't resolve it by name — and the entity guards the direct call too.
    const NAME = 'E2E todo-card dup probe';
    const id = await createTask({
      name: NAME,
      recurrence_type: 'one-off',
      due: '2026-07-15T09:00:00-04:00',
    });
    created.push(id);
    await expectOnTodoList(page, NAME);

    await callService('todo', 'update_item', {
      entity_id: TODO_ENTITY,
      item: NAME,
      status: 'completed',
    });
    await expectAbsentFromActiveSurfaces(page, NAME);

    await expect(
      callService('todo', 'update_item', {
        entity_id: TODO_ENTITY,
        item: NAME,
        status: 'completed',
      }),
      'HA cannot resolve an item the entity no longer lists',
    ).rejects.toThrow();

    const task = (await listTasks()).find((t) => t.id === id);
    expect(task!.completions, 'work done once is recorded once').toHaveLength(1);
  });

  test('renaming an item in the card persists to the task', async ({ page }) => {
    // The entity declares UPDATE_TODO_ITEM, so a rename must actually stick rather
    // than silently revert on the next coordinator refresh.
    const NAME = 'E2E todo-card rename probe';
    const RENAMED = 'E2E todo-card renamed probe';
    const id = await createTask({ name: NAME, recurrence_type: 'floating', interval: 3, unit: 'months' });
    created.push(id);
    await expectOnTodoList(page, NAME);

    await callService('todo', 'update_item', {
      entity_id: TODO_ENTITY,
      item: NAME,
      rename: RENAMED,
    });

    await expect
      .poll(async () => (await listTasks()).find((t) => t.id === id)?.name, { timeout: 20_000 })
      .toBe(RENAMED);
    const card = await openTodoCard(page);
    await expect(card).toContainText(RENAMED);
  });
});
