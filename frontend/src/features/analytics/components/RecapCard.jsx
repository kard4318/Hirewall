// Weekly recap: template sentences from the backend plus rule-based findings, each with its evidence and a sparkline
import { Fragment } from "react";
import { count, decimal, deltaPts, percent, quarter, ratio } from "../../../shared/format.js";
import { COLORS } from "../chartTheme.jsx";

/** Evidence rows per rule: [label, value]. Unknown rules fall back to their raw numbers. */
function evidence(item) {
  const n = item.numbers;
  switch (item.rule) {
    case "attrition_spike":
      return [["Latest quarter", quarter(n.quarter)], ["Rate", percent(n.rate)],
        ["Company average", percent(n.company_quarterly_average)], ["Ratio", ratio(n.ratio)],
        ["Exits", count(n.exits)], ["People", count(n.n)]];
    case "training_gap":
      return [["Completion", percent(n.completion, 0)], ["Company", percent(n.company_completion, 0)],
        ["Gap", deltaPts(-n.gap, 0)], ["People", count(n.n)]];
    case "engagement_drop":
      return [[quarter(n.from_quarter), decimal(n.before, 2)], [quarter(n.to_quarter), decimal(n.after, 2)],
        ["Drop", decimal(n.drop, 2)], ["Respondents", count(n.n)]];
    default:
      return Object.entries(n).filter(([k]) => k !== "department").map(([k, v]) => [k, String(v)]);
  }
}

const W = 168, H = 44, PAD = 4;

/** Inline sparkline: gaps for hidden quarters, dashed company reference, flagged quarter marked. */
export function Sparkline({ series, reference, flagged, kind, referenceLabel }) {
  const values = series.map((p) => p.value).filter((v) => v !== null);
  if (values.length < 2) return null;
  const all = reference === null || reference === undefined ? values : [...values, reference];
  const lo = kind === "rate" ? 0 : Math.min(...all), hi = Math.max(...all);
  const span = hi - lo || 1;
  const x = (i) => PAD + (i * (W - 2 * PAD)) / (series.length - 1);
  const y = (v) => H - PAD - ((v - lo) / span) * (H - 2 * PAD);
  const segments = [];
  let current = [];
  series.forEach((p, i) => {
    if (p.value === null) { if (current.length) segments.push(current); current = []; }
    else current.push(`${x(i).toFixed(1)},${y(p.value).toFixed(1)}`);
  });
  if (current.length) segments.push(current);
  const fi = series.findIndex((p) => p.quarter === flagged);
  const fmt = kind === "rate" ? (v) => percent(v) : (v) => decimal(v, 2);
  const summary = series.map((p) => `${quarter(p.quarter)} ${p.value === null ? "hidden" : fmt(p.value)}`).join(", ");
  return (
    <figure className="spark">
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`Trend: ${summary}`}>
        {reference !== null && reference !== undefined && (
          <line x1={PAD} x2={W - PAD} y1={y(reference)} y2={y(reference)} stroke={COLORS.inkSoft} strokeDasharray="3 3" strokeWidth="1" />
        )}
        {segments.map((pts) => <polyline key={pts[0]} points={pts.join(" ")} fill="none" stroke={COLORS.ink} strokeWidth="1.5" />)}
        {fi >= 0 && series[fi].value !== null && (
          <circle cx={x(fi)} cy={y(series[fi].value)} r="3.5" fill={COLORS.vermilion} stroke={COLORS.paper} strokeWidth="1" />
        )}
      </svg>
      <figcaption>
        <span>{quarter(series[0].quarter, { short: true })} to {quarter(series[series.length - 1].quarter, { short: true })}</span>
        {reference !== null && reference !== undefined && <span className="spark-ref">dashed: {referenceLabel || "company"}</span>}
      </figcaption>
    </figure>
  );
}

export function Highlight({ item }) {
  return (
    <li className="finding">
      <div className="finding-main">
        <p className="finding-dept label">{item.numbers.department}</p>
        <p className="finding-head">{item.text}</p>
        <dl className="finding-evidence">
          {evidence(item).map(([label, value]) => (
            <Fragment key={label}>
              <dt>{label}</dt>
              <dd className="num">{value}</dd>
            </Fragment>
          ))}
        </dl>
      </div>
      {item.series && (
        <Sparkline series={item.series} reference={item.reference} flagged={item.flagged_quarter}
          kind={item.series_kind} referenceLabel={item.reference_label} />
      )}
      <p className="finding-why">{item.rule_text}</p>
    </li>
  );
}

export function RecapCard({ recap }) {
  return (
    <div className="recap">
      <ol className="recap-sentences">
        {recap.sentences.map((s) => <li key={s}>{s}</li>)}
      </ol>
      {recap.highlights.length > 0 && (
        <>
          <p className="label recap-subhead">Findings in the data</p>
          <ul className="highlights">{recap.highlights.map((h) => <Highlight key={h.rule + h.text} item={h} />)}</ul>
        </>
      )}
    </div>
  );
}
