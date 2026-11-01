// One question an employee passed to the People Team: reply by email (when they left an address) or resolve
import { useState } from "react";

const DELIVERY = { smtp: "Sent by email" };
const ERRORS = {
  409: "This employee stayed anonymous, so there is no address to reply to.",
  422: "Write a reply of up to 2000 characters.",
  502: "The email could not be delivered. Check the SMTP settings and try again.",
};

export function EscalationCard({ entry, withheldLabel, onResolve, onReply, when }) {
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState(null);
  const { escalation } = entry;
  const open = escalation.status === "open";

  async function act(fn) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(ERRORS[err.status] || "That didn't work. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  function send(event) {
    event.preventDefault();
    act(async () => {
      await onReply(draft.trim());
      setDraft("");
    });
  }

  return (
    <article className={`handoff${open ? " is-open" : ""}`}>
      <div className="handoff-top">
        <time className="log-time">{when(escalation.at)}</time>
        <span className={`stamp ${open ? "stamp-pending_approval" : "stamp-booked"}`}>
          {open ? "Open" : escalation.reply ? "Replied" : "Resolved"}
        </span>
      </div>
      <p className={entry.question ? "q-text" : "q-text is-withheld"}>{entry.question || withheldLabel}</p>
      <p className="handoff-contact">
        {escalation.contact ? <>From <b>{escalation.contact}</b></> : "No contact left (anonymous)"}
      </p>

      {escalation.reply && (
        <div className="handoff-reply">
          <p className="label">Your reply · {when(escalation.reply.at)}</p>
          <p className="reply-text">{escalation.reply.message}</p>
          {DELIVERY[escalation.reply.delivery] && <p className="reply-delivery">{DELIVERY[escalation.reply.delivery]}</p>}
        </div>
      )}

      {open && escalation.contact && (
        <form className="reply-form" onSubmit={send}>
          <label className="visually-hidden" htmlFor={`reply-${entry.id}`}>Reply to {escalation.contact}</label>
          <textarea id={`reply-${entry.id}`} rows={3} maxLength={2000} value={draft}
            onChange={(e) => setDraft(e.target.value)} placeholder={`Write your answer to ${escalation.contact}…`} />
          <div className="reply-actions">
            <button className="btn btn-primary btn-small" disabled={busy || !draft.trim()}>
              {busy ? "Sending…" : "Send reply"}
            </button>
            <button type="button" className="btn btn-ghost btn-small" disabled={busy} onClick={() => act(onResolve)}>
              Resolve without replying
            </button>
          </div>
        </form>
      )}
      {open && !escalation.contact && (
        <button className="btn btn-small" disabled={busy} onClick={() => act(onResolve)}>Mark resolved</button>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
    </article>
  );
}
