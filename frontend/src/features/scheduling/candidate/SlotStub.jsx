// A tear-off slot stub: tapping it tears the counterfoil and picks that interview time
import { useEffect, useState } from "react";

export function SlotStub({ slot, number, chosen, disabled, onChoose }) {
  const [torn, setTorn] = useState(chosen);
  const [day, time] = slot.label.split(", ");

  useEffect(() => {
    if (!chosen) setTorn(false); // another stub was picked: this one is whole again
  }, [chosen]);

  function choose() {
    if (disabled) return;
    setTorn(true);
    onChoose();
  }

  return (
    <button
      className={`stub${torn ? " is-torn" : ""}${chosen ? " is-chosen" : ""}`}
      onClick={choose}
      disabled={disabled}
      aria-pressed={chosen}
      aria-label={`Option ${number}: ${slot.label}`}
    >
      <span className="stub-main">
        <span className="stub-no">No. {String(number).padStart(2, "0")}</span>
        <span className="stub-day">{day}</span>
        <span className="stub-time">{time}</span>
      </span>
      <span className="stub-counterfoil" aria-hidden="true">{chosen ? "picked" : "take"}</span>
    </button>
  );
}
