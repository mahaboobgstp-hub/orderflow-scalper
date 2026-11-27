# Phase A — Live Feed Monitoring & Certification Contract

**Mode:** public market-data only; demo stream; no exchange orders or paper-session activation.

## Primary Binance demo stream diagnostics

The read-only endpoint `GET /api/market-data/status` and consolidated `GET /api/market-data/observability` expose the primary Binance demo depth stream metrics. Additive fields must remain compatible with existing consumers.

| Field | Definition |
|---|---|
| `stale_after_seconds` | Feed freshness cutoff (default 3 seconds). |
| Primary Binance stream cutoff normalization | Invalid, non-finite, boolean, or nonpositive values fall back to 3 seconds; positive values below 0.1 seconds clamp to 0.1 seconds. |
| `last_event_age_seconds` | Age of the most recently received WebSocket depth message (diagnostic only). |
| `last_book_update_age_seconds` | Age of the most recent validated REST snapshot or accepted live depth event that advanced the order-book sequence; snapshot time is the freshness baseline until a progressing event arrives. |
| `stale` | True when disconnected, unsynchronized, no validated snapshot/live freshness baseline exists, or baseline age exceeds the cutoff. |
| `fresh` | Logical inverse of `stale`; freshness alone does not imply connectivity or book synchronization. |
| `healthy` | True only while connected, synchronized, and the applied book is fresh. |
| `connected_duration_seconds` | Time since the current successful WebSocket connection began; resets on reconnect. |
| `synchronized_duration_seconds` | Time since the current snapshot bridge succeeded; clears on disconnect or sequence gap. |
| `connection_attempt_count` | WebSocket connection attempts, including failed handshakes. |
| `successful_connection_count` | Successfully opened WebSocket sessions. |
| `reconnect_count` | Successful connections after the initial successful connection. |
| `recovery_count` | Successful snapshot-bridge synchronization events on a later connection. This is not incremented for snapshots alone. |
| `sequence_gap_count` | Sequence continuity failures detected after synchronization or when snapshot-bridge application fails. |
| `invalid_depth_message_count` | Malformed depth frames or depth payloads rejected before book mutation (including empty bid-and-ask updates). |
| `last_disconnect_reason` | Most recent observed connection end or recovery-triggering failure. |

A snapshot is not considered synchronized merely because an event's IDs span the snapshot bridge. The bridge event must also be successfully applied. **For USD-M Futures, the first bridge event must satisfy `U <= snapshot.lastUpdateId <= u` (not the Spot `lastUpdateId + 1` rule). Its `pu` is not compared to the REST snapshot's `lastUpdateId`, because `pu` refers to the previous WebSocket event.** Subsequent events must contain `pu` and enforce `pu == previous event's u`; frames without `pu` are rejected (no fallback to U/u overlap for live continuity). A failed bridge application leaves the book unsynchronized and forces snapshot recovery.
The read-only order-book endpoint must refuse data when the stream is disconnected or unsynchronized, or when neither a validated REST snapshot nor an accepted sequence-progress event has established a freshness baseline within the stale cutoff. Raw message receipt and duplicate/old sequence events must not refresh usable-book freshness.

## Frontend and API contract

Feed Monitor labels connected time separately from synchronized time, shows freshness classification, attempts/successes, reconnect/recovery counts, REST snapshot count, sequence gaps, and last disconnect reason. Missing metrics from an older API payload use safe display fallbacks. The deterministic API contract test calls the consolidated observability route with stubs and asserts the Phase A fields and public-feed-only execution flag.

## Feed summary metric definitions

The consolidated observability summary separates recent message receipt from fully healthy order books:
- `fresh_message_feed_count`: enabled/connected feed adapters whose latest message age is within the configured stale threshold. It does not imply book synchronization.
- Backend summary counts require adapter records to be dictionaries and `connected` to be the literal boolean `true`, matching the frontend classifier; truthy strings or integers do not count as connected. Malformed adapter entries are skipped for freshness counts and counted in `feed_errors`.
- `feed_errors` counts each adapter record at most once when it reports `last_error`, has a non-boolean/missing `connected` status, or supplies a malformed explicit `enabled` flag. The legacy omitted `enabled` flag is allowed. A malformed exchange-adapter container counts as one schema error; invalid message age alone is freshness data, not an adapter error.
- `healthy_feed_count`: fresh-message adapters whose matching `exchange:symbol` book is synchronized, explicitly non-stale, has no integrity error, and has a valid finite nonnegative `age_seconds` within the effective stale cutoff. Missing or malformed book-age values are excluded from the healthy count.
- Message ages must be finite and nonnegative. Invalid message ages are excluded. Invalid/nonpositive stale cutoffs fall back to 3 seconds, and positive cutoffs below 0.1 seconds clamp to 0.1 seconds. Backend summary counting and the frontend message-freshness helper apply the same cutoff policy as the unified engine; malformed diagnostics cannot falsely report fresh feeds.
- `synchronized_book_count`: books marked synchronized and explicitly fresh, with no integrity error and an independently validated `age_seconds` within the effective stale cutoff. The summary does not rely on a stale flag alone.
- Unified exchange message activity includes trades and depth messages, but order-book freshness timestamps advance only on depth/snapshot updates; trade-only activity must not mask a stale book.
Older UI/API consumers may fall back to the previous `healthy_feed_count` value for the connected-feed tile; new consumers should use `fresh_message_feed_count` for message freshness and `healthy_feed_count` only for full book health.

