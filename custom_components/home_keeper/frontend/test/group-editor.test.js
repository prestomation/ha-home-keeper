import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { emptyGroup } from '../src/card-filter.ts';
import { renderGroupsEditor } from '../src/group-editor.ts';
import { setLanguage } from '../src/i18n.ts';

// The filter-groups editor, rendered by the Settings → Profiles rows and (later) by
// the dashboard card's own editor. It owns three things nothing else can check: the
// DOM one group is drawn as, the add/delete rules that renumber it, and which group a
// form event writes to. Everything about *matching* is `card-filter-profile.test.js`;
// everything about *saving* is `profile-groups.test.js`.
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
const titles = (host) =>
  [...host.querySelectorAll('.hk-filter-group-title')].map((el) => el.textContent);
const formIn = (card) => card.querySelector('ha-form');
const addBtn = (host) => host.querySelector('.hk-filter-group-add');

describe('renderGroupsEditor — one group', () => {
  it('draws the group with its title, its help and its form', () => {
    const { host } = mount([emptyGroup()]);
    expect(cards(host)).toHaveLength(1);
    expect(titles(host)).toEqual(['Group 1']);
    expect(cards(host)[0].dataset.group).toBe('0');
    expect(cards(host)[0].querySelector('.hk-settings-intro').textContent).toBe(STRINGS.help);
    expect(formIn(cards(host)[0])).toBeTruthy();
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
    expect(form.schema.map((f) => f.name)).toContain('exclude_shopping');
    // `labels` is the shared task field; everything else is named under `notify.`.
    expect(form.labelling.computeLabel({ name: 'labels' })).toBe('Labels');
    expect(form.labelling.computeLabel({ name: 'exclude_areas' })).toBe('Exclude areas');
  });

  it('takes an English computeLabel from a caller that has no translations', () => {
    // The card editor is English-only, so it overrides rather than reaching into t().
    const { host } = mount([emptyGroup()], { computeLabel: (s) => `X:${s.name}` });
    expect(formIn(cards(host)[0]).labelling.computeLabel({ name: 'labels' })).toBe('X:labels');
  });
});

describe('renderGroupsEditor — several groups', () => {
  it('draws each group, one divider between them, and a Delete on each', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    expect(cards(host)).toHaveLength(2);
    expect(titles(host)).toEqual(['Group 1', 'Group 2']);
    // One divider for two groups — it joins them, it does not label them.
    expect(host.querySelectorAll('.hk-filter-or')).toHaveLength(1);
    expect(host.querySelector('.hk-filter-or').textContent).toBe('OR');
    expect(host.querySelectorAll('.hk-filter-group-delete')).toHaveLength(2);
  });

  it('names the Delete button for a screen reader and a hover', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    const del = host.querySelector('.hk-filter-group-delete');
    expect(del.getAttribute('icon')).toBe('mdi:delete-outline');
    expect(del.getAttribute('title')).toBe('Delete group');
    expect(del.getAttribute('aria-label')).toBe('Delete group');
    // The divider is decoration; the titles already say which group is which.
    expect(host.querySelector('.hk-filter-or').getAttribute('aria-hidden')).toBe('true');
  });

  it('keeps every group on its own index', () => {
    const { host } = mount([emptyGroup(), emptyGroup(), emptyGroup()]);
    expect(cards(host).map((c) => c.dataset.group)).toEqual(['0', '1', '2']);
    expect(host.querySelectorAll('.hk-filter-or')).toHaveLength(2);
  });
});

describe('renderGroupsEditor — add', () => {
  it('appends an empty group and reports the new list', () => {
    const { host, emitted } = mount([{ ...emptyGroup(), labels: ['dog'] }, emptyGroup()]);
    addBtn(host).click();
    expect(cards(host)).toHaveLength(3);
    expect(titles(host)).toEqual(['Group 1', 'Group 2', 'Group 3']);
    expect(emitted).toHaveLength(1);
    expect(emitted[0]).toHaveLength(3);
    // The new one constrains nothing, so adding it cannot change what is selected...
    expect(emitted[0][2]).toEqual(emptyGroup());
    // ...and the groups already there are untouched.
    expect(emitted[0][0].labels).toEqual(['dog']);
  });

  it('takes the id the caller asked for, so one surface can name its button', () => {
    const { host } = mount([emptyGroup()], { addId: 'hk-profile-p1-group-add' });
    expect(addBtn(host).id).toBe('hk-profile-p1-group-add');
    expect(addBtn(host).textContent).toBe('Add another group');
    // Not the page's primary action — the profile is already there to be saved.
    expect(addBtn(host).getAttribute('data-hk-weight')).toBe('secondary');
  });

  it('sits after the last group, whatever the count', () => {
    const { host } = mount([emptyGroup(), emptyGroup()]);
    expect(host.lastElementChild).toBe(addBtn(host));
    addBtn(host).click();
    expect(host.lastElementChild.className).toBe('hk-filter-group-add');
  });
});

describe('renderGroupsEditor — delete', () => {
  it('removes that group, renumbers the rest and reports the new list', () => {
    const first = { ...emptyGroup(), labels: ['dog'] };
    const second = { ...emptyGroup(), areas: ['garage'] };
    const { host, emitted } = mount([first, second]);
    host.querySelectorAll('.hk-filter-group-delete')[0].click();

    expect(cards(host)).toHaveLength(1);
    // The survivor is the former Group 2, now titled Group 1.
    expect(titles(host)).toEqual(['Group 1']);
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
