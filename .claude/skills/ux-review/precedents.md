# Precedent library — genre conventions

What users have been trained to expect by every other app in the genre. A senior
reviewer's edge is mostly this: knowing where users will look, what they'll call
things, and what the rest of the web has taught them — so a violation reads as
"users trained by other checkout flows will look for X here and not find it",
not as a taste preference.

**How to use (Stage 2).** Look up the brief's `surface_type` below. For each
finding candidate, ask whether a convention explains *why* it hurts — an
expectation break is stronger, more legible reasoning than a bare heuristic.
Also scan the list for conventions the app violates that the checklist didn't
surface. Discipline:

- A violated convention is a **candidate**, not automatically a finding — it
  still must slow or block *this persona's* goal, and `scope.out` still applies
  (a deliberate divergence stated in the brief is not a finding).
- Conventions describe the genre's dominant pattern, not a law. An app may break
  one deliberately *and well*; flag it only when the break costs orientation,
  trust, or task success.
- Cite the convention in the finding's `why it matters` ("every mainstream
  dashboard puts the range picker top-right; the persona will look there
  first").

Item format: **convention** — where users learned it; what violating it looks
like.

---

## guided-flow — checkout, signup, wizards, booking

### Layout & placement
- **Keep the order/booking summary persistently visible (right rail on desktop).** — Universal e-commerce pattern (Amazon, Shopify checkout, airline/hotel booking). Violation: the summary lives only at the top of a scrolling page and disappears by the time the user enters payment details.
- **Primary continue action bottom-right on desktop, full-width bottom on mobile.** — Near-universal checkout/wizard convention; matches reading direction and thumb reach. Violation: the primary CTA is centered, left-aligned, or floats mid-page, so users hunt for it after each section.
- **Collapse promo/coupon entry behind a "Have a promo code?" link, not an open field.** — Baymard checkout research. Violation: an always-open coupon box next to the total makes every user without a code feel they're overpaying and leave to hunt for one.
- **Show the full cost breakdown (subtotal, shipping, tax, total) before the final step.** — Baymard: surprise costs at checkout are the #1 cited abandonment reason. Violation: shipping/tax first appears after card details are entered.
- **Offer guest checkout as prominently as sign-in; never force account creation.** — Baymard: forced registration is a top abandonment cause. Violation: the only path past the cart is a "Sign in or Register" wall.
- **Anchor field errors inline at the field, with a top-of-page error summary linking down to each.** — GOV.UK Design System error-summary pattern. Violation: a lone toast says "There was a problem" with no pointer to which of 12 fields is wrong.

### Buttons & labels
- **Label the primary button with the outcome of the next step, not a generic verb.** — Form-design research (Wroblewski) and mainstream checkout copy: "Continue to payment", "Book now" — not "Submit"/"Next"/"OK". Violation: every step says "Submit", so users can't tell which click commits.
- **Reserve "Place order" / "Pay now" / "Confirm booking" for the single money-moving step — and never label that step "Next".** — Users rely on the label to know when they'll be charged. Violation: "Next" actually charges the card, or an early step says "Place order" and users think they've already paid.
- **Back/secondary actions visually subordinate to the primary (link or outline, never equal weight).** — Material / Apple HIG button hierarchy, carried into every mature checkout. Violation: "Back" and "Continue" are twin solid buttons and users click the wrong one.

### Progress & navigation
- **Show a labeled step indicator across the top of a multi-step flow.** — NN/g wizard pattern; "Cart → Shipping → Payment → Review". Violation: unlabeled dots or nothing, so users can't estimate remaining effort.
- **Going back — or editing an earlier step — never erases data entered elsewhere.** — Core wizard expectation (NN/g); mature checkouts return you to your place with everything intact. Violation: editing the shipping address wipes the filled payment fields.
- **Completed steps in the indicator are clickable to jump back and edit.** — Standard in GOV.UK-style and e-commerce wizards. Violation: the progress bar is decorative and the only way back is one screen at a time.
- **One primary question/decision per screen in long or branching flows.** — GOV.UK "one thing per page". Violation: address, shipping method, and gift options on one mega-page whose validation errors bury each other.
- **Partially entered data survives a closed tab or a resumed session.** — Cart/draft persistence is the norm in booking and commerce. Violation: reopening the site drops the selected dates and returns to search.

