function fnv1a32(input: string): string {
  let hash = 0x811c9dc5;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

export function createIdempotencyKey(scope: string, parts: unknown[]): string {
  const payload = parts
    .map((p) => {
      if (p === undefined || p === null) return "";
      if (typeof p === "string" || typeof p === "number" || typeof p === "boolean") return String(p);
      try {
        return JSON.stringify(p);
      } catch {
        return String(p);
      }
    })
    .join("|");
  return `wu-${scope}-${fnv1a32(`${scope}::${payload}`)}`;
}

export function createRandomRequestId(prefix = "wu"): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
