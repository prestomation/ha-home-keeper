import { test, Page, Locator } from "@playwright/test";
import { mkdirSync } from "fs";
import { callService, listTasks, setTaskLayout } from "./tests/helpers";
import { PHONE, DESKTOP } from "./viewports";

/**
 * EXPLORATION TOOL (not product code). Measures the panel and the card in a home that
 * has many tasks. It prints one `EXPLORE {json}` line for each measurement and saves
 * screenshots. It changes no assertion state: it never fails on a slow number.
 *
 * Run it on a stack from tools/explore-many-tasks/run_stack.sh N:
 *   SHOT_DIR=/tmp/shots LABEL=n1000 npx playwright test \
 *     --config=explore-many-tasks.config.ts
 * Set ONLY=panel or ONLY=card to run one half.
 */
const OUT = process.env.SHOT_DIR || "/tmp/hk-explore-shots";
const LABEL = process.env.LABEL || "run";
const ONLY = process.env.ONLY || "";
mkdirSync(OUT, { recursive: true });

function emit(o: Record<string, unknown>): void {
  console.log("EXPLORE " + JSON.stringify(o));
}

/** Install a long task recorder and a node counter before any page script runs. */
async function instrument(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as any;
    w.__lt = [] as number[];
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) w.__lt.push(e.duration);
      }).observe({ type: "longtask", buffered: true });
    } catch {
      /* no longtask support */
    }
    // All nodes under a root, including the shadow roots of the elements inside it.
    w.__deep = (root: ParentNode): number => {
      let n = 0;
      const walk = (r: ParentNode) => {
        const all = r.querySelectorAll("*");
        n += all.length;
        all.forEach((el) => {
          const sr = (el as HTMLElement).shadowRoot;
          if (sr) walk(sr);
        });
      };
      walk(root);
      return n;
    };
  });
}

async function resetLT(page: Page): Promise<void> {
  await page.evaluate(() => ((window as any).__lt = []));
}
async function readLT(
  page: Page,
): Promise<{ count: number; total: number; max: number }> {
  return page.evaluate(() => {
    const a: number[] = (window as any).__lt;
    return {
      count: a.length,
      total: Math.round(a.reduce((x, y) => x + y, 0)),
      max: Math.round(Math.max(0, ...a)),
    };
  });
}
async function heapMB(page: Page): Promise<number> {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("HeapProfiler.collectGarbage");
  const h = await cdp.send("Runtime.getHeapUsage");
  await cdp.detach();
  return Math.round(h.usedSize / 1048576);
}
const panelLoc = (page: Page) => page.locator("home-keeper-panel").first();

async function panelNodes(
  panel: Locator,
): Promise<{ shallow: number; deep: number }> {
  return panel.evaluate((el) => {
    const sr = el.shadowRoot!;
    return {
      shallow: sr.querySelectorAll("*").length,
      deep: (window as any).__deep(sr),
    };
  });
}

/** Load the panel; time to the first task row; report long tasks and node counts. */
async function loadPanel(
  page: Page,
  tag: string,
  rowSel = ".hk-card-row.hk-row-task",
): Promise<number> {
  const t0 = Date.now();
  await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
  const panel = panelLoc(page);
  await panel
    .locator(rowSel)
    .first()
    .waitFor({ state: "attached", timeout: 180_000 });
  const first = Date.now() - t0;
  await page.waitForTimeout(3000);
  const lt = await readLT(page);
  const rows = await panel.locator(rowSel).count();
  const nodes = await panelNodes(panel);
  emit({
    step: "load",
    tag,
    ms_to_first_row: first,
    rows,
    nodes,
    longtasks: lt,
    heap_mb: await heapMB(page),
  });
  return first;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: `${OUT}/${LABEL}-${name}.png` });
}

async function setLocal(
  page: Page,
  k: string,
  v: string | null,
): Promise<void> {
  await page.evaluate(
    ([key, val]) => {
      if (val === null) localStorage.removeItem(key as string);
      else localStorage.setItem(key as string, val as string);
    },
    [k, v],
  );
}

const STEPS = (process.env.STEPS || "").split(",").filter(Boolean);
const on = (s: string): boolean => !STEPS.length || STEPS.includes(s);

