// HR "question desk": what employees ask the handbook, gaps it could not answer, and People Team escalations
import { useCallback, useState } from "react";
import { usePolling } from "../../scheduling/usePolling.js";
import { hrKnowledgeApi, KIND_LABELS } from "../api.js";
import { EscalationCard } from "./EscalationCard.jsx";
import "../styles/knowledge.css";
import { dateTime } from "../../../shared/format.js";

const WITHHELD = {
  sensitive: "Sensitive matter: question not stored",
  refused_personal: "Personal record request: question not stored",
  blocked: "Blocked attempt: question not stored",
};
const time = (iso) => dateTime(iso);

export function QuestionDesk({ token, onError }) {
  const [questions, setQuestions] = useState(null);
  const [escalations, setEscalations] = useState([]);
  const [stats, setStats] = useState(null);

  const load = useCallback(async () => {
    try {
      const [q, e, s] = await Promise.all([hrKnowledgeApi.questions(token), hrKnowledgeApi.escalations(token),
        hrKnowledgeApi.stats(token)]);
      setQuestions(q);
      setEscalations(e);
      setStats(s);
    } catch (err) {
      onError(err);
    }
  }, [token, onError]);
  usePolling(load, 5000, [token]);

  // Card actions: a lost session signs HR out; other errors are shown on the card itself.
  async function guarded(call) {
    try {
      await call();
      await load();
    } catch (err) {
      if (err.status === 401) onError(err);
      else throw err;
    }
  }
  const resolve = (id) => guarded(() => hrKnowledgeApi.resolve(token, id));
  const reply = (id, message) => guarded(() => hrKnowledgeApi.reply(token, id, message));

  const kinds = stats?.by_kind || {};
  const withheld = (kinds.sensitive || 0) + (kinds.refused_personal || 0) + (kinds.blocked || 0);
  const tiles = [
    ["Questions asked", stats?.total ?? "–"],
    ["Answered", kinds.answered || 0],
    ["Not in the handbook", kinds.not_found || 0],
    ["Withheld", withheld],
    ["Open hand-offs", stats?.open_escalations ?? 0],
  ];

  return (
    <main className="desk-main">
      <section className="desk-ledger" aria-label="Employee questions">
        <header className="ledger-head">
          <p className="label">The question desk · employee handbook</p>
          <h1 className="display">What people ask</h1>
          <p className="ledger-tally">Anonymous. Sensitive and personal questions are counted, never stored.</p>
        </header>
        <div className="desk-tiles">
          {tiles.map(([label, value], i) => (
            <div key={label} className={`desk-tile${i === 4 && value ? " is-hot" : ""}`}>
              <span className="tile-num">{value}</span>
              <span className="label">{label}</span>
            </div>
          ))}
        </div>
        {stats?.top_topics?.length > 0 && (
          <p className="topics"><span className="label">Most asked</span>
            {stats.top_topics.map(([topic, n]) => <span key={topic} className="tag">{topic} · {n}</span>)}
          </p>
        )}

        {questions === null && <p className="ledger-empty">Opening the desk…</p>}
        {questions?.length === 0 && <p className="ledger-empty">No questions yet. Open /ask and try a few.</p>}
        <ol className="question-rows">
          {questions?.map((q) => (
            <li key={q.id} className={`question-row kind-${q.kind}`}>
              <time className="log-time">{time(q.at)}</time>
              <div className="question-body">
                <p className={q.question ? "q-text" : "q-text is-withheld"}>{q.question || WITHHELD[q.kind]}</p>
                {q.citations.length > 0 && (
                  <p className="q-cites">{q.citations.map((c) => <span key={c} className="tag">§ {c}</span>)}</p>
                )}
              </div>
              <span className={`stamp stamp-kind-${q.kind}`}>{KIND_LABELS[q.kind] || q.kind}</span>
              {q.audience === "hr" && <span className="tag">HR</span>}
            </li>
          ))}
        </ol>
      </section>

      <aside className="handoffs" aria-label="Passed to the People Team">
        <header className="wall-head">
          <p className="label">Hand-offs · passed to the People Team</p>
        </header>
        {escalations.length === 0 && <p className="ledger-empty">Nothing waiting. Unanswered questions appear here when an employee passes them on.</p>}
        {escalations.map((e) => (
          <EscalationCard key={e.id} entry={e} withheldLabel={WITHHELD[e.kind]} when={time}
            onResolve={() => resolve(e.id)} onReply={(message) => reply(e.id, message)} />
        ))}
      </aside>
    </main>
  );
}
