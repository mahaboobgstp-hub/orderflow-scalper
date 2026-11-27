export const DEFAULT_FEED_STALE_AFTER_SECONDS = 3;

export function isFreshMessageFeed(adapter, staleAfterSeconds) {
  if (!adapter || adapter.enabled === false || !adapter.connected || adapter.last_message_age_seconds == null) return false;
  const rawAge = adapter.last_message_age_seconds;
  if (typeof rawAge === "boolean" || (typeof rawAge === "string" && rawAge.trim() === "")) return false;
  const age = Number(rawAge);
  const rawCutoff = staleAfterSeconds == null || typeof staleAfterSeconds === "boolean"
    ? Number.NaN
    : Number(staleAfterSeconds);
  const cutoff = Number.isFinite(rawCutoff) && rawCutoff > 0
    ? Math.max(0.1, rawCutoff)
    : DEFAULT_FEED_STALE_AFTER_SECONDS;
  return Number.isFinite(age) && age >= 0 && age <= cutoff;
}

export function getPrimaryBookState(primary) {
  if (!primary || typeof primary !== "object") return "UNKNOWN";
  if (primary.connected === false) return "DISCONNECTED";
  if (primary.connected !== true) return "UNKNOWN";
  if (primary.synchronized !== true) return "UNSYNCHRONIZED";
  if (primary.stale === true) return "STALE";
  if (primary.healthy === true) return "HEALTHY";
  if (primary.healthy === false) return "UNHEALTHY";
  if (primary.stale === false) return "FRESH (LEGACY)";
  return "UNKNOWN";
}