async function panelPass(page: Page, vp: "desktop" | "phone"): Promise<void> {
  const tag = `${LABEL}-${vp}`;
  await instrument(page);
  await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
  await page
    .locator("home-keeper-panel")
    .waitFor({ state: "attached", timeout: 60_000 });
  await setTaskLayout(page, "rows");
  await setLocal(page, "home-keeper.groupBy", null);
  await setLocal(page, "home-keeper.filter", null);

  // --- default view, rows
  await loadPanel(page, `${tag}-rows-default`);
  await shot(page, `${vp}-rows-top`);
  const panel = panelLoc(page);

  const search = panel.locator("#hk-search");
  const tasks = await listTasks();
  if (on("scroll")) {
    // --- scroll jank: frame gaps while the page scrolls down
    const scroll = await panel.evaluate(async (host) => {
      const sr = host.shadowRoot!;
      const cands = [
        document.scrollingElement,
        ...Array.from(sr.querySelectorAll("*")),
      ] as HTMLElement[];
      const sc =
        cands.find(
          (e) =>
            e &&
            e.scrollHeight > e.clientHeight + 200 &&
            /auto|scroll/.test(getComputedStyle(e).overflowY),
        ) || (document.scrollingElement as HTMLElement);
      const gaps: number[] = [];
      let last = performance.now();
      const t0 = last;
      let y = 0;
      return await new Promise<any>((res) => {
        const step = () => {
          const n = performance.now();
          gaps.push(n - last);
          last = n;
          y += 400;
          sc.scrollTop = y;
          if (n - t0 < 2500 && y < sc.scrollHeight) requestAnimationFrame(step);
          else
            res({
              frames: gaps.length,
              worst_gap_ms: Math.round(Math.max(...gaps)),
              scrollHeight: sc.scrollHeight,
              scroller: sc.tagName + "." + sc.className,
            });
        };
        requestAnimationFrame(step);
      });
    });
    emit({ step: "scroll", tag, ...scroll });
    await shot(page, `${vp}-rows-scrolled`);
  }
  if (on("search")) {
    // --- search typing
    await resetLT(page);
    if (vp === "phone") {
      // the search box is in the list bar on both widths
    }
    await search.scrollIntoViewIfNeeded().catch(() => {});
    const ts = Date.now();
    await search.pressSequentially("Replace", { delay: 0 });
    await page.waitForTimeout(1500);
    const sRows = await panel.locator(".hk-card-row.hk-row-task").count();
    emit({
      step: "search_type",
      tag,
      term: "Replace",
      ms_total: Date.now() - ts,
      rows_after: sRows,
      longtasks: await readLT(page),
    });
    await shot(page, `${vp}-search`);
    // a term with zero hits
    await search.fill("zzzzzz-no-hit");
    await page.waitForTimeout(800);
    emit({
      step: "search_none",
      tag,
      empty_shown: await panel.locator("ha-alert").count(),
    });
    // unicode term
    await search.fill("滤网");
    await page.waitForTimeout(800);
    emit({
      step: "search_unicode",
      tag,
      rows: await panel.locator(".hk-card-row.hk-row-task").count(),
    });
    await search.fill("");
    await page.waitForTimeout(800);
  }
  if (on("memory")) {
    // --- memory growth after repeated search cycles
    const h0 = await heapMB(page);
    for (let i = 0; i < 15; i++) {
      await search.fill("Clean");
      await search.fill("");
    }
    await page.waitForTimeout(1500);
    emit({
      step: "memory_cycle",
      tag,
      heap_before_mb: h0,
      heap_after_mb: await heapMB(page),
      nodes: await panelNodes(panel),
    });
  }
  if (on("change")) {
    // --- one change: how many nodes does one completion redraw?
    const floater = tasks.find(
      (t) => t.recurrence_type === "floating" && t.enabled !== false,
    );
    if (floater) {
      await resetLT(page);
      await panel.evaluate((el) => {
        const w = window as any;
        w.__mut = { added: 0, removed: 0, batches: 0 };
        const mo = new MutationObserver((recs) => {
          w.__mut.batches++;
          for (const r of recs) {
            w.__mut.added += r.addedNodes.length;
            w.__mut.removed += r.removedNodes.length;
          }
        });
        mo.observe(el.shadowRoot!, { childList: true, subtree: true });
        w.__mo = mo;
      });
      const tc = Date.now();
      await callService("home_keeper", "complete_task", {
        task_id: floater.id,
      });
      await page.waitForTimeout(4000);
      const mut = await page.evaluate(() => (window as any).__mut);
      emit({
        step: "one_change_redraw",
        tag,
        mutated: mut,
        longtasks: await readLT(page),
        waited_ms: Date.now() - tc,
      });
    }
  }
  if (on("layout")) {
    // --- layouts and groupings
    for (const layout of ["tiles", "board"]) {
      await setTaskLayout(page, layout);
      const sel = layout === "tiles" ? ".hk-tile" : ".hk-board-col";
      await resetLT(page);
      await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
      const t0 = Date.now();
      await panelLoc(page)
        .locator(sel)
        .first()
        .waitFor({ state: "attached", timeout: 180_000 });
      await page.waitForTimeout(3000);
      const p2 = panelLoc(page);
      emit({
        step: "layout",
        tag,
        layout,
        ms_to_first: Date.now() - t0,
        items: await p2
          .locator(layout === "tiles" ? ".hk-tile" : ".hk-board-col .hk-card")
          .count(),
        nodes: await panelNodes(p2),
        longtasks: await readLT(page),
      });
      await shot(page, `${vp}-${layout}`);
    }
    await setTaskLayout(page, "rows");
    for (const g of ["status", "area", "device", "integration"]) {
      await setLocal(page, "home-keeper.groupBy", g);
      await resetLT(page);
      const t0 = Date.now();
      await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
      const p2 = panelLoc(page);
      await p2
        .locator(".hk-group")
        .first()
        .waitFor({ state: "attached", timeout: 180_000 })
        .catch(() => {});
      await page.waitForTimeout(3000);
      const groups = await p2.locator(".hk-group").count();
      const openGroups = await p2.locator(".hk-group[open]").count();
      emit({
        step: "groupby",
        tag,
        group: g,
        ms: Date.now() - t0,
        groups,
        open_groups: openGroups,
        rows: await p2.locator(".hk-card-row.hk-row-task").count(),
        nodes: await panelNodes(p2),
        longtasks: await readLT(page),
      });
      if (g === "area") await shot(page, `${vp}-groupby-area`);
    }
    await setLocal(page, "home-keeper.groupBy", null);
  }
  if (on("filter")) {
    // --- scope filters through localStorage values the panel reads
    for (const f of ["due", "overdue", "upcoming", "completed"]) {
      await setLocal(page, "home-keeper.filter", f);
      await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
      const p2 = panelLoc(page);
      await p2
        .locator("#hk-search")
        .waitFor({ state: "attached", timeout: 60_000 });
      await page.waitForTimeout(2000);
      emit({
        step: "filter",
        tag,
        filter: f,
        rows: await p2.locator(".hk-card-row.hk-row-task").count(),
        alerts: await p2.locator("ha-alert").count(),
      });
    }
    await setLocal(page, "home-keeper.filter", null);
  }
  if (on("detail")) {
    // --- detail with a long history
    const heavy = [...tasks].sort(
      (a, b) => (b.completions?.length ?? 0) - (a.completions?.length ?? 0),
    )[0];
    if (heavy) {
      await resetLT(page);
      const t0 = Date.now();
      await page.goto(`/home-keeper/tasks/${heavy.id}`, {
        waitUntil: "domcontentloaded",
      });
      const p2 = panelLoc(page);
      await p2
        .getByText("History")
        .first()
        .waitFor({ state: "attached", timeout: 120_000 });
      await page.waitForTimeout(3000);
      emit({
        step: "detail_heavy_history",
        tag,
        completions: heavy.completions?.length,
        ms: Date.now() - t0,
        nodes: await panelNodes(p2),
        longtasks: await readLT(page),
      });
      await shot(page, `${vp}-detail-heavy`);
      await resetLT(page);
      const th = Date.now();
      await p2.getByText("History").first().click();
      await page.waitForTimeout(3000);
      emit({
        step: "history_tab_open",
        tag,
        ms: Date.now() - th,
        nodes: await panelNodes(p2),
        longtasks: await readLT(page),
        text_len: await p2.evaluate((el) => el.shadowRoot!.textContent!.length),
      });
      await shot(page, `${vp}-history-tab`);
    }

    // --- Settings sections
    for (const s of [
      "general",
      "cost",
      "profiles",
      "notifications",
      "transfer",
      "shopping",
      "problem",
    ]) {
      await resetLT(page);
      const t0 = Date.now();
      await page.goto(`/home-keeper/settings/${s}`, {
        waitUntil: "domcontentloaded",
      });
      await panelLoc(page)
        .locator(".hk-settings-layout")
        .waitFor({ state: "attached", timeout: 60_000 })
        .catch(() => {});
      await page.waitForTimeout(2500);
      emit({
        step: "settings",
        tag,
        section: s,
        ms: Date.now() - t0,
        nodes: await panelNodes(panelLoc(page)),
        longtasks: await readLT(page),
      });
      if (s === "profiles" || s === "cost")
        await shot(page, `${vp}-settings-${s}`);
    }

    // --- Add task form: pickers for area, device
    await page.goto("/home-keeper", { waitUntil: "domcontentloaded" });
    const p3 = panelLoc(page);
    await p3
      .locator(".hk-card-row.hk-row-task")
      .first()
      .waitFor({ state: "attached", timeout: 180_000 });
    await resetLT(page);
    const addBtn = p3
      .locator(
        '#add-task, [data-add-task], .hk-add-btn, button:has-text("Add"), ha-button:has-text("Add")',
      )
      .first();
    const t1 = Date.now();
    await addBtn
      .click({ timeout: 10_000 })
      .catch((e) =>
        emit({ step: "add_click_failed", tag, err: String(e).slice(0, 100) }),
      );
    await page.waitForTimeout(2500);
    emit({
      step: "add_form_open",
      tag,
      ms: Date.now() - t1,
      longtasks: await readLT(page),
      nodes: await panelNodes(p3),
    });
    await shot(page, `${vp}-add-form`);
  }
}

