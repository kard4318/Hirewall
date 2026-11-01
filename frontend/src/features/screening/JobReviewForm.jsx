// Review a job offer extracted from a document: edit a draft, then publish it; close a published one
import { useEffect, useState } from "react";

const LISTS = [
  ["required_skills", "Required skills"],
  ["preferred_skills", "Preferred skills"],
  ["responsibilities", "Responsibilities"],
  ["languages", "Languages"],
  ["benefits", "Benefits"],
];
const TEXTS = [
  ["company", "Company", 200],
  ["department", "Department", 200],
  ["location", "Location", 200],
  ["duration", "Duration", 100],
  ["start_date", "Start date", 100],
  ["application_deadline", "Application deadline", 100],
  ["education_level", "Education level", 200],
];
const CONTRACTS = [["internship", "Internship"], ["full_time", "Full time"], ["part_time", "Part time"],
  ["fixed_term", "Fixed term"], ["freelance", "Freelance"], ["other", "Other"]];
const REMOTE = [["onsite", "On site"], ["hybrid", "Hybrid"], ["remote", "Remote"]];

function toForm(details) {
  const form = { ...details };
  for (const [key] of LISTS) form[key] = (details[key] ?? []).join("\n");
  for (const key of ["title", "summary", "contract_type", "remote", ...TEXTS.map(([k]) => k)]) form[key] = details[key] ?? "";
  form.min_years_experience = details.min_years_experience ?? "";
  return form;
}

function toDetails(form) {
  const details = { ...form };
  for (const [key] of LISTS) details[key] = form[key].split("\n").map((line) => line.trim()).filter(Boolean);
  for (const key of ["summary", "contract_type", "remote", ...TEXTS.map(([k]) => k)]) details[key] = form[key].trim() || null;
  details.title = form.title.trim();
  details.min_years_experience = form.min_years_experience === "" ? null : Number(form.min_years_experience);
  return details;
}

export function JobReviewForm({ posting, busy, onSave, onPublish, onClose, onDismiss }) {
  const [form, setForm] = useState(() => toForm(posting.details));
  useEffect(() => { setForm(toForm(posting.details)); }, [posting]);

  const draft = posting.status === "draft";
  const set = (key) => (event) => setForm({ ...form, [key]: event.target.value });
  const valid = form.title.trim().length > 0;

  const publish = async () => {
    const saved = await onSave(toDetails(form));
    if (!saved) return;
    // Saving forgets lines seen only in the source document, but HR should still be asked about them once.
    const flags = new Set([...posting.flagged_requirements, ...saved.flagged_requirements]).size;
    if (flags && !window.confirm(`${flags} line(s) mention a protected attribute such as age or gender. Publish anyway?`)) return;
    onPublish();
  };

  return (
    <form className="scr-review" onSubmit={(event) => { event.preventDefault(); if (valid) onSave(toDetails(form)); }}>
      <h3>Review offer <span className={`scr-pill is-status-${posting.status}`}>{posting.status}</span></h3>
      {posting.extraction_failed && (
        <p className="scr-alert" role="alert">The model could not read this offer. Please fill in the fields by hand.</p>
      )}
      {posting.injection_excerpts.length > 0 && (
        <div className="scr-alert" role="alert">
          <strong>Possible prompt injection.</strong> These lines were removed from the offer.
          <ul>{posting.injection_excerpts.map((line) => <li key={line}><code>{line}</code></li>)}</ul>
        </div>
      )}
      {posting.hidden_text_removed && <p className="scr-alert">Hidden text was removed from this file.</p>}
      {posting.flagged_requirements.length > 0 && (
        <div className="scr-alert" role="alert">
          <strong>Please check these lines.</strong> They mention a protected attribute such as age or gender. You decide whether they stay.
          <ul>{posting.flagged_requirements.map((line) => <li key={line}>{line}</li>)}</ul>
        </div>
      )}

      <fieldset disabled={!draft || busy} className="scr-fieldset">
        <label className="scr-field">Title<input required maxLength={200} value={form.title} onChange={set("title")} /></label>
        <div className="scr-two">
          <label className="scr-field">
            Contract
            <select value={form.contract_type} onChange={set("contract_type")}>
              <option value="">Not stated</option>
              {CONTRACTS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="scr-field">
            Work mode
            <select value={form.remote} onChange={set("remote")}>
              <option value="">Not stated</option>
              {REMOTE.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        </div>
        {TEXTS.map(([key, label, max]) => (
          <label className="scr-field" key={key}>{label}<input maxLength={max} value={form[key]} onChange={set(key)} /></label>
        ))}
        <label className="scr-field">
          Minimum years of experience
          <input type="number" min="0" max="50" step="0.5" value={form.min_years_experience} onChange={set("min_years_experience")} />
        </label>
        <label className="scr-field">Summary<textarea rows={3} maxLength={2000} value={form.summary} onChange={set("summary")} /></label>
        {LISTS.map(([key, label]) => (
          <label className="scr-field" key={key}>
            {label}, one per line
            <textarea rows={3} value={form[key]} onChange={set(key)} />
          </label>
        ))}
      </fieldset>

      <details className="scr-requirements" open>
        <summary>{posting.requirements.length} requirements used for scoring (updated when saved)</summary>
        <ul>{posting.requirements.map((r) => <li key={r.text}>{r.text} <span className="scr-muted">({r.kind})</span></li>)}</ul>
      </details>
      <details className="scr-requirements">
        <summary>View extracted JSON</summary>
        <pre className="scr-json">{JSON.stringify(posting.details, null, 2)}</pre>
      </details>

      <div className="scr-row">
        {draft && <button className="scr-btn" disabled={busy || !valid}>Save draft</button>}
        {draft && <button type="button" className="scr-btn is-primary" disabled={busy || !valid} onClick={publish}>Publish</button>}
        {posting.status === "published" && <button type="button" className="scr-btn" disabled={busy} onClick={onClose}>Close offer</button>}
        <button type="button" className="scr-link" onClick={onDismiss}>Back to screening</button>
      </div>
    </form>
  );
}
