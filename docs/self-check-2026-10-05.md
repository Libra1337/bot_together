# Project self-check — 2026-10-05

## Verified

- Official bot: 216 offline regression tests passed, including native webhook authentication, full-group command routing, deduplication, Markdown normalization/fallback, images, resource quotas, control API, dashboard, and both compatibility bridges.
- NapCatQQ: 132 tests across five suites passed. Workspace TypeScript checks and ESLint passed after correcting 13 existing style/import-order findings.
- All Python sources in `official_qqbot`, `qqbot`, and `only-group-bot` compiled successfully; the isolated Python environment passed `pip check`.
- On the production host's Python 3.11 environment, a separate staging directory passed 39 routing, Markdown, webhook-authentication, and NoneBot compatibility tests. Production credentials/state were not used by these tests.
- Existing worker/API health endpoints and nginx configuration passed the pre-deployment checks.

## Changes and findings

The official `GROUP_MESSAGE_CREATE` event uses the same `1 << 25` intent as group @ and C2C events. QQ's **接收所有消息** setting must be enabled. Empty group allowlists now permit commands from all groups; populated lists still restrict by `group_openid`. Numeric QQ group numbers are not interchangeable with OpenIDs. Production had a numeric group number configured in both YAML and the environment; both entries must be cleared to enable all groups.

Full-group messages now process explicit commands and active follow-ups in the same conversation. Normal chat, images, and links do not fall through to AI, and ignored events do not suppress subsequent @ deliveries. Bot-authored messages are ignored. User IDs fall back to the documented `author.id` when `member_openid` is absent.

Markdown and its text fallback now remove leading empty lines, BOM, and zero-width spaces while preserving internal paragraphs and indentation. The most recent 1,000 production group/private outbound records had no leading whitespace. The reported fixed gap on every Markdown message therefore remains a QQ-client rendering question; automated payload tests do not verify the visual gap on an actual QQ client.

The Python webhook previously dispatched unauthenticated events. It now validates application identity and Ed25519 signatures over the original request bytes, while retaining the op-13 verification handshake. New NoneBot versions' overly strict optional fields are handled compatibly with QQ's documented payload.

Added a sample configuration and a disposable test runner. Corrected the README's reference to a nonexistent combined Linux installer.

## Scope limits

Offline tests mock external QQ, AI, mail, and resource services. They do not send live messages, consume accounts, generate billable images, or prove QQ-client rendering. The two legacy NapCat-backed Python bots received source compilation checks; they have no automated test suites in this repository and are not running on this production host.

## Reproduce

Use `python official_qqbot/run_tests.py` after installing the official bot requirements and the Koishi bridge's Node dependencies. The runner copies code into a temporary directory, supplies sample configuration, clears service-related environment overrides, and keeps test state separate from production. NapCatQQ checks are `pnpm typecheck`, `pnpm lint`, and `pnpm --filter napcat-test exec vitest run`.
