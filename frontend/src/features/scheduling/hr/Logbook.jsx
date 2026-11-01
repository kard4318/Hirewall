// "The logbook": bottom drawer with the latest audit entry; expands to the last 30 entries
import { useState } from "react";

const time = (iso) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "--:--";
const label = (event) => event.replaceAll("_", " ");
const tone = (event) =>
  /blocked|failed|rejected|limit/.test(event) ? "bad" : /booking_created|approved/.test(event) ? "ok" : "";

function Entry({ entry }) {
  return (
    <li className={`log-entry ${tone(entry.event)}`}>
      <time className="log-time">{time(entry.at)}</time>
      <span className="log-event">{label(entry.event)}</span>
      {entry.reason && <span className="log-reason">{entry.reason.replaceAll("_", " ")}</span>}
      {entry.candidate && <span className="log-who">{entry.candidate}</span>}
    </li>
  );
}

export function Logbook({ audit }) {
  const [open, setOpen] = useState(false);
  const latest = audit.entries[0];

  return (
    <aside className={`logbook${open ? " is-open" : ""}`} aria-label="Audit logbook">
      <button className="logbook-bar" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="label">The logbook</span>
        <span className="logbook-latest">{latest ? <Entry entry={latest} /> : "Nothing recorded yet."}</span>
        <span className={`blocked-badge${audit.blocked_count ? " has-blocks" : ""}`}>
          {audit.blocked_count} blocked
        </span>
        <span className="logbook-caret" aria-hidden="true">{open ? "▾" : "▴"}</span>
      </button>
      {open && (
        <ol className="logbook-list">
          {audit.entries.map((entry, i) => <Entry key={`${entry.at}-${i}`} entry={entry} />)}
        </ol>
      )}
    </aside>
  );
}
