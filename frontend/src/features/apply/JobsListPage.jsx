// /jobs: public list of published job offers
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Wordmark } from "../scheduling/Wordmark.jsx";
import "../scheduling/styles/base.css";
import "../screening/screening.css";
import "./apply.css";
import { applyApi, label } from "./api.js";

export function JobsListPage() {
  const [jobs, setJobs] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    applyApi.jobs().then((data) => setJobs(data.jobs)).catch(() => setFailed(true));
  }, []);

  return (
    <main className="scr-page apl-page">
      <div className="apl-column">
        <header className="apl-header">
          <Wordmark subtitle="Careers" />
          <h1>Open positions</h1>
        </header>
        {failed && <p className="scr-alert" role="alert">The offers could not be loaded. Please try again later.</p>}
        {jobs === null && !failed && <p className="scr-muted" aria-busy="true">Loading...</p>}
        {jobs?.length === 0 && <p className="scr-muted">There are no open positions right now.</p>}
        <ul className="apl-list">
          {jobs?.map(({ job_id: id, details }) => (
            <li key={id} className="scr-card">
              <h2><Link to={`/jobs/${encodeURIComponent(id)}`}>{details.title}</Link></h2>
              <p className="scr-muted">
                {[details.company, details.location, label(details.contract_type), label(details.remote)].filter(Boolean).join(" · ")}
              </p>
              {details.summary && <p>{details.summary}</p>}
            </li>
          ))}
        </ul>
      </div>
    </main>
  );
}
