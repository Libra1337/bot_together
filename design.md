---
name: miracle-console-design
description: Presentation rules for Miracle's Chinese administration dashboard, dense data tables, and configuration forms on desktop and mobile.
version: 2026-10-05-r3
---

## 1. Scope and Priority

- [MUST] Apply these rules to the administrative interface, including its sign-in screen; exclude bot messages and marketing content.
- [MUST] Prioritize truthful data, user requirements, accessibility, readable density, existing framework conventions, then decoration.
- [SHOULD] Use a light theme. Decision: no dark-theme requirement was provided.

## 2. Brand and Readers

- [MUST] Follow the user's supplied login and dashboard screenshots: warm light-gray canvas, white bordered cards, teal accents, icon navigation and a compact title bar. The screenshots supersede the earlier open-surface direction.
- [SHOULD] Express precision through aligned table columns, tabular numerals, restrained borders, and explicit units.
- [SHOULD] Use short Chinese descriptions with direct action labels. Reserve English for the brand and compact supporting labels.
- [SHOULD] Support dense scanning on desktop and readable stacked sections on phones. Decision: observed mobile navigation previously consumed most of the first screen.

## 3. Page Structure and Composition

- [SHOULD] Use a 224px white navigation rail with grouped line icons, a top brand block and a bottom administrator block. Center main content at max-width 1400px, with 24–32px padding; collapse navigation below 900px.
- [MUST] Use one page heading. Omit decorative English eyebrows, repeated breadcrumbs, taglines and repeated descriptions.
- [SHOULD] Put the single page heading and its description in a white 72px top bar; place snapshot time, settings and sign-out at the right. Do not repeat a large heading inside the content.
- [SHOULD] Compose overview pages from a row of six compact metric cards, a primary time-series chart occupying about 60% width, and a secondary column with compact action rows above recent records. Put detailed resource evidence below.
- [SHOULD] Use underlined page tabs to separate different tasks. Keep filters adjacent to the table and editing forms out of the default browsing flow.
- [SHOULD] Use white cards with a one-pixel neutral border, 14px radius and a subtle shadow. Keep internal tables and forms flat. Use 20px between cards and 24px inside cards.
- [SHOULD] Compose forms as a readable main column and a smaller supporting column; stack them on narrow screens.
- [MUST] Keep tables horizontally scrollable inside their own region without overflowing the document.

## 4. Visual Rules

- [SHOULD] Use five base colors: brand `#0f807d`, ink `#25282b`, muted `#687078`, canvas `#f6f7f5`, surface `#ffffff`. Derive borders and state backgrounds with opacity. Use teal for actions, active navigation and primary chart lines; secondary series use ink/muted with distinct dash patterns.
- [SHOULD] Use a system sans family with Chinese system fallbacks; use a system monospace family only for identifiers. Decision: no remote font dependency is needed for this existing Python HTML application.
- [MUST] Keep body, controls, metadata, and table text at least 14px; use body line-height 1.5.
- [SHOULD] Set page titles to 18px/1.3/600, section titles to 17px/1.4/600, numeric metrics to 26px/1.2/600. Limit heading weights so the page does not become a wall of bold text.
- [MUST] Render counts with tabular numerals and align numeric column headers and cells to the right.
- [SHOULD] Use 8/12/16/24/32/40px spacing, 10px surface radii and 7px control radii. Use 32–40px between sections and 12–16px within related controls; avoid equal spacing between everything.
- [SHOULD] Keep static panels still on hover. Reserve state transitions for controls and navigable rows.
- [MUST] Show keyboard focus with a visible 2px brand outline and 3px offset.
- [MUST] Keep touch controls at least 40px high and give each an accessible name.
- [SHOULD] Use solid colors and restrained line icons. A small teal tinted brand emblem is permitted to match the reference. No ornamental illustration or invented status badges.
- [SHOULD] Use native progress meters only for ratios with matching numerator and denominator. Use chronological buckets for trends, with actual timestamps, counts and an accessible numeric alternative. Never encode nested time windows as parts of one pie.
- [MUST] Pair status colors with words; never communicate a status using color alone.
- [MUST] Provide visible empty, error, disabled, and loading states where applicable.
- [MUST] Disable nonessential transitions under `prefers-reduced-motion`.

## 5. Available Primitives

