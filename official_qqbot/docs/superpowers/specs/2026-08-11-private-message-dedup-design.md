# Official QQ Inbound Message Deduplication Design

Date: 2026-08-11

## Goal

Prevent one inbound QQ private message from executing a command and sending its response more than once, while preserving the existing behavior for group messages and messages that do not contain a stable message ID.

## Root Cause

The official group-message handler records each message before command processing, but the C2C handler has no equivalent check. The Koishi bridge also applies the existing check only to group events. When QQ retries a webhook delivery or the same private message reaches the bot through both official and Koishi ingress, each delivery independently calls `process_message`, so one user message can produce multiple responses.

The current webhook path waits for command processing before acknowledging the request. That can make retries more likely, but changing acknowledgement or outbound delivery would broaden the fix unnecessarily. The immediate defect is that repeated inbound events are not idempotent.

## Scope

Replace the group-only in-memory cache with a unified inbound-message cache used by:

- official QQ group messages;
- official QQ C2C messages; and
- Koishi bridge group and private messages.

This change does not alter command routing, outbound message sending, webhook acknowledgement behavior, message adapters, or persistent storage.

## Deduplication Identity

Each cached message uses these normalized event fields:

```text
message type + conversation identity + message ID
```

- Message type separates group and private namespaces.
- A group event uses `group_openid` as its conversation identity.
- A private event uses `user_openid` as its conversation identity.
- Message ID is the stable QQ message identifier exposed by either adapter.

The key deliberately excludes ingress source. The same QQ message arriving once through the official handler and once through Koishi must resolve to the same key and execute only once.

No content or timestamp hash is used. Two distinct messages with identical text remain distinct as long as QQ supplies distinct message IDs.

## Processing Flow

After an ingress-specific adapter has produced a normalized event:

1. Build the unified key from the normalized event.
2. Check and record that key synchronously, before the first `await` in the handler.
3. Stop processing when the key is already present.
4. Otherwise call `process_message` using the existing context and content.

Because cache registration contains no suspension point, concurrent asyncio tasks in the same bot process cannot both pass the check before either records the key.

Koishi duplicates keep the existing successful ignored response with reason `duplicate`. Official handler duplicates return without command execution, matching current group-message behavior. Duplicate log entries identify the event type, conversation, and message ID without logging full message content.

## Missing Message IDs

If an adapted event has no message ID, it is accepted and processed without being cached. This preserves current behavior and avoids suppressing legitimate messages using an unstable content-based fallback.

## Cache Bounds

Keep the existing process-local ordered cache and maximum size of 1,000 entries. Each accepted keyed event is appended, and the oldest entries are evicted when the limit is exceeded.

This is a bounded recent-message guard, not permanent persistence. A process restart clears it, and a duplicate delivered after eviction can be processed again. Those limits match the existing group-message contract and are sufficient for immediate duplicate deliveries and webhook retries.

## Tests

Add focused regression tests that verify:

- the same official C2C message ID is processed once when delivered twice;
- concurrent delivery of the same C2C message is processed once;
- the same C2C message delivered through official and Koishi ingress is processed once;
- messages without an ID continue to be processed;
- the existing official and Koishi group-message duplicate behavior remains unchanged.

Tests clear the shared inbound cache between cases so ordering and prior test state cannot affect results. The concurrent case blocks the first `process_message` call long enough to invoke the second handler while the first is still active, proving that registration occurs before command processing yields.

## Deployment And Rollback

Deploy the updated `official_qqbot/bot.py` and tests, restart the `official-qqbot` service on `154.44.31.213`, and inspect logs while sending one private command. Exactly one command execution and one response should appear for each message ID.

Rollback restores the previous group-only helper and handler calls. No database, configuration, protocol, or API migration is involved.

## Non-Goals

- Changing QQ webhook acknowledgement timing.
- Adding a distributed or persistent deduplication store.
- Retrying or deduplicating outbound messages.
- Inferring duplicates from message content or arrival time.
- Changing SAuth routing or the ACCC backend.

## Self-Review

- The design covers every current normalized inbound path without changing adapter or command semantics.
- Cross-ingress private duplicates share a key because ingress source is intentionally excluded.
- Group and private messages cannot collide because message type is part of the key.
- Concurrent duplicates are blocked because cache registration happens before any handler `await`.
- Cache growth remains bounded and missing-ID behavior is explicit.
- No unresolved placeholders or implementation decisions remain.
