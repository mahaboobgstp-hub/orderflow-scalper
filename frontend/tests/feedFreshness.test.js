import assert from "node:assert/strict";
import { test } from "node:test";
import { isFreshMessageFeed, getMessageFeedState, getUnifiedFeedMessageState, getPrimaryBookState, getPrimaryBookDisplayLabel, effectiveFeedStaleCutoff, getUnifiedBookState, normalizeFeedMonitorPayload, normalizeDiagnosticCounter, displayDiagnosticCounter } from "../src/feedFreshness.js";

test("fresh feed accepts finite nonnegative age inside the cutoff", () => {
  assert.equal(isFreshMessageFeed({ enabled: true, connected: true, last_message_age_seconds: 0.25 }, 3), true);
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: "2.5" }, "3"), true);
});

test("invalid message ages never appear fresh", () => {
  for (const age of [null, true, false, -0.1, Number.NaN, Number.POSITIVE_INFINITY, "invalid", "", "   "]) {
    assert.equal(isFreshMessageFeed({ enabled: true, connected: true, last_message_age_seconds: age }, 3), false, `age ${String(age)}`);
  }
});

test("positive stale cutoff uses the backend minimum clamp", () => {
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 0.08 }, 0.05), true);
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 0.1001 }, 0.05), false);
  assert.equal(effectiveFeedStaleCutoff(0.05), 0.1);
});

test("invalid or missing cutoff uses the backend three-second default", () => {
  for (const cutoff of [undefined, null, true, false, Number.NaN, Number.POSITIVE_INFINITY, 0, -1, "invalid", ""]) {
    assert.equal(effectiveFeedStaleCutoff(cutoff), 3);
    assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 2.5 }, cutoff), true, `cutoff ${String(cutoff)}`);
    assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 3.1 }, cutoff), false, `cutoff ${String(cutoff)}`);
  }
});

test("disconnected or disabled adapters never appear fresh", () => {
  assert.equal(isFreshMessageFeed({ enabled: false, connected: true, last_message_age_seconds: 0.1 }, 3), false);
  assert.equal(isFreshMessageFeed({ enabled: true, connected: false, last_message_age_seconds: 0.1 }, 3), false);
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: null }, 3), false);
});

test("per-adapter state distinguishes fresh, stale, and unknown age", () => {
  assert.equal(getMessageFeedState({ connected: true, last_message_age_seconds: 3 }, 3), "FRESH");
  assert.equal(getMessageFeedState({ connected: true, last_message_age_seconds: 3.01 }, 3), "STALE");
  for (const age of [null, undefined, true, Number.NaN, Number.POSITIVE_INFINITY, -1, "invalid", ""]) {
    assert.equal(getMessageFeedState({ connected: true, last_message_age_seconds: age }, 3), "AGE UNKNOWN", `age ${String(age)}`);
  }
});

test("per-adapter state distinguishes disabled, disconnected, and unknown connection", () => {
  assert.equal(getMessageFeedState({ enabled: false, connected: true, last_message_age_seconds: 0.1 }, 3), "DISABLED");
  assert.equal(getMessageFeedState({ enabled: true, connected: false, last_message_age_seconds: 0.1 }, 3), "DISCONNECTED");
  assert.equal(getMessageFeedState({ connected: "true", last_message_age_seconds: 0.1 }, 3), "UNKNOWN");
  assert.equal(getMessageFeedState(null, 3), "UNKNOWN");
  assert.equal(getMessageFeedState([], 3), "UNKNOWN");
  // A missing flag is supported for legacy adapters; explicit malformed values
  // must not be interpreted as enabled merely because they are truthy.
  for (const enabled of [null, 0, 1, "true", "false", {}, []]) {
    assert.equal(
      getMessageFeedState({ enabled, connected: true, last_message_age_seconds: 0.1 }, 3),
      "UNKNOWN",
      `enabled ${String(enabled)}`,
    );
  }
  assert.equal(getMessageFeedState({ connected: true, last_message_age_seconds: 0.1 }, 3), "FRESH");
});

