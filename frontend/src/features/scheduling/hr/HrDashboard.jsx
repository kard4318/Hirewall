// HR dashboard: scheduling (ledger, calendar wall) or the employee question desk, plus the logbook
import { useCallback, useEffect, useRef, useState } from "react";
import { getMeta, hrApi } from "../api.js";
import { usePolling } from "../usePolling.js";
import { CalendarWall } from "./CalendarWall.jsx";
import { Ledger } from "./Ledger.jsx";
import { Logbook } from "./Logbook.jsx";
import { TopBar } from "./TopBar.jsx";
import { hrKnowledgeApi } from "../../knowledge/api.js";
import { QuestionDesk } from "../../knowledge/hr/QuestionDesk.jsx";

const POLL_MS = 5000;
const WALL_RELOAD_DELAY_MS = 3000; // give Google a moment to show the new event

export function HrDashboard({ token, onSignOut, embedded = false }) {
  const [meta, setMeta] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [rows, setRows] = useState(null);
  const [audit, setAudit] = useState({ entries: [], blocked_count: 0 });
  const [embed, setEmbed] = useState(null);
  const [strict, setStrict] = useState(false);
  const [wallKey, setWallKey] = useState(0);
  const [notice, setNotice] = useState(null);
  const [view, setView] = useState("scheduling");
  const [openHandoffs, setOpenHandoffs] = useState(0);
  const bookedCount = useRef(null);

  const fail = useCallback(
    (err) => (err.status === 401 ? onSignOut() : setNotice(err.message || "Request failed")),
    [onSignOut],
  );

  useEffect(() => {
    getMeta().then(setMeta).catch(() => {});
    hrApi.calendarEmbed(token).then(setEmbed).catch(fail);
    hrApi.settings(token).then((s) => setStrict(s.strict)).catch(fail);
  }, [token, fail]);

  const load = useCallback(async () => {
    try {
      const [jobList, log] = await Promise.all([hrApi.jobs(token), hrApi.audit(token)]);
      setJobs(jobList);
      setAudit(log);
      const current = jobId ?? jobList[0]?.job_id;
      if (!jobId && current) setJobId(current);
      if (current) setRows(await hrApi.candidates(token, current));
      const booked = jobList.reduce((sum, job) => sum + job.counts.booked, 0);
      if (bookedCount.current !== null && booked !== bookedCount.current) {
        setTimeout(() => setWallKey((k) => k + 1), WALL_RELOAD_DELAY_MS);
      }
      bookedCount.current = booked;
      hrKnowledgeApi.stats(token).then((s) => setOpenHandoffs(s.open_escalations)).catch(() => {});
    } catch (err) {
      fail(err);
    }
  }, [token, jobId, fail]);

  usePolling(load, POLL_MS, [jobId]);

  async function run(action) {
    setNotice(null);
    try {
      const result = await action();
      await load();
      return result;
    } catch (err) {
      fail(err);
      return null;
    }
  }

  const actions = {
    invite: (id) => run(() => hrApi.invite(token, id)),
    cancel: (bookingId) => run(() => hrApi.cancel(token, bookingId)),
    approve: (bookingId) => run(() => hrApi.approve(token, bookingId)),
    decline: (bookingId) => run(() => hrApi.decline(token, bookingId)),
  };

  async function toggleStrict() {
    const result = await run(() => hrApi.setStrict(token, !strict));
    if (result) setStrict(result.strict);
  }

  const job = jobs.find((j) => j.job_id === jobId);

  return (
    <div className="hr paper">
      <TopBar
        jobs={jobs}
        jobId={jobId}
        onSelect={(id) => { setRows(null); setJobId(id); }}
        meta={meta}
        strict={strict}
        onToggleStrict={toggleStrict}
        onSignOut={onSignOut}
        view={view}
        onView={setView}
        openHandoffs={openHandoffs}
        embedded={embedded}
      />
      {notice && (
        <div className="notice" role="alert">
          {notice}
          <button className="btn-link" onClick={() => setNotice(null)}>Dismiss</button>
        </div>
      )}
      {view === "scheduling" ? (
        <main className="hr-main">
          <Ledger job={job} rows={rows} actions={actions} />
          <CalendarWall embed={embed} reloadKey={wallKey} onRefresh={() => setWallKey((k) => k + 1)} />
        </main>
      ) : (
        <QuestionDesk token={token} onError={fail} />
      )}
      <Logbook audit={audit} />
    </div>
  );
}
