/**
 * Keep the task list's rows when the list changes, instead of building them again.
 *
 * Building 1,000 rows costs seconds of main thread: the browser parses the markup,
 * upgrades every `ha-button`, lays out the rows, and later frees the old ones. A
 * search keystroke and a live refresh each used to do all of it for a list in which
 * most rows did not change.
 *
 * The patch keeps each row's element, keyed by the task id, with the markup it was
 * built from. A row whose new markup is the same text is kept as it is, with its
 * listeners. A row that changed is built again. A row that the list no longer shows
 * (a search that skips it) is parked, and comes back as it was when the search widens.
 * The result is the DOM that `tasksList` would draw, with fewer nodes touched.
 *
 * Only the layout "rows" is patched. The tiles and the board stay 1 string.
 */

import { wireDetailOpeners } from './panel-detail';
import { wireDeviceChips, wirePartChips } from './panel-chips';
import { groupIsOpen, groupShell } from './panel-controls';
import type { PanelHost } from './panel-host';
import { wireLists } from './panel-lists';
import type { ListGroup, TaskListModel } from './panel-lists';

interface Slot {
  el: HTMLElement;
  html: string;
}

interface ListState {
  /** The nodes of the head, and the markup that they came from. */
  headNodes: Node[];
  headHtml: string;
  /** The rows that the list shows, by task id. */
  rows: Map<string, Slot>;
  /** Rows that a search took out. They are not in the DOM. */
  parked: Map<string, Slot>;
  /** The group sections that the list shows, by group key. */
  groups: Map<string, HTMLDetailsElement>;
  /** The list got other content from a string (an empty result). Its rows wait in `parked`. */
  stale: boolean;
}

const STATE = new WeakMap<HTMLElement, ListState>();

/**
 * Call it before the list gets other content from a string, such as the message for an
 * empty result. The rows stay with the patch, so that the list comes back from the
 * message without a new draw of every row.
 */
export function suspendPatchedList(list: HTMLElement): void {
  const state = STATE.get(list);
  if (state) state.stale = true;
}

/** True if the list was built by `patchTasksList`, so that a patch can reuse its rows. */
export function isPatchedList(list: HTMLElement): boolean {
  return STATE.has(list);
}

/**
 * Move what a patched list holds to a new list element, rows and all.
 *
 * `_render` replaces the whole shadow tree. It takes the old list out first, and puts
 * it back where the new, empty list stands. Returns false if the old list holds
 * nothing to keep.
 */
export function adoptPatchedList(oldList: HTMLElement | null, placeholder: HTMLElement): boolean {
  if (!oldList || !STATE.has(oldList)) return false;
  placeholder.replaceWith(oldList);
  return true;
}

function parse(html: string): DocumentFragment {
  const template = document.createElement('template');
  template.innerHTML = html;
  return template.content;
}

/** Wire the nodes that are new. The nodes that stay keep the listeners that they have. */
function wireNew(p: PanelHost, fragment: DocumentFragment): void {
  wireLists(p, fragment);
  wireDetailOpeners(p, fragment);
  wireDeviceChips(p, fragment);
  wirePartChips(p, fragment);
}

/**
 * Put `wanted` in order under `parent`, starting at `first`. An element that is in place
 * stays. An element that is not wanted goes. Nothing else under `parent` changes.
 */
function arrange(parent: Element, first: Element | null, wanted: Element[]): void {
  const keep = new Set<Element>(wanted);
  let cur = first;
  for (const el of wanted) {
    // An element that is not wanted goes at once. If it stayed, each wanted element
    // after it would move in front of it, instead of that 1 element leaving.
    // Stryker disable next-line all: an unwanted element then leaves at the end, and only the number of moves differs
    while (cur && !keep.has(cur)) {
      const next: Element | null = cur.nextElementSibling;
      cur.remove();
      cur = next;
    }
    if (el === cur) cur = cur.nextElementSibling;
    else parent.insertBefore(el, cur);
  }
  while (cur) {
    const next: Element | null = cur.nextElementSibling;
    // Stryker disable next-line all: every element left here is unwanted, so the check never decides
    if (!keep.has(cur)) cur.remove();
    cur = next;
  }
}

/**
 * Bring `list` to the state that `model` describes.
 *
 * Returns false, with the list unchanged, when the markup does not have the shape the
 * patch relies on (1 element for each row). The caller then draws the list from a
 * string.
 */
