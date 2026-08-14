# SAuth Client Timeout Alignment Design

**Date:** 2026-08-14

## Problem

The Bot gives up on `POST /api/accounts/sauth/quick` after 30 seconds, while ACCC allows one five-account candidate group to run for up to 60 seconds. Production evidence from the latest 100 requests showed 73 successful backend requests, including 17 successes completed after the Bot timeout. Those requests consume an account and complete billing even though the user sees a timeout or instability message.

The proxy pool is not the bottleneck: it reported 96 idle proxies, no leaked leases, no queued requests, and no active logins when sampled. Recent backend failures were dominated by stored-account login rejection and captcha failures rather than proxy exhaustion.

## Decision

Increase the Bot-side SAuth HTTP timeout from 30 seconds to 65 seconds. Keep the ACCC request-group deadline at 60 seconds, leaving five seconds for CDN transit, response parsing, and scheduling overhead.

The Bot continues to make exactly one ACCC request per user command. It does not add retries.

## Preserved Backend Behavior

- ACCC tries at most five stored accounts sequentially.
- Each account uses a different direct proxy within the request group.
- Candidates one through three use direct proxies only.
- Candidates four and five try direct proxies first and use residential fallback only for eligible transient failures.
- Bridge capacity remains 10 active requests with 8 queued requests and a 100-proxy target pool.
- Bot single-flight and global admission controls remain enabled.

## Request Flow

1. The Bot admits one request for the user and acquires its bounded SAuth slot.
2. The Bot sends one HTTP request to ACCC with a 65-second timeout.
3. ACCC completes successfully or returns a structured failure within its 60-second group deadline.
4. The Bot formats the result or structured failure and releases both guards in `finally`.
5. A true transport timeout is reported only after 65 seconds.

## Error Handling

Existing status and error-code mapping remains unchanged. HTTP 429, structured 502, queue responses, and inventory responses continue to use their current user messages. The change only prevents the Bot from abandoning a backend request that is still valid within ACCC's documented deadline.

No account credentials, proxy addresses, API keys, or upstream response bodies are added to logs.

## Testing

- Add or update a focused Bot test proving the SAuth request uses a 65-second timeout.
- Preserve the existing assertion that one command creates one ACCC request with no Bot retry.
- Run the focused SAuth tests and the full Bot test suite.

## Deployment And Verification

Deploy only the Bot repository to `38.58.59.215`, restart `official-qqbot`, and verify `/health`. Confirm the running source uses 65 seconds, then observe production logs for SAuth completions between 30 and 60 seconds without Bot-side `transport_timeout` entries.

The ACCC code, proxy configuration, concurrency limits, inventory policy, and residential credentials are not changed by this deployment.
