// Step 1: upload resumes or load the demo set, with one result per file
import { useRef, useState } from "react";
import { shortId } from "./api.js";

const REASONS = {
  unsupported_type: "Only PDF and DOCX are accepted",
  file_too_large: "Larger than 5 MB",
  bad_signature: "The content does not match the file type",
  encrypted_pdf: "Password-protected PDF",
  too_many_pages: "More than 10 pages",
  zip_bomb: "Unsafe DOCX archive",
  bad_archive_path: "Unsafe DOCX archive",
  no_text: "No readable text",
  empty_file: "Empty file",
  unreadable_pdf: "The PDF could not be read",
  unreadable_docx: "The DOCX could not be read",
  ingest_failed: "Processing failed",
};

function fileLine(file, names) {
  const name = names?.[file.index] ?? `Item ${file.index + 1}`;
  if (file.status === "rejected" || file.status === "failed") {
    return { level: "error", text: `${name}: ${REASONS[file.reason_code] ?? "Refused"}` };
  }
  const notes = [];
  if (file.status === "duplicate") notes.push("already loaded");
  if (file.injection_flag) notes.push("injection flagged");
  if (file.hidden_text_removed) notes.push("hidden text removed");
  if (file.extraction_failed) notes.push("sections only");
  const level = file.injection_flag || file.hidden_text_removed ? "warn" : "ok";
  return { level, text: `${name} → ${shortId(file.candidate_id ?? "")}${notes.length ? ` (${notes.join(", ")})` : ""}` };
}

export function UploadPanel({ task, names, count, busy, onFiles, onDemo }) {
  const input = useRef(null);
  const [over, setOver] = useState(false);

  const take = (list) => {
    const files = [...list];
    if (files.length) onFiles(files);
  };

  return (
    <section className="scr-card">
      <h2>1. Candidates <span className="scr-muted">({count})</span></h2>
      <button
        type="button"
        className={`scr-drop${over ? " is-over" : ""}`}
        disabled={busy}
        onClick={() => input.current.click()}
        onDragOver={(event) => { event.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(event) => { event.preventDefault(); setOver(false); take(event.dataTransfer.files); }}
      >
        Drop PDF or DOCX resumes here, or choose files
        <span className="scr-muted">Up to 20 files, 5 MB each</span>
      </button>
      <input
        ref={input}
        type="file"
        hidden
        multiple
        accept=".pdf,.docx"
        onChange={(event) => { take(event.target.files); event.target.value = ""; }}
      />
      <button type="button" className="scr-btn" disabled={busy} onClick={onDemo}>Load demo candidates</button>
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
    </section>
  );
}
