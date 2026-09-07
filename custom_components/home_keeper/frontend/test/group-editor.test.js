import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { emptyGroup } from '../src/card-filter.ts';
import { groupSummaryLine, openGroupIndex, renderGroupsEditor } from '../src/group-editor.ts';
import { setLanguage } from '../src/i18n.ts';

// The filter-groups editor, rendered by the Settings → Profiles rows and by the
// dashboard card's own editor. It owns four things nothing else can check: the DOM one
// group is drawn as, the add/delete rules that renumber it, which group a form event
// writes to, and which row is open. Everything about *matching* is
// `card-filter-profile.test.js`; everything about *saving* is `profile-groups.test.js`.
//
// The `ha-form` is a stand-in here on purpose. This suite is about the editor around
// the forms, so the fake records what it was given and hands back a way to emit.

beforeEach(() => setLanguage('en'));

afterEach(() => {
  document.body.innerHTML = '';
});

/** A stand-in `ha-form` that keeps its schema, data and change handler. */
function fakeForm(schema, data, onChange, labelling) {
  const el = document.createElement('ha-form');
  el.schema = schema;
  el.data = data;
  el.labelling = labelling;
  el.emit = (value) => onChange(value);
  return el;
}

const STRINGS = {
  title: (n) => `Group ${n}`,
  add: 'Add another group',
  remove: 'Delete group',
  or: 'OR',
  help: 'A task matches this group when…',
  empty: 'No filters yet',
  labelsAll: 'All selected labels',
  excludeShopping: 'Exclude shopping',
};

/** Render into a fresh host, collecting every list `onChange` reported. */
function mount(groups, over = {}) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const emitted = [];
  renderGroupsEditor(host, groups, {
    companions: [],
    makeForm: fakeForm,
    strings: STRINGS,
    onChange: (next) => emitted.push(next),
    ...over,
  });
  return { host, emitted, groups };
}

const cards = (host) => [...host.querySelectorAll('.hk-filter-group')];
const names = (host) =>
  [...host.querySelectorAll('.hk-filter-group-name')].map((el) => el.textContent);
const sums = (host) => [...host.querySelectorAll('.hk-filter-group-sum')].map((el) => el.textContent);
const formIn = (card) => card.querySelector('ha-form');
const addBtn = (host) => host.querySelector('.hk-filter-group-add');
const opens = (host) => cards(host).map((c) => c.open);
/** jsdom fires `toggle` on the next task, and a row that closes a sibling queues a
 *  second one behind it — so a change of `open` needs two turns to settle. */
const settle = async () => {
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
};

describe('renderGroupsEditor — one group', () => {
  it('draws the group as a details, with its heading, its help and its form', () => {
    const { host } = mount([emptyGroup()]);
    expect(cards(host)).toHaveLength(1);
    expect(cards(host)[0].tagName).toBe('DETAILS');
    expect(names(host)).toEqual(['Group 1']);
    expect(cards(host)[0].dataset.group).toBe('0');
    expect(cards(host)[0].querySelector('.hk-settings-intro').textContent).toBe(STRINGS.help);
    expect(formIn(cards(host)[0])).toBeTruthy();
  });

  it('heads the row with an icon, the name and a chevron, in that order', () => {
    // The same summary shape a part row carries, so the two accordions read alike.
    const { host } = mount([emptyGroup()]);
    const summary = cards(host)[0].querySelector('summary.hk-filter-group-head');
    expect(summary).toBeTruthy();
    expect([...summary.children].map((el) => el.className)).toEqual([
      'hk-filter-group-ic',
      'hk-filter-group-text',
      'hk-section-chevron',
    ]);
    // ha-svg-icon draws from `path`; an `icon` attribute would render nothing at all.
    expect(summary.querySelector('.hk-filter-group-ic').path).toBe(
      'M6,13H18V11H6M3,6V8H21V6M10,18H14V16H10V18Z',
    );
    expect(summary.querySelector('.hk-section-chevron').getAttribute('icon')).toBe(
      'mdi:chevron-down',
    );
  });

  it('opens a lone group, because there is nothing else it could be', () => {
    const { host } = mount([emptyGroup()]);
    expect(opens(host)).toEqual([true]);
  });

  it('offers no Delete on a lone group', () => {
    // A profile always has one group, and an empty one is how "everything" is
    // spelled — so there is nothing a delete here could mean.
    const { host } = mount([emptyGroup()]);
    expect(host.querySelector('.hk-filter-group-delete')).toBeNull();
  });

  it('draws no OR divider with nothing to join', () => {
    const { host } = mount([emptyGroup()]);
    expect(host.querySelector('.hk-filter-or')).toBeNull();
  });

  it('seeds the form from the group and labels its fields', () => {
    const { host } = mount([{ ...emptyGroup(), labels: ['dog'], labels_match: 'all' }]);
    const form = formIn(cards(host)[0]);
    expect(form.data.labels).toEqual(['dog']);
    expect(form.data.labels_match).toBe('all');
    // The name comes first, where the folded row reads it from.
    expect(form.schema[0].name).toBe('name');
    expect(form.schema.map((f) => f.name)).toContain('exclude_shopping');
    // `labels` is the shared task field; everything else is named under `notify.`.
    expect(form.labelling.computeLabel({ name: 'labels' })).toBe('Labels');
    expect(form.labelling.computeLabel({ name: 'exclude_areas' })).toBe('Exclude areas');
    // The group's own name, not the profile's — `field.name` is the profile's.
    expect(form.labelling.computeLabel({ name: 'name' })).toBe('Group name');
  });

  it('takes an English computeLabel from a caller that has no translations', () => {
    // The card editor is English-only, so it overrides rather than reaching into t().
    const { host } = mount([emptyGroup()], { computeLabel: (s) => `X:${s.name}` });
    expect(formIn(cards(host)[0]).labelling.computeLabel({ name: 'labels' })).toBe('X:labels');
  });
});

