// The photo markup of the task page header and the task list row (#399): the cover,
// and the photo of the last completion beside it.
import { describe, expect, it } from 'vitest';
import { listCoverHtml, taskHeadPhotosHtml } from '../src/panel-photo-markup.ts';
import { t } from '../src/i18n.ts';

// The panel's signed URL cache, with nothing signed yet.
const p = { _signedUrl: () => undefined };

// What the completion dialog's picture upload stores.
const AFTER = '/api/image/serve/abc123/512x512';
const cover = { id: 'p1', name: 'gap.jpg', filename: 'gap.jpg', content_type: 'image/jpeg', size: 1 };
const doneOneOff = (over = {}) => ({
  id: 't1',
  name: 'Repair insulation',
  recurrence_type: 'one-off',
  next_due: null,
  last_completed: '2026-10-01T10:00:00Z',
  completions: [{ ts: '2026-10-01T10:00:00Z', photo: AFTER }],
  photos: [cover],
  ...over,
});

const html = (s) => {
  const el = document.createElement('div');
  el.innerHTML = s;
  return el;
};

describe('taskHeadPhotosHtml', () => {
  it('shows the cover and the after photo of a one-off as a labelled pair', () => {
    const el = html(taskHeadPhotosHtml(p, doneOneOff()));
    const tiles = el.querySelectorAll('.hk-head-photos > .hk-head-photo');
    expect(tiles).toHaveLength(2);
    expect([...tiles].map((x) => x.querySelector('.hk-photo-badge').textContent)).toEqual([
      t('photos.before'),
      t('photos.after'),
    ]);
    // The cover is the signed task photo; the after photo is the image store's URL,
    // its 256px copy in the tile and the original behind the link.
    expect(tiles[0].querySelector('img[data-sign]')).toBeTruthy();
    const after = tiles[1].querySelector('a.hk-task-cover');
    expect(after.getAttribute('href')).toBe('/api/image/serve/abc123/original');
    expect(after.getAttribute('target')).toBe('_blank');
    expect(after.getAttribute('rel')).toBe('noopener');
    expect(after.querySelector('img').getAttribute('src')).toBe('/api/image/serve/abc123/256x256');
    expect(after.querySelector('img').getAttribute('alt')).toBe(
      t('photos.afterAlt', { task: 'Repair insulation' }),
    );
  });

  it('labels a repeating task cover and last completion', () => {
    const el = html(taskHeadPhotosHtml(p, doneOneOff({ recurrence_type: 'floating' })));
    expect([...el.querySelectorAll('.hk-photo-badge')].map((x) => x.textContent)).toEqual([
      t('photos.cover'),
      t('photos.lastCompletion'),
    ]);
  });

  it('shows the after photo alone when the task has no cover', () => {
    const el = html(taskHeadPhotosHtml(p, doneOneOff({ photos: [] })));
    const tiles = el.querySelectorAll('.hk-head-photo');
    expect(tiles).toHaveLength(1);
    expect(tiles[0].querySelector('.hk-photo-badge').textContent).toBe(t('photos.after'));
  });

  it('shows the cover alone, as before, when the last completion has no photo', () => {
    const el = html(taskHeadPhotosHtml(p, doneOneOff({ completions: [{ ts: '2026-10-01T10:00:00Z' }] })));
    expect(el.querySelector('.hk-head-photos')).toBeNull();
    expect(el.querySelector('a.hk-task-cover img.hk-task-cover-img[data-sign]')).toBeTruthy();
    expect(taskHeadPhotosHtml(p, doneOneOff({ completions: [], photos: [] }))).toBe('');
  });

  it('escapes the URL and the task name', () => {
    const s = taskHeadPhotosHtml(
      p,
      doneOneOff({
        name: '<b>x</b>',
        completions: [{ ts: '2026-10-01T10:00:00Z', photo: '/a.jpg?"><script>' }],
      }),
    );
    expect(s).not.toContain('<script>');
    expect(s).not.toContain('<b>x</b>');
  });
});

describe('listCoverHtml', () => {
  it('shows the after photo with a check on a done one-off', () => {
    const el = html(listCoverHtml(p, doneOneOff()));
    const img = el.querySelector('.hk-row-after img.hk-row-cover');
    expect(img.getAttribute('src')).toBe('/api/image/serve/abc123/256x256');
    expect(img.hasAttribute('data-sign')).toBe(false);
    expect(el.querySelector('.hk-row-after-check').getAttribute('aria-hidden')).toBe('true');
  });

  it('keeps the cover on a task that is not a done one-off', () => {
    // A repeating task goes back to its due group after Done, and an open one-off
    // has no result yet, so both keep showing what needs work.
    for (const over of [
      { recurrence_type: 'floating' },
      { next_due: '2026-11-01T10:00:00Z' },
      { last_completed: null },
    ]) {
      const el = html(listCoverHtml(p, doneOneOff(over)));
      expect(el.querySelector('.hk-row-after')).toBeNull();
      expect(el.querySelector('img.hk-row-cover[data-sign]')).toBeTruthy();
    }
  });

  it('keeps the cover on a done one-off whose completion has no photo', () => {
    const el = html(listCoverHtml(p, doneOneOff({ completions: [{ ts: '2026-10-01T10:00:00Z' }] })));
    expect(el.querySelector('.hk-row-after')).toBeNull();
    expect(el.querySelector('img.hk-row-cover[data-sign]')).toBeTruthy();
  });
});
