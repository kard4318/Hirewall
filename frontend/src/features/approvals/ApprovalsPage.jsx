// /hr/approvals: proposed shortlists and rejections awaiting a person, past decisions, and the audit log
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { approvalsApi, shortId } from "../screening/api.js";
import { dateTime } from "../../shared/format.js";
import "../screening/screening.css";

const TITLES = { record_shortlist: "Shortlist", record_rejection: "Rejection", send_email: "Email reply" };
const label = (text) => (text ?? "").replaceAll("_", " ");
const when = (iso) => (iso ? dateTime(iso) : "");

function auditLine(entry) {
  const { status, reason, approval_id: approval, candidate_id: candidate, run_id: run } = entry.fields;
  const id = approval ?? candidate ?? run;
  return [label(entry.event), status && label(status), reason && label(reason), id && String(id).slice(0, 12)].filter(Boolean).join(" · ");
}

function Item({ item, target, busy, onDecide }) {
  const ids = item.summary.candidate_ids;
  const pending = item.status === "pending";
  const isEmail = item.action_type === "send_email";
  return (
    <li className={`apr-item${target ? " is-target" : ""}`}>
      <h3>{TITLES[item.action_type] ?? label(item.action_type)} · {label(item.status)}</h3>
      {ids ? (
        <>
          <p className="scr-muted">Job {item.summary.job_id} · run {item.summary.run_id} · {ids.length} candidate(s)</p>
          <ul className="apr-ids">{ids.map((id) => <li key={id} className="scr-pill">{shortId(id)}</li>)}</ul>
        </>
      ) : <p className="scr-muted">Reply to email {item.summary.in_reply_to}</p>}
      <p className="scr-muted">
        Proposed {when(item.created_at)}
        {item.decided_by && ` · decided by ${item.decided_by} ${when(item.decided_at)}`}
      </p>
      <p className="scr-muted">Hash <code>{item.payload_hash.slice(0, 16)}</code></p>
      {pending && isEmail && <Link to="/hr/inbox">Review this draft in the inbox</Link>}
      {pending && !isEmail && (
        <div className="scr-row">
          <button type="button" className="scr-btn is-primary" disabled={busy} onClick={() => onDecide(item, "approve")}>Approve and record</button>
          <button type="button" className="scr-btn" disabled={busy} onClick={() => onDecide(item, "reject")}>Reject</button>
        </div>
      )}
    </li>
  );
}

export function ApprovalsPage() {
  const { token, signOut } = useHrSession();
  const [params] = useSearchParams();
  const [items, setItems] = useState(null);
  const [audit, setAudit] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const target = params.get("id");

  const fail = useCallback((err) => {
    if (err.status === 401) signOut();
    else setError(err.message || "Request failed");
  }, [signOut]);

  const refresh = useCallback(async () => {
    try {
      const [queue, log] = await Promise.all([approvalsApi.list(token), approvalsApi.audit(token)]);
      setItems(queue.items);
      setAudit(log);
    } catch (err) {
      fail(err);
    }
  }, [token, fail]);

  useEffect(() => { refresh(); }, [refresh]);

  const decide = async (item, action) => {
    setBusy(true);
    setError(null);
    try {
      const decision = action === "approve" ? { action, reviewed_hash: item.payload_hash } : { action };
      const view = await approvalsApi.decide(token, item.approval_id, decision);
      if (view.waiting_for_human) setError(view.message || label(view.reason_code));
    } catch (err) {
      fail(err);
    }
    await refresh();
    setBusy(false);
  };

  const pending = (items ?? []).filter((i) => i.status === "pending");
  const past = (items ?? []).filter((i) => i.status !== "pending");
  const render = (item) => <Item key={item.approval_id} item={item} target={item.approval_id === target} busy={busy} onDecide={decide} />;

  return (
    <main className="scr-page">
      <header className="scr-header">
        <div>
          <h1>Approval queue</h1>
          <p className="scr-muted">Nothing is recorded or sent until a person approves it here.</p>
        </div>
      </header>
      {error && <p className="scr-alert" role="alert">{label(error)}</p>}
      {items === null && !error && <p className="scr-muted" aria-busy="true">Loading...</p>}
      {items !== null && (
        <div className="apr-grid">
          <div className="scr-center">
            <section className="scr-card">
              <h2>Waiting for a decision ({pending.length})</h2>
              {pending.length ? <ul className="apr-list">{pending.map(render)}</ul> : <p className="scr-muted">Nothing is waiting. Propose a shortlist from <Link to="/hr/screening">Talent Orbit</Link>.</p>}
            </section>
            {past.length > 0 && (
              <section className="scr-card">
                <h2>Decided</h2>
                <ul className="apr-list">{past.map(render)}</ul>
              </section>
            )}
          </div>
          <section className="scr-card">
            <h2>Audit log</h2>
            {audit && (
              <p className={audit.verified ? "scr-note" : "scr-alert"}>
                {audit.verified ? "Hash chain verified." : "The audit log failed verification."}
              </p>
            )}
            <ul className="apr-audit">
              {(audit?.entries ?? []).map((entry) => (
                <li key={entry.hash}>
                  <span className="scr-muted">{when(entry.at)}</span><br />
                  {auditLine(entry)}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </main>
  );
}
