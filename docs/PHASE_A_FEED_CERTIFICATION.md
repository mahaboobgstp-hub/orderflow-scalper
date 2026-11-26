# Phase A — Live Feed Monitoring & Certification Contract

**Mode:** public market-data only; demo stream; no exchange orders or paper-session activation.

## Primary Binance demo stream diagnostics

The read-only endpoint `GET /api/market-data/status` and consolidated `GET /api/market-data/observability` expose the primary Binance demo depth stream metrics. Additive fields must remain compatible with existing consumers.

| Field | Definition |
|---|---|
| `stale_after_seconds` | Feed freshness cutoff (default 3 seconds). |
| `last_event_age_seconds` | Age of the most recently received WebSocket depth message (diagnostic only). |
| `last_book_update_age_seconds` | Age of the most recent accepted event that advanced the order-book sequence. |
| `stale` | True when disconnected, unsynchronized, no accepted sequence progress has occurred, or applied-book age exceeds the cutoff. |
| `fresh` | Logical inverse of `stale`; freshness alone does not imply connectivity or book synchronization. |
| `healthy` | True only while connected, synchronized, and the applied book is fresh. |
| `connected_duration_seconds` | Time since the current successful WebSocket connection began; resets on reconnect. |
| `synchronized_duration_seconds` | Time since the current snapshot bridge succeeded; clears on disconnect or sequence gap. |
| `connection_attempt_count` | WebSocket connection attempts, including failed handshakes. |
| `successful_connection_count` | Successfully opened WebSocket sessions. |
| `reconnect_count` | Successful connections after the initial successful connection. |
| `recovery_count` | Successful snapshot-bridge synchronization events on a later connection. This is not incremented for snapshots alone. |
| `sequence_gap_count` | Sequence continuity failures detected after synchronization or when snapshot-bridge application fails. |
| `last_disconnect_reason` | Most recent observed connection end or recovery-triggering failure. |

A snapshot is not considered synchronized merely because an event's IDs span the snapshot bridge. The bridge event must also be successfully applied. **For USD-M Futures, the first bridge event must satisfy `U <= snapshot.lastUpdateId <= u` (not the Spot `lastUpdateId + 1` rule). Its `pu` is not compared to the REST snapshot's `lastUpdateId`, because `pu` refers to the previous WebSocket event.** Subsequent events must enforce `pu == previous event's u`. A failed bridge application leaves the book unsynchronized and forces snapshot recovery.
The read-only order-book endpoint must also refuse to return data when the stream is disconnected or when no accepted sequence-progress event has refreshed the book within the stale cutoff; raw message receipt or duplicate/old sequence events must not refresh usable-book freshness.

## Frontend and API contract

Feed Monitor labels connected time separately from synchronized time, shows freshness classification, attempts/successes, reconnect/recovery counts, REST snapshot count, sequence gaps, and last disconnect reason. Missing metrics from an older API payload use safe display fallbacks. The deterministic API contract test calls the consolidated observability route with stubs and asserts the Phase A fields and public-feed-only execution flag.

## Feed summary metric definitions

The consolidated observability summary separates recent message receipt from fully healthy order books:
- `fresh_message_feed_count`: enabled/connected feed adapters whose latest message age is within the configured stale threshold. It does not imply book synchronization.
- `healthy_feed_count`: fresh-message adapters whose matching `exchange:symbol` book is synchronized, fresh, and has no integrity error.
- Message ages must be finite and nonnegative. Invalid age values are excluded; invalid/nonpositive stale cutoffs fall back to the 3-second default so malformed diagnostics cannot falsely report fresh feeds.
- `synchronized_book_count`: books marked synchronized and fresh with no integrity error.
Older UI/API consumers may fall back to the previous `healthy_feed_count` value for the connected-feed tile; new consumers should use `fresh_message_feed_count` for message freshness and `healthy_feed_count` only for full book health.

## Evidence required for certification

CI validates deterministic synchronization, sequence and stale-state logic only. It does not count as live exchange evidence.

Operational certification requires independently observed public endpoint samples showing real incoming depth events, fresh synchronized book, continuous sequence, recovery following an actual disconnect/gap, message age within threshold, stable uptime across sustained observation, and documented exchange/symbol coverage. Capture at least hourly uptime, reconnects, gaps, message age, and feed coverage checkpoints. Any DNS/API access failure is a blocker, not a pass.

Paper performance is a separate track and requires a user-controlled paper session, execution disabled, persisted simulated trades, at least 100 closed paper trades over at least 14 days, adequate market-regime coverage, and validated after-fee performance metrics. Passing Phase A feed checks alone does not prove profitability or readiness to trade.