describe('renderGroupsEditor — the row heading', () => {
  it('heads a named group with its name instead of its number', () => {
    const { host } = mount([
      { ...emptyGroup(), name: 'The dog' },
      { ...emptyGroup(), name: 'The garage' },
    ]);
    expect(names(host)).toEqual(['The dog', 'The garage']);
  });

  it('falls back to Group N for a group with no name of its own', () => {
    const { host } = mount([{ ...emptyGroup(), name: 'The dog' }, emptyGroup()]);
    expect(names(host)).toEqual(['The dog', 'Group 2']);
  });

  it('repaints the heading as the name is typed, without rebuilding the row', () => {
    // Rebuilding on a keystroke would take the text box out from under the reader.
    const { host } = mount([emptyGroup(), emptyGroup()]);
    const before = formIn(cards(host)[1]);
    formIn(cards(host)[1]).emit({ ...emptyGroup(), name: 'The garage' });
    expect(names(host)).toEqual(['Group 1', 'The garage']);
    expect(formIn(cards(host)[1])).toBe(before);
    // Emptying it again brings the numbered fallback back.
    formIn(cards(host)[1]).emit({ ...emptyGroup(), name: '   ' });
    expect(names(host)).toEqual(['Group 1', 'Group 2']);
  });
});

describe('renderGroupsEditor — the summary line', () => {
  it('says the group is empty when it constrains nothing', () => {
    const { host } = mount([emptyGroup()]);
    expect(sums(host)).toEqual(['No filters yet']);
    expect(host.querySelector('.hk-filter-group-sum').hidden).toBe(false);
  });

  it('counts each non-empty list, in the order the form shows them', () => {
    const { host } = mount([
      {
        ...emptyGroup(),
        labels: ['dog', 'vet'],
        areas: ['garage'],
        exclude_areas: ['shed'],
      },
    ]);
    expect(sums(host)).toEqual(['Labels 2 · Areas 1 · Exclude areas 1']);
  });

  it('names the label mode straight after the count it changes', () => {
    const { host } = mount([
      { ...emptyGroup(), labels: ['dog', 'outdoor'], labels_match: 'all', areas: ['garage'] },
    ]);
    expect(sums(host)).toEqual(['Labels 2 · All selected labels · Areas 1']);
  });

  it('leaves the label mode out when no label is chosen', () => {
    // "All selected labels" of nothing says nothing, and the mode alone never makes
    // the group active — so the line would read as a rule where there is none.
    const { host } = mount([{ ...emptyGroup(), labels_match: 'all', areas: ['garage'] }]);
    expect(sums(host)).toEqual(['Areas 1']);
  });

  it('names the shopping switch last, and on its own for an exclude-only group', () => {
    const { host } = mount([
      { ...emptyGroup(), exclude_shopping: true },
      { ...emptyGroup(), devices: ['d1'], exclude_shopping: true },
    ]);
    expect(sums(host)).toEqual(['Exclude shopping', 'Devices 1 · Exclude shopping']);
  });

  it('repaints the line as the form is edited, without rebuilding the row', () => {
    const { host } = mount([emptyGroup()]);
    const before = formIn(cards(host)[0]);
    before.emit({ ...emptyGroup(), labels: ['dog'] });
    expect(sums(host)).toEqual(['Labels 1']);
    expect(formIn(cards(host)[0])).toBe(before);
  });
});

