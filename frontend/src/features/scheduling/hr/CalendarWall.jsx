// "The wall": the HR Google Calendar embedded in a framed window, reloadable on demand
export function CalendarWall({ embed, reloadKey, onRefresh }) {
  return (
    <section className="wall" aria-label="HR calendar">
      <header className="wall-head">
        <p className="label">The wall · HR calendar</p>
        <button className="btn btn-small" onClick={onRefresh} disabled={!embed?.url}>Refresh</button>
      </header>
      <div className="wall-frame">
        {embed?.url ? (
          <iframe
            key={reloadKey}
            title="HR interview calendar"
            src={embed.url}
            loading="lazy"
            referrerPolicy="no-referrer"
            sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox"
          />
        ) : (
          <div className="wall-empty">
            <p className="display-small">{embed ? embed.hint : "Loading the calendar…"}</p>
            <p>Calendar blank? Open it in a normal window signed in to the demo Google account.</p>
          </div>
        )}
      </div>
    </section>
  );
}
