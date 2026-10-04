---
name: miracle-console-design
description: Presentation rules for Miracle's Chinese administration dashboard, dense data tables, and configuration forms on desktop and mobile.
version: 2026-10-05
---

## 1. Scope and Priority

- [MUST] Apply these rules to the administrative interface, including its sign-in screen; exclude bot messages and marketing content.
- [MUST] Prioritize truthful data, user requirements, accessibility, readable density, existing framework conventions, then decoration.
- [SHOULD] Use a light theme. Decision: no dark-theme requirement was provided.

## 2. Brand and Readers

- [SHOULD] Express precision through aligned table columns, tabular numerals, restrained borders, and explicit units. Decision: the task emphasizes operational tables.
- [SHOULD] Use short Chinese descriptions with direct action labels. Reserve English for the brand and compact supporting labels.
- [SHOULD] Support dense scanning on desktop and readable stacked sections on phones. Decision: observed mobile navigation previously consumed most of the first screen.

## 3. Page Structure and Composition

- [SHOULD] Use a persistent 232px navigation rail on desktops and a compact expandable navigation on screens below 900px. Decision: retain recognizable navigation while prioritizing content.
- [SHOULD] Place a thin context bar above a left-aligned page title, one explanatory sentence, and a small action area.
- [SHOULD] Compose overview pages from a single metric strip, primary evidence, and secondary navigation.
- [SHOULD] Compose dense data pages from summary metrics, one full-width evidence surface, then secondary editing controls. Avoid nesting cards inside that surface.
- [SHOULD] Compose forms as a readable main column and a smaller supporting column; stack them on narrow screens.
- [MUST] Keep tables horizontally scrollable inside their own region without overflowing the document.

## 4. Visual Rules

- [SHOULD] Use the five base colors defined in `dashboard.css`: brand `#2563eb`, ink `#172033`, muted `#64748b`, canvas `#f5f7fb`, surface `#ffffff`. Derive borders and state backgrounds with opacity. Decision: v0 palette constraint and readable operations-focused hierarchy.
- [SHOULD] Use a system sans family with Chinese system fallbacks; use a system monospace family only for identifiers. Decision: no remote font dependency is needed for this existing Python HTML application.
- [MUST] Keep body, controls, metadata, and table text at least 14px; use body line-height 1.5.
- [SHOULD] Set page titles to 28px/1.3/650, section titles to 17px/1.4/650, numeric metrics to 30px/1.2/650. Decision: prominent values without oversized dashboards.
- [MUST] Render counts with tabular numerals and align numeric column headers and cells to the right.
- [SHOULD] Use 8/12/16/24/32px spacing, 12px surface radii, 8px control radii, and subtle one-pixel borders. Decision: a compact consistent rhythm.
- [SHOULD] Keep static panels still on hover. Reserve state transitions for controls and navigable rows.
- [MUST] Show keyboard focus with a visible 2px brand outline and 3px offset.
- [MUST] Keep touch controls at least 40px high and give each an accessible name.
- [SHOULD] Use solid colors, no gradients, no decorative images or icon tiles. Decision: data is the primary visual material.
- [SHOULD] Use native progress meters only for ratios with matching numerator and denominator. Use bars for comparable independent counts. Never encode nested time windows as parts of one pie. Decision: preserve statistical meaning.
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
| Metrics | `.metrics`, `.metric` | `dashboard.css` | Compact counts and labels | Implemented |
| Tables | `.table-wrap`, `.numeric`, `.resource-name`, `.cell-note` | `dashboard.css` | Dense evidence | Implemented |
| Forms | `.stack-form`, `.inline-form`, `.form-grid-2`, `.field-note` | `dashboard.css` | Labeled controls and help | Implemented |
| Actions | `.button`, `.ghost`, `.danger`, `.actions` | `dashboard.css` | Links and native buttons | Implemented |
| Feedback | `.notice`, `.chip`, `.empty`, `.status-label` | `dashboard.css` | Explicit states, not ordinary metadata | Implemented |
| Data controls | `.table-toolbar`, `.segmented`, `.usage-meter`, `.comparison-bars` | `dashboard.css` | Filtering and quantitative comparisons | Implemented |
| Dialog | `.confirm-dialog` | `dashboard.css` | Destructive action confirmation | Implemented |

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
- [SHOULD] Avoid decorative icon tiles and colored icon backgrounds.
- [SHOULD] Avoid colors and typography outside the shared primitives.
- [MUST] Avoid small low-contrast primary information.
- [SHOULD] Avoid pill labels for ordinary metadata.
- [MUST] Do not imply a trend from a set of nested duration totals.

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