describe('groupSummaryLine', () => {
  // The line itself, away from the DOM — the counting rules are what a reader trusts.
  const label = (s) => `L:${s.name}`;

  it("answers the caller's empty phrase for a group that constrains nothing", () => {
    expect(groupSummaryLine(emptyGroup(), STRINGS, label)).toBe('No filters yet');
    expect(groupSummaryLine({ ...emptyGroup(), name: 'The dog' }, STRINGS, label)).toBe(
      'No filters yet',
    );
  });

  it('takes its field names from the caller, so the card editor reads in English', () => {
    const group = { ...emptyGroup(), labels: ['a'], exclude_devices: ['b'] };
    expect(groupSummaryLine(group, STRINGS, label)).toBe('L:labels 1 · L:exclude_devices 1');
  });

  it('counts every list a group can carry', () => {
    const group = {
      ...emptyGroup(),
      labels: ['a'],
      areas: ['b'],
      devices: ['c'],
      companions: ['d'],
      exclude_labels: ['e'],
      exclude_areas: ['f'],
      exclude_devices: ['g'],
      exclude_companions: ['h'],
    };
    expect(groupSummaryLine(group, STRINGS, (s) => s.name)).toBe(
      'labels 1 · areas 1 · devices 1 · companions 1 · ' +
        'exclude_labels 1 · exclude_areas 1 · exclude_devices 1 · exclude_companions 1',
    );
  });

  it('reports the real count, not just that a list is set', () => {
    const group = { ...emptyGroup(), labels: ['a', 'b', 'c'] };
    expect(groupSummaryLine(group, STRINGS, (s) => s.name)).toBe('labels 3');
  });
});

describe('openGroupIndex', () => {
  // The same rule `openPartIndex` applies to a part row.
  it('opens a lone group when nothing has been chosen', () => {
    expect(openGroupIndex(undefined, 1)).toBe(0);
  });

  it('folds a longer list when nothing has been chosen', () => {
    expect(openGroupIndex(undefined, 2)).toBe(-1);
    expect(openGroupIndex(undefined, 5)).toBe(-1);
  });

  it('folds everything for a deliberate null, even a lone group', () => {
    expect(openGroupIndex(null, 1)).toBe(-1);
    expect(openGroupIndex(null, 3)).toBe(-1);
  });

  it('honours a chosen index inside the list', () => {
    expect(openGroupIndex(0, 3)).toBe(0);
    expect(openGroupIndex(2, 3)).toBe(2);
  });

  it('folds the list rather than opening a stranger past the end', () => {
    // A group deleted from under the index must not hand the open state to whatever
    // moved into its place.
    expect(openGroupIndex(3, 3)).toBe(-1);
    expect(openGroupIndex(9, 2)).toBe(-1);
  });
});

describe('renderGroupsEditor — several groups', () => {
  it('draws each group, one divider between them, and a Delete on each', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    expect(cards(host)).toHaveLength(2);
    expect(names(host)).toEqual(['Group 1', 'Group 2']);
    // One divider for two groups — it joins them, it does not label them.
    expect(host.querySelectorAll('.hk-filter-or')).toHaveLength(1);
    expect(host.querySelector('.hk-filter-or').textContent).toBe('OR');
    expect(host.querySelectorAll('.hk-filter-group-delete')).toHaveLength(2);
  });

  it('folds every group when there is more than one', () => {
    // Two open forms do not fit on a phone, and neither is the one asked for.
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    expect(opens(host)).toEqual([false, false, false]);
  });

  it('opens the group the caller asked for', () => {
    const { host } = mount([emptyGroup(), emptyGroup()], { openIndex: 1 });
    expect(opens(host)).toEqual([false, true]);
  });

  it('folds every group for a caller that asked for none', () => {
    const { host } = mount([emptyGroup()], { openIndex: null });
    expect(opens(host)).toEqual([false]);
  });

  it('names the Delete button for a screen reader and a hover', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    const del = host.querySelector('.hk-filter-group-delete');
    // The icon is the `path` property, not an attribute: an attribute draws nothing.
    expect(del.path).toMatch(/^M19,4H15\.5/);
    expect(del.getAttribute('icon')).toBeNull();
    expect(del.getAttribute('title')).toBe('Delete group');
    expect(del.getAttribute('aria-label')).toBe('Delete group');
    // The divider is decoration; the headings already say which group is which.
    expect(host.querySelector('.hk-filter-or').getAttribute('aria-hidden')).toBe('true');
  });

  it('puts the Delete in the body, not in the summary', () => {
    // A button inside a `summary` toggles the row as well as firing, and the browsers
    // disagree on which happens first.
    const { host } = mount([emptyGroup(), emptyGroup()]);
    const del = cards(host)[0].querySelector('.hk-filter-group-delete');
    expect(del.closest('summary')).toBeNull();
    expect(del.closest('.hk-filter-group-body')).toBeTruthy();
    // In its own row, which is what pushes it to the right-hand edge.
    expect(del.parentElement.className).toBe('hk-filter-group-foot');
    // Last in the body, after the form it acts on.
    expect(cards(host)[0].querySelector('.hk-filter-group-body').lastElementChild).toBe(
      del.parentElement,
    );
  });

  it('keeps every group on its own index', () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    expect(cards(host).map((c) => c.dataset.group)).toEqual(['0', '1', '2']);
    expect(host.querySelectorAll('.hk-filter-or')).toHaveLength(2);
  });
});

