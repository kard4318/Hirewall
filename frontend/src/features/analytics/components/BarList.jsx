// Accessible horizontal bars for group data: label, bar, value and n; suppressed groups shown as hatched rows
import { Suppressed } from "./Panel.jsx";

export function BarList({ groups, value = (g) => g.n, format = (v) => v, max, marker, markerLabel, label = (g) => g.key,
  showN = true, tone = "ink" }) {
  const visible = groups.filter((g) => !g.suppressed);
  const top = max ?? Math.max(1, ...visible.map(value));
  return (
    <ul className={`bar-list tone-${tone}`}>
      {groups.map((g) => (
        <li key={g.key} className={g.suppressed ? "is-suppressed" : ""}>
          <span className="bar-label">{label(g)}</span>
          {g.suppressed ? (
            <span className="bar-track hatched"><Suppressed /></span>
          ) : (
            <span className="bar-track" role="img" aria-label={`${label(g)}: ${format(value(g))}`}>
              <span className="bar-fill" style={{ width: `${Math.max(2, (value(g) / top) * 100)}%` }} />
              {marker !== undefined && marker !== null && (
                <span className="bar-marker" style={{ left: `${(marker / top) * 100}%` }} title={markerLabel} />
              )}
            </span>
          )}
          <span className="bar-value">{g.suppressed ? "–" : format(value(g))}</span>
          {showN && <span className="bar-n">{g.suppressed ? "" : `n=${g.n}`}</span>}
        </li>
      ))}
    </ul>
  );
}
