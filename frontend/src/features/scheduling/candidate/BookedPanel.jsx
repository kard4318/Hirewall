// Booked state of the ticket: rubber BOOKED stamp, the time, and an add-to-your-calendar link
const compact = (iso) => new Date(iso).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");

// Builds a Google "add event" link for the candidate's own calendar; it never exposes the HR calendar.
function addToCalendarUrl(booking, jobTitle, company) {
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: `Interview: ${jobTitle}${company ? ` at ${company}` : ""}`,
    dates: `${compact(booking.start)}/${compact(booking.end)}`,
    details: "Interview booked through the Hirewall scheduling assistant.",
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

export function BookedPanel({ booking, jobTitle, company }) {
  const [day, time] = booking.label.split(", ");
  return (
    <section className="booked" aria-label="Your interview is booked">
      <span className="booked-stamp" aria-hidden="true">Booked</span>
      <p className="label">Your interview</p>
      <p className="booked-day display">{day}</p>
      <p className="booked-time">{time}</p>
      <a className="btn btn-primary" href={addToCalendarUrl(booking, jobTitle, company)} target="_blank" rel="noopener noreferrer">
        Open in calendar ↗
      </a>
    </section>
  );
}