### Trust & payment
- **Trust signals (lock icon, card-brand logos, "secure checkout") sit next to the payment fields, not just the footer.** — Baymard trust-seal research. Violation: nothing near the card-number field says the form is safe.
- **Card inputs auto-format as you type (spacing, brand icon); never reject a pasted number over spaces.** — Stripe-era convention across modern payment forms. Violation: "4111 1111 1111 1111" errors with no live formatting or hint.
- **"Billing same as shipping" is a pre-checked shortcut, not two full duplicate forms.** — Universal checkout pattern; its absence is one of Baymard's most-cited friction points.

**Watch first — most likely to cause outright task failure:** forced account
creation with no guest path; back/edit destroying entered data; costs surfacing
only at the final screen.

---

## browse-search — listings, search results, faceted filtering, docs search

### Search box
- **Search sits top-center/top-right of the header, magnifier icon, submits on Enter.** — Universal pattern since the 2000s. Violation: search buried in a hamburger menu, or Enter does nothing.
- **Autocomplete/instant suggestions appear as the user types, with the match highlighted.** — Algolia-era standard on retailers and docs sites. Violation: a full query + Enter lands on an empty "type to search" page.
- **The typed query persists in the box after results load (and in the URL).** — Universal. Violation: the box resets to placeholder, so users can't see or refine what they searched.
- **On docs/developer sites, Cmd/Ctrl+K (or `/`) opens search.** — Normalized by Algolia DocSearch across thousands of docs sites. Violation: a docs site where the reflexive Cmd+K does nothing.

### Filters & facets
- **Filters live in a left rail on desktop; on mobile, behind a "Filters" button opening a sheet/tray over the results.** — Baymard product-list research and NN/g faceted search; Amazon/eBay-era muscle memory. Violation: filters below the results or on a separate page that loses the list.
- **Applied filters show as removable chips above the results, each with its own ×, plus a "Clear all".** — Baymard: sites that hide applied filters strand users debugging their own result set. Violation: the only record of active filters is re-opening the panel to find checked boxes.
- **Facet values carry live result counts ("Blue (128)"), and long lists truncate behind "Show more".** — Baymard/NN/g faceted search. Violation: users select a filter blind and land on zero results, or scroll 80 brand checkboxes.
- **Desktop filters apply immediately on toggle; an explicit "Show results" button belongs only on the mobile sheet.** — The converged pattern per Baymard/NN/g. Violation: desktop checkboxes that silently wait for an Apply click, so users think the click did nothing.

### Results & scanning
- **Result cards carry the decision info inline — image, title, price, rating + review count — before any click.** — Universal e-commerce pattern. Violation: comparison-shopping requires opening each item to see its rating or price.
- **A result count sits at the top of the list ("1,248 results") and updates live with filters.** — Baymard/NN/g. Violation: no count, so users can't tell whether three filters left 4 items or 400.
- **Sort control top-right of the results, labeled "Sort by", defaulting to relevance/featured, with the standard option set.** — Universal; users' mental model of the options comes from Amazon/eBay. Violation: a "Price: Low to High" default buries the best matches under clearance junk.
- **Pagination style matches the task: infinite scroll / "Load more" for casual browsing; numbered pages for precise, returnable sets (docs, parts catalogs).** — Baymard distinguishes these by task type. Violation: infinite scroll on a reference list makes "result #40" impossible to return to.

### Orientation & recovery
- **Breadcrumbs sit above the title with every ancestor clickable; the header logo always links home.** — Universal web conventions. Violation: dead breadcrumb text (or none) on a deep category page strands users who arrived from a search engine.
- **Query, filters, and sort are reflected in the URL — shareable, bookmarkable, back-button-safe.** — Universal. Violation: browser back after opening a product returns to an unfiltered page one.
- **Zero results offer real recovery: "did you mean…" spelling fix plus a broader-category link — never a bare dead end.** — Baymard zero-results research (generic "try different keywords" text gets ignored). Violation: "No results for 'snikers'" with no way forward.
- **On docs search, results group by type/section ("Guides", "API Reference"), not one flat list.** — DocSearch-era standard. Violation: changelog entries, reference pages, and blog posts interleaved with no visual distinction.

**Watch first — most likely to cause outright task failure:** applied filters
invisible/not removable; zero-results dead ends; a non-relevance sort default.

---

## monitoring — dashboards, admin consoles, status pages, analytics

