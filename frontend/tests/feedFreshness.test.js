import assert from "node:assert/strict";
import { test } from "node:test";
import { isFreshMessageFeed, getPrimaryBookState } from "../src/feedFreshness.js";

test("fresh feed accepts finite nonnegative age inside the cutoff", () => {
  assert.equal(isFreshMessageFeed({ enabled: true, connected: true, last_message_age_seconds: 0.25 }, 3), true);
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: "2.5" }, "3"), true);
});

test("invalid message ages never appear fresh", () => {
  for (const age of [null, true, false, -0.1, Number.NaN, Number.POSITIVE_INFINITY, "invalid", "", "   "]) {
    assert.equal(isFreshMessageFeed({ enabled: true, connected: true, last_message_age_seconds: age }, 3), false, `age ${String(age)}`);
  }
});

test("invalid or missing cutoff uses the backend three-second default", () => {
  for (const cutoff of [undefined, null, true, false, Number.NaN, Number.POSITIVE_INFINITY, 0, -1, "invalid", ""]) {
    assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 2.5 }, cutoff), true, `cutoff ${String(cutoff)}`);
    assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: 3.1 }, cutoff), false, `cutoff ${String(cutoff)}`);
  }
});

test("disconnected or disabled adapters never appear fresh", () => {
  assert.equal(isFreshMessageFeed({ enabled: false, connected: true, last_message_age_seconds: 0.1 }, 3), false);
  assert.equal(isFreshMessageFeed({ enabled: true, connected: false, last_message_age_seconds: 0.1 }, 3), false);
  assert.equal(isFreshMessageFeed({ connected: true, last_message_age_seconds: null }, 3), false);
});

test("primary book status distinguishes message freshness from book health", () => {
  assert.equal(getPrimaryBookState(null), "UNKNOWN");
  assert.equal(getPrimaryBookState({ connected: false, synchronized: true, stale: false, healthy: false }), "DISCONNECTED");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: false, stale: false, healthy: false }), "UNSYNCHRONIZED");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: true, stale: true, healthy: false }), "STALE");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: true, stale: false, healthy: true }), "HEALTHY");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: true, stale: false }), "FRESH (LEGACY)");
  assert.equal(getPrimaryBookState({ connected: true, synchronized: true, stale: false, healthy: false }), "UNHEALTHY");
});
