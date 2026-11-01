// /hr/approvals: proposed shortlists and rejections awaiting a person, and past decisions
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { approvalsApi, shortId } from "../screening/api.js";
import { dateTime } from "../../shared/format.js";
import "../screening/screening.css";

const TITLES = { record_shortlist: "Shortlist", record_rejection: "Rejection", send_email: "Email reply" };
const label = (text) => (text ?? "").replaceAll("_", " ");
const when = (iso) => (iso ? dateTime(iso) : "");

const OUTCOMES = {
  sent: "Email sent",
  outbox: "Kept in the local outbox, not delivered",
  no_email: "No email address found in the CV",
  in_progress: "Already has a booking in progress",
  failed: "Could not be sent",
};
const EFFECTS = {
  record_shortlist: "Approving emails each candidate an invitation to book an interview with the Scheduler.",
  record_rejection: "Approving emails each candidate a rejection. This cannot be taken back.",
};
const APPROVE = { record_shortlist: "Approve and invite", record_rejection: "Approve and send rejection" };

function Item({ item, target, busy, onDecide, delivery }) {
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
      {pending && isEmail && <Link to="/hr/inbox">Review this draft in the inbox</Link>}
      {pending && !isEmail && <p>{EFFECTS[item.action_type]}</p>}
      {pending && !isEmail && delivery !== "smtp" && (
        <p className="scr-alert">Email delivery is off (EMAIL_MODE={delivery}), so candidates will not receive this.</p>
      )}
      {item.notifications.length > 0 && (
        <ul className="apr-audit">
          {item.notifications.map((note) => (
            <li key={note.candidate_id}>{shortId(note.candidate_id)}: {OUTCOMES[note.outcome] ?? label(note.outcome)}</li>
          ))}
        </ul>
      )}
      {pending && !isEmail && (
        <div className="scr-row">
          <button type="button" className="scr-btn is-primary" disabled={busy} onClick={() => onDecide(item, "approve")}>{APPROVE[item.action_type] ?? "Approve"}</button>
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
  const [delivery, setDelivery] = useState("outbox");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const target = params.get("id");

  const fail = useCallback((err) => {
    if (err.status === 401) signOut();
    else setError(err.message || "Request failed");
  }, [signOut]);

  const refresh = useCallback(async () => {
    try {
      const queue = await approvalsApi.list(token);
      setItems(queue.items);
      setDelivery(queue.delivery);
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
  const render = (item) => <Item key={item.approval_id} item={item} target={item.approval_id === target} busy={busy} onDecide={decide} delivery={delivery} />;

  return (
    <main className="scr-page apr-page">
      <header className="scr-header">
        <div>
          <h1>Approval queue</h1>
          <p className="scr-muted">Nothing is recorded or sent until a person approves it here.</p>
        </div>
      </header>
      {error && <p className="scr-alert apr-column" role="alert">{label(error)}</p>}
      {items === null && !error && <p className="scr-muted apr-column" aria-busy="true">Loading...</p>}
      {items !== null && (
        <div className="scr-center apr-column">
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
      )}
    </main>
  );
}