### Page anatomy
- **KPI/summary cards run across the top, ordered left-to-right by importance — the decision-critical metric leftmost.** — Few, *Information Dashboard Design*; NN/g eye-tracking (attention lands top-left first). Violation: the north-star metric mid-row or last (or a cost metric in the hero slot) so a skimming reader never weights it correctly.
- **Top band = status/KPIs, middle = trends, bottom = detail tables.** — Few's at-a-glance layering, reused by Datadog/Grafana. Violation: a raw data table above the summary, forcing a scroll past detail to find the headline.
- **Global scope selectors (org, project, environment) live in a persistent header, above and separate from page-level filters; the left nav navigates, it never scopes data.** — Grafana/Datadog/AWS-console convention; NN/g complex-application guidance. Violation: a nav click that silently changes the applied account or date range.

### Time & scope controls
- **The date/time-range picker sits top-right, above the fold, and applies globally to everything below it.** — Universal (Google Analytics, Looker, Grafana, Mixpanel, Amplitude, Datadog). Violation: a per-chart-only picker, or a global control that silently scopes only some charts with no cue which.
- **Range presets (Today, 7d, 30d, MTD, Custom) come before a raw calendar, and the active range stays visible as a label.** — GA/Mixpanel/Looker convention. Violation: counting back 30 days on a calendar by hand, or no way to see which range is active.
- **"Vs. previous period" comparison is a toggle next to the range picker, not a separate report.** — GA/Amplitude/Mixpanel. Violation: mentally diffing two exports to see growth.
- **A "last updated" freshness stamp sits near the top (typically by the range picker), never buried in a footer.** — Universal ops/BI convention. Violation: no stamp on a live-looking view, so a flat line could mean "quiet" or "data stopped flowing".
- **Auto-refresh is a visible, user-controllable toggle near the time picker.** — Grafana/Datadog. Violation: a silent refresh yanks a zoomed chart back to default with no indication why.

### KPI cards & deltas
- **Every KPI carries a delta vs. the prior comparable period beside it, with an up/down arrow.** — Universal SaaS dashboard pattern (Stripe, GA, Mixpanel). Violation: a bare number — is 4,213 signups good or a 40% drop?
- **Delta color follows the metric's goodness direction, not the arrow's direction.** — Few's color semantics; Stripe/Datadog practice ("error rate ↓" is green; "revenue ↓" is red). Violation: a falling churn number colored red, reading as bad news when it's the win.
- **KPI cards click through to the underlying detail, often with a sparkline inline.** — GA/Mixpanel/Looker/Stripe-era convention. Violation: a dead-end number whose breakdown must be hunted through a separate menu.

### Charts & legends
- **Legends sit immediately adjacent to their chart (right or directly beneath), never shared across the page.** — Few's proximity principle; standard in Looker/Grafana/Tableau. Violation: one bottom-of-page legend for six charts above it.
- **The same entity keeps the same series color in every chart on the page.** — Few + Grafana/Datadog convention. Violation: "US" is blue in one chart and orange in the next, breaking the legend-by-memory users build while scanning.
- **Charts drill down: clicking a point/bar narrows into that slice's detail.** — GA/Mixpanel/Amplitude/Looker. Violation: charts that are inert images.
- **Time-series panels sharing an axis share a synchronized hover crosshair.** — Grafana/Datadog multi-panel convention. Violation: correlating 2pm across two adjacent graphs by eye.

### Status & alerting
- **Red/amber/green severity keeps red = worst, everywhere, ordered by severity in the scan direction.** — Statuspage-era convention across Datadog/PagerDuty/AWS Health. Violation: a swapped or inconsistent mapping that misleads an operator mid-incident.
- **The aggregate status banner sits at the very top of a status page, above per-component rows.** — Statuspage convention. Violation: reading every component row to infer overall health.
- **Active incidents/alerts pin above resolved history, with a count badge near the title/nav.** — Datadog/PagerDuty/Grafana. Violation: a live outage sorted under resolved items by ID.
- **Severity carries an icon/shape per level, never color alone.** — WCAG-driven convention adopted by Datadog/Grafana. Violation: color-only status dots, indistinguishable in grayscale or to colorblind users.

**Watch first — most likely to cause misreading (not just friction):** delta
color ignoring the metric's goodness direction; a missing/stale freshness stamp;
inconsistent severity color mapping.
