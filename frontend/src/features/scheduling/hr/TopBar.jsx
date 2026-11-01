// HR top bar: wordmark, Scheduling / Questions switch, job tabs, calendar-mode chip, strict toggle, sign out
import { Wordmark } from "../Wordmark.jsx";

const CALENDAR_MODES = {
  mock: "Mock calendar",
  "google-readonly": "Google · read only",
  google: "Google Calendar",
};

export function TopBar({ jobs, jobId, onSelect, meta, strict, onToggleStrict, onSignOut, view, onView, openHandoffs, embedded = false }) {
  return (
    <header className="topbar">
      {!embedded && <Wordmark subtitle={meta?.company_name} />}
      <div className="view-switch" role="tablist" aria-label="Dashboard view">
        <button role="tab" aria-selected={view === "scheduling"} className={view === "scheduling" ? "is-active" : ""}
          onClick={() => onView("scheduling")}>Scheduling</button>
        <button role="tab" aria-selected={view === "questions"} className={view === "questions" ? "is-active" : ""}
          onClick={() => onView("questions")}>
          Questions {openHandoffs > 0 && <span className="view-badge">{openHandoffs}</span>}
        </button>
      </div>
      <nav className="job-tabs" role="tablist" aria-label="Job offers" hidden={view !== "scheduling"}>
        {jobs.map((job) => (
          <button
            key={job.job_id}
            role="tab"
            aria-selected={job.job_id === jobId}
            className={`job-tab${job.job_id === jobId ? " is-active" : ""}`}
            onClick={() => onSelect(job.job_id)}
          >
            <span className="job-tab-title">{job.title}</span>
            <span className="job-tab-count">{job.total}</span>
          </button>
        ))}
      </nav>
      {view !== "scheduling" && <span className="job-tabs" aria-hidden="true" />}
      <div className="topbar-tools">
        {meta && view === "scheduling" && <span className="chip">{CALENDAR_MODES[meta.calendar_mode] || meta.calendar_mode}</span>}
        {meta?.strict_mode_available && view === "scheduling" && (
          <button
            className={`chip chip-toggle${strict ? " is-on" : ""}`}
            aria-pressed={strict}
            onClick={onToggleStrict}
            title="When on, HR approves each booking before the calendar event is created"
          >
            HR approval · {strict ? "on" : "off"}
          </button>
        )}
        {!embedded && <button className="btn-link" onClick={onSignOut}>Sign out</button>}
      </div>
    </header>
  );
}
