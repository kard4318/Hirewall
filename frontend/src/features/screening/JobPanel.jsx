// Step 2: pick a job offer or write one, then start scoring
import { useEffect, useRef, useState } from "react";
import { JobReviewForm } from "./JobReviewForm.jsx";
import { FILE_REASONS } from "./reasons.js";

const EMPTY = { title: "", skills: "", years: "", description: "" };

function toRequirements(form) {
  const skills = form.skills.split(",").map((s) => s.trim()).filter((s) => s.length >= 2);
  const lines = form.description.split(/\n+/).map((s) => s.trim()).filter((s) => s.length >= 3);
  const requirements = skills.map((skill) => ({ text: `Experience with ${skill}`, kind: "required" }));
  if (Number(form.years) > 0) requirements.push({ text: `At least ${Number(form.years)} years of experience`, kind: "required" });
  return [...requirements, ...lines.map((text) => ({ text, kind: "responsibility" }))];
}

const STATUS = { draft: " [draft]", published: " [published]", closed: " [closed]" };

export function JobPanel({
  jobs, jobId, onPick, onCreate, onScore, canScore, run, posting, importing, importError, onImport, onSavePosting,
  onPublish, onClosePosting, postingBusy, applicationCount,
}) {
  const [form, setForm] = useState(null);
  const fileInput = useRef(null);
  const reviewDialog = useRef(null);
  const openReview = () => reviewDialog.current?.showModal();
  const closeReview = () => reviewDialog.current?.close();

  // A draft opens for review as soon as it is picked or imported. Publishing closes it.
  const reviewKey = posting?.status === "draft" ? posting.job_id : null;
  useEffect(() => {
    if (reviewKey) openReview();
    else closeReview();
  }, [reviewKey]);
  const set = (field) => (event) => setForm({ ...form, [field]: event.target.value });
  const requirements = form ? toRequirements(form) : [];
  const job = jobs.find((j) => j.job_id === jobId);
  const running = run && run.status !== "done" && run.status !== "failed";

  const submit = async (event) => {
    event.preventDefault();
    if (await onCreate({ title: form.title.trim(), requirements })) setForm(null);
  };

  return (
    <section className="scr-card scr-job">
      <h2>Job offer</h2>
      <div className="scr-job-row">
        <label className="scr-field scr-job-pick">
          Job
          <select value={jobId ?? ""} onChange={(event) => onPick(event.target.value)}>
            {jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title}{STATUS[j.status] ?? ""}</option>)}
          </select>
        </label>
        <div className="scr-job-links">
          {posting && (
            <>
              <span className={`scr-pill is-status-${posting.status}`}>{posting.status}</span>
              <button type="button" className="scr-link" onClick={openReview}>Review offer</button>
            </>
          )}
          {!form && <button type="button" className="scr-link" onClick={() => setForm(EMPTY)}>Write a new job</button>}
          <button type="button" className="scr-link" disabled={importing} onClick={() => fileInput.current.click()}>
            {importing ? "Reading offer..." : "Import offer from PDF"}
          </button>
          <input
            ref={fileInput}
            type="file"
            hidden
            accept=".pdf,.docx"
            aria-label="Offer document"
            onChange={(event) => {
              if (event.target.files[0]) onImport(event.target.files[0]);
              event.target.value = "";
            }}
          />
        </div>
        <button type="button" className="scr-btn is-primary scr-job-score" disabled={!canScore || running} onClick={onScore}>
          {running ? "Scoring..." : "Score candidates"}
        </button>
      </div>
      {job && (
        <details className="scr-requirements">
          <summary>{job.requirements.length} requirements</summary>
          <ul>{job.requirements.map((r) => <li key={r.text}>{r.text} <span className="scr-muted">({r.kind})</span></li>)}</ul>
        </details>
      )}
      {posting && (
        <dialog ref={reviewDialog} className="scr-dialog" aria-label="Review offer">
          <JobReviewForm
            posting={posting}
            busy={postingBusy}
            onSave={onSavePosting}
            onPublish={onPublish}
            onClose={onClosePosting}
            onDismiss={closeReview}
          />
        </dialog>
      )}
      {form && (
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
      )}
      {importError && <p className="scr-alert" role="alert">{FILE_REASONS[importError] ?? "The offer could not be read"}.</p>}
      {posting && posting.status !== "draft" && applicationCount === 0 && (
        <p className="scr-muted">No candidates attached yet, so scoring uses the whole candidate pool.</p>
      )}
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
