# Layer 1 — Order Book Imbalance / Synchronization Validation

**Current status: validation in progress.** This document tracks software-only synchronization and detector testing. Certification is not a claim of predictive edge or profitability.

## Synchronization fix under test
The Binance futures diff-depth snapshot bridge now requires the first accepted event to span the next update ID after the snapshot (`snapshot lastUpdateId + 1`). Events already covered by the snapshot are discarded rather than marked synchronized.

## Test coverage
- Snapshot bridge: events fully covered by snapshot rejected; bridge/next-sequence accepted; future gap rejected.
- Snapshot state: missing update ID rejects bridge.
- Update application: bid/ask update, zero-quantity deletion, overlapping events, old events ignored.
- Sequence recovery: previous-update-ID mismatch and sequence gap reject updates and leave state unchanged.
- Invalid update payloads surface validation errors rather than silently mutating the book.
- Existing detector suite validates fresh/synchronized/non-crossed books, imbalance scoring, pressure persistence, invalid levels, and classification.

## Scope / remaining
- Unit tests are deterministic and offline.
- Network/reconnect, snapshot retry timing, live exchange sequence behavior, latency, data completeness, and spoofing resistance require controlled runtime validation and are not certified by these tests.
- No live order placement.
