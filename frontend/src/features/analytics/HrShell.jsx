// HR area shell: slim navigation (Overview, People, Retention, Scheduling), demo-data badge, nested pages
import { useEffect, useMemo, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Wordmark } from "../scheduling/Wordmark.jsx";
import { hrApi } from "../scheduling/api.js";
import { getAnalytics } from "./api.js";
import { HrSessionContext } from "./HrSession.jsx";
import "./styles/analytics.css";

const LINKS = [["overview", "Overview"], ["people", "People"], ["directory", "Directory"], ["retention", "Retention"],
  ["screening", "Screening"], ["approvals", "Approvals"], ["scheduling", "Scheduling"], ["digest", "Digest"],
  ["inbox", "Inbox"], ["questions", "Questions"]];

export function HrShell({ token, onSignOut }) {
  const [meta, setMeta] = useState(null);
  const [me, setMe] = useState(null);

  useEffect(() => {
    hrApi.me(token).then(setMe).catch(() => setMe(null));
  }, [token]);

  useEffect(() => {
    getAnalytics(token, "filters")
      .then(setMeta)
      .catch((err) => (err.status === 401 ? onSignOut() : setMeta({ error: err })));
  }, [token, onSignOut]);

  const session = useMemo(() => ({ token, signOut: onSignOut, asOf: meta?.as_of, meta }), [token, onSignOut, meta]);

  return (
    <HrSessionContext.Provider value={session}>
      <div className="hr-shell paper">
        <header className="hr-nav">
          <Wordmark />
          <nav aria-label="HR sections">
            {LINKS.map(([to, label]) => (
              <NavLink key={to} to={to} className={({ isActive }) => `hr-nav-link${isActive ? " is-active" : ""}`}>
                {label}
              </NavLink>
            ))}
          </nav>
          {meta?.as_of && <span className="chip">As of {meta.as_of}</span>}
          {me && <span className="chip" title={me.role.replace("_", " ")}>{me.display_name}</span>}
          <button className="btn-link" onClick={onSignOut}>Sign out</button>
        </header>
        <Outlet />
      </div>
    </HrSessionContext.Provider>
  );
}
