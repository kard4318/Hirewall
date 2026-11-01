// /candidate?token=… : the candidate's appointment ticket and chat with the scheduling agent
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { candidateApi, getMeta } from "../api.js";
import { usePolling } from "../usePolling.js";
import { BookedPanel } from "./BookedPanel.jsx";
import { ChatThread } from "./ChatThread.jsx";
import { InvalidLink } from "./InvalidLink.jsx";
import { SlotStub } from "./SlotStub.jsx";
import "../styles/base.css";
import "../styles/candidate.css";

export function CandidatePage() {
  const [params] = useSearchParams();
  const token = params.get("token");
  const [meta, setMeta] = useState(null);
  const [ticket, setTicket] = useState(null);
  const [phase, setPhase] = useState(token ? "loading" : "invalid");
  const [sending, setSending] = useState(null); // text shown while the agent is answering
  const [error, setError] = useState(null);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    getMeta().then(setMeta).catch(() => {});
  }, []);

  useEffect(() => {
    if (!token) return;
    candidateApi
      .state(token)
      .then((state) => { setTicket(state); setPhase("ready"); })
      .catch((err) => setPhase(err.status === 401 ? "invalid" : "error"));
  }, [token]);

  // While HR is approving, check back quietly so the BOOKED stamp lands without a reload.
  usePolling(() => {
    if (ticket?.awaiting_hr) candidateApi.state(token).then(setTicket).catch(() => {});
  }, 5000, [ticket?.awaiting_hr]);

  async function send(call, shown) {
    setSending(shown);
    setError(null);
    try {
      const result = await call();
      setTicket((current) => ({ ...current, ...result }));
    } catch (err) {
      if (err.status === 401) setPhase("invalid");
      else setError("That didn't go through. Please try again.");
    } finally {
      setSending(null);
    }
  }

  function submit(event) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;
    setDraft("");
    send(() => candidateApi.say(token, text), text);
  }

  if (phase === "invalid") return <InvalidLink />;
  if (phase === "error") return <InvalidLink problem />;
  if (!ticket) return <div className="desk paper"><p className="desk-loading label">Opening your invitation…</p></div>;

  const booked = Boolean(ticket.booking);
  const pending = ticket.offered.find((slot) => slot.id === ticket.pending_slot_id);

  return (
    <div className="desk paper">
      <article className={`ticket${booked ? " is-booked" : ""}`}>
        <header className="ticket-head">
          <p className="label">{[meta?.company_name || ticket.company_name, "Interview appointment"].filter(Boolean).join(" · ")}</p>
          <h1 className="display">Hello, {ticket.first_name}.</h1>
          <p className="ticket-role">{ticket.job_title}</p>
        </header>
        <div className="perforation" aria-hidden="true" />

        <ChatThread history={ticket.history} sending={sending} />

        {booked ? (
          <BookedPanel booking={ticket.booking} jobTitle={ticket.job_title} company={ticket.company_name} />
        ) : (
          <>
            {ticket.awaiting_hr && <p className="ticket-note">Your chosen time is with HR for approval.</p>}
            {ticket.offered.length > 0 && !ticket.awaiting_hr && (
              <div className="stubs" role="group" aria-label="Offered interview times">
                {ticket.offered.map((slot, i) => (
                  <SlotStub
                    key={slot.id}
                    slot={slot}
                    number={i + 1}
                    chosen={slot.id === ticket.pending_slot_id}
                    disabled={Boolean(sending)}
                    onChoose={() => send(() => candidateApi.act(token, { type: "choose", slot_id: slot.id }), slot.label)}
                  />
                ))}
              </div>
            )}
            {pending && !ticket.awaiting_hr && (
              <div className="confirm-row">
                <span className="confirm-q">Book {pending.label}?</span>
                <button className="btn btn-primary" disabled={Boolean(sending)}
                  onClick={() => send(() => candidateApi.act(token, { type: "confirm" }), "Yes, book it")}>
                  Yes
                </button>
                <button className="btn" disabled={Boolean(sending)}
                  onClick={() => send(() => candidateApi.act(token, { type: "decline" }), "No, another time")}>
                  No
                </button>
              </div>
            )}
          </>
        )}

        {error && <p className="form-error" role="alert">{error}</p>}

        <form className="composer" onSubmit={submit}>
          <label className="visually-hidden" htmlFor="message">Message to the scheduling assistant</label>
          <input
            id="message"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={booked ? "Your interview is booked." : "e.g. Thursday afternoon works best"}
            maxLength={500}
            autoComplete="off"
            disabled={booked || ticket.awaiting_hr}
          />
          <button className="btn btn-primary" disabled={booked || Boolean(sending) || !draft.trim()}>Send</button>
        </form>

        <footer className="ticket-foot">
          <span>Times shown in the office's local time.</span>
        </footer>
      </article>
    </div>
  );
}
