// Step 2: pick a job offer or write one, then start scoring
import { useState } from "react";

const EMPTY = { title: "", skills: "", years: "", description: "" };

function toRequirements(form) {
  const skills = form.skills.split(",").map((s) => s.trim()).filter((s) => s.length >= 2);
  const lines = form.description.split(/\n+/).map((s) => s.trim()).filter((s) => s.length >= 3);
  const requirements = skills.map((skill) => ({ text: `Experience with ${skill}`, kind: "required" }));
  if (Number(form.years) > 0) requirements.push({ text: `At least ${Number(form.years)} years of experience`, kind: "required" });
  return [...requirements, ...lines.map((text) => ({ text, kind: "responsibility" }))];
}

export function JobPanel({ jobs, jobId, onPick, onCreate, onScore, canScore, run }) {
  const [form, setForm] = useState(null);
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });
  const requirements = form ? toRequirements(form) : [];
  const job = jobs.find((j) => j.job_id === jobId);
  const running = run && run.status !== "done" && run.status !== "failed";

  const submit = async (event) => {
    event.preventDefault();
    if (await onCreate({ title: form.title.trim(), requirements })) setForm(null);
  };

  return (
    <section className="scr-card">
      <h2>2. Job offer</h2>
      <label className="scr-field">
        Job
        <select value={jobId ?? ""} onChange={(event) => onPick(event.target.value)}>
          {jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
        </select>
      </label>
      {job && (
        <details className="scr-requirements">
          <summary>{job.requirements.length} requirements</summary>
          <ul>{job.requirements.map((r) => <li key={r.text}>{r.text} <span className="scr-muted">({r.kind})</span></li>)}</ul>
        </details>
      )}
      {form ? (
        <form className="scr-form" onSubmit={submit}>
          <label className="scr-field">Title<input required minLength={2} maxLength={200} value={form.title} onChange={set("title")} /></label>
          <label className="scr-field">Skills, comma-separated<input value={form.skills} onChange={set("skills")} /></label>
          <label className="scr-field">Minimum years<input type="number" min="0" max="50" value={form.years} onChange={set("years")} /></label>
          <label className="scr-field">Responsibilities, one per line<textarea rows={3} value={form.description} onChange={set("description")} /></label>
          <div className="scr-row">
            <button className="scr-btn" disabled={!requirements.length}>Save job</button>
            <button type="button" className="scr-link" onClick={() => setForm(null)}>Cancel</button>
          </div>
        </form>
      ) : (
        <button type="button" className="scr-link" onClick={() => setForm(EMPTY)}>Write a new job</button>
      )}
      <button type="button" className="scr-btn is-primary" disabled={!canScore || running} onClick={onScore}>
        {running ? "Scoring..." : "Score candidates"}
      </button>
      {run && running && (
        <div aria-live="polite">
          <progress max={run.total || 1} value={run.done} />
          <span className="scr-muted"> {run.done} of {run.total} scored</span>
        </div>
      )}
      {run?.status === "failed" && <p className="scr-alert" role="alert">Scoring failed ({run.reason_code}). Try again.</p>}
    </section>
  );
}
