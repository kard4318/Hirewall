// Ranking table: the total and each criterion, with N/A where a criterion does not apply
import { percent } from "./api.js";
import { DecisionButtons } from "./DecisionButtons.jsx";

const STATUS = { shortlisted: "Shortlisted", rejected: "Rejected" };

export function RankingTable({
  candidates, pending, statuses, labelFor, selectedId, checked, onSelect, onToggle, proposals, canDecide, onDecide,
}) {
  if (!candidates.length && !pending.length) {
    return <p className="scr-muted">Scores appear here once a run starts.</p>;
  }
  return (
    <div className="scr-table-wrap">
      <table className="scr-table">
        <thead>
          <tr>
            <th scope="col"><span className="scr-sr">Select</span></th>
            <th scope="col">#</th>
            <th scope="col">Candidate</th>
            <th scope="col">Profile</th>
            <th scope="col" className="is-num">Total</th>
            <th scope="col" className="is-num">Semantic</th>
            <th scope="col" className="is-num">Rubric</th>
            <th scope="col" className="is-num">Experience</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => (
            <tr key={c.candidate_id} className={c.candidate_id === selectedId ? "is-selected" : ""} onClick={() => onSelect(c.candidate_id)}>
              <td onClick={(event) => event.stopPropagation()}>
                <input
                  type="checkbox"
                  aria-label={`Select ${labelFor(c.candidate_id)}`}
                  checked={checked.has(c.candidate_id)}
                  onChange={() => onToggle(c.candidate_id)}
                />
              </td>
              <td>{c.rank}</td>
              <td>
                <button type="button" className="scr-link" onClick={() => onSelect(c.candidate_id)}>{labelFor(c.candidate_id)}</button>
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
              <td>{c.profile}</td>
              <td className="is-num"><strong>{percent(c.total_score)}</strong></td>
              <td className="is-num">{percent(c.scores.semantic)}</td>
              <td className="is-num">{percent(c.scores.rubric)}</td>
              <td className="is-num">{percent(c.scores.experience)}</td>
              <td>{STATUS[statuses[c.candidate_id]] ?? ""}</td>
            </tr>
          ))}
          {pending.map((id) => (
            <tr key={id} className="is-pending">
              <td />
              <td />
              <td>{labelFor(id)}</td>
              <td colSpan={6} className="scr-muted">Waiting to be scored</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
