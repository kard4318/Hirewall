// /jobs/:jobId: a public job offer and its application form. Offer text is rendered as plain text
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Wordmark } from "../scheduling/Wordmark.jsx";
import { applicationMessage } from "../screening/reasons.js";
import "../scheduling/styles/base.css";
import "../screening/screening.css";
import "./apply.css";
import { applyApi, label } from "./api.js";

function Items({ title, items }) {
  if (!items?.length) return null;
  return (
    <section>
      <h2>{title}</h2>
      <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
    </section>
  );
}

function Facts({ details }) {
  const years = details.min_years_experience;
  const facts = [
    ["Company", details.company], ["Department", details.department], ["Contract", label(details.contract_type)],
    ["Location", details.location], ["Work mode", label(details.remote)], ["Duration", details.duration],
    ["Start date", details.start_date], ["Experience", years ? `At least ${years} years` : null],
    ["Education", details.education_level], ["Apply before", details.application_deadline],
  ].filter(([, value]) => value);
  return <dl className="apl-facts">{facts.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>;
}

function ApplicationForm({ jobId }) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);
  const [reference, setReference] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!form.get("cover_letter")?.size) form.delete("cover_letter");
    setSending(true);
    setError(null);
    try {
      setReference((await applyApi.submit(jobId, form)).reference_id);
    } catch (err) {
      setError(applicationMessage(err.message));
    }
    setSending(false);
  };

  if (reference) {
    return (
      <section className="scr-card" aria-live="polite">
        <h2>Application received</h2>
        <p>Thank you. A recruiter will review your application.</p>
        <p className="scr-muted">Your reference: <code>{reference}</code></p>
      </section>
    );
  }
  return (
    <form className="scr-card apl-form" onSubmit={submit}>
      <h2>Apply</h2>
      {error && <p className="scr-alert" role="alert">{error}</p>}
      <label className="scr-field">Full name<input name="full_name" required minLength={2} maxLength={200} autoComplete="name" /></label>
      <label className="scr-field">Email<input name="email" type="email" required maxLength={254} autoComplete="email" /></label>
      <label className="scr-field">CV (PDF or DOCX, up to 5 MB)<input name="cv" type="file" required accept=".pdf,.docx" /></label>
      <label className="scr-field">Cover letter, optional (PDF or DOCX, up to 5 MB)<input name="cover_letter" type="file" accept=".pdf,.docx" /></label>
      <label className="apl-consent">
        <input name="consent" type="checkbox" value="true" required />
        <span>I agree that my documents and contact details are processed for this application. An automated tool helps the recruiter read them, and a person makes every decision.</span>
      </label>
      <button className="scr-btn is-primary" disabled={sending}>{sending ? "Sending..." : "Send application"}</button>
    </form>
  );
}

export function JobApplyPage() {
  const { jobId } = useParams();
  const [job, setJob] = useState(null);
  const [problem, setProblem] = useState(null);

  useEffect(() => {
    setJob(null);
    setProblem(null);
    applyApi.job(jobId).then(setJob).catch((err) => setProblem(applicationMessage(err.message)));
  }, [jobId]);

  return (
    <main className="scr-page apl-page">
      <div className="apl-column">
        <header className="apl-header">
          <Wordmark subtitle="Careers" />
          <Link to="/jobs">All open positions</Link>
        </header>
        {problem && <p className="scr-alert" role="alert">{problem}</p>}
        {!job && !problem && <p className="scr-muted" aria-busy="true">Loading...</p>}
        {job && (
          <>
            <article className="scr-card apl-offer">
              <h1>{job.details.title}</h1>
              <Facts details={job.details} />
              {job.details.summary && <p>{job.details.summary}</p>}
              <Items title="Responsibilities" items={job.details.responsibilities} />
              <Items title="Required skills" items={job.details.required_skills} />
              <Items title="Preferred skills" items={job.details.preferred_skills} />
              <Items title="Languages" items={job.details.languages} />
              <Items title="Benefits" items={job.details.benefits} />
            </article>
            <ApplicationForm jobId={jobId} />
          </>
        )}
      </div>
    </main>
  );
}
