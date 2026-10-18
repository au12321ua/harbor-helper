import { useCallback, useEffect, useRef, useState } from "react";
export function useLoad<T>(
  loader: () => Promise<T>,
  dependency = "",
  poll = 0,
) {
  const loaderRef = useRef(loader);
  const generation = useRef(0);
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [updatedAt, setUpdatedAt] = useState<number>();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);
  const load = useCallback(async (quiet = false) => {
    const token = ++generation.current;
    if (!quiet) setRefreshing(true);
    try {
      const value = await loaderRef.current();
      if (token !== generation.current) return;
      setData(value);
      setError(undefined);
      setUpdatedAt(Date.now());
    } catch (e) {
      if (token === generation.current) setError(e);
    } finally {
      if (token === generation.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);
  const reload = useCallback(() => load(), [load]);
  useEffect(() => {
    const requests = generation;
    let disposed = false;
    queueMicrotask(() => {
      if (!disposed) void load();
    });
    if (poll) {
      const id = setInterval(() => {
        if (document.visibilityState === "visible") void load(true);
      }, poll);
      return () => {
        disposed = true;
        requests.current++;
        clearInterval(id);
      };
    }
    return () => {
      disposed = true;
      requests.current++;
    };
  }, [load, dependency, poll]);
  return { data, error, loading, refreshing, reload, updatedAt };
}
