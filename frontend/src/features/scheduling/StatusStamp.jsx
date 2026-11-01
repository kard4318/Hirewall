// Rubber-stamp status chip; plays the stamp "thud" once when the status becomes BOOKED
import { useEffect, useRef, useState } from "react";

const LABELS = {
  passed: "Passed",
  invited: "Invited",
  pending_approval: "Awaiting HR",
  booked: "Booked",
};

export function StatusStamp({ status }) {
  const previous = useRef(status);
  const [thud, setThud] = useState(false);

  useEffect(() => {
    if (status === "booked" && previous.current !== "booked") setThud(true);
    previous.current = status;
  }, [status]);

  return (
    <span
      className={`stamp stamp-${status}${thud ? " stamp-thud" : ""}`}
      onAnimationEnd={() => setThud(false)}
    >
      {LABELS[status] || status}
    </span>
  );
}
