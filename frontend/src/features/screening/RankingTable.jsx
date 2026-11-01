// Ranking table: the total and each criterion, with N/A where a criterion does not apply
import { DecisionButtons } from "./DecisionButtons.jsx";
import { ScoreBar } from "./ScoreBar.jsx";

const STATUS = { shortlisted: ["Shortlisted", "is-ok"], rejected: ["Rejected", "is-danger"] };
const WAITING = { shortlist: "Shortlist proposed", rejection: "Rejection proposed" };

function Status({ status, proposal }) {
  if (STATUS[status]) return <span className={`scr-pill ${STATUS[status][1]}`}>{STATUS[status][0]}</span>;
  if (proposal) return <span className="scr-pill is-warn">{WAITING[proposal.kind]}</span>;
  return <span className="scr-muted">–</span>;
}

export function RankingTable({
  candidates, pending, statuses, labelFor, selectedId, checked, onSelect, onToggle, proposals, canDecide, onDecide,
}) {
  if (!candidates.length && !pending.length) {
    return (
      <div className="scr-empty">
        <p><strong>No ranking yet.</strong></p>
        <p className="scr-muted">Pick a job above and choose <em>Score candidates</em>. Results stream in as each CV is scored.</p>
      </div>
    );
  }
  return (
    <div className="scr-table-wrap">
      <table className="scr-table">
        <thead>
          <tr>
            <th scope="col"><span className="scr-sr">Select</span></th>
            <th scope="col" className="is-num">#</th>
            <th scope="col">Candidate</th>
            <th scope="col">Profile</th>
            <th scope="col">Total</th>
            <th scope="col">Semantic</th>
            <th scope="col">Rubric</th>
            <th scope="col">Experience</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.candidate_id} className={[c.candidate_id === selectedId && "is-selected", c.injection_flag && "is-flagged"].filter(Boolean).join(" ")} onClick={() => onSelect(c.candidate_id)}>
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={`Select ${labelFor(c.candidate_id)}`}
                  checked={checked.has(c.candidate_id)}
                  onChange={() => onToggle(c.candidate_id)}
                />
              </td>
              <td className="is-num"><span className={`scr-rank${c.rank <= 3 ? " is-top" : ""}`}>{c.rank}</span></td>
              <td>
                <button type="button" className="scr-name" onClick={() => onSelect(c.candidate_id)}>{labelFor(c.candidate_id)}</button>
                {c.injection_flag && <span className="scr-pill is-danger">flagged</span>}
                {c.hidden_text_removed && !c.injection_flag && <span className="scr-pill is-warn">hidden text</span>}
                <DecisionButtons
                  candidateId={c.candidate_id}
                  status={statuses[c.candidate_id]}
                  proposal={proposals[c.candidate_id]}
                  disabled={!canDecide}
                  onDecide={onDecide}
                />
              </td>
              <td className="scr-muted">{c.profile}</td>
              <td><ScoreBar value={c.total_score} strong label="Total score" /></td>
              <td><ScoreBar value={c.scores.semantic} label="Semantic" /></td>
              <td><ScoreBar value={c.scores.rubric} label="Rubric" /></td>
              <td><ScoreBar value={c.scores.experience} label="Experience" /></td>
              <td><Status status={statuses[c.candidate_id]} proposal={proposals[c.candidate_id]} /></td>
            </tr>
          ))}
          {pending.map((id) => (
            <tr key={id} className="is-pending">
              <td />
              <td />
              <td>{labelFor(id)}</td>
              <td colSpan={6}><span className="scr-skeleton" aria-hidden="true" /><span className="scr-sr">Waiting to be scored</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
