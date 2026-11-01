// /hr/inbox: recruiter inbox. Classify an email, draft a reply, then approve, edit, redraft or reject it
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { inboxApi, statusLabel } from "./api.js";
import { DraftEditor } from "./DraftEditor.jsx";
import "./inbox.css";

const when = (iso) => new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function useAsync(token, signOut) {
  const [error, setError] = useState(null);
  const run = useCallback(async (call) => {
    setError(null);
    try {
      return await call(token);
    } catch (err) {
      if (err.status === 401) signOut();
      else setError(err.message || "Request failed");
      return null;
    }
  }, [token, signOut]);
  return [run, error, setError];
}

export function InboxPage() {
  const { token, signOut } = useHrSession();
  const [run, error] = useAsync(token, signOut);
  const [tab, setTab] = useState("inbox");
  const [rows, setRows] = useState(null);
  const [sent, setSent] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [busy, setBusy] = useState(null);

  const refresh = useCallback(async () => {
    const [list, out] = await Promise.all([run((t) => inboxApi.list(t)), run((t) => inboxApi.sent(t))]);
    if (list) setRows(list);
    if (out) setSent(out);
  }, [run]);

  const open = useCallback(async (id) => {
    setSelected(id);
    setDetail(null);
    const data = await run((t) => inboxApi.get(t, id));
    if (data) setDetail(data);
  }, [run]);

  useEffect(() => { refresh(); }, [refresh]);

  // The digest links to one email with ?email=<id>.
  const [params] = useSearchParams();
  const linkedEmail = params.get("email");
  useEffect(() => { if (linkedEmail) open(linkedEmail); }, [linkedEmail, open]);

  async function act(label, call) {
    setBusy(label);
    await run(call);
    setBusy(null);
    await Promise.all([refresh(), selected && open(selected)]);
  }

  const email = detail?.email;
  const active = detail?.active;

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">Talent flow · email</p>
        <h1 className="display">Inbox</h1>
      </header>
      <div className="inbox-tabs" role="tablist">
        <button role="tab" aria-selected={tab === "inbox"} className={tab === "inbox" ? "is-active" : ""} onClick={() => setTab("inbox")}>
          Inbox {rows && <span className="mono">{rows.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === "sent"} className={tab === "sent" ? "is-active" : ""} onClick={() => setTab("sent")}>
          Sent {sent.length > 0 && <span className="mono">{sent.length}</span>}
        </button>
      </div>
      {error && <p className="notice" role="alert">{error.replaceAll("_", " ")}</p>}

      {tab === "sent" ? (
        <section className="a-panel">
          {sent.length === 0 && <p className="panel-state">Nothing sent yet. Replies appear here after a human approves them.</p>}
          <ul className="sent-list">
            {sent.map((m) => (
              <li key={m.idempotency_key}>
                <p className="mail-meta"><b>{m.subject}</b> <span className="mono">{when(m.sent_at)}</span></p>
                <p className="muted">to {m.to}</p>
                <pre className="mail-body">{m.body}</pre>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <div className="inbox-layout">
          <section className="a-panel inbox-list" aria-label="Emails">
            {rows === null && <div className="skeleton"><span /><span /><span /></div>}
            <ul>
              {rows?.map((r) => (
                <li key={r.email_id}>
                  <button className={`mail-row${selected === r.email_id ? " is-open" : ""}`} onClick={() => open(r.email_id)}>
                    <span className="mail-from">{r.from}</span>
                    <span className="mail-subject">{r.subject}</span>
                    <span className="mail-preview">{r.preview}</span>
                    <span className="mail-tags">
                      <span className="mono">{when(r.received_at)}</span>
                      {r.classification && <span className="tag">{statusLabel(r.classification.type)}</span>}
                      <span className={`stamp ${r.waiting_for_human ? "stamp-pending_approval" : r.draft_status === "sent" ? "stamp-booked" : "stamp-passed"}`}>
                        {r.waiting_for_human ? "draft to review" : statusLabel(r.draft_status === "not_started" ? r.triage_status : r.draft_status)}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="a-panel inbox-detail" aria-label="Selected email">
            {!selected && <p className="panel-state">Pick an email on the left.</p>}
            {selected && !detail && <div className="skeleton"><span /><span /><span /></div>}
            {email && (
              <>
                <header className="a-panel-head">
                  <p className="label">{email.from_address} · {when(email.received_at)}</p>
                  <h2 className="a-panel-title">{email.subject}</h2>
                </header>
                {detail.history.length > 0 && (
                  <details className="history">
                    <summary>{detail.history.length} earlier message(s) in this thread</summary>
                    {detail.history.map((h, i) => (
                      <div key={i} className="history-item">
                        <p className="label">{h.direction === "outbound" ? "We wrote" : h.from_address} · {when(h.sent_at)}</p>
                        <pre className="mail-body">{h.body}</pre>
                      </div>
                    ))}
                  </details>
                )}
                <pre className="mail-body">{email.body}</pre>

                {detail.classification && (
                  <p className="classification">
                    <span className="label">Classified as</span> <b>{statusLabel(detail.classification.type)}</b>
                    {" · "}urgency {detail.classification.urgency}
                    {detail.classification.needs_human && " · needs a person"}
                  </p>
                )}

                {!active && (
                  <div className="inbox-actions">
                    <button className="btn" disabled={Boolean(busy)} onClick={() => act("triage", (t) => inboxApi.triage(t, selected))}>
                      {busy === "triage" ? "Classifying…" : "Classify"}
                    </button>
                    <button className="btn btn-primary" disabled={Boolean(busy)} onClick={() => act("draft", (t) => inboxApi.draft(t, selected))}>
                      {busy === "draft" ? "Drafting…" : "Draft a reply"}
                    </button>
                    <span className="muted">Status: {statusLabel(detail.draft.status !== "not_started" ? detail.draft.status : detail.triage.status)}</span>
                  </div>
                )}
                {(detail.draft.message || detail.triage.message) && !active && (
                  <p className="notice-soft">{detail.draft.message || detail.triage.message}</p>
                )}
                {active && detail.pending_draft && (
                  <DraftEditor key={detail.pending_draft.payload_hash} draft={detail.pending_draft} busy={busy}
                    onDecide={(label, decision) => act(label, (t) => inboxApi.decide(t, selected, decision))} />
                )}
              </>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
