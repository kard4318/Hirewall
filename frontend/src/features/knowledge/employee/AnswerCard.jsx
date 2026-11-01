// One answered question as an index card: kind stamp, answer, cited sections, and the People Team hand-off
import { useState } from "react";
import { KIND_LABELS } from "../api.js";

export function AnswerCard({ card, onEscalate }) {
  const [open, setOpen] = useState(false);
  const [contact, setContact] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function send(event) {
    event.preventDefault();
    setSending(true);
    setFailed(false);
    const ok = await onEscalate(card.id, contact.trim() || null);
    setSending(false);
    if (!ok) setFailed(true);
  }

  return (
    <article className={`index-card kind-${card.kind}`}>
      <div className="card-head">
        <p className="card-question">{card.question}</p>
        <span className={`stamp stamp-kind-${card.kind}`}>{KIND_LABELS[card.kind] || card.kind}</span>
      </div>
      <p className="card-answer">{card.answer}</p>

      {card.citations.length > 0 && (
        <ol className="citations" aria-label="Sources">
          {card.citations.map((c) => (
            <li key={c.section_id}>
              <span className="cite-id">§ {c.section_id}</span>
              <span className="cite-title">{c.title}</span>
              <span className="cite-version">v{c.version}</span>
            </li>
          ))}
        </ol>
      )}

      {card.escalation_offered && !card.escalated && !open && (
        <button className="btn" onClick={() => setOpen(true)}>Pass to the People Team</button>
      )}
      {open && !card.escalated && (
        <form className="escalate" onSubmit={send}>
          <label className="label" htmlFor={`contact-${card.id}`}>Your work email (optional, so they can reply)</label>
          <div className="escalate-row">
            <input id={`contact-${card.id}`} type="email" value={contact} onChange={(e) => setContact(e.target.value)}
              placeholder="name@example.test" maxLength={120} />
            <button className="btn btn-primary" disabled={sending}>{sending ? "Sending…" : "Send"}</button>
          </div>
          {failed && <p className="form-error">Couldn't send. Check the email address and try again.</p>}
        </form>
      )}
      {card.escalated && <p className="sent-note"><span className="stamp stamp-booked">Sent</span> The People Team has your question.</p>}
    </article>
  );
}
