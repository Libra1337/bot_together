# Screenshot-directed dashboard revision

## Source and design brief

User supplied two screenshots: a Miracle token login and a Miracle administration dashboard. They explicitly requested imitation of this direction after rejecting the previous layouts. These images supersede the earlier preference for open unboxed surfaces.

Reference copies are preserved locally at `.venv/dashboard-review-r3/reference-login.png` and `reference-dashboard.png`. They are reference evidence, not embedded UI assets. Browser chrome and screenshot data are not copied into the application.

Observed presentation: pale warm-gray page canvas, white lightly shadowed rounded cards, teal actions, compact title/subtitle bar, grouped left navigation with outline icons, small brand emblem, a centered login card, small metrics above a dominant chart and two smaller right-hand panels. The dashboard content is centered within the remaining width. The reference's account/IP inventory and health assertions are not data sources for this project.

Measurement limit: exact font families, computed CSS, responsive breakpoints and colors cannot be identified from screenshots. The screenshot files are 2560 × 1392; login card occupies a small centered portion. Implementation values are decisions: 224px navigation, 72px toolbar, 1400px maximum content width, 400px login card, 14px minimum text, 14px card radii, 20px section gaps, teal #0f807d, ink #25282b, muted #687078, canvas #f6f7f5 and white #ffffff.

## Functional correspondence

The six metrics use existing project data: recorded users, 24-hour acquisitions, 1-hour acquisitions, rules, managers and banned users. The chart uses real ResourceUsage records in disjoint minute/hour/day buckets, aligned to Beijing time, excluding future records. It does not reinterpret overlapping rolling totals as a trend. The current unfinished bucket is labeled. The right-hand actions navigate to real settings and the recent table contains actual resource acquisitions. Resource aggregates remain below the chart.

The chart has hover readings, a keyboard-operable time-point slider and a numeric table alternative. The login continues using existing authentication; the help text names the actual configuration variable.

## Review

Scenario: login, dashboard, trend controls, limits and AI configuration.
Input: existing isolated local preview database; visible demo banner.
Viewport: 1440 × 900 and 390 × 844.
Theme: light.
design.md version: 2026-10-05-r3.
Generation context: fresh-context subagent generated shell/CSS from design.md, fixed markup requirements and user-provided screenshots; parent implemented actual statistics/chart integration.
Method: screenshots, browser interactions, computed-style inspection and existing test suite.
Result: passed within the reviewed scope.
Violations: muted contrast and range default margin were repaired.
Deviations: the preview has a visible demo banner; metrics and recent rows use project-specific data rather than the screenshot inventory. Small screens scroll the chart within its panel to preserve readable labels.
Open questions: user's acceptance of visual similarity.
Limits: screenshot imitation is not pixel-exact; original DOM/fonts are unavailable. No production deploy or external AI requests are part of this validation.


### Rendered checks and repairs

- The 1440px login has exactly one h1 and a 400px centered card. The 390px login stays within the viewport and uses the same field/button/security-note hierarchy.
- Dashboard desktop has the six-card row, dominant trend panel and right action/recent-record column. Header has one h1. Desktop and phone document widths stay within their viewports.
- Daily/hourly controls load real corresponding buckets. Home/End keyboard operations on the slider update the reading from the first to last timestamp. Numeric details remain accessible without chart interpretation.
- Desktop limits and narrow rule views were visually reviewed. Existing labels, edit disclosures and table scopes remain intact.
- Contrast calculation found #727980 below 4.5:1 on white; changed the shared muted color to #687078. Browser review found the default range input margin causing four pixels of chart overflow; explicit margin:0 fixes it (rechecked 630px scroll width / 630px client width). Mobile page tabs now wrap instead of creating an unnecessary scroll container.
- Final official suite: 226 tests passed in 18.276 seconds, covering Beijing midnight, exact bucket boundaries, zero filling, exclusion of future records, selected interval and HTML escaping. JavaScript syntax and Python compilation passed.
- Local screenshots: `.venv/dashboard-review-r3/login-desktop.jpg`, `login-mobile.jpg`, `dashboard-desktop.jpg`, `dashboard-mobile.jpg`. The earlier incomplete render during concurrent stylesheet writing was not treated as a completed design output.

Deployment is explicitly authorized by the user's follow-up and recorded separately after verification.