export function patchTasksList(p: PanelHost, list: HTMLElement, model: TaskListModel): boolean {
  let state = STATE.get(list);
  const fresh = !state || state.stale;
  const old: Map<string, Slot> = new Map([...(state?.parked ?? []), ...(state?.rows ?? [])]);

  // Which rows are new, or changed? Parse them in 1 pass, before anything moves.
  const build: { id: string; html: string }[] = [];
  const keep = new Map<string, Slot>();
  for (const g of model.groups) {
    for (const row of g.rows) {
      const had = old.get(row.id);
      if (had && had.html === row.html) keep.set(row.id, had);
      else build.push(row);
    }
  }
  // Stryker disable next-line all: an empty join and a join of text give the same elements
  const rowFragment = parse(build.map((r) => r.html).join(''));
  const built = Array.from(rowFragment.children) as HTMLElement[];
  // Stryker disable next-line all: a guard for markup that taskCard never gives (1 root element a row)
  if (built.length !== build.length) return false;
  wireNew(p, rowFragment);
  built.forEach((el, i) => keep.set(build[i].id, { el, html: build[i].html }));

  if (!state) {
    list.replaceChildren();
    state = {
// Stryker disable next-line all: the head code overwrites both values before they are read
      headNodes: [],
// Stryker disable next-line all: the head code overwrites both values before they are read
      headHtml: '',
      rows: new Map(),
      parked: new Map(),
      groups: new Map(),
// Stryker disable next-line all: a new state is never read as stale before the first patch ends
      stale: false,
    };
    STATE.set(list, state);
  } else if (state.stale) {
    // The content is not the one that the state describes. Start from an empty list,
    // and keep the rows that it had.
    list.replaceChildren();
    state.headNodes = [];
    state.headHtml = '';
    state.groups.clear();
    state.stale = false;
  }

  // The head.
  if (fresh || model.head !== state.headHtml) {
    // Stryker disable next-line all: a node that is already out of the list has no parent, and removal is then a no-op
    for (const node of state.headNodes) node.parentNode?.removeChild(node);
    const head = parse(model.head);
    wireNew(p, head);
    state.headNodes = Array.from(head.childNodes);
    state.headHtml = model.head;
    list.prepend(head);
  }
  // Stryker disable next-line all: a text node in the head is never the last element, so the filter only skips white space
  const headEls = state.headNodes.filter((n): n is Element => n.nodeType === 1);
  const afterHead = (): Element | null =>
    headEls.length ? headEls[headEls.length - 1].nextElementSibling : list.firstElementChild;

  const flat = model.groups.length === 1 && !model.groups[0].label;
  if (flat) {
    arrange(
      list,
      afterHead(),
      model.groups[0].rows.map((r) => keep.get(r.id)!.el),
    );
    // Stryker disable next-line all: the map is only a cache of sections, and a stale entry is replaced on its next use
    state.groups.clear();
  } else {
    // The rows move into their sections first, and then the sections are put in order.
    const sections = model.groups.map((g) => syncGroup(p, state!, g, keep));
    arrange(list, afterHead(), sections);
    // Stryker disable next-line all: the map is only a cache of sections, and a stale entry is replaced on its next use
    for (const key of [...state.groups.keys()]) {
      if (!model.groups.some((g) => g.key === key)) state.groups.delete(key);
    }
  }

  // Rows that left the list wait in `parked`, unless the task is gone.
  const live = new Set(p._tasks.map((task) => task.id));
  const parked = new Map<string, Slot>();
  for (const [id, slot] of old) {
    // Stryker disable next-line all: a parked row that is also shown is replaced by the shown row on the next patch
    if (!keep.has(id) && live.has(id)) parked.set(id, slot);
  }
  state.rows = keep;
  state.parked = parked;
  return true;
}

/** The section element of one group, with its heading and its rows in order. */
function syncGroup(
  p: PanelHost,
  state: ListState,
  g: ListGroup,
  rows: Map<string, Slot>,
): HTMLDetailsElement {
  let section = state.groups.get(g.key);
  if (!section) {
    const fragment = parse(groupShell(p, g, g.rows.length, ''));
    wireNew(p, fragment);
    section = fragment.querySelector('details.hk-group') as HTMLDetailsElement;
    state.groups.set(g.key, section);
  }
  const title = section.querySelector('.hk-group-title');
  // Stryker disable next-line all: the guard avoids a write of equal text, so the DOM is the same without it
  if (title && title.textContent !== g.label) title.textContent = g.label;
  const count = section.querySelector('.hk-group-count');
  // Stryker disable next-line all: the guard avoids a write of equal text, so the DOM is the same without it
  if (count && count.textContent !== String(g.rows.length)) count.textContent = String(g.rows.length);
  const open = groupIsOpen(p, g.key);
  // Stryker disable next-line all: the guard avoids a write of an equal value, so the DOM is the same without it
  if (section.open !== open) section.open = open;
  const body = section.querySelector('.hk-group-body') as HTMLElement;
  arrange(
    body,
    body.firstElementChild,
    g.rows.map((r) => rows.get(r.id)!.el),
  );
  return section;
}