describe('renderGroupsEditor — one row open at a time', () => {
  it('closes the other rows when one is opened', async () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    cards(host)[1].open = true;
    await settle();
    expect(opens(host)).toEqual([false, true, false]);
    cards(host)[2].open = true;
    await settle();
    expect(opens(host)).toEqual([false, false, true]);
  });

  it('keeps the chosen row open across an add', async () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    cards(host)[0].open = true;
    await settle();
    addBtn(host).click();
    // The new row is the one the click asked for, so it opens and the rest fold.
    expect(opens(host)).toEqual([false, false, false, true]);
  });

  it('reopens nothing when the open row is the one deleted', async () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    cards(host)[1].open = true;
    await settle();
    host.querySelectorAll('.hk-filter-group-delete')[1].click();
    expect(opens(host)).toEqual([false, false]);
  });

  it('follows the open row down when a row above it is deleted', async () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    // Opened, then swapped for another: the row that folds must not take the choice
    // with it — the reader is now in the row they opened second.
    cards(host)[0].open = true;
    await settle();
    cards(host)[2].open = true;
    await settle();
    host.querySelectorAll('.hk-filter-group-delete')[0].click();
    // The row that was third is now second, and still the one being edited.
    expect(opens(host)).toEqual([false, true]);
  });

  it('folds the list again when the open row is closed by hand', async () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    cards(host)[0].open = true;
    await settle();
    cards(host)[0].open = false;
    await settle();
    // A delete repaints the list from the remembered choice, and there is none.
    host.querySelectorAll('.hk-filter-group-delete')[2].click();
    expect(opens(host)).toEqual([false, false]);
  });

  it('leaves an untouched list on its default after a delete', async () => {
    // Nothing was ever opened, so a delete may not invent a choice: three folded
    // groups become two folded groups.
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    host.querySelectorAll('.hk-filter-group-delete')[0].click();
    expect(opens(host)).toEqual([false, false]);
    // ...and down to one, the lone survivor opens, because it is the only thing left.
    host.querySelectorAll('.hk-filter-group-delete')[0].click();
    expect(opens(host)).toEqual([true]);
  });
});

describe('renderGroupsEditor — add', () => {
  it('appends an empty group and reports the new list', () => {
    const { host, emitted } = mount([{ ...emptyGroup(), labels: ['dog'] }, emptyGroup()]);
    addBtn(host).click();
    expect(cards(host)).toHaveLength(3);
    expect(names(host)).toEqual(['Group 1', 'Group 2', 'Group 3']);
    expect(emitted).toHaveLength(1);
    expect(emitted[0]).toHaveLength(3);
    // The new one constrains nothing, so adding it cannot change what is selected...
    expect(emitted[0][2]).toEqual(emptyGroup());
    // ...and the groups already there are untouched.
    expect(emitted[0][0].labels).toEqual(['dog']);
  });

  it('opens the group it just added', () => {
    // The one thing the click asked for. A folded blank row would have to be found
    // and opened before anything could be typed into it.
    const { host } = mount([emptyGroup()]);
    addBtn(host).click();
    expect(opens(host)).toEqual([false, true]);
  });

  it('takes the id the caller asked for, so one surface can name its button', () => {
    const { host } = mount([emptyGroup()], { addId: 'hk-profile-p1-group-add' });
    expect(addBtn(host).id).toBe('hk-profile-p1-group-add');
    expect(addBtn(host).textContent).toBe('Add another group');
    // Not the page's primary action — the profile is already there to be saved.
    expect(addBtn(host).getAttribute('data-hk-weight')).toBe('secondary');
  });

  it('carries no id at all for a caller that did not ask for one', () => {
    // The card editor names its button; a caller that does not must not end up with
    // an element identified as "undefined".
    const { host } = mount([emptyGroup()]);
    expect(addBtn(host).id).toBe('');
    expect(addBtn(host).hasAttribute('id')).toBe(false);
  });

  it('sits after the last group, whatever the count', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    expect(host.lastElementChild).toBe(addBtn(host));
    addBtn(host).click();
    expect(host.lastElementChild.className).toBe('hk-filter-group-add');
  });

  it('leaves nothing of the pass before behind when it re-renders', () => {
    // A re-render rebuilds the host, so every child has to be an element this pass
    // drew — a stray text node would sit above the first group on screen.
    const { host } = mount([emptyGroup()]);
    addBtn(host).click();
    expect([...host.childNodes].map((n) => n.nodeType)).toEqual([1, 1, 1, 1]);
  });
});