test("unified per-symbol message freshness distinguishes fresh, stale, and unknown", () => {
  const valid = { exchange: "binance", symbol: "BTCUSDT", messages_received: 4, last_message_age_seconds: 3 };
  assert.equal(getUnifiedFeedMessageState(valid, 3), "FRESH");
  assert.equal(getUnifiedFeedMessageState({ ...valid, last_message_age_seconds: 3.01 }, 3), "STALE");
  for (const age of [null, undefined, true, Number.NaN, Number.POSITIVE_INFINITY, -1, "invalid", ""]) {
    assert.equal(getUnifiedFeedMessageState({ ...valid, last_message_age_seconds: age }, 3), "AGE UNKNOWN", `age ${String(age)}`);
  }
  assert.equal(getUnifiedFeedMessageState({ symbol: "BTCUSDT", last_message_age_seconds: 0.1 }, 3), "UNKNOWN");
  assert.equal(getUnifiedFeedMessageState({ exchange: "binance", last_message_age_seconds: 0.1 }, 3), "UNKNOWN");
});

test("primary book status requires explicit connectivity and synchronization", () => {
  assert.equal(getPrimaryBookState(null), "UNKNOWN");
  assert.equal(getPrimaryBookState({ connected: false, synchronized: true, stale: false, healthy: false }), "DISCONNECTED");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: false, stale: false, healthy: false }), "UNSYNCHRONIZED");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: true, stale: true, healthy: false }), "STALE");
});

test("primary healthy classification requires valid book age within effective cutoff", () => {
  const base = { connected: true, synchronized: true, stale: false, healthy: true, last_book_update_age_seconds: 0.2 };
  assert.equal(getPrimaryBookState(base), "HEALTHY");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: 3.1 }), "STALE");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: true }), "AGE UNKNOWN");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: Number.NaN }), "AGE UNKNOWN");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: -0.01 }), "AGE UNKNOWN");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: 0.08 }, 0.05), "HEALTHY");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: 0.11 }, 0.05), "STALE");
});

test("legacy primary freshness is not inferred without valid book-age evidence", () => {
  const legacy = { connected: true, synchronized: true, stale: false, last_book_update_age_seconds: 0.2 };
  assert.equal(getPrimaryBookState({ ...legacy, last_book_update_age_seconds: null }), "AGE UNKNOWN");
  assert.equal(getPrimaryBookState(legacy), "FRESH (LEGACY)");
  assert.equal(getPrimaryBookState({ ...legacy, last_book_update_age_seconds: 4 }), "STALE");
  assert.equal(getPrimaryBookState({ ...legacy, last_error: "integrity issue" }), "UNHEALTHY");
});
test("explicit primary integrity errors outrank stale and missing-age classifications", () => {
  const base = { connected: true, synchronized: true, stale: false };
  for (const age of [null, undefined, Number.NaN, "invalid"]) {
    assert.equal(
      getPrimaryBookState({ ...base, last_book_update_age_seconds: age, last_error: "depth integrity failure" }),
      "UNHEALTHY",
      `age ${String(age)} with explicit error`,
    );
    assert.equal(
      getPrimaryBookState({ ...base, last_book_update_age_seconds: age, integrity_error: "crossed book" }),
      "UNHEALTHY",
      `age ${String(age)} with integrity error`,
    );
    assert.equal(
      getPrimaryBookState({ ...base, stale: true, last_book_update_age_seconds: age, last_error: "depth integrity failure" }),
      "UNHEALTHY",
      `stale age ${String(age)} with explicit error`,
    );
    assert.equal(
      getPrimaryBookState({ ...base, stale: true, last_book_update_age_seconds: age, integrity_error: "crossed book" }),
      "UNHEALTHY",
      `stale age ${String(age)} with integrity error`,
    );
  }
  assert.equal(getPrimaryBookState({ ...base, stale: true, last_book_update_age_seconds: 4 }), "STALE");
  assert.equal(getPrimaryBookState({ ...base, last_book_update_age_seconds: null }), "AGE UNKNOWN");
});

