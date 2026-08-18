import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import {
  definePanelStubs,
  makeHass,
  mountPanel,
  stubLazyMarkdown,
  waitFor,
} from './panel-harness.js';

/**
 * The positive control for the guard in `form-focus.test.js`: holding a late
 * `ha-markdown` upgrade back while a form is open must not turn into never taking it.
 *
 * Own file because a custom element cannot be un-registered — this needs a registry
 * that has never seen `ha-markdown`, and each vitest file gets a fresh one.
 */

beforeAll(definePanelStubs);

afterEach(() => {
  document.body.innerHTML = '';
});

describe('a late ha-markdown upgrade repaints when nothing is being edited', () => {
  it('re-renders so notes stop showing the escaped-text fallback', async () => {
    const registerMarkdown = stubLazyMarkdown();
    const { panel } = await mountPanel('/tasks', makeHass());
    const listBefore = panel.shadowRoot.querySelector('#hk-list');
    expect(listBefore, 'the task list should be painted').toBeTruthy();

    registerMarkdown();

    const repainted = await waitFor(() => {
      const list = panel.shadowRoot?.querySelector('#hk-list');
      return list && list !== listBefore ? list : null;
    });
    expect(repainted, 'the upgrade should repaint the panel').toBeTruthy();
  });
});
