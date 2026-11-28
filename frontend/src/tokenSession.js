export function normalizeBackendBase(value) {
  return String(value ?? "").trim().replace(/\/$/, "");
}

export function tokenHeaderForBackend(token, tokenBoundBase, backendBase) {
  const currentBase = normalizeBackendBase(backendBase);
  const boundBase = normalizeBackendBase(tokenBoundBase);
  const normalizedToken = String(token ?? "").trim();
  if (!normalizedToken || !currentBase || currentBase !== boundBase) return {};
  return { "X-Control-Token": normalizedToken };
}
