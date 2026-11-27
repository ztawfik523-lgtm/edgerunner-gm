export function safeStorageGet(key: string): string | null {
  try {
    return typeof window !== "undefined" && typeof window.localStorage?.getItem === "function"
      ? window.localStorage.getItem(key)
      : null;
  } catch {
    return null;
  }
}

export function safeStorageSet(key: string, value: string): void {
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.setItem === "function") {
      window.localStorage.setItem(key, value);
    }
  } catch {
    // ignore storage errors
  }
}

export function safeStorageRemove(key: string): void {
  try {
    if (typeof window !== "undefined" && typeof window.localStorage?.removeItem === "function") {
      window.localStorage.removeItem(key);
    }
  } catch {
    // ignore storage errors
  }
}

const memoryDrafts = new Map<string, string>();

const PREFIX = "redgm:draft:";

export function loadDraft<T>(key: string): T | null {
  const fullKey = `${PREFIX}${key}`;
  const raw = safeStorageGet(fullKey);
  if (raw) memoryDrafts.set(fullKey, raw);
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
  const serialized = JSON.stringify(value);
  memoryDrafts.set(fullKey, serialized);
  safeStorageSet(fullKey, serialized);
}

export function clearDraft(key: string): void {
  const fullKey = `${PREFIX}${key}`;
  memoryDrafts.delete(fullKey);
  safeStorageRemove(fullKey);
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
