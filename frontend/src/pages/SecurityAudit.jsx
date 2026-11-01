// Page: security overview for HR admins: verdicts, refused uploads, model integrity, audit chain, attack report.
// Everything here is plain text: excerpts come from outside and were masked, but are never rendered as HTML.
import { useCallback, useEffect, useState } from "react";
import { securityApi } from "../api/security.js";
import { useHrSession } from "../features/analytics/HrSession.jsx";
import "../features/screening/screening.css";

const label = (text) => String(text ?? "").replaceAll("_", " ");
const when = (iso) => (iso ? new Date(iso).toLocaleString() : "");
const INTEGRITY = {
  ok: "Checksums match",
  not_downloaded: "Not downloaded: rules only",
  no_checksums: "No checksums recorded: rules only. Run scripts/download_security_models.py",
  missing_files: "Files missing: rules only",
  checksum_mismatch: "Files changed since download: model refused, rules only",
};

function Counts({ rows, empty }) {
  if (!rows.length) return <p className="scr-muted">{empty}</p>;
  return (
    <table className="scr-subscores">
      <tbody>
        {rows.map(([name, count]) => (
          <tr key={name}><td>{label(name)}</td><td className="is-num">{count}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function AttackReport({ report }) {
  if (!report) {
    return <p className="scr-muted">No report yet. Run <code>python scripts/run_attack_suite.py</code>.</p>;
  }
  const rate = Math.round(report.pass_rate * 100);
  return (
    <>
      <p className={report.stopped === report.total ? "scr-note" : "scr-alert"}>
        {report.stopped} of {report.total} attacks stopped ({rate}%), {report.mode} run, {when(report.generated_at)}
      </p>
      <table className="scr-subscores">
        <thead><tr><th scope="col">OWASP LLM 2025</th><th scope="col" className="is-num">Stopped</th></tr></thead>
        <tbody>
          {Object.entries(report.owasp).map(([code, row]) => (
            <tr key={code}><td>{code}</td><td className="is-num">{row.stopped} / {row.total}</td></tr>
          ))}
        </tbody>
      </table>
      {report.failed.length > 0 && (
        <>
          <h3>Not stopped</h3>
          <ul className="apr-audit">
            {report.failed.map((row) => <li key={row.id}><strong>{row.id}</strong> {row.title}: {row.actual}</li>)}
          </ul>
        </>
      )}
    </>
  );
}

export function SecurityAudit() {
  const { token, signOut } = useHrSession();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(() => {
    securityApi.summary(token).then(setData).catch((err) => {
      if (err.status === 401) signOut();
      else setError(err.status === 403 ? "Only HR admins can open this page." : err.message || "Request failed");
    });
  }, [token, signOut]);
  useEffect(() => { load(); }, [load]);

  return (
    <main className="scr-page apr-page">
      <header className="scr-header">
        <div>
          <h1>Security</h1>
          <p className="scr-muted">What the defenses caught. Counts, codes and masked excerpts only.</p>
        </div>
        <button type="button" className="scr-btn" onClick={load}>Refresh</button>
      </header>
      {error && <p className="scr-alert apr-column" role="alert">{error}</p>}
      {!data && !error && <p className="scr-muted apr-column" aria-busy="true">Loading...</p>}
      {data && (
        <div className="scr-center apr-column">
          <section className="scr-card">
            <h2>Audit log</h2>
            <p className={data.audit.intact ? "scr-note" : "scr-alert"} role={data.audit.intact ? undefined : "alert"}>
              {data.audit.intact
                ? `Hash chain intact: ${data.audit.entries} entries verified.`
                : `Hash chain broken at entry ${data.audit.first_broken + 1} of ${data.audit.entries}: an entry was changed or removed.`}
            </p>
          </section>

          <section className="scr-card">
            <h2>Red-team attack suite</h2>
            <AttackReport report={data.attack_report} />
          </section>

          <section className="scr-card">
            <h2>Injection classifier</h2>
            <p>Mode: <strong>{data.model.mode}</strong> · {INTEGRITY[data.model.integrity] ?? label(data.model.integrity)}</p>
          </section>

          <section className="scr-card">
            <h2>Screened text</h2>
            <h3>Blocked or flagged, by source</h3>
            <Counts rows={data.verdicts.map((v) => [`${v.action} · ${v.source}`, v.count])} empty="Nothing blocked or flagged yet." />
            <h3>Reasons</h3>
            <Counts rows={Object.entries(data.reasons)} empty="None." />
            <h3>Refused uploads</h3>
            <Counts rows={Object.entries(data.uploads_refused)} empty="No upload refused." />
          </section>

          <section className="scr-card">
            <h2>Recent quarantined text</h2>
            {data.recent_quarantine.length === 0 ? <p className="scr-muted">None.</p> : (
              <ul className="apr-audit">
                {data.recent_quarantine.map((entry, i) => (
                  <li key={`${entry.at}-${i}`}>
                    <span className="scr-muted">{when(entry.at)} · {label(entry.action)} · {label(entry.source)} · {(entry.reasons || []).join(", ")}</span>
                    <br /><code>{entry.excerpt}</code>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="scr-card">
            <h2>Recent security events</h2>
            {data.recent_events.length === 0 ? <p className="scr-muted">None.</p> : (
              <ul className="apr-audit">
                {data.recent_events.map((event, i) => (
                  <li key={`${event.at}-${i}`}>
                    <span className="scr-muted">{when(event.at)}</span> {label(event.event)}
                    {Object.entries(event).filter(([k]) => !["at", "event"].includes(k)).map(([k, v]) => ` · ${label(k)} ${v}`).join("")}
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