## Evidence required for certification

CI validates deterministic synchronization, sequence and stale-state logic only. It does not count as live exchange evidence.

Operational certification requires independently observed public endpoint samples showing real incoming depth events, fresh synchronized book, continuous sequence, recovery following an actual disconnect/gap, message age within threshold, stable uptime across sustained observation, and documented exchange/symbol coverage. Capture at least hourly uptime, reconnects, gaps, message age, and feed coverage checkpoints. Any DNS/API access failure is a blocker, not a pass.

Paper performance is a separate track and requires a user-controlled paper session, execution disabled, persisted simulated trades, at least 100 closed paper trades over at least 14 days, adequate market-regime coverage, and validated after-fee performance metrics. Passing Phase A feed checks alone does not prove profitability or readiness to trade.
## Depth collector termination and malformed-frame recovery

The Binance depth WebSocket collector must always signal its queue consumer when the stream ends, including normal close and malformed JSON/update-ID frames. The snapshot synchronization and live-update consumers treat this termination sentinel as a session end and return so the connection loop can reconnect and obtain a fresh snapshot. Malformed frames are rejected before they enter the synchronization queue, including string, float, or boolean ID values; missing or invalid `pu` values; negative IDs; and inverted `U`/`u` ranges; they cannot silently leave the consumer blocked waiting for events.
## REST snapshot integrity gate

The Binance REST depth snapshot is validated before replacing the in-memory book. Both sides must be lists of exact two-value rows containing finite positive prices and finite nonnegative quantities; boolean values and extra/missing row fields are rejected, and zero quantities are discarded. The snapshot update ID must be a nonnegative integer, and both bid and ask sides must be nonempty. Validation is atomic: if either side or the update ID is invalid, the previous book state is retained and the snapshot is rejected so the reconnect/recovery loop can retry. Deterministic tests cover malformed levels, non-finite values, negative prices/quantities, empty sides, invalid IDs, and preservation of the existing book.

## Live depth-event atomic integrity gate

Incoming depth diffs validate both bid and ask update arrays before changing the in-memory order book. Each level must be exactly a two-value row with a finite positive price and finite nonnegative quantity; booleans are rejected instead of being implicitly converted to numeric 0/1. An event with both bid and ask update arrays empty is rejected as a no-op, so it cannot advance the sequence or refresh freshness. The event is applied to copies of both sides, and only committed if both sides remain nonempty and the best bid is strictly below the best ask. Malformed, empty-side, crossed, or locked results are rejected without partial book mutation; the stream must reconnect and resynchronize rather than expose an integrity-compromised book. Rejected malformed depth messages increment `invalid_depth_message_count`; sequence gaps remain counted separately. This check is separate from update-ID continuity: invalid book content is not counted as a sequence gap.

## Unified-engine depth integrity and freshness guard

The unified engine normalizes its stale cutoff at construction using the same safe defaults as the primary stream: invalid, boolean, non-finite, or nonpositive values fall back to 3 seconds; positive values below 0.1 seconds clamp to 0.1 seconds. This prevents NaN or infinity from disabling book-staleness checks and keeps the effective threshold explicit for API/frontend classification.

The exchange-neutral unified market-data engine must not mark an order book fresh from malformed, non-finite, empty, crossed, locked, or non-progressing depth data. Snapshot and delta levels are validated as exact two-value rows containing finite positive prices and finite nonnegative quantities. Updates are applied to copies of both sides and committed together only when both sides remain populated and the best bid is strictly below the best ask. Rejected payloads preserve the last accepted arrays and book timestamp, set the book unsynchronized/stale with an integrity error, and increment message activity without refreshing usable-book freshness. Bybit deltas are accepted only after a valid snapshot and a strictly increasing update ID; this engine does not claim gap-free sequence continuity from Bybit's update ID alone. Unbridged Binance depth diffs are not applied by this exchange-neutral engine and cannot refresh book freshness. Trade prices and quantities must be finite and positive; malformed trade fields are discarded without invalidating or refreshing the order book.