| Role | Implementation | Source | Usage | Status |
|---|---|---|---|---|
| Palette | `--brand`, `--ink`, `--muted`, `--canvas`, `--surface` | `official_qqbot/control_api/dashboard.css` | Shared colors only | Implemented |
| Shell | `render_layout(title, active, body)` | `official_qqbot/control_api/dashboard_ui.py` | Authenticated layouts | Implemented |
| Login | `render_login(error)` | `official_qqbot/control_api/dashboard_ui.py` | Sign-in layout | Implemented |
| Content | `.panel`, `.panel-head`, `.grid`, `.split`, `.span-2` | `dashboard.css` | Evidence and forms | Implemented |
| Metrics | `.mc-overview-stats`, `.metric` | `dashboard.css` | Compact counts and labels | Implemented |
| Tables | `.table-wrap`, `.numeric`, `.resource-name`, `.cell-note` | `dashboard.css` | Dense evidence | Implemented |
| Forms | `.stack-form`, `.inline-form`, `.form-grid-2`, `.field-note` | `dashboard.css` | Labeled controls and help | Implemented |
| Actions | `.button`, `.ghost`, `.danger`, `.actions` | `dashboard.css` | Links and native buttons | Implemented |
| Feedback | `.notice`, `.chip`, `.empty`, `.status-label` | `dashboard.css` | Explicit states, not ordinary metadata | Implemented |
| Data controls | `.table-toolbar`, `.usage-meter` | `dashboard.css` | Filtering and quantitative comparisons | Implemented |
| Dialog | `.confirm-dialog` | `dashboard.css` | Destructive action confirmation | Implemented |
| Page tabs | `.mc-tabs`, `.is-active` | `dashboard.css` | Linked task views | Implemented |
| Resource rows | `.mc-resource-list`, `.mc-resource-row` | `dashboard.css` | Resource identity, totals and a contextual action | Implemented |
| Trend | `.mc-trend-chart`, `.mc-chart-controls`, `.mc-chart-legend` | `dashboard.css`, `dashboard_trend.py` | Time series with accessible details | Implemented |
| Overview | `.mc-stat-grid`, `.mc-home-grid`, `.mc-home-side`, `.mc-action-list` | `dashboard.css` | Reference composition | Implemented |
| Disclosure | `.mc-disclosure`, `.mc-rule` | `dashboard.css` | Secondary details and inline rule editing | Implemented |

- [SHOULD] Extend page-specific compositions with `.mc-*` names. Decision: preserve existing shared selectors without adding a second theme.
- [MUST] Do not silently alter shared primitives from page-specific selectors.
- [SHOULD] Use native HTML and existing server-rendered forms. Decision: this application has no React or Tailwind stack.

## 6. Copy and Number Formats

- [MUST] Distinguish total counts from per-person quotas and give every ratio its denominator scope.
- [SHOULD] Format integers with thousands separators; display zero explicitly and unknown values as an em dash.
- [MUST] Label rolling durations precisely; do not label a rolling 24-hour count as a calendar-day count.
- [SHOULD] Show snapshot freshness with a timestamp instead of asserting unverified live synchronization.
- [MUST] Label preview/demo data visibly in preview environments; do not put invented production totals in product templates.

## 7. Anti-Patterns

- [SHOULD] Avoid centered hero sections in administration views.
- [SHOULD] Avoid cards inside cards and excessive empty columns.
- [SHOULD] Keep navigation icons unboxed. Reserve a tinted icon surface for the small brand emblem.
- [SHOULD] Avoid colors and typography outside the shared primitives.
- [MUST] Avoid small low-contrast primary information.
- [SHOULD] Avoid pill labels for ordinary metadata.
- [MUST] Do not imply a trend from a set of nested duration totals.

- [SHOULD] Center the sign-in card within the viewport on the warm gray canvas. Use a 400px card, brand emblem/name inside, a labeled token field, full-width teal button and a separated security note.

## 8. Implementation and Integration

- [SHOULD] Load shared CSS and JS through the existing server-rendered shell. Keep them in `official_qqbot/control_api/dashboard.css` and `dashboard.js`.
- [SHOULD] Use system fonts with explicit fallbacks and no third-party image assets. Decision: asset availability and Chinese rendering.
- [SHOULD] Keep the shared shell and login markup in `dashboard_ui.py`; retain shared presentation bindings in this document.

## Glossary

| Term | Meaning |
|---|---|
| Shell | Navigation, context bar, heading, content boundary |
| Evidence surface | One bounded table or comparison region |
| Snapshot | Displayed data as of the stated time |
| Metric | A labeled count with optional explanatory text |
| Usage meter | A bounded ratio with a meaningful denominator |
