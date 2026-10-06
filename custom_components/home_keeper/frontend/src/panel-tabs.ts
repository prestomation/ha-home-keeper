/**
 * Companion panel tabs: the tab bar entries, the module load, and the host object.
 *
 * A companion integration registers a tab in Python (`panel_tabs.py`). The panel reads
 * the list through `home_keeper/get_panel_tabs`. On the first open of a tab, the panel
 * imports the tab's ES module 1 time per URL, waits until the module defines the
 * tab's custom element, and makes 1 element per tab. The element stays while the
 * panel lives. A redraw of the panel moves the element into the new tree.
 *
 * The panel sets these properties on the element and keeps them current: `hass`,
 * `narrow`, `route` (`{ path }`, the part of the URL after `/home-keeper/<id>`) and
 * `host` (the host API object, see `hostApi`). The tab changes the URL only through
 * `host.navigate`, which goes through the panel's own `_navigate`.
 *
 * The contract for integrators is in docs/INTEGRATING.md, "Add a panel tab".
 */

import { t } from './i18n';
import type { PanelHost } from './panel-host';
import type { Hass, PanelTabInfo } from './types';
import {
  PANEL_HOST_API,
  btnAttrs,
  escapeHTML,
  normalizeTabPath,
  panelSubPath,
  parseRoute,
  toast,
  visiblePanelTabs,
  type PanelLocation,
} from './utils';

/** How long the panel waits for a module to define the tab element. */
export const TAB_DEFINE_TIMEOUT_MS = 10000;

/** The host API object that the panel gives to a companion tab (version 1). */
export interface PanelTabHost {
  readonly apiVersion: number;
  navigate(path: string, opts?: { replace?: boolean }): void;
  taskLink(taskId: string): string;
  applianceLink(assetId: string): string;
  openTask(taskId: string): void;
  openAppliance(assetId: string): void;
  showToast(text: string): void;
}

/** A tab element, with the properties that the panel sets. */
export type PanelTabElement = HTMLElement & {
  hass?: Hass;
  narrow?: boolean;
  route?: { path: string };
  host?: PanelTabHost;
};

/** The load state of 1 tab. `outdated`: the tab needs a newer host API. */
export type PanelTabStatus = 'loading' | 'ready' | 'error' | 'outdated';

/** What the panel keeps about the companion tabs while it lives. */
export interface PanelTabRuntime {
  elements: Map<string, PanelTabElement>;
  status: Map<string, PanelTabStatus>;
  /** How many times each tab was loaded again with Retry. */
  attempts: Map<string, number>;
}

export function newTabRuntime(): PanelTabRuntime {
  return { elements: new Map(), status: new Map(), attempts: new Map() };
}

// 1 import per module URL for the life of the page. A failed import is removed, so
// Retry imports again.
const moduleLoads = new Map<string, Promise<unknown>>();

/** Import *url* 1 time. Kept apart, so a test can replace the import. */
export const tabModuleLoader = {
  load: (url: string): Promise<unknown> => import(/* @vite-ignore */ url),
};

function importOnce(url: string): Promise<unknown> {
  let load = moduleLoads.get(url);
  if (!load) {
    load = tabModuleLoader.load(url);
    moduleLoads.set(url, load);
    load.catch(() => moduleLoads.delete(url));
  }
  return load;
}

/**
 * The URL to import for a load. A browser keeps a failed module import in its module
 * map, so each Retry adds a query value that makes a new URL.
 */
function attemptUrl(url: string, attempt: number): string {
  if (!attempt) return url;
  return `${url}${url.includes('?') ? '&' : '?'}hk_retry=${attempt}`;
}