describe('renderGroupsEditor — delete', () => {
  it('removes that group, renumbers the rest and reports the new list', () => {
    const first = { ...emptyGroup(), labels: ['dog'] };
    const second = { ...emptyGroup(), areas: ['garage'] };
    const { host, emitted } = mount([first, second]);
    host.querySelectorAll('.hk-filter-group-delete')[0].click();

    expect(cards(host)).toHaveLength(1);
    // The survivor is the former Group 2, now headed Group 1.
    expect(names(host)).toEqual(['Group 1']);
    expect(formIn(cards(host)[0]).data.areas).toEqual(['garage']);
    expect(emitted).toEqual([[second]]);
  });

  it('drops the last Delete button when one group is left', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    host.querySelectorAll('.hk-filter-group-delete')[1].click();
    expect(host.querySelector('.hk-filter-group-delete')).toBeNull();
    expect(host.querySelector('.hk-filter-or')).toBeNull();
  });

  it('deletes the group whose button was pressed, not the first one', () => {
    const groups = [0, 1, 2].map((i) => ({ ...emptyGroup(), labels: [`l${i}`] }));
    const { host, emitted } = mount(groups);
    host.querySelectorAll('.hk-filter-group-delete')[1].click();
    expect(emitted[0].map((g) => g.labels[0])).toEqual(['l0', 'l2']);
    expect(cards(host).map((c) => formIn(c).data.labels[0])).toEqual(['l0', 'l2']);
  });
});

describe('renderGroupsEditor — form edits', () => {
  it('writes an edit into that group alone', () => {
    const { host, emitted } = mount([emptyGroup(), emptyGroup()]);
    formIn(cards(host)[1]).emit({ ...emptyGroup(), labels: ['dog'] });
    expect(emitted).toHaveLength(1);
    expect(emitted[0][0]).toEqual(emptyGroup());
    expect(emitted[0][1].labels).toEqual(['dog']);
  });

  it('normalizes what the form emitted', () => {
    // `ha-form` clears a picker to `undefined`, and JSON drops that on the way to the
    // backend — so the key would never reach the saved profile.
    const { host, emitted } = mount([emptyGroup()]);
    formIn(cards(host)[0]).emit({ labels: undefined, labels_match: 'nope', exclude_shopping: 1 });
    expect(emitted[0][0]).toEqual({ ...emptyGroup(), exclude_shopping: true });
  });

  it('trims the name it was given', () => {
    const { host, emitted } = mount([emptyGroup()]);
    formIn(cards(host)[0]).emit({ ...emptyGroup(), name: '  The dog  ' });
    expect(emitted[0][0].name).toBe('The dog');
  });

  it('does not re-render the row it was typed in', () => {
    // Rebuilding on every keystroke would take the control out from under the user.
    const { host } = mount([emptyGroup(), emptyGroup()]);
    const before = formIn(cards(host)[0]);
    formIn(cards(host)[1]).emit({ ...emptyGroup(), labels: ['dog'] });
    expect(formIn(cards(host)[0])).toBe(before);
  });

  it('carries an earlier edit through a later add', () => {
    // The editor mutates the caller's array in place, so the list an add reports
    // still holds what was typed before it.
    const { host, emitted } = mount([emptyGroup()]);
    formIn(cards(host)[0]).emit({ ...emptyGroup(), labels: ['dog'] });
    addBtn(host).click();
    expect(emitted[1].map((g) => g.labels)).toEqual([['dog'], []]);
  });
});
