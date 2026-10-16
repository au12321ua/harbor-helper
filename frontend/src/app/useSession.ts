import { api, ApiError, type User } from "@/api";
import { useEffect, useState } from "react";
export function useSession() {
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [setup, setSetup] = useState(false),
    [failure, setFailure] = useState<unknown>();
  useEffect(() => {
    api("/setup")
      .then((status) => {
        if (!status.initialized) {
          setSetup(true);
          return null;
        }
        return api("/me");
      })
      .then((value) => {
        if (value) setUser(value);
      })
      .catch((e) => {
        if (!(
          e instanceof ApiError &&
          ["unauthorized", "login_required"].includes(e.code)
        ))
          setFailure(e);
      })
      .finally(() => setLoading(false));
    const expired = () => setUser(null);
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  return { user, setUser, loading, setup, setSetup, failure, setFailure };
}
