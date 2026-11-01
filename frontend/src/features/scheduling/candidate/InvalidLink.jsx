// Shown when a candidate link is missing, invalid or expired; reveals nothing about the booking
import { Wordmark } from "../Wordmark.jsx";

export function InvalidLink({ problem = false }) {
  return (
    <div className="desk paper">
      <article className="ticket ticket-void">
        <Wordmark />
        <h1 className="display">{problem ? "We couldn't open your ticket." : "This ticket can't be opened."}</h1>
        <p>
          {problem
            ? "Something went wrong on our side. Please try again in a moment."
            : "Open the link from your invitation email. If it has expired, reply to that email and HR will send a new one."}
        </p>
      </article>
    </div>
  );
}
