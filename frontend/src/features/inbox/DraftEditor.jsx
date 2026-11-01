// The drafted reply waiting for a human: approve and send, save an edit, ask for a redraft, or reject
import { useState } from "react";

export function DraftEditor({ draft, busy, onDecide }) {
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const [feedback, setFeedback] = useState("");
  const edited = subject !== draft.subject || body !== draft.body;

  return (
    <div className="draft">
      <p className="label">Draft reply · revision {draft.revision ?? 1} · to {draft.to}</p>
      <label className="visually-hidden" htmlFor="draft-subject">Subject</label>
      <input id="draft-subject" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={300} />
      <label className="visually-hidden" htmlFor="draft-body">Body</label>
      <textarea id="draft-body" rows={10} value={body} onChange={(e) => setBody(e.target.value)} maxLength={10000} />
      {draft.warnings.length > 0 && (
        <ul className="draft-warnings">{draft.warnings.map((w) => <li key={w}>{String(w).replaceAll("_", " ")}</li>)}</ul>
      )}
      <div className="inbox-actions">
        {edited ? (
          <button className="btn btn-primary" disabled={Boolean(busy)}
            onClick={() => onDecide("edit", { action: "edit", subject, body })}>
            {busy === "edit" ? "Checking…" : "Save my edit"}
          </button>
        ) : (
          <button className="btn btn-primary" disabled={Boolean(busy)}
            onClick={() => onDecide("approve", { action: "approve", reviewed_hash: draft.payload_hash })}>
            {busy === "approve" ? "Sending…" : "Approve & send"}
          </button>
        )}
        <button className="btn btn-ghost" disabled={Boolean(busy)} onClick={() => onDecide("reject", { action: "reject" })}>Reject</button>
      </div>
      {edited && <p className="muted">Save your edit first; it is checked again, then you can approve it.</p>}
      <div className="redraft">
        <input value={feedback} onChange={(e) => setFeedback(e.target.value)} maxLength={1000}
          placeholder="Ask for a redraft, e.g. shorter and warmer" />
        <button className="btn btn-small" disabled={Boolean(busy)}
          onClick={() => onDecide("redraft", { action: "redraft", feedback })}>
          {busy === "redraft" ? "Redrafting…" : "Redraft"}
        </button>
      </div>
    </div>
  );
}