test("unified book freshness requires valid age and non-crossed top of book", () => {
  const base = {
    synchronized: true,
    stale: false,
    integrity_error: null,
    age_seconds: 0.2,
    best_bid: 100,
    best_ask: 101,
  };
  assert.equal(getUnifiedBookState(base, 3), "HEALTHY");
  assert.equal(getUnifiedBookState({ ...base, age_seconds: 3.1 }, 3), "STALE");
  assert.equal(getUnifiedBookState({ ...base, stale: true }, 3), "STALE");
  assert.equal(getUnifiedBookState({ ...base, synchronized: false }, 3), "UNSYNCHRONIZED");
  assert.equal(getUnifiedBookState({ ...base, integrity_error: "crossed book" }, 3), "UNHEALTHY");
  assert.equal(getUnifiedBookState({ ...base, age_seconds: null }, 3), "AGE UNKNOWN");
  assert.equal(getUnifiedBookState({ ...base, age_seconds: Number.NaN }, 3), "AGE UNKNOWN");
  const invalidTopOfBook = [
    { best_bid: null },
    { best_ask: null },
    { best_bid: true },
    { best_ask: Number.POSITIVE_INFINITY },
    { best_bid: 0 },
    { best_bid: -1 },
    { best_bid: 101, best_ask: 101 },
    { best_bid: 102, best_ask: 101 },
    { best_bid: "bad" },
    { best_ask: "" },
  ];
  for (const patch of invalidTopOfBook) {
    assert.equal(getUnifiedBookState({ ...base, ...patch }, 3), "UNHEALTHY", JSON.stringify(patch));
  }
  assert.equal(getUnifiedBookState(null, 3), "UNKNOWN");
  assert.equal(getUnifiedBookState([], 3), "UNKNOWN");
});


test("primary book display label preserves classifier distinctions", () => {
  const cases = [
    ["HEALTHY", "SYNCHRONIZED & FRESH"],
    ["FRESH (LEGACY)", "SYNCHRONIZED & FRESH (LEGACY)"],
    ["STALE", "SYNCHRONIZED / STALE"],
    ["UNHEALTHY", "SYNCHRONIZED / UNHEALTHY"],
    ["AGE UNKNOWN", "SYNCHRONIZED / AGE UNKNOWN"],
    ["UNSYNCHRONIZED", "CONNECTED / WAITING FOR SYNC"],
    ["DISCONNECTED", "NOT CONNECTED"],
    ["UNKNOWN", "STATUS UNKNOWN"],
    [null, "STATUS UNKNOWN"],
  ];
  for (const [state, label] of cases) {
    assert.equal(getPrimaryBookDisplayLabel(state), label, `state ${String(state)}`);
  }
});


test("monitor payload safely normalizes malformed containers", () => {
  const empty = {
    payload: {
      mode: "Unknown",
      summary: { safety: "PUBLIC FEEDS ONLY" },
      unified_market_data: { books: {}, exchanges: {}, feeds: {} },
      exchange_connections: { exchanges: [] },
      primary_binance_demo_stream: {},
    },
    summary: { safety: "PUBLIC FEEDS ONLY" },
    unified: { books: {}, exchanges: {}, feeds: {} },
    adapterList: [],
    books: {},
    exchangeStats: {},
    feeds: {},
    primary: {},
  };
  assert.deepEqual(normalizeFeedMonitorPayload(null), empty);
  assert.deepEqual(normalizeFeedMonitorPayload([]), empty);
  const malformed = normalizeFeedMonitorPayload({
    summary: [],
    unified_market_data: [],
    exchange_connections: { exchanges: "not-an-array" },
    primary_binance_demo_stream: [],
  });
  assert.deepEqual(malformed.summary, { safety: "PUBLIC FEEDS ONLY" });
  assert.deepEqual(malformed.unified, { books: {}, exchanges: {}, feeds: {} });
  assert.deepEqual(malformed.adapterList, []);
  assert.deepEqual(malformed.books, {});
  assert.deepEqual(malformed.exchangeStats, {});
  assert.deepEqual(malformed.primary, {});
  assert.deepEqual(malformed.payload.summary, { safety: "PUBLIC FEEDS ONLY" });
  assert.equal(malformed.payload.mode, "Unknown");
  assert.deepEqual(malformed.payload.unified_market_data, { books: {}, exchanges: {}, feeds: {} });
  assert.deepEqual(malformed.payload.exchange_connections, { exchanges: [] });
  assert.deepEqual(malformed.payload.primary_binance_demo_stream, {});
});

