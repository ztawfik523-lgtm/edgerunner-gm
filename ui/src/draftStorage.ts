const memoryDrafts = new Map<string, string>();

const PREFIX = "redgm:draft:";

export function loadDraft<T>(key: string): T | null {
  const fullKey = `${PREFIX}${key}`;
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.getItem === "function") {
      const raw = window.localStorage.getItem(fullKey);
      if (raw) {
        memoryDrafts.set(fullKey, raw);
        return JSON.parse(raw) as T;
      }
    }
  } catch {
    // ignore storage errors
  }
  const mem = memoryDrafts.get(fullKey);
  if (!mem) return null;
  try {
    return JSON.parse(mem) as T;
  } catch {
    return null;
  }
}

export function saveDraft<T>(key: string, value: T): void {
  const fullKey = `${PREFIX}${key}`;
  try {
    const serialized = JSON.stringify(value);
    memoryDrafts.set(fullKey, serialized);
    if (typeof window !== "undefined" && typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(fullKey, serialized);
    }
  } catch {
    // ignore storage errors
  }
}

export function clearDraft(key: string): void {
  const fullKey = `${PREFIX}${key}`;
  memoryDrafts.delete(fullKey);
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.removeItem === "function") {
      window.localStorage.removeItem(fullKey);
    }
  } catch {
    // ignore storage errors
  }
}

export function clearAllDrafts(): void {
  memoryDrafts.clear();
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.length === "number") {
      for (let i = window.localStorage.length - 1; i >= 0; i -= 1) {
        const k = window.localStorage.key(i);
        if (k && k.startsWith(PREFIX)) {
          window.localStorage.removeItem(k);
        }
      }
    }
  } catch {
    // ignore storage errors
  }
}
