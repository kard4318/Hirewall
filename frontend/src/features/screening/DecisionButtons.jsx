// Shortlist or reject one candidate. This only proposes: nothing is recorded or sent until the queue approves it
import { Link } from "react-router-dom";

const WAITING = { shortlist: "Shortlist awaiting approval", rejection: "Rejection awaiting approval" };

export function DecisionButtons({ candidateId, status, proposal, disabled, onDecide }) {
  const open = (event) => event.stopPropagation();
  return (
    <div className="scr-decide" onClick={open}>
      <button
        type="button"
        className="scr-btn is-small"
        disabled={disabled || status === "shortlisted" || proposal?.kind === "shortlist"}
        onClick={() => onDecide(candidateId, "shortlist")}
      >
        Shortlist
      </button>
      <button
        type="button"
        className="scr-btn is-small is-danger"
        disabled={disabled || status === "rejected" || proposal?.kind === "rejection"}
        onClick={() => onDecide(candidateId, "rejection")}
      >
        Reject
      </button>
      {proposal && (
        <Link to={`/hr/approvals?id=${encodeURIComponent(proposal.approval_id)}`}>{WAITING[proposal.kind]}</Link>
      )}
    </div>
  );
}