## Unified-engine retained-depth bound

The exchange-neutral engine's `max_levels` is a per-side in-memory bound, not merely an output-display limit. Snapshots and accepted deltas retain the nearest bid levels (highest prices) and nearest ask levels (lowest prices) up to the configured cap. The best bid/ask and integrity checks are evaluated before trimming, and the cap must be a positive integer. This keeps depth state bounded while preserving the top of book. Tests verify both snapshot and delta trimming and invalid cap rejection.


## Database status endpoint is read-only

`GET /api/database/status` performs a read-only connectivity check against `engine_state` and returns cached status fields. It does **not** write an `engine_heartbeat` row. The response keeps `heartbeat_write_verified` for compatibility, set to `null` because no write was attempted, and reports `diagnostic_mode: read_only`. Heartbeats remain lifecycle/periodic writes and must not be triggered by a GET diagnostic.
## Bounded REST snapshot synchronization buffer

The primary Binance depth collector buffers WebSocket depth frames while the REST snapshot is loading. The buffer is bounded to **1,000 events**. If the queue fills, the collector drops the incomplete buffered sequence, increments `snapshot_buffer_overflow_count`, records a recovery reason, and inserts the termination sentinel. The consumer must not synchronize from a partial buffer; it returns and the connection loop obtains a new REST snapshot. If the stream ends while a full queue prevents inserting the termination sentinel, the collector likewise discards the queued partial sequence, increments the overflow counter, and signals termination without blocking. The Feed Monitor exposes this counter. Buffer overflow is a recovery event, not a sequence gap or malformed-frame count.


## Primary Binance retained-depth bound

The primary demo-stream snapshot_limit accepts only Binance USD-M Futures depth limits 5, 10, 20, 50, 100, 500, or 1000. Invalid values are rejected during stream construction rather than sent to REST. The initial snapshot and accepted depth updates retain the highest bid levels and lowest ask levels up to this limit, bounding in-memory book size per side. The API exposes snapshot_limit, and Feed Monitor displays the cap. Levels outside the retained cap are not tracked; the book is a bounded-depth view, not a claim of a full exchange book.


## Primary Feed Monitor frontend age gate

The frontend primary-book classification must not infer freshness from `healthy: true` or the legacy `stale: false` flag alone. It requires explicit connectivity and synchronization, an explicit non-stale flag, and a finite nonnegative `last_book_update_age_seconds` within the normalized stale cutoff. Missing or malformed age is displayed as `AGE UNKNOWN` and must not be counted as fresh. The legacy classification is retained only when valid book-age evidence is present. This is a UI defense-in-depth gate; the backend remains authoritative for book integrity.

## Primary Feed Monitor error precedence

For a connected and synchronized primary book with an explicit `integrity_error` or `last_error`, the frontend displays `UNHEALTHY` before stale-flag or age classification. Connectivity and synchronization states retain precedence; otherwise an explicit integrity/runtime error outranks `STALE`, and missing or malformed age alone displays `AGE UNKNOWN`. This avoids hiding known integrity/runtime failures behind a freshness-only label.


## Per-adapter freshness state in Feed Monitor

The Exchange Feed Connections panel labels each adapter's latest-message state separately from book health:
- `FRESH`: enabled/connected and message age is finite, nonnegative, and within the effective cutoff.
- `STALE`: enabled/connected but message age exceeds the effective cutoff.
- `AGE UNKNOWN`: connected but message age is absent or invalid.
- `DISCONNECTED`: explicitly disconnected.
- `DISABLED`: explicitly disabled.
- `UNKNOWN`: adapter payload or connection state is missing/invalid.

The top summary tile is labeled **Fresh Message Feeds**, because its count measures recent messages rather than merely connected sockets. These message-state labels do not imply a synchronized or healthy order book; book integrity remains displayed separately.

## Unified-book health display integrity gate

A normalized unified order book is counted as fresh/synchronized only when the API includes a finite nonnegative age within the effective cutoff and a valid two-sided top of book: finite positive best bid and best ask with best bid strictly below best ask. Missing or malformed top-of-book fields, a locked/crossed spread, or an explicit integrity error must not be counted as healthy. The Feed Monitor UI applies the same conservative classification and shows malformed top-of-book data as `UNHEALTHY`, instead of trusting `synchronized`/`stale` flags alone.

## Explicit adapter enabled-flag validation

The freshness classifier accepts an omitted 'enabled' flag for older adapter payloads (legacy default enabled), accepts only literal boolean true as explicitly enabled, and reports literal false as DISABLED. Any other explicit value (null, numeric, string, object, or array) is classified UNKNOWN and excluded from fresh-message counts. Backend and frontend apply the same rule so malformed adapter configuration cannot produce a false fresh-feed signal.