test("monitor payload preserves valid fields while normalizing malformed list entries", () => {
  const primaryBook = { synchronized: true, stale: false, age_seconds: 0.2 };
  const payload = {
    mode: "PUBLIC_MARKET_DATA_PAPER_ONLY",
    summary: { fresh_message_feed_count: 2 },
    unified_market_data: {
      books: { "binance:BTCUSDT": primaryBook, "bad:entry": null },
      exchanges: { binance: { messages_received: 5 }, malformed: null },
      feeds: { "binance:BTCUSDT": { exchange: "binance", symbol: "BTCUSDT", messages_received: 3, last_message_age_seconds: 0.25 }, malformed: null },
    },
    exchange_connections: {
      exchanges: [{ exchange: "binance", connected: true }, null, ["unexpected"]],
    },
    primary_binance_demo_stream: { connected: true, synchronized: true },
  };
  const normalized = normalizeFeedMonitorPayload(payload);
  assert.notEqual(normalized.payload, payload);
  assert.equal(normalized.payload.mode, payload.mode);
  assert.deepEqual(normalized.payload.summary, { fresh_message_feed_count: 2, safety: "PUBLIC FEEDS ONLY" });
  assert.equal(normalized.summary.fresh_message_feed_count, 2);
  assert.equal(normalized.adapterList.length, 3);
  assert.deepEqual(normalized.adapterList[1], {});
  assert.deepEqual(normalized.adapterList[2], {});
  assert.equal(normalized.books["binance:BTCUSDT"], primaryBook);
  assert.deepEqual(normalized.books["bad:entry"], {});
  assert.equal(normalized.exchangeStats.binance.messages_received, 5);
  assert.deepEqual(normalized.exchangeStats.malformed, {});
  assert.equal(normalized.feeds["binance:BTCUSDT"].messages_received, 3);
  assert.equal(normalized.feeds["binance:BTCUSDT"].last_message_age_seconds, 0.25);
  assert.deepEqual(normalized.feeds.malformed, {});
  assert.equal(normalized.primary.connected, true);
});


test("monitor summary sanitizes malformed counters and non-string labels", () => {
  const normalized = normalizeFeedMonitorPayload({
    mode: { unexpected: "object" },
    summary: {
      exchange_adapter_count: "7",
      unified_book_count: -1,
      synchronized_book_count: true,
      fresh_message_feed_count: {},
      healthy_feed_count: "3.5",
      feed_errors: Number.POSITIVE_INFINITY,
      safety: ["unexpected"],
    },
  });
  assert.equal(normalized.payload.mode, "Unknown");
  assert.equal(normalized.summary.exchange_adapter_count, 7);
  assert.equal(normalized.summary.unified_book_count, 0);
  assert.equal(normalized.summary.synchronized_book_count, 0);
  assert.equal(normalized.summary.fresh_message_feed_count, 0);
  assert.equal(normalized.summary.healthy_feed_count, 0);
  assert.equal(normalized.summary.feed_errors, 0);
  assert.equal(normalized.summary.safety, "PUBLIC FEEDS ONLY");
});

test("diagnostic counter strings require decimal integer notation", () => {
  for (const raw of ["0x10", "1e2", "7.0", "+7", "-0", "-1", "Infinity", ""]) {
    assert.equal(normalizeDiagnosticCounter(raw), 0, `counter string ${JSON.stringify(raw)}`);
  }
  assert.equal(normalizeDiagnosticCounter("007"), 7);
  assert.equal(normalizeDiagnosticCounter(" 7 "), 7);
});

test("missing diagnostic counters display unavailable instead of zero", () => {
  assert.equal(displayDiagnosticCounter({}, "connection_attempt_count"), "--");
  assert.equal(displayDiagnosticCounter(null, "reconnect_count"), "--");
  assert.equal(displayDiagnosticCounter({ snapshot_count: null }, "snapshot_count"), 0);
  assert.equal(displayDiagnosticCounter({ sequence_gap_count: "004" }, "sequence_gap_count"), 4);
  assert.equal(displayDiagnosticCounter({ messages_received: "1e2" }, "messages_received"), 0);
});

