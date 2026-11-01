// One candidate dossier: score, matched skills, justification, status stamp and the one action that fits
import { useState } from "react";
import { StatusStamp } from "../StatusStamp.jsx";

export function DossierCard({ row, rank, actions }) {
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  async function act(fn) {
    setBusy(true);
    try {
      await fn();
    } finally {
      setBusy(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(new URL(row.candidate_link, window.location.origin).href);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      window.prompt("Copy the candidate link:", new URL(row.candidate_link, window.location.origin).href);
    }
  }

  function cancel() {
    if (window.confirm(`Cancel ${row.first_name}'s interview? The calendar event will be deleted.`)) {
      act(() => actions.cancel(row.booking.booking_id));
    }
  }

  return (
    <li className={`dossier status-${row.status}`} style={{ "--i": rank - 1 }}>
      <div className="dossier-rank" aria-label={`Rank ${rank}`}>{String(rank).padStart(2, "0")}</div>
      <div className="dossier-body">
        <div className="dossier-top">
          <h2 className="dossier-name">{row.first_name} {row.last_name}</h2>
          <StatusStamp status={row.status} />
        </div>
        <ul className="skills" aria-label="Matched skills">
          {row.matched_skills.map((skill) => <li key={skill} className="tag">{skill}</li>)}
        </ul>
        <p className="justification">{row.justification}</p>
        <div className="dossier-actions">
          {row.status === "passed" && (
            <button className="btn btn-primary" disabled={busy} onClick={() => act(() => actions.invite(row.candidate_id))}>
              Invite to book
            </button>
          )}
          {row.status === "invited" && row.candidate_link && (
            <>
              <button className="btn" onClick={copyLink}>{copied ? "Copied ✓" : "Copy link"}</button>
              <a className="btn btn-ghost" href={row.candidate_link} target="_blank" rel="noopener noreferrer">
                Open candidate page ↗
              </a>
            </>
          )}
          {row.status === "invited" && !row.candidate_link && (
            <button className="btn" disabled={busy} onClick={() => act(() => actions.invite(row.candidate_id))}>
              Issue a new link
            </button>
          )}
          {row.status === "pending_approval" && row.pending_booking_id && (
            <>
              <button className="btn btn-primary" disabled={busy} onClick={() => act(() => actions.approve(row.pending_booking_id))}>
                Approve
              </button>
              <button className="btn" disabled={busy} onClick={() => act(() => actions.decline(row.pending_booking_id))}>
                Decline
              </button>
            </>
          )}
          {row.status === "booked" && row.booking && (
            <>
              <span className="slot-line">{row.booking.label}</span>
              {row.booking.link && (
                <a className="btn" href={row.booking.link} target="_blank" rel="noopener noreferrer">
                  Open in Google Calendar ↗
                </a>
              )}
              <button className="btn btn-ghost" disabled={busy} onClick={cancel}>Cancel</button>
            </>
          )}
        </div>
      </div>
      <div className="dossier-score" aria-label={`Score ${row.score} out of 100`}>
        <span className="score-num">{row.score}</span>
        <span className="label">score</span>
      </div>
    </li>
  );
}