test.describe("panel with many tasks", () => {
  test.skip(ONLY === "card");
  test("vp-desktop", async ({ page }) => {
    test.skip(process.env.VP === "phone");
    test.setTimeout(1_500_000);
    await page.setViewportSize(DESKTOP);
    await panelPass(page, "desktop");
  });
  test("vp-phone", async ({ page }) => {
    test.skip(process.env.VP === "desktop");
    test.setTimeout(1_500_000);
    await page.setViewportSize(PHONE);
    await panelPass(page, "phone");
  });
});

async function ws(page: Page, msg: Record<string, unknown>): Promise<any> {
  return page.evaluate(
    (m) => (document.querySelector("home-assistant") as any).hass.callWS(m),
    msg,
  );
}

/** Make a storage dashboard with the given views. */
async function makeDash(
  page: Page,
  url: string,
  views: unknown[],
): Promise<void> {
  const dashes = await ws(page, { type: "lovelace/dashboards/list" });
  if (!dashes.some((d: any) => d.url_path === url)) {
    await ws(page, {
      type: "lovelace/dashboards/create",
      url_path: url,
      mode: "storage",
      title: url,
      require_admin: true,
      show_in_sidebar: false,
    });
  }
  await ws(page, {
    type: "lovelace/config/save",
    url_path: url,
    config: { views },
  });
}