test("unified invalid-symbol diagnostic counter is normalized when present", () => {
  const normalized = normalizeFeedMonitorPayload({
    unified_market_data: { invalid_symbol_message_count: "004" },
  });
  assert.equal(normalized.unified.invalid_symbol_message_count, 4);
  const malformed = normalizeFeedMonitorPayload({
    unified_market_data: { invalid_symbol_message_count: "1e2" },
  });
  assert.equal(malformed.unified.invalid_symbol_message_count, 0);
  const legacy = normalizeFeedMonitorPayload({ unified_market_data: {} });
  assert.equal(Object.hasOwn(legacy.unified, "invalid_symbol_message_count"), false);
});

test("legacy summary without fresh-message counter keeps healthy-count fallback", () => {
  const normalized = normalizeFeedMonitorPayload({
    summary: { healthy_feed_count: "2" },
  });
  assert.equal(Object.hasOwn(normalized.summary, "fresh_message_feed_count"), false);
  assert.equal(normalized.summary.healthy_feed_count, 2);
});

test("feed, exchange, adapter, and primary counters normalize safely", () => {
  const normalized = normalizeFeedMonitorPayload({
    primary_binance_demo_stream: {
      messages_received: " 007 ",
      sequence_gap_count: "1.5",
      snapshot_count: "0x10",
      connection_attempt_count: 4,
      invalid_depth_message_count: -2,
    },
    unified_market_data: {
      exchanges: { binance: { messages_received: "9" }, malformed: { messages_received: {} } },
      feeds: { "binance:BTCUSDT": { messages_received: "12" }, malformed: { messages_received: "1e2" } },
    },
    exchange_connections: {
      exchanges: [
        { reconnect_count: "3", messages_received: "5" },
        { reconnect_count: -1, messages_received: "NaN" },
      ],
    },
  });
  assert.equal(normalized.primary.messages_received, 7);
  assert.equal(normalized.primary.sequence_gap_count, 0);
  assert.equal(normalized.primary.snapshot_count, 0);
  assert.equal(normalized.primary.connection_attempt_count, 4);
  assert.equal(normalized.primary.invalid_depth_message_count, 0);
  assert.equal(normalized.exchangeStats.binance.messages_received, 9);
  assert.equal(normalized.exchangeStats.malformed.messages_received, 0);
  assert.equal(normalized.feeds["binance:BTCUSDT"].messages_received, 12);
  assert.equal(normalized.feeds.malformed.messages_received, 0);
  assert.equal(normalized.adapterList[0].reconnect_count, 3);
  assert.equal(normalized.adapterList[0].messages_received, 5);
  assert.equal(normalized.adapterList[1].reconnect_count, 0);
  assert.equal(normalized.adapterList[1].messages_received, 0);
});

test("public adapter lifecycle counters normalize while uptime durations remain separate", () => {
  const normalized = normalizeFeedMonitorPayload({
    exchange_connections: {
      exchanges: [{
        exchange: "bybit",
        connection_attempt_count: "4",
        successful_connection_count: "3",
        reconnect_count: "2",
        connected_duration_seconds: 12.5,
        last_connection_duration_seconds: 8.25,
      }],
    },
  });
  const adapter = normalized.adapterList[0];
  assert.equal(adapter.connection_attempt_count, 4);
  assert.equal(adapter.successful_connection_count, 3);
  assert.equal(adapter.reconnect_count, 2);
  assert.equal(adapter.connected_duration_seconds, 12.5);
  assert.equal(adapter.last_connection_duration_seconds, 8.25);
  const malformed = normalizeFeedMonitorPayload({
    exchange_connections: {
      exchanges: [{ connection_attempt_count: "1e2", successful_connection_count: -1 }],
    },
  });
  assert.equal(malformed.adapterList[0].connection_attempt_count, 0);
  assert.equal(malformed.adapterList[0].successful_connection_count, 0);
});

test("primary Binance stream last-session duration is preserved and legacy omission stays unavailable", () => {
  const normalized = normalizeFeedMonitorPayload({
    primary_binance_demo_stream: {
      connected: false,
      connected_duration_seconds: null,
      last_connection_duration_seconds: 6.75,
    },
  });
  assert.equal(normalized.primary.last_connection_duration_seconds, 6.75);
  const legacy = normalizeFeedMonitorPayload({
    primary_binance_demo_stream: { connected: false },
  });
  assert.equal(Object.hasOwn(legacy.primary, "last_connection_duration_seconds"), false);
});
