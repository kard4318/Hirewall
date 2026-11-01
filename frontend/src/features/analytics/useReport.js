// Fetches one analytics report and refetches when its parameters change (no polling)
import { useCallback, useEffect, useState } from "react";
import { getAnalytics } from "./api.js";
import { useHrSession } from "./HrSession.jsx";

export function useReport(path, params = {}, { enabled = true } = {}) {
  const { token, signOut } = useHrSession();
  const [state, setState] = useState({ status: "loading", data: null, error: null });
  const [attempt, setAttempt] = useState(0);
  const key = JSON.stringify(params);

  useEffect(() => {
    if (!enabled) return undefined;
    let alive = true;
    setState((s) => ({ status: "loading", data: s.data, error: null }));
    getAnalytics(token, path, JSON.parse(key))
      .then((data) => alive && setState({ status: "ready", data, error: null }))
      .catch((error) => {
        if (!alive) return;
        if (error.status === 401) signOut();
        else setState({ status: "error", data: null, error });
      });
    return () => { alive = false; };
  }, [token, path, key, attempt, enabled, signOut]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
