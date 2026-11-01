// /hr/approvals: proposals waiting for a person. Decided items are not listed; a decision shows its result once
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { approvalsApi, screeningApi, shortId } from "../screening/api.js";
import { dateTime } from "../../shared/format.js";
import "../screening/screening.css";

const KINDS = {
  record_shortlist: { title: "Shortlist", tone: "is-ok", approve: "Approve and invite",
    effect: "Approving emails each candidate an invitation to book an interview with the Scheduler." },
  record_rejection: { title: "Rejection", tone: "is-danger", approve: "Approve and send rejection",
    effect: "Approving emails each candidate a rejection. This cannot be taken back." },
  send_email: { title: "Email reply", tone: "", approve: "Review in the inbox", effect: "" },
};
const OUTCOMES = {
  sent: ["Email sent", "is-ok"],
  no_email: ["No email address in the CV", "is-warn"],
  in_progress: ["Booking already in progress", ""],
  failed: ["Could not be sent", "is-danger"],
};
const label = (text) => (text ?? "").replaceAll("_", " ");
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function Item({ item, target, busy, onDecide, jobTitle }) {
  const kind = KINDS[item.action_type] ?? { title: label(item.action_type), tone: "", effect: "" };
  const ids = item.summary.candidate_ids;
  const isEmail = item.action_type === "send_email";
  const ref = useRef(null);
  useEffect(() => { if (target) ref.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [target]);

  return (
    <li ref={ref} className={`apr-item${target ? " is-target" : ""}`}>
      <div className="apr-item-head">
        <span className={`apr-kind ${kind.tone}`}>{kind.title}</span>
        <h3>
          {ids ? plural(ids.length, "candidate") : "Reply to a candidate email"}
          {ids && <span className="scr-muted"> · {jobTitle(item.summary.job_id)}</span>}
        </h3>
        <span className="apr-when scr-muted">Proposed {dateTime(item.created_at)}</span>
      </div>

      {ids && <ul className="apr-ids" aria-label="Candidates">{ids.map((id) => <li key={id} className="scr-pill">{shortId(id)}</li>)}</ul>}
      {kind.effect && <p className="apr-effect">{kind.effect}</p>}

      <div className="apr-actions">
        {isEmail ? (
          <Link className="scr-btn is-primary" to="/hr/inbox">Review this draft in the inbox</Link>
        ) : (
          <>
            <button type="button" className="scr-btn" disabled={busy} onClick={() => onDecide(item, "reject")}>Decline proposal</button>
            <button type="button" className="scr-btn is-primary" disabled={busy} onClick={() => onDecide(item, "approve")}>{kind.approve}</button>
          </>
        )}
      </div>
    </li>
  );
}

/** One-off confirmation of the decision just made, with the email result for each candidate. */
export function Result({ result, onClose }) {
  const kind = KINDS[result.item.action_type]?.title ?? "Proposal";
  const notes = (result.item.notifications ?? []).filter((note) => OUTCOMES[note.outcome]);
  return (
    <div className={`apr-result ${result.action === "approve" ? "is-approved" : "is-declined"}`} role="status">
      <div className="apr-result-head">
        <strong>{kind} {result.action === "approve" ? "approved" : "declined"}.</strong>
        <button type="button" className="scr-link" onClick={onClose}>Dismiss</button>
      </div>
      {result.action !== "approve" && <p>Nothing was recorded or sent.</p>}
      {notes.length > 0 && (
        <ul className="apr-outcomes">
          {notes.map((note) => {
            const [text, tone] = OUTCOMES[note.outcome];
            return <li key={note.candidate_id}><span className="scr-pill">{shortId(note.candidate_id)}</span><span className={`apr-outcome ${tone}`}>{text}</span></li>;
          })}
        </ul>
      )}
    </div>
  );
}

export function ApprovalsPage() {
  const { token, signOut } = useHrSession();
  const [params] = useSearchParams();
  const [items, setItems] = useState(null);
  const [jobs, setJobs] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const target = params.get("id");

  const fail = useCallback((err) => {
    if (err.status === 401) signOut();
    else setError(err.message || "Request failed");
  }, [signOut]);

  const refresh = useCallback(async () => {
    try {
      const queue = await approvalsApi.list(token);
      setItems(queue.items);
      return queue.items;
    } catch (err) {
      fail(err);
      return null;
    }
  }, [token, fail]);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    screeningApi.jobs(token)
      .then((data) => setJobs(Object.fromEntries(data.jobs.map((job) => [job.job_id, job.title]))))
      .catch(() => { /* titles are a convenience: ids still show */ });
  }, [token]);

  const decide = async (item, action) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const decision = action === "approve" ? { action, reviewed_hash: item.payload_hash } : { action };
      const view = await approvalsApi.decide(token, item.approval_id, decision);
      if (view.waiting_for_human) setError(view.message || label(view.reason_code));
    } catch (err) {
      fail(err);
    }
    const fresh = await refresh();
    const decided = fresh?.find((i) => i.approval_id === item.approval_id);
    if (decided && decided.status !== "pending") setResult({ action, item: decided });
    setBusy(false);
  };

  const pending = (items ?? []).filter((i) => i.status === "pending");
  const jobTitle = (id) => jobs[id] ?? `Job ${id}`;

  return (
    <main className="scr-page apr-page">
      <header className="scr-header apr-column">
        <div>
          <p className="label">Human in the loop</p>
          <h1>Approval queue</h1>
          <p className="scr-muted">Nothing is recorded or sent until a person approves it here.</p>
        </div>
        {items !== null && (
          <span className={`apr-count${pending.length ? " is-waiting" : ""}`}>
            <strong className="num">{pending.length}</strong> waiting
          </span>
        )}
      </header>

      <div className="apr-column">
        {error && <p className="scr-alert" role="alert">{label(error)}</p>}
        {result && <Result result={result} onClose={() => setResult(null)} />}
        {items === null && !error && <p className="scr-muted" aria-busy="true">Loading…</p>}
        {items !== null && (pending.length ? (
          <ul className="apr-list">
            {pending.map((item) => (
              <Item key={item.approval_id} item={item} target={item.approval_id === target} busy={busy}
                onDecide={decide} jobTitle={jobTitle} />
            ))}
          </ul>
        ) : (
          <section className="scr-card scr-empty">
            <p><strong>All clear.</strong> Nothing is waiting for a decision.</p>
            <p className="scr-muted">Propose a shortlist or a rejection from <Link to="/hr/screening">Talent Orbit</Link>, or review email drafts in the <Link to="/hr/inbox">Inbox</Link>.</p>
          </section>
        ))}
      </div>
    </main>
  );
}
