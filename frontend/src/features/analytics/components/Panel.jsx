// Ledger panel with paper grain and a double rule; renders loading skeleton, error-with-retry and empty states
export function Panel({ title, kicker, note, report, isEmpty = () => false, className = "", children, i = 0 }) {
  let body;
  if (report && report.status === "loading" && !report.data) {
    body = <div className="skeleton" aria-busy="true" aria-label="Loading"><span /><span /><span /></div>;
  } else if (report && report.status === "error") {
    const missing = report.error?.status === 503;
    body = (
      <div className="panel-state" role="alert">
        <p>{missing ? "No people data yet. Run python scripts\\generate_people_data.py, then retry." : "Couldn't load this panel."}</p>
        <button className="btn btn-small" onClick={report.retry}>Retry</button>
      </div>
    );
  } else if (report && report.data && isEmpty(report.data)) {
    body = <p className="panel-state">Nothing to show for these filters.</p>;
  } else {
    body = children;
  }
  return (
    <section className={`a-panel ${className}`} style={{ "--i": i }}>
      <header className="a-panel-head">
        {kicker && <p className="label">{kicker}</p>}
        <h2 className="a-panel-title">{title}</h2>
        {note && <p className="a-panel-note">{note}</p>}
      </header>
      {body}
    </section>
  );
}

export function Suppressed({ children = "Group too small to show" }) {
  return <span className="suppressed-chip" title="Groups under 5 people are hidden to protect privacy">{children}</span>;
}
