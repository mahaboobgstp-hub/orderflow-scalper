export const DEFAULT_FEED_STALE_AFTER_SECONDS = 3;

export function effectiveFeedStaleCutoff(rawCutoff) {
  if (rawCutoff == null || typeof rawCutoff === "boolean" || (typeof rawCutoff === "string" && rawCutoff.trim() === "")) {
    return DEFAULT_FEED_STALE_AFTER_SECONDS;
  }
  const cutoff = Number(rawCutoff);
  return Number.isFinite(cutoff) && cutoff > 0
    ? Math.max(0.1, cutoff)
    : DEFAULT_FEED_STALE_AFTER_SECONDS;
}

export function isFreshMessageFeed(adapter, staleAfterSeconds) {
  if (!adapter || adapter.enabled === false || !adapter.connected || adapter.last_message_age_seconds == null) return false;
  const rawAge = adapter.last_message_age_seconds;
  if (typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) return false;
  const age = Number(rawAge);
  const cutoff = effectiveFeedStaleCutoff(staleAfterSeconds);
  return Number.isFinite(age) && age >= 0 && age <= cutoff;
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
