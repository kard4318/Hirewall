// "The ledger": screener-passed candidates for the selected job, ranked by score
import { DossierCard } from "./DossierCard.jsx";

export function Ledger({ job, rows, actions }) {
  return (
    <section className="ledger" aria-label="Candidates for this job">
      <header className="ledger-head">
        <p className="label">The ledger · passed screening</p>
        <h1 className="display">{job ? job.title : "…"}</h1>
        {job && (
          <p className="ledger-tally">
            {job.counts.booked} booked · {job.counts.invited + job.counts.pending_approval} invited · {job.counts.passed} waiting
            {job.location && <span> · {job.location}</span>}
          </p>
        )}
      </header>
      {rows === null && <p className="ledger-empty">Opening the ledger…</p>}
      {rows?.length === 0 && <p className="ledger-empty">No screened candidates for this job yet.</p>}
      <ol className="dossiers" key={job?.job_id}>
        {rows?.map((row, index) => (
          <DossierCard key={row.candidate_id} row={row} rank={index + 1} actions={actions} />
        ))}
      </ol>
    </section>
  );
}
