import { useLayoutEffect, useMemo, useRef } from "react";

type HandlerMap = Record<string, (...args: never[]) => unknown>;

/**
 * Returns an object with the same keys whose functions keep a stable identity
 * across renders but always call the latest handler passed in. Lets memoized
 * children skip re-rendering when only the parent's closures changed.
 * The set of keys must not change between renders.
 */
export function useStableHandlers<T extends HandlerMap>(handlers: T): T {
  const latest = useRef(handlers);
  useLayoutEffect(() => {
    latest.current = handlers;
  });
  return useMemo(
    () =>
      Object.fromEntries(
        Object.keys(latest.current).map((key) => [
          key,
          (...args: unknown[]) => (latest.current[key] as (...a: unknown[]) => unknown)(...args),
        ]),
      ) as unknown as T,
    [],
  );
}
