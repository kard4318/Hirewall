// "Needs you now": live scheduling and question-desk counts that wait on a human decision
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { hrKnowledgeApi } from "../../knowledge/api.js";
import { hrApi } from "../../scheduling/api.js";
import { useHrSession } from "../HrSession.jsx";

export function NeedsYouCard() {
  const { token, signOut } = useHrSession();
  const [counts, setCounts] = useState(null);

  useEffect(() => {
    let alive = true;
    Promise.all([hrApi.jobs(token), hrKnowledgeApi.stats(token).catch(() => null)])
      .then(([jobs, stats]) => {
        if (!alive) return;
        const sum = (status) => jobs.reduce((n, job) => n + job.counts[status], 0);
        setCounts({ invited: sum("invited"), pending: sum("pending_approval"), handoffs: stats?.open_escalations ?? null });
      })
      .catch((err) => (err.status === 401 ? signOut() : alive && setCounts({ error: true })));
    return () => { alive = false; };
  }, [token, signOut]);

  if (!counts) return <div className="skeleton" aria-busy="true"><span /><span /></div>;
  if (counts.error) return <p className="panel-state">Scheduling data is unavailable right now.</p>;
  const items = [
    ["Invited, not booked yet", counts.invited, "Candidates who have a link but have not picked a time."],
    ["Bookings awaiting your approval", counts.pending, "Only when HR approval is switched on."],
    ...(counts.handoffs === null ? [] : [["Employee questions passed to you", counts.handoffs, "Open hand-offs on the question desk."]]),
  ];
  return (
    <div className="needs">
      <ul>
        {items.map(([label, value, hint]) => (
          <li key={label} className={value ? "is-waiting" : ""}>
            <span className="needs-num">{value}</span>
            <span><b>{label}</b><br /><span className="muted">{hint}</span></span>
          </li>
        ))}
      </ul>
      <Link className="btn btn-small" to="/hr/scheduling">Open scheduling</Link>
      <p className="muted needs-note">Live from scheduling and the question desk.</p>
    </div>
  );
}
