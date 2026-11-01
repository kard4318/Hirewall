// Step 1: upload resumes or load the demo set, with one result per file
import { useRef, useState } from "react";
import { shortId } from "./api.js";
import { FILE_REASONS as REASONS } from "./reasons.js";

function fileLine(file, names) {
  const name = names?.[file.index] ?? `Row ${file.index + 1}`;
  if (file.status === "rejected" || file.status === "failed") {
    return { level: "error", text: `${name}: ${REASONS[file.reason_code] ?? "Refused"}` };
  }
  const notes = [];
  if (file.status === "duplicate") notes.push("already loaded");
  if (file.injection_flag) notes.push("injection flagged");
  if (file.hidden_text_removed) notes.push("hidden text removed");
  if (file.extraction_failed) notes.push("sections only");
  if (file.reason_code) notes.push(REASONS[file.reason_code] ?? file.reason_code);
  const level = file.injection_flag || file.hidden_text_removed || file.reason_code ? "warn" : "ok";
  return { level, text: `${name} → ${shortId(file.candidate_id ?? "")}${notes.length ? ` (${notes.join(", ")})` : ""}` };
}

export function UploadPanel({ task, names, count, busy, onFiles, onDemo, applications, labelFor, attachTitle, onSelect }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);

  const take = (list) => {
    const files = [...list];
    if (files.length) onFiles(files);
  };

  return (
    <section className="scr-card">
      <h2>Candidates <span className="scr-muted">({count})</span></h2>
      <button
        type="button"
        className={`scr-drop${over ? " is-over" : ""}`}
        disabled={busy}
        onClick={() => input.current.click()}
        onDragOver={(event) => { event.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => { event.preventDefault(); setOver(false); take(event.dataTransfer.files); }}
      >
        Drop PDF or DOCX resumes, or a CSV with its files
        <span className="scr-muted">Up to 20 files without a CSV, 5 MB each</span>
      </button>
      <input
        ref={input}
        type="file"
        hidden
        multiple
        accept=".pdf,.docx,.csv"
        onChange={(event) => { take(event.target.files); event.target.value = ""; }}
      />
      <details className="scr-requirements">
        <summary>CSV format</summary>
        <p className="scr-muted">
          Columns: <code>name</code>, <code>email</code>, <code>cv</code>, <code>cover_letter</code>. Only <code>cv</code> is required.
          In <code>cv</code> and <code>cover_letter</code>, write a file name and drop that file with the CSV, or paste the text itself.
          Select a published offer first to keep cover letters.
        </p>
      </details>
      {applications && (
        <details className="scr-applicants scr-requirements">
          <summary>{applications.length} application{applications.length === 1 ? "" : "s"}</summary>
          {attachTitle && <p className="scr-muted">New uploads are attached to {attachTitle}.</p>}
          <ul>
            {applications.map((row) => (
              <li key={row.application_id}>
                <button type="button" className="scr-link" onClick={() => onSelect(row.candidate_id)}>{labelFor(row.candidate_id)}</button>
                {row.source === "hr_upload" && <span className="scr-pill">HR upload</span>}
                {row.candidate.injection_flag && <span className="scr-pill is-danger">flagged</span>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {task && (
        <div className="scr-task" aria-live="polite">
          {task.status !== "done" && <progress max={task.total || 1} value={task.done} />}
          <ul>
            {task.files.map((file) => {
              const line = fileLine(file, names);
              return <li key={file.index} className={`is-${line.level}`}>{line.text}</li>;
            })}
          </ul>
        </div>
      )}
      <button type="button" className="scr-btn scr-demo" disabled={busy} onClick={onDemo}>Load demo candidates</button>
    </section>
  );
}
