import type { Hass, Task } from './types';

/** Thin wrappers around the Home Keeper websocket commands. */

export async function getTasks(hass: Hass): Promise<Task[]> {
  const res = await hass.callWS<{ tasks: Task[] }>({ type: 'home_keeper/get_tasks' });
  return res.tasks;
}

export async function addTask(hass: Hass, task: Partial<Task>): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/add_task',
    task,
  });
  return res.task;
}

export async function updateTask(
  hass: Hass,
  taskId: string,
  updates: Partial<Task>,
): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/update_task',
    task_id: taskId,
    updates,
  });
  return res.task;
}

export async function deleteTask(hass: Hass, taskId: string): Promise<void> {
  await hass.callWS({ type: 'home_keeper/delete_task', task_id: taskId });
}

export async function completeTask(hass: Hass, taskId: string): Promise<Task> {
  const res = await hass.callWS<{ task: Task }>({
    type: 'home_keeper/complete_task',
    task_id: taskId,
  });
  return res.task;
}
