# Administration layout revision

## Request and direction

The user rejected the first design as generic/AI-looking, cramped and bloated, and selected a modern product interface with clear hierarchy, moderate whitespace and refined presentation.

The design brief is a quiet white workspace with a restrained navigation rail, readable system sans typography and monospace identifiers. Palette: blue #2563eb, ink #20242c, muted #6b7280, canvas #f7f8fa, white #ffffff. Remove decorative English, taglines, repeated navigation cards and stacked summaries. Use section spacing to distinguish tasks instead of enclosing every section in a card.

Baseline evidence is recorded in design-review-2026-10-05.md. The current overview was also observed in the browser at its default wide viewport: oversized horizontal card surfaces and duplicated shortcut navigation amplified the user's concern. No change of frontend framework is needed.

## Functional composition

- Overview: three unboxed counts, a resource list with contextual usage links, and recent command activity.
- Resource limits: linked user-usage and rule views. The usage view starts with filters and the table; all-user duration totals remain available in a collapsed disclosure. The rule view has one disclosure per resource with current values and an inline editing form.
- Logs: command, outbound and audit views each use the full content width instead of three competing tables.
- Advertisement management: list first, a smaller editor second. Roles/bans use the same list/editor hierarchy.
- AI settings: readable configuration column plus a narrow explanation column; stack on mobile.

All totals, records, saving and filtering retain the real database and authenticated routes. Preview values are isolated demo data. No bot message logic is changed.

## Review record

Scenario: overview, resource usage, quota editing, AI configuration and advertisement management.
Input: the existing disposable local SQLite preview, visibly marked as demo data.
Viewport: 1440 × 900 and 390 × 844.
Theme: light only.
design.md version: 2026-10-05-r2.
Generation context: shared shell/CSS implemented by a fresh subagent using the revised design contract and fixed integration requirements; page composition and tests by the parent.
Review method: browser rendering, computed styles, native control interactions, existing Python suite.
Result: completed for the reviewed scope, after one repair/recheck cycle.
Violations: none remaining in the measured scope.
Deviations: usage rows measure about 78.5px with two text lines and meters; this preserves legible content. Small phone screens use horizontal scrolling inside the table instead of shrinking its text.
Open questions: user preference after seeing the revised result.
Limits: production deployment and external AI calls are outside this revision's verification.

### Evidence and repair

- Overview and limits rendered at 1440px and 390px, with one h1 and no document overflow. Overview h1 is 32px on desktop and navigation rail is 208px.
- Usage header/cell alignments match in all seven columns. The phone table is 809px within a 341px scroll region, with no document overflow.
- Real filtering returned one matching user with 4/5 used and 1 remaining. The rule disclosure prefilled the existing 4399 rule as 10 per hour; saving returned success and kept the rule view selected.
- The log view switched to management operations. Desktop advertisements show the list first and a narrow creation form second. Desktop and phone AI forms were visually inspected without making external requests.
- Mobile navigation opens, Escape closes it and returns focus with a 2px blue outline.
- Requirement issue found in the first phone rendering: resource identity/count/action crowded one line, and rule edit affordances wrapped independently. Repair: use two-level resource rows and a two-column rule summary. Rechecked with the same sample at 390px; controls stay inside the viewport and the edit action remains aligned with its resource.
- Implementation error: compact timestamps replaced the month/day separator instead of the date/time separator. Repaired using explicit date/time slices; rendered value is `10-05 00:20:17`.
- No new design rule was required: these repairs implement the existing responsive hierarchy requirement.
- 223 tests passed, including new tests for rule prefill, invalid-input retention without mutation, and selecting one log data source. JavaScript syntax and whitespace checks passed.

First and final screenshot evidence is preserved under ignored `.venv/dashboard-review-r2/`: `overview-first.jpg`, `overview-desktop.jpg`, `overview-mobile.jpg`, `usage-desktop.jpg`, `rules-mobile.jpg`.

The local preview runs at `http://127.0.0.1:9088/dashboard`. Its data remains explicitly labeled as a preview. No production deployment was attempted. Performance at production scale and other browser engines were not measured. The user's aesthetic acceptance remains an open question; rendered checks do not establish it.
