// Weekly recap: template sentences from the backend plus rule-based highlights, each with its numbers
import { Fragment } from "react";

const NUMBER_LABELS = {
  rate: "rate", company_quarterly_average: "company avg", ratio: "ratio", exits: "exits", n: "n",
  completion: "completion", company_completion: "company", gap: "gap", before: "before", after: "after", drop: "drop",
  quarter: "quarter", from_quarter: "from", to_quarter: "to",
};
const PERCENT_KEYS = new Set(["rate", "company_quarterly_average", "completion", "company_completion", "gap"]);

function formatNumber(key, value) {
  if (PERCENT_KEYS.has(key)) return `${(value * 100).toFixed(1)}%`;
  if (key === "ratio") return `${value}x`;
  if (key === "n" && typeof value === "number") return Math.round(value);
  return value;
}

export function Highlight({ item }) {
  return (
    <li className="highlight">
      <p className="highlight-text">{item.text}</p>
      <dl className="highlight-numbers">
        {Object.entries(item.numbers).filter(([k]) => k !== "department").map(([key, value]) => (
          <Fragment key={key}>
            <dt>{NUMBER_LABELS[key] || key}</dt>
            <dd>{formatNumber(key, value)}</dd>
          </Fragment>
        ))}
      </dl>
      <p className="highlight-rule"><span className="label">Rule</span> {item.rule_text}</p>
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
          <p className="label recap-subhead">Highlights found in the data</p>
          <ul className="highlights">{recap.highlights.map((h) => <Highlight key={h.rule + h.text} item={h} />)}</ul>
        </>
      )}
    </div>
  );
}
