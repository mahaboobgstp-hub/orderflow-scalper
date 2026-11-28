export const DEFAULT_FEED_STALE_AFTER_SECONDS = 3;

export function asRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeDiagnosticCounter(rawValue) {
  if (typeof rawValue === "number") {
    return Number.isSafeInteger(rawValue) && rawValue >= 0 ? rawValue : 0;
  }
  if (typeof rawValue !== "string") return 0;
  const value = rawValue.trim();
  // Legacy numeric strings are accepted only in decimal integer notation.
  // Number() alone also accepts hexadecimal, exponent, and fractional forms.
  if (!/^\d+$/.test(value)) return 0;
  const count = Number(value);
  return Number.isSafeInteger(count) && count >= 0 ? count : 0;
}

export function normalizeFeedMonitorPayload(rawPayload) {
  const payload = asRecord(rawPayload);
  const summary = { ...asRecord(payload.summary) };
  // Diagnostic counters must remain primitive, finite, nonnegative integers so
  // malformed API values cannot crash React or produce misleading UI counts.
  for (const field of [
    "exchange_adapter_count",
    "unified_book_count",
    "synchronized_book_count",
    "fresh_message_feed_count",
    "healthy_feed_count",
    "feed_errors",
  ]) {
    if (Object.hasOwn(summary, field)) summary[field] = normalizeDiagnosticCounter(summary[field]);
  }
  if (typeof summary.safety !== "string" || !summary.safety.trim()) {
    summary.safety = "PUBLIC FEEDS ONLY";
  }
  const unified = asRecord(payload.unified_market_data);
  const exchangeConnections = asRecord(payload.exchange_connections);
  const adapterList = asArray(exchangeConnections.exchanges).map(asRecord);
  const books = Object.fromEntries(
    Object.entries(asRecord(unified.books)).map(([key, book]) => [key, asRecord(book)]),
  );
  const exchangeStats = Object.fromEntries(
    Object.entries(asRecord(unified.exchanges)).map(([key, stats]) => [key, asRecord(stats)]),
  );
  const feeds = Object.fromEntries(
    Object.entries(asRecord(unified.feeds)).map(([key, feed]) => [key, asRecord(feed)]),
  );
  const primary = asRecord(payload.primary_binance_demo_stream);
  const normalizedPayload = {
    ...payload,
    mode: typeof payload.mode === "string" ? payload.mode : "Unknown",
    summary,
    unified_market_data: { ...unified, books, exchanges: exchangeStats, feeds },
    exchange_connections: { ...exchangeConnections, exchanges: adapterList },
    primary_binance_demo_stream: primary,
  };
  return { payload: normalizedPayload, summary, unified: normalizedPayload.unified_market_data, adapterList, books, exchangeStats, feeds, primary };
}

export function effectiveFeedStaleCutoff(rawCutoff) {
  if (rawCutoff == null || typeof rawCutoff === "boolean" || (typeof rawCutoff === "string" && rawCutoff.trim() === "")) {
    return DEFAULT_FEED_STALE_AFTER_SECONDS;
  }
  const cutoff = Number(rawCutoff);
  return Number.isFinite(cutoff) && cutoff > 0
    ? Math.max(0.1, cutoff)
    : DEFAULT_FEED_STALE_AFTER_SECONDS;
}

export function getMessageFeedState(adapter, staleAfterSeconds) {
  if (!adapter || typeof adapter !== "object" || Array.isArray(adapter)) return "UNKNOWN";
  if (adapter.enabled === false) return "DISABLED";
  if (adapter.enabled !== undefined && adapter.enabled !== true) return "UNKNOWN";
  if (adapter.connected === false) return "DISCONNECTED";
  if (adapter.connected !== true) return "UNKNOWN";

  const rawAge = adapter.last_message_age_seconds;
  if (rawAge == null || typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) {
    return "AGE UNKNOWN";
  }
  const age = Number(rawAge);
  const cutoff = effectiveFeedStaleCutoff(staleAfterSeconds);
  if (!Number.isFinite(age) || age < 0) return "AGE UNKNOWN";
  return age <= cutoff ? "FRESH" : "STALE";
}

