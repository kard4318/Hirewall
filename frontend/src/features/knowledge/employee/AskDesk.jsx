// The handbook desk: ask a question, read cited answers on index cards, pass unknowns to the People Team
import { useState } from "react";
import { Wordmark } from "../../scheduling/Wordmark.jsx";
import { knowledgeApi } from "../api.js";
import { AnswerCard } from "./AnswerCard.jsx";

const SUGGESTIONS = [
  "How many days of annual leave do I get?",
  "Can I work from another country?",
  "What should I do if my laptop is stolen?",
  "How big is the learning budget?",
];

export function AskDesk({ token, onSignOut }) {
  const [draft, setDraft] = useState("");
  const [cards, setCards] = useState([]); // newest first, kept in this browser tab only
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);

  async function ask(question) {
    const text = question.trim();
    if (!text || pending) return;
    setDraft("");
    setPending(text);
    setError(null);
    try {
      const result = await knowledgeApi.ask(token, text);
      setCards((list) => [{ question: text, ...result }, ...list]);
    } catch (err) {
      if (err.status === 401) onSignOut();
      else setError("That didn't go through. Please try again.");
    } finally {
      setPending(null);
    }
  }

  async function escalate(id, contact) {
    try {
      await knowledgeApi.escalate(token, id, contact);
      setCards((list) => list.map((c) => (c.id === id ? { ...c, escalated: true } : c)));
      return true;
    } catch (err) {
      if (err.status === 401) onSignOut();
      return false;
    }
  }

  return (
    <div className="handbook paper">
      <header className="handbook-top">
        <Wordmark subtitle="Handbook desk" />
        <button className="btn-link" onClick={onSignOut}>Sign out</button>
      </header>

      <main className="handbook-main">
        <section className="ask-sheet" aria-label="Ask a question">
          <p className="label">Northwind Labs · Employee handbook</p>
          <h1 className="display">What do you need to know?</h1>
          <form className="ask-line" onSubmit={(e) => { e.preventDefault(); ask(draft); }}>
            <label className="visually-hidden" htmlFor="question">Your question</label>
            <input id="question" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={500}
              placeholder="e.g. Can I carry over unused leave?" autoComplete="off" autoFocus />
            <button className="btn btn-primary" disabled={!draft.trim() || Boolean(pending)}>Ask</button>
          </form>
          <div className="suggestions" aria-label="Example questions">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="tag tag-button" onClick={() => ask(s)} disabled={Boolean(pending)}>{s}</button>
            ))}
          </div>
          <p className="privacy-note">
            The People Team can read questions asked here, without your name, to improve the handbook.
            Questions about personal records or sensitive matters are never stored.
          </p>
          {error && <p className="form-error" role="alert">{error}</p>}
        </section>

        <section className="cards" aria-live="polite" aria-label="Answers">
          {pending && (
            <article className="index-card is-pending">
              <p className="card-question">{pending}</p>
              <p className="looking">Looking it up in the handbook<span>.</span><span>.</span><span>.</span></p>
            </article>
          )}
          {cards.map((card) => <AnswerCard key={card.id} card={card} onEscalate={escalate} />)}
          {!pending && cards.length === 0 && (
            <p className="cards-empty">Your answers will appear here as index cards, each with the policy sections it comes from.</p>
          )}
        </section>
      </main>
    </div>
  );
}