## Primary Binance depth-frame identity gate

The raw BTCUSDT depth collector requires every JSON frame to identify itself as `e: depthUpdate` and include a symbol matching the configured symbol (case-insensitive). Frames with a missing/invalid symbol or unexpected event type are rejected before entering the snapshot buffer or live book consumer, increment the invalid-depth counter, and terminate the collector so the stream loop reconnects and re-synchronizes. This prevents a structurally valid depth payload for another instrument or event channel from mutating the configured book. Tests cover missing fields, unexpected event type, wrong symbol, and accepted symbol case normalization.

## Snapshot-based freshness baseline for the primary depth stream

A successfully validated REST snapshot establishes the primary order-book freshness timestamp immediately after validation and atomic replacement. This is a usable baseline even if the first WebSocket bridge event overlaps the snapshot without advancing the snapshot update ID. A later accepted depth event that advances sequence replaces the baseline with its arrival time. Invalid snapshots do not change the prior book or freshness timestamp. The book remains unavailable until the bridge is successfully applied and synchronization is confirmed; the snapshot alone does not mark the stream synchronized.

## Overflow-safe numeric conversion in depth validation

REST snapshots and WebSocket depth levels are parsed atomically. Numeric conversion overflow (for example, an unbounded JSON integer that cannot be represented as a finite float) is treated as malformed level data and normalized to a validation `ValueError`, rather than escaping as an unexpected `OverflowError`. Rejected snapshots preserve the previously loaded book and snapshot count; rejected live updates preserve bids, asks, and update ID, and are counted as invalid depth messages.


## Fail-closed collector termination and buffer loss

When the primary Binance depth WebSocket collector terminates (normal close, malformed frame, or queue overflow), synchronized-book availability is invalidated before the termination sentinel is delivered. A snapshot bridge is not allowed to restore synchronization after the collector has already ended; the connection loop must reconnect and obtain a new snapshot. After the live collector has ended, queued events are not applied as if the stream were still active. Deterministic tests cover invalid-frame termination, bounded-buffer overflow, normal close, and a closed collector during snapshot bridging. This is fail-closed behavior: it preserves diagnostic freshness timestamps but prevents the read-only book endpoint from serving a book as synchronized.


## Primary-book display state mapping

The primary-book status label is derived from the freshness classifier instead of a fallback that labels every synchronized-but-not-healthy state as stale. This distinguishes `STALE`, `UNHEALTHY`, `AGE UNKNOWN`, `UNSYNCHRONIZED`, `DISCONNECTED`, healthy (including legacy freshness-only payloads), and unknown status to avoid overstating diagnostics.


## Feed Monitor payload-shape guard

The Feed Monitor normalizes the consolidated diagnostics payload before rendering. Non-object payload containers fall back to empty objects, non-array adapter collections fall back to empty lists, and malformed adapter/book/exchange-stat entries are normalized to empty objects. Valid diagnostic records are preserved. This prevents malformed or legacy schema shapes from crashing the monitor UI while keeping the existing unknown/empty-state behavior; it does not convert malformed records into fresh or healthy status.


## Feed Monitor summary counter normalization

The frontend normalizes optional summary counters before rendering. Present counters must be finite, safe, nonnegative integers; malformed values (including booleans, arrays/objects, negative values, fractions, and non-finite numbers) display as zero rather than being rendered as arbitrary objects or misleading counts. Numeric strings remain supported for legacy payload compatibility when they represent safe nonnegative integers. The optional `fresh_message_feed_count` field is preserved as absent when older payloads omit it so the UI can fall back to `healthy_feed_count`. Non-string `mode` and `safety` labels use safe text fallbacks.


## Live delta guard after synchronization invalidation

The live Binance depth consumer must re-check that the book remains synchronized before applying queued depth events. The collector invalidates synchronization in its termination handler before signaling the queue consumer; this ordering prevents a race where buffered events are consumed during the brief period before the collector task reports completion. Live event application also refuses to mutate the book while synchronization is invalidated. The snapshot bridge path is the only intentional exception and uses the separate overlap validation. This guard is not counted as a sequence gap or malformed payload because the session has already been invalidated and must reconnect for a fresh snapshot.


## Diagnostic counter string normalization

Frontend summary counters accept numeric values only when they are safe, nonnegative integers. Legacy string values are accepted only in trimmed decimal integer notation (digits only); hexadecimal, exponent, fractional, signed, negative, blank, boolean, object, and non-finite forms normalize to zero. This avoids JavaScript `Number()` coercions making malformed diagnostic counts look valid.
