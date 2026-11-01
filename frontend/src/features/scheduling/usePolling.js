// Hook that runs a callback now and then every `ms` milliseconds while the component is mounted
import { useEffect, useRef } from "react";

export function usePolling(callback, ms, deps = []) {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    let alive = true;
    const tick = () => alive && saved.current();
    tick();
    const id = setInterval(tick, ms);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ms, ...deps]);
}
