export const DEFAULT_FEED_STALE_AFTER_SECONDS = 3;

export function asRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function normalizeFeedMonitorPayload(rawPayload) {
  const payload = asRecord(rawPayload);
  const summary = asRecord(payload.summary);
  const unified = asRecord(payload.unified_market_data);
  const exchangeConnections = asRecord(payload.exchange_connections);
  const adapterList = asArray(exchangeConnections.exchanges).map(asRecord);
  const books = Object.fromEntries(
    Object.entries(asRecord(unified.books)).map(([key, book]) => [key, asRecord(book)]),
  );
  const exchangeStats = Object.fromEntries(
    Object.entries(asRecord(unified.exchanges)).map(([key, stats]) => [key, asRecord(stats)]),
  );
  const primary = asRecord(payload.primary_binance_demo_stream);
  return { payload, summary, unified, adapterList, books, exchangeStats, primary };
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
  if (primary.stale === true) return "STALE";
  if (primary.stale !== false) return "UNKNOWN";
  // An explicit integrity/runtime error takes precedence over missing age data.
  if (primary.integrity_error || primary.last_error) return "UNHEALTHY";

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