async function cardPass(page: Page, vp: "desktop" | "phone"): Promise<void> {
  const tag = `${LABEL}-${vp}`;
  await instrument(page);
  await page.goto("/lovelace/0", { waitUntil: "domcontentloaded" });
  await page.locator("home-assistant").waitFor({ state: "attached" });
  await page.waitForTimeout(3000);
  const card = (extra: Record<string, unknown> = {}) => ({
    type: "custom:home-keeper-card",
    ...extra,
  });
  await makeDash(page, "hk-explore", [
    { title: "one-default", path: "one-default", cards: [card()] },
    { title: "one-max10", path: "one-max10", cards: [card({ max_items: 10 })] },
    {
      title: "five-default",
      path: "five-default",
      cards: [card(), card(), card(), card(), card()],
    },
    {
      title: "five-max5",
      path: "five-max5",
      cards: [
        card({ max_items: 5 }),
        card({ max_items: 5 }),
        card({ max_items: 5 }),
        card({ max_items: 5 }),
        card({ max_items: 5 }),
      ],
    },
    {
      title: "collapsed",
      path: "collapsed",
      cards: [card({ startsCollapsed: true })],
    },
  ]);
  for (const view of [
    "one-default",
    "one-max10",
    "five-default",
    "five-max5",
    "collapsed",
  ]) {
    const t0 = Date.now();
    await page.goto(`/hk-explore/${view}`, { waitUntil: "domcontentloaded" });
    const first = page.locator("home-keeper-card").first();
    await first.waitFor({ state: "attached", timeout: 120_000 });
    await first
      .locator(".hk-row, .hk-more, .hk-empty, ha-alert")
      .first()
      .waitFor({ state: "attached", timeout: 180_000 })
      .catch(() => {});
    const ms = Date.now() - t0;
    await page.waitForTimeout(3000);
    const cards = page.locator("home-keeper-card");
    const info = await cards.evaluateAll((els) =>
      els.map((e) => ({
        rows: e.shadowRoot?.querySelectorAll(".hk-row").length ?? -1,
        more:
          (
            e.shadowRoot?.querySelector(".hk-more") as HTMLElement | null
          )?.innerText?.trim() ?? null,
        height: Math.round(e.getBoundingClientRect().height),
        nodes: (window as any).__deep(e.shadowRoot!),
      })),
    );
    emit({
      step: "card",
      tag,
      view,
      cards: info.length,
      ms_to_first_row: ms,
      per_card: info.slice(0, 5),
      longtasks: await readLT(page),
      heap_mb: await heapMB(page),
    });
    await shot(page, `${vp}-card-${view}`);
  }
  // HA's own pages that read the to-do and the calendar entity.
  for (const [name, url, sel] of [
    [
      "todo_page",
      "/todo?entity_id=todo.home_keeper_tasks",
      "ha-check-list-item, mwc-list-item, ha-list-item, ha-md-list-item",
    ],
    ["calendar_page", "/calendar", "ha-full-calendar, ha-calendar"],
  ] as const) {
    await resetLT(page);
    const t0 = Date.now();
    await page.goto(url, { waitUntil: "domcontentloaded" });
    await page
      .locator(sel)
      .first()
      .waitFor({ state: "attached", timeout: 120_000 })
      .catch(() => {});
    await page.waitForTimeout(6000);
    emit({
      step: name,
      tag,
      ms: Date.now() - t0,
      longtasks: await readLT(page),
      heap_mb: await heapMB(page),
    });
    await shot(page, `${vp}-${name}`);
  }
  // The card editor: open the dashboard editor on the default card and read the preview.
  await page.goto("/hk-explore/one-default", { waitUntil: "domcontentloaded" });
  await page
    .locator("home-keeper-card")
    .first()
    .waitFor({ state: "attached", timeout: 120_000 });
  await page.waitForTimeout(3000);
  try {
    if (vp === "phone") {
      await page.mouse.click(PHONE.width - 28, 28);
      await page
        .getByText(/edit dashboard/i)
        .first()
        .click({ timeout: 10_000 });
    } else {
      await page
        .locator("hui-root ha-icon-button")
        .last()
        .click({ timeout: 15_000 });
    }
    await page
      .getByText(/edit dashboard|done/i)
      .first()
      .waitFor({ timeout: 5_000 })
      .catch(() => {});
    await page.waitForTimeout(1500);
    await resetLT(page);
    const t0 = Date.now();
    await page
      .locator("hui-card-options, hui-card-edit-mode")
      .first()
      .locator("ha-icon-button, ha-button, button")
      .first()
      .click({ timeout: 10_000 });
    await page
      .getByText(/edit/i)
      .first()
      .click({ timeout: 5_000 })
      .catch(() => {});
    await page.waitForTimeout(4000);
    emit({
      step: "card_editor_open",
      tag,
      ms: Date.now() - t0,
      longtasks: await readLT(page),
    });
    await shot(page, `${vp}-card-editor`);
  } catch (e) {
    emit({
      step: "card_editor_open_failed",
      tag,
      err: String(e).slice(0, 160),
    });
    await shot(page, `${vp}-card-editor-failed`);
  }
}

test.describe("card with many tasks", () => {
  test.skip(ONLY === "panel");
  test("card-desktop", async ({ page }) => {
    test.skip(process.env.VP === "phone");
    test.setTimeout(900_000);
    await page.setViewportSize(DESKTOP);
    await cardPass(page, "desktop");
  });
  test("card-phone", async ({ page }) => {
    test.skip(process.env.VP === "desktop");
    test.setTimeout(900_000);
    await page.setViewportSize(PHONE);
    await cardPass(page, "phone");
  });
});
