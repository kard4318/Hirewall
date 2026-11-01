// Score shown as a number with a thin meter behind it; N/A criteria get an empty track, never a zero bar
import { percent } from "./api.js";

export function ScoreBar({ value, strong = false, label }) {
  const missing = value === null || value === undefined;
  const width = missing ? 0 : Math.max(0, Math.min(1, value)) * 100;
  const tier = missing ? "is-na" : value >= 0.75 ? "is-high" : value >= 0.5 ? "is-mid" : "is-low";
  return (
    <span className={`scr-score ${tier}${strong ? " is-strong" : ""}`}>
      <span className="scr-score-value num">{percent(value)}</span>
      <span
        className="scr-score-track"
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={missing ? undefined : Math.round(width)}
        aria-valuetext={missing ? "not applied" : percent(value)}
      >
        <span className="scr-score-fill" style={{ width: `${width}%` }} />
      </span>
    </span>
  );
}
