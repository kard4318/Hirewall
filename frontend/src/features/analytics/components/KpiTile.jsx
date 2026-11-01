// KPI tile: big serif numeral, label, and the change vs the previous period in words and an arrow (not colour only)
import { Suppressed } from "./Panel.jsx";

export function KpiTile({ label, tile, format, deltaFormat = format, goodWhen = "up", hint, i = 0 }) {
  if (!tile) return <div className="kpi skeleton-kpi" style={{ "--i": i }} aria-busy="true" />;
  if (tile.suppressed) {
    return (
      <div className="kpi" style={{ "--i": i }}>
        <p className="label">{label}</p>
        <Suppressed />
      </div>
    );
  }
  const d = tile.delta;
  const direction = d === null || d === undefined || d === 0 ? "flat" : d > 0 ? "up" : "down";
  const good = direction === "flat" ? null : direction === goodWhen;
  return (
    <div className="kpi" style={{ "--i": i }}>
      <p className="label">{label}</p>
      <p className="kpi-value">{format(tile.value)}</p>
      {direction === "flat" && d === null ? (
        <p className="kpi-delta">{hint || "no earlier figure"}</p>
      ) : (
        <p className={`kpi-delta ${good === null ? "" : good ? "is-good" : "is-bad"}`}>
          <span aria-hidden="true">{direction === "up" ? "▲" : direction === "down" ? "▼" : "■"}</span>{" "}
          {direction === "flat" ? "no change" : `${direction} ${deltaFormat(Math.abs(d))}`} <span className="kpi-vs">vs previous</span>
        </p>
      )}
    </div>
  );
}
