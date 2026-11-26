# Phase A — Live Feed Monitoring & Certification Contract

**Mode:** public market-data only; demo stream; no exchange orders or paper-session activation.

## Primary Binance demo stream diagnostics

The read-only endpoint `GET /api/market-data/status` and consolidated `GET /api/market-data/observability` expose the primary Binance demo depth stream metrics. Additive fields must remain compatible with existing consumers.

| Field | Definition |
|---|---|
| `stale_after_seconds` | Feed freshness cutoff (default 3 seconds). |
| `last_event_age_seconds` | Age of the most recently received depth event. |
| `stale` | True if no depth event has been received or the event age exceeds the cutoff. |
| `fresh` | Logical inverse of `stale`; freshness alone does not imply connectivity or book synchronization. |
| `healthy` | True only while connected, synchronized, and fresh. |
| `connected_duration_seconds` | Time since the current successful WebSocket connection began; resets on reconnect. |
| `synchronized_duration_seconds` | Time since the current snapshot bridge succeeded; clears on disconnect or sequence gap. |
| `connection_attempt_count` | WebSocket connection attempts, including failed handshakes. |
| `successful_connection_count` | Successfully opened WebSocket sessions. |
| `reconnect_count` | Successful connections after the initial successful connection. |
| `recovery_count` | Successful snapshot-bridge synchronization events on a later connection. This is not incremented for snapshots alone. |
| `sequence_gap_count` | Sequence continuity failures detected after synchronization or when snapshot-bridge application fails. |
| `last_disconnect_reason` | Most recent observed connection end or recovery-triggering failure. |

A snapshot is not considered synchronized merely because an event's IDs span the snapshot bridge. The bridge event must also be successfully applied. **The first bridge event is validated by the `U`/`u` overlap rule; its `pu` is not compared to the REST snapshot's `lastUpdateId`, because `pu` refers to the previous WebSocket event.** Subsequent events must enforce `pu == previous event's u`. A failed bridge application leaves the book unsynchronized and forces snapshot recovery.

## Frontend and API contract

Feed Monitor labels connected time separately from synchronized time, shows freshness classification, attempts/successes, reconnect/recovery counts, REST snapshot count, sequence gaps, and last disconnect reason. Missing metrics from an older API payload use safe display fallbacks. The deterministic API contract test calls the consolidated observability route with stubs and asserts the Phase A fields and public-feed-only execution flag.

## Evidence required for certification

CI validates deterministic synchronization, sequence and stale-state logic only. It does not count as live exchange evidence.

Operational certification requires independently observed public endpoint samples showing real incoming depth events, fresh synchronized book, continuous sequence, recovery following an actual disconnect/gap, message age within threshold, stable uptime across sustained observation, and documented exchange/symbol coverage. Capture at least hourly uptime, reconnects, gaps, message age, and feed coverage checkpoints. Any DNS/API access failure is a blocker, not a pass.

Paper performance is a separate track and requires a user-controlled paper session, execution disabled, persisted simulated trades, at least 100 closed paper trades over at least 14 days, adequate market-regime coverage, and validated after-fee performance metrics. Passing Phase A feed checks alone does not prove profitability or readiness to trade.
