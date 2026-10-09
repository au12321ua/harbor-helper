import { useCallback, useEffect, useState, useRef } from "react";
export function useLoad<T>(
  loader: () => Promise<T>,
  dependency = "",
  poll = 0,
) {
  const loaderRef = useRef(loader);
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);
  const reload = useCallback(async () => {
    try {
      setData(await loaderRef.current());
      setError(undefined);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload();
    if (poll) {
      const id = setInterval(() => {
        if (document.visibilityState === "visible") void reload();
      }, poll);
      return () => clearInterval(id);
    }
  }, [reload, dependency, poll]);
  return { data, error, loading, reload };
}