export function getPrimaryBookDisplayLabel(state) {
  switch (state) {
    case "HEALTHY": return "SYNCHRONIZED & FRESH";
    case "FRESH (LEGACY)": return "SYNCHRONIZED & FRESH (LEGACY)";
    case "STALE": return "SYNCHRONIZED / STALE";
    case "UNHEALTHY": return "SYNCHRONIZED / UNHEALTHY";
    case "AGE UNKNOWN": return "SYNCHRONIZED / AGE UNKNOWN";
    case "UNSYNCHRONIZED": return "CONNECTED / WAITING FOR SYNC";
    case "DISCONNECTED": return "NOT CONNECTED";
    default: return "STATUS UNKNOWN";
  }
}


export function isFreshMessageFeed(adapter, staleAfterSeconds) {
  return getMessageFeedState(adapter, staleAfterSeconds) === "FRESH";
}

export function getPrimaryBookState(primary, staleAfterSeconds) {
  if (!primary || typeof primary !== "object") return "UNKNOWN";
  if (primary.connected === false) return "DISCONNECTED";
  if (primary.connected !== true) return "UNKNOWN";
  if (primary.synchronized !== true) return "UNSYNCHRONIZED";
  // Known integrity/runtime failures take precedence over a stale flag: stale is
  // a freshness diagnosis, while an error means the current book is unusable.
  if (primary.integrity_error || primary.last_error) return "UNHEALTHY";
  if (primary.stale === true) return "STALE";
  if (primary.stale !== false) return "UNKNOWN";

  const rawAge = primary.last_book_update_age_seconds;
  if (rawAge == null || typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) {
    return "AGE UNKNOWN";
  }
  const age = Number(rawAge);
  const cutoff = effectiveFeedStaleCutoff(staleAfterSeconds ?? primary.stale_after_seconds);
  if (!Number.isFinite(age) || age < 0) return "AGE UNKNOWN";
  if (age > cutoff) return "STALE";
  if (primary.healthy === true) return "HEALTHY";
  if (primary.healthy === false) return "UNHEALTHY";
  return "FRESH (LEGACY)";
}

export function getUnifiedFeedMessageState(feed, staleAfterSeconds) {
  if (!feed || typeof feed !== "object" || Array.isArray(feed)) return "UNKNOWN";
  const exchange = feed.exchange;
  const symbol = feed.symbol;
  if (typeof exchange !== "string" || !exchange.trim() || typeof symbol !== "string" || !symbol.trim()) return "UNKNOWN";
  const rawAge = feed.last_message_age_seconds;
  if (rawAge == null || typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) return "AGE UNKNOWN";
  const age = Number(rawAge);
  if (!Number.isFinite(age) || age < 0) return "AGE UNKNOWN";
  return age <= effectiveFeedStaleCutoff(staleAfterSeconds) ? "FRESH" : "STALE";
}

export function getUnifiedBookState(book, staleAfterSeconds) {
  if (!book || typeof book !== "object" || Array.isArray(book)) return "UNKNOWN";
  if (book.integrity_error) return "UNHEALTHY";
  if (book.synchronized !== true) return "UNSYNCHRONIZED";
  if (book.stale === true) return "STALE";
  if (book.stale !== false) return "UNKNOWN";

  const rawAge = book.age_seconds;
  if (rawAge == null || typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) {
    return "AGE UNKNOWN";
  }
  const age = Number(rawAge);
  const cutoff = effectiveFeedStaleCutoff(staleAfterSeconds);
  if (!Number.isFinite(age) || age < 0) return "AGE UNKNOWN";
  if (age > cutoff) return "STALE";

  const rawBid = book.best_bid;
  const rawAsk = book.best_ask;
  if (
    rawBid == null || rawAsk == null
    || typeof rawBid === "boolean" || typeof rawAsk === "boolean"
    || (typeof rawBid === "string" && rawBid.trim() === "")
    || (typeof rawAsk === "string" && rawAsk.trim() === "")
  ) return "UNHEALTHY";
  const bid = Number(rawBid);
  const ask = Number(rawAsk);
  if (!Number.isFinite(bid) || !Number.isFinite(ask) || bid <= 0 || ask <= 0 || bid >= ask) {
    return "UNHEALTHY";
  }
  return "HEALTHY";
}
