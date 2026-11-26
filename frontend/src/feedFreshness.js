export const DEFAULT_FEED_STALE_AFTER_SECONDS = 3;

export function isFreshMessageFeed(adapter, staleAfterSeconds) {
  if (!adapter || adapter.enabled === false || !adapter.connected || adapter.last_message_age_seconds == null) return false;
  const rawAge = adapter.last_message_age_seconds;
  if (typeof rawAge === "string" && rawAge.trim() === "") return false;
  const age = Number(rawAge);
  const rawCutoff = staleAfterSeconds == null ? DEFAULT_FEED_STALE_AFTER_SECONDS : Number(staleAfterSeconds);
  const cutoff = Number.isFinite(rawCutoff) && rawCutoff > 0 ? rawCutoff : DEFAULT_FEED_STALE_AFTER_SECONDS;
  return Number.isFinite(age) && age >= 0 && age <= cutoff;
}