function whenDefined(element: string, ms: number): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${element} is not defined`)), ms);
    customElements.whenDefined(element).then(
      () => {
        clearTimeout(timer);
        resolve();
      },
      (err: unknown) => {
        clearTimeout(timer);
        reject(err);
      },
    );
  });
}

/** The tabs that the tab bar shows, in their order. */
export function shownTabs(p: PanelHost): PanelTabInfo[] {
  return visiblePanelTabs(p._panelTabs, p._options?.hidden_panel_tabs);
}

/** The tab that the URL names, if the tab bar shows it. */
export function currentTab(p: PanelHost): PanelTabInfo | undefined {
  const id = p._panelTab?.id;
  return id ? shownTabs(p).find((tab) => tab.id === id) : undefined;
}

/** The host API object for *tab*. Frozen, so a tab cannot change it. */
export function hostApi(p: PanelHost, tab: PanelTabInfo): PanelTabHost {
  return Object.freeze({
    apiVersion: PANEL_HOST_API,
    navigate(path: string, opts?: { replace?: boolean }): void {
      p._navigate(
        { view: 'tab', detail: null, tab: tab.id, path: normalizeTabPath(path) },
        Boolean(opts?.replace),
      );
    },
    taskLink(taskId: string): string {
      return p._hrefFor({ view: 'tasks', detail: { kind: 'task', id: String(taskId) } });
    },
    applianceLink(assetId: string): string {
      return p._hrefFor({ view: 'appliances', detail: { kind: 'asset', id: String(assetId) } });
    },
    openTask(taskId: string): void {
      p._navigate({ view: 'tasks', detail: { kind: 'task', id: String(taskId) } });
    },
    openAppliance(assetId: string): void {
      p._navigate({ view: 'appliances', detail: { kind: 'asset', id: String(assetId) } });
    },
    showToast(text: string): void {
      toast(p, String(text));
    },
  });
}

/**
 * Open a plain left click on a link to a Home Keeper page inside a tab with the
 * panel's own navigation, with no page load.
 *
 * The listener is on the tab area, so it runs after the tab's own handlers. It
 * leaves alone a click that a tab handled (`defaultPrevented`), a click with a
 * modifier key or another button, and a link with a `target` or `download`.
 */
export function onTabLinkClick(p: PanelHost, e: MouseEvent): void {
  if (e.defaultPrevented || e.button !== 0) return;
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const anchor = e
    .composedPath()
    .find((n): n is HTMLAnchorElement => n instanceof HTMLAnchorElement && n.hasAttribute('href'));
  if (!anchor) return;
  const target = anchor.getAttribute('target');
  if ((target && target !== '_self') || anchor.hasAttribute('download')) return;
  // `buildPath` writes the task list as `/tasks`, so this is the panel prefix.
  const prefix = p._hrefFor({ view: 'tasks', detail: null }).replace(/\/tasks$/, '');
  const sub = panelSubPath(anchor.href, location.origin, prefix);
  if (sub === null) return;
  e.preventDefault();
  p._navigate(parseRoute(sub));
}

/** Start the load of *tab* if it did not start. Renders again when it ends. */
export function ensureTabLoaded(p: PanelHost, tab: PanelTabInfo): void {
  const rt = p._tabRuntime;
  if (rt.status.has(tab.id)) return;
  if (tab.host_api > PANEL_HOST_API) {
    rt.status.set(tab.id, 'outdated');
    return;
  }
  rt.status.set(tab.id, 'loading');
  const attempt = rt.attempts.get(tab.id) ?? 0;
  importOnce(attemptUrl(tab.module_url, attempt))
    .then(() => whenDefined(tab.element, TAB_DEFINE_TIMEOUT_MS))
    .then(() => {
      if (!rt.elements.has(tab.id)) {
        const el = document.createElement(tab.element) as PanelTabElement;
        el.host = hostApi(p, tab);
        rt.elements.set(tab.id, el);
      }
      rt.status.set(tab.id, 'ready');
    })
    .catch((err: unknown) => {
      // eslint-disable-next-line no-console
      console.error(`home-keeper: the ${tab.id} tab did not load`, err);
      rt.status.set(tab.id, 'error');
    })
    .finally(() => {
      if (p._panelTab?.id === tab.id) p._render();
    });
}

/** Set the live properties on a tab element. */
export function feedTab(p: PanelHost, el: PanelTabElement, path: string): void {
  el.hass = p._hass;
  el.narrow = p.narrow;
  if (el.route?.path !== path) el.route = { path };
}

/** Give *hass* to every tab element (the panel calls this on each `hass` update). */
export function feedTabsHass(p: PanelHost, hass: Hass): void {
  for (const el of p._tabRuntime.elements.values()) el.hass = hass;
}

/** Give *narrow* to every tab element. */
export function feedTabsNarrow(p: PanelHost, narrow: boolean): void {
  for (const el of p._tabRuntime.elements.values()) el.narrow = narrow;
}

/** Set the new path on the open tab's element, with no redraw of the panel. */
export function routeOpenTab(p: PanelHost): void {
  const loc = p._panelTab;
  const el = loc ? p._tabRuntime.elements.get(loc.id) : undefined;
  if (loc && el) feedTab(p, el, loc.path);
}

/** The markup of the tab content area. `mountTab` fills it after the render. */
export function tabArea(): string {
  return `<div id="hk-tab-host" class="hk-tab-host"></div>`;
}

/** Fill the tab content area with the element, a spinner or a message. */
export function mountTab(p: PanelHost, root: ShadowRoot): void {
  const host = root.getElementById('hk-tab-host');
  const tab = currentTab(p);
  if (!host || !tab || !p._panelTab) return;
  ensureTabLoaded(p, tab);
  const status = p._tabRuntime.status.get(tab.id);
  const el = p._tabRuntime.elements.get(tab.id);
  if (status === 'ready' && el) {
    feedTab(p, el, p._panelTab.path);
    host.addEventListener('click', (e) => onTabLinkClick(p, e));
    host.appendChild(el);
    return;
  }
  if (status === 'outdated') {
    host.innerHTML = `<ha-alert alert-type="warning" class="hk-tab-msg">${escapeHTML(
      t('panelTab.updateNeeded', { title: tab.title }),
    )}</ha-alert>`;
    return;
  }
  if (status === 'error') {
    host.innerHTML = `<div class="hk-tab-msg">
        <ha-alert alert-type="error">${escapeHTML(t('panelTab.loadFailed', { title: tab.title }))}</ha-alert>
        <ha-button id="hk-tab-retry" ${btnAttrs('primary')}>${escapeHTML(t('btn.retry'))}</ha-button>
      </div>`;
    host.querySelector('#hk-tab-retry')?.addEventListener('click', () => retryTab(p, tab));
    return;
  }
  host.innerHTML = `<div class="hk-loading"><ha-spinner size="large"></ha-spinner></div>`;
}

/** Load a tab again after a failed load. */
export function retryTab(p: PanelHost, tab: PanelTabInfo): void {
  const rt = p._tabRuntime;
  rt.attempts.set(tab.id, (rt.attempts.get(tab.id) ?? 0) + 1);
  rt.status.delete(tab.id);
  ensureTabLoaded(p, tab);
  p._render();
}

/** Open a companion tab from the tab bar. On the open tab, go back to its root. */
export function switchTab(p: PanelHost, id: string): void {
  if (p._panelTab?.id === id && !p._panelTab.path) return;
  p._navigate({ view: 'tab', detail: null, tab: id, path: '' }, true);
}

/**
 * If the URL names a tab that the tab bar does not show, go to the task list.
 * Returns whether it moved. Only after the load, because before it the list is empty.
 */
export function redirectUnknownTab(p: PanelHost, loaded: boolean): boolean {
  if (!loaded || !p._panelTab || currentTab(p)) return false;
  const loc: PanelLocation = { view: 'tasks', detail: null };
  p._navigate(loc, true);
  return true;
}

/** The desktop tab bar entries of the companion tabs. */
export function topTabs(p: PanelHost): string {
  const open = p._panelTab?.id;
  return shownTabs(p)
    .map(
      (tab) =>
        `<ha-tab-group-tab id="tab-x-${escapeHTML(tab.id)}" class="hk-ptab" data-panel-tab="${escapeHTML(tab.id)}" panel="x-${escapeHTML(tab.id)}" ${open === tab.id ? 'active' : ''}>${escapeHTML(tab.title)}</ha-tab-group-tab>`,
    )
    .join('');
}

/** The phone tab bar entries of the companion tabs. */
export function bottomTabs(p: PanelHost): string {
  const open = p._panelTab?.id;
  return shownTabs(p)
    .map((tab) => {
      const on = open === tab.id;
      return `<button class="hk-bottomtab${on ? ' active' : ''}" id="mtab-x-${escapeHTML(tab.id)}" data-view="tab" data-panel-tab="${escapeHTML(tab.id)}"
         ${on ? 'aria-current="page"' : ''}><span class="hk-bottomtab-mark"></span><span class="hk-bottomtab-label">${escapeHTML(tab.title)}</span></button>`;
    })
    .join('');
}

/** Wire the companion entries of both tab bars. */
export function wireTabBars(p: PanelHost, root: ShadowRoot): void {
  root.querySelectorAll<HTMLElement>('[data-panel-tab]').forEach((el) =>
    el.addEventListener('click', () => {
      const id = el.dataset.panelTab;
      if (id) switchTab(p, id);
    }),
  );
}
