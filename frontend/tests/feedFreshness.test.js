import assert from "node:assert/strict";
import { test } from "node:test";
import { isFreshMessageFeed, getMessageFeedState, getPrimaryBookState, effectiveFeedStaleCutoff, getUnifiedBookState } from "../src/feedFreshness.js";

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
test("explicit primary integrity errors outrank missing or malformed book age", () => {
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
  }
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
    { best_ask: "",
  ];
  for (const patch of invalidTopOfBook) {
    assert.equal(getUnifiedBookState({ ...base, ...patch }, 3), "UNHEALTHY", JSON.stringify(patch));
  }
  assert.equal(getUnifiedBookState(null, 3), "UNKNOWN");
  assert.equal(getUnifiedBookState([], 3), "UNKNOWN");
});
