# Dashboard design record

## Scope and initial evidence

User request: install and use Ikaleio/skills `ikadesign3` and `v0-design-guidelines` to redesign the administration frontend and resource usage tables. Both installed under `C:/Users/Administrator/.codex/skills/`.

Host: FastAPI server-rendered HTML in `official_qqbot/control_api/app.py`. No React/Tailwind layer. Allowed changes: shared dashboard presentation, usage-data queries needed for correct displays, dashboard regression tests, design/review documentation. Bot message logic is outside this redesign.

Source samples: overview, limits (dense data), AI configuration (form), local disposable preview, light theme. Desktop 1440×900 and narrow 390×844. Sample values are explicitly demo data, never production claims.

### Measurements before redesign

| Role | Overview / limits observed computed values | Viewport |
|---|---|---|
| Page title | Inter, Arial, Microsoft YaHei, sans-serif; 34px, 700, 37.4px line height | 1440×900 |
| Section title | same family; 18px, 700, normal line height | 1440×900 |
| Body | same family; 16px, 400, normal line height | 1440×900 |
| Table headers/cells | 13px; header 700; padding 10px 12px | 1440×900 |
| Metric number | 26px (source CSS) | 1440×900 |
| Canvas / surface | #f6f5f1 / #ffffff | light |
| Text / secondary | #111111 / #666666 (table header) | light |
| Border / action | #ddd8ce / #050505 (source CSS) | light |
| Container padding | 28px 32px 60px | 1440×900 |
| Section gap | 18px | 1440×900 |
| Panel heading gap | 12px | 1440×900 |
| Main grid | 569px 569px | 1440×900 |
| Sidebar / content | 220px / 1220px computed outer width | 1440×900 |
| Narrow behavior | navigation becomes a tall full-width block, content starts below ~575px | 390×844 screenshot |
| Breakpoint | max-width 980px in source | source observation |
| Paragraph rhythm | not separately observed | — |

Observed issues: mobile navigation dominates the first viewport; text is small in dense tables; decorative chart alternatives misrepresent nested time-window counts; total usage and personal limits are visually juxtaposed without clear scope. Existing reusable classes retained where useful.

Design decision: five-color light operational interface (#2563eb, #172033, #64748b, #f5f7fb, #ffffff), system sans and identifier monospace, compact sidebar, flat evidence tables and explicit scope. No new frontend framework.

## Review

Scenario: resource limits, plus overview, AI configuration and login.
Input: a disposable SQLite preview with 18 visibly labeled demo users, three quota rules and 84 resource records. Production data was not used.
Viewport: 1440 × 900 and 390 × 844.
Theme: light; dark theme is not supported.
design.md version: 2026-10-05.
Generation context: shared shell, CSS and JavaScript were generated in a fresh subagent context from design.md and fixed integration requirements. Page composition and real data integration were implemented in the parent context.
Review method: running FastAPI application in the in-app browser, screenshots, read-only DOM/computed-style inspection, real form interactions, and the existing Python test runner.
Result: pass for the reviewed scope after one repair and recheck.

### Mechanical and rendered evidence

- Exactly one h1 on the measured limits and AI pages.
- Desktop limits: viewport 1440px, document scroll width 1425px. Narrow limits: viewport 390px, scroll width 375px. The difference is the scrollbar; neither document overflows horizontally.
- Computed desktop h1 28px, h2 17px, table cells/headers, labels and metadata 14px. Narrow h1 is intentionally 26px.
- All columns in all three limits tables have matching header/cell alignment; count columns align right.
- Mobile navigation starts collapsed, opens with its button and closes with Escape; focus returns to the button with a 2px blue outline.
- Actual resource + OpenID filtering returned the matching user's 4/5 used and 1 remaining. An unmatched query displayed the empty state and disabled pagination controls.
- Saving the existing demo rule returned the success notice and the persisted rule. The reset dialog focused Cancel; cancelling closed the dialog without clearing records.
- Login rejected an invalid demo token and accepted the valid preview token. AI controls have associated accessible labels. AI forms reflow without document overflow at 390px.
- Overview and AI configuration were visually inspected at desktop width; mobile AI and the limits rule editor were also inspected.
- The official bot suite passed: 221 tests in 16.842 seconds, including quota windows, literal wildcard filtering, pagination, validation, HTML escaping and existing bot behavior. JavaScript syntax checks and git diff whitespace checks passed.

### Repair and recheck

Violation / implementation error: `.mc-main:focus` suppressed the outline after keyboard activation of the skip link. The observed focused element was `main-content` with outline style `none`.

Repair: replaced the suppression with a visible 2px brand outline, inset 3px to stay inside the viewport. No design rule was missing: the existing focus requirement already covered this case.

Recheck: the same limits page at 390px showed `main-content` focused with `rgb(37, 99, 235) solid 2px`; no document overflow. The first output is retained separately from final screenshots. Review stopped after this recheck.

Deviations: AI configuration retains a full-width form and a following help panel to preserve the existing server-rendered composition. This is intentional. Mobile titles use 26px to fit narrow screens.

Open questions: none blocking the reviewed scope.

Limits: no production deployment or QQ-client review was performed in this frontend task. No external AI request or service restart was triggered. Loading behavior was reviewed in JavaScript rather than by inducing a slow external request. Large-volume production query latency and visual stress tests with unusually long identifiers were not measured. Pagination is covered by service tests; the browser sample fits on one page. This review does not claim design stability across untested browsers.

Local screenshot evidence (ignored preview artifacts):

- `.venv/dashboard-review/limits-before.jpg`
- `.venv/dashboard-review/limits-desktop.jpg`
- `.venv/dashboard-review/limits-mobile.jpg`
- `.venv/dashboard-review/usage-table.jpg`

Local preview: `http://127.0.0.1:9088/dashboard/limits`; its database and launcher are isolated under `.venv/`. `DASHBOARD_PREVIEW=1` displays the demo banner. Production templates use actual database values.
