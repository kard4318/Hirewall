// Stacked proportion bar with labelled, patterned segments (approve/edit/reject, answered/escalated)
export function SplitBar({ parts, label }) {
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  if (!total) return <p className="panel-state">No activity in this window.</p>;
  return (
    <figure className="split">
      <div className="split-bar" role="img" aria-label={`${label}: ${parts.map((p) => `${p.label} ${p.value}`).join(", ")}`}>
        {parts.map((p) => p.value > 0 && (
          <span key={p.label} className={`split-seg seg-${p.style}`} style={{ flexGrow: p.value }} />
        ))}
      </div>
      <figcaption className="split-legend">
        {parts.map((p) => (
          <span key={p.label}>
            <i className={`split-key seg-${p.style}`} aria-hidden="true" />
            {p.label} <b>{p.value}</b> <span className="muted">({Math.round((p.value / total) * 100)}%)</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
