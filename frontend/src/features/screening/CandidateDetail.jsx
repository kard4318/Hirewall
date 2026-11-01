// Detail panel. Resume and model text is rendered as plain text only
import { percent } from "./api.js";
import { DecisionButtons } from "./DecisionButtons.jsx";

const CRITERIA = [["semantic", "Semantic match"], ["rubric", "Rubric"], ["experience", "Experience"]];
const SUB_SCORES = [
  ["skills_coverage", "Skills coverage", "skills_text"],
  ["related_experience", "Related experience", "experience_text"],
  ["field_closeness", "Field and role", "field_text"],
];

function Values({ data, labels }) {
  const rows = labels
    .map(([key, name]) => [name, Array.isArray(data[key]) ? data[key].join(", ") : data[key]])
    .filter(([, value]) => value);
  if (!rows.length) return <p className="scr-muted">Nothing extracted.</p>;
  return <dl className="scr-identity">{rows.map(([name, value]) => <div key={name} className="scr-contents"><dt>{name}</dt><dd>{value}</dd></div>)}</dl>;
}

const LETTER_LABELS = [["motivation_summary", "Motivation"], ["skills_mentioned", "Skills"], ["relevant_experiences", "Experience"],
  ["availability", "Availability"], ["start_date", "Start date"], ["desired_duration", "Duration"], ["languages", "Languages"], ["mobility", "Mobility"]];

function ExtractedData({ extracted, application, open = false }) {
  if (!extracted) return null;
  const { profile } = extracted;
  const letter = application?.cover_letter;
  return (
    <details className="scr-requirements scr-extracted" open={open}>
      <summary>Extracted data</summary>
      <h4>CV</h4>
      {profile ? (
        <>
          <Values data={profile} labels={[["current_title", "Current title"], ["skills", "Skills"]]} />
          <ul className="scr-evidence">
            {profile.positions.map((p) => (
              <li key={`${p.title}${p.organization}${p.end}`}>{[p.title, p.organization].filter(Boolean).join(", ")} {[p.start, p.end].filter(Boolean).join(" - ")}</li>
            ))}
          </ul>
        </>
      ) : <p className="scr-muted">The model could not structure this CV. The sections below came from its headings.</p>}
      <details className="scr-requirements">
        <summary>View CV JSON</summary>
        <pre className="scr-json">{JSON.stringify({ profile, sections: extracted.sections }, null, 2)}</pre>
      </details>
      {application && (letter || application.cover_letter_text || application.cover_letter_failed) && (
        <>
          <h4>Cover letter (display only, not scored)</h4>
          {letter && <Values data={letter} labels={LETTER_LABELS} />}
          {application.cover_letter_failed && <p className="scr-muted">The model could not structure this letter.</p>}
          {(letter || application.cover_letter_text) && (
            <details className="scr-requirements" open={!letter}>
              <summary>{letter ? "View letter JSON and text" : "View letter text"}</summary>
              {letter && <pre className="scr-json">{JSON.stringify(letter, null, 2)}</pre>}
              {application.cover_letter_text && <blockquote className="scr-letter">{application.cover_letter_text}</blockquote>}
            </details>
          )}
        </>
      )}
    </details>
  );
}

function Identity({ identity, blind, onReveal }) {
  if (!identity) {
    return <button type="button" className="scr-btn" onClick={onReveal}>Reveal identity (recorded in the audit log)</button>;
  }
  if (blind) return null;
  return (
    <dl className="scr-identity">
      <dt>Name</dt><dd>{identity.full_name || "Not found"}</dd>
      {identity.emails.length > 0 && <><dt>Email</dt><dd>{identity.emails.join(", ")}</dd></>}
      {identity.phones.length > 0 && <><dt>Phone</dt><dd>{identity.phones.join(", ")}</dd></>}
      {identity.links.length > 0 && <><dt>Links</dt><dd>{identity.links.join(", ")}</dd></>}
      {identity.contacts.map((contact) => (
        <div key={contact.reference_id} className="scr-contents"><dt>From the form</dt><dd>{contact.full_name}, {contact.email}</dd></div>
      ))}
    </dl>
  );
}

function Skills({ title, items, tone }) {
  if (!items.length) return null;
  return (
    <div className="scr-skills">
      <h4>{title}</h4>
      <div>{items.map((skill) => <span key={skill} className={`scr-pill ${tone}`}>{skill}</span>)}</div>
    </div>
  );
}

export function CandidateDetail({ candidate, label, identity, blind, onReveal, extracted, application, status, proposal, canDecide, onDecide }) {
  if (!candidate && !extracted) return <section className="scr-card scr-detail"><p className="scr-muted">Select a candidate in the orbit or the table.</p></section>;
  if (!candidate) {
    // An applicant who has not been scored yet: what was extracted is all there is to read.
    const excerpts = application?.injection_excerpts ?? [];
    const lines = [...extracted.injection_excerpts, ...excerpts];
    return (
      <section className="scr-card scr-detail" aria-label={`Details for ${label}`}>
        <h2>{label}</h2>
        <p className="scr-muted">Not scored yet</p>
        <Identity identity={identity} blind={blind} onReveal={onReveal} />
        {lines.length > 0 && (
          <div className="scr-alert" role="alert">
            <strong>Possible prompt injection.</strong> These lines were removed.
            <ul>{lines.map((line) => <li key={line}><code>{line}</code></li>)}</ul>
          </div>
        )}
        <ExtractedData extracted={extracted} application={application} open />
      </section>
    );
  }
  const { rubric, experience, weights_used: weights, scores } = candidate;
  const chunks = Object.fromEntries(candidate.evidence_chunks.map((chunk) => [chunk.chunk_id, chunk.text]));

  return (
    <section className="scr-card scr-detail" aria-label={`Details for ${label}`}>
      <h2>{label}</h2>
      <p className="scr-muted">{candidate.profile} · rank {candidate.rank}</p>
      <DecisionButtons
        candidateId={candidate.candidate_id}
        status={status}
        proposal={proposal}
        disabled={!canDecide}
        onDecide={onDecide}
      />

      <Identity identity={identity} blind={blind} onReveal={onReveal} />

      {(candidate.injection_flag || candidate.hidden_text_removed) && (
        <div className="scr-alert" role="alert">
          {candidate.injection_flag && (
            <>
              <strong>Possible prompt injection.</strong> These lines were removed before scoring. The flag does not change the score.
              <ul>{candidate.injection_excerpts.map((line) => <li key={line}><code>{line}</code></li>)}</ul>
            </>
          )}
          {candidate.hidden_text_removed && <p>Hidden text (white, tiny, off-page or invisible characters) was removed from this file.</p>}
        </div>
      )}

      <p className="scr-total"><strong>{percent(candidate.total_score)}</strong> total</p>
      <table className="scr-subscores">
        <thead><tr><th scope="col">Criterion</th><th scope="col" className="is-num">Score</th><th scope="col" className="is-num">Weight used</th></tr></thead>
        <tbody>
          {CRITERIA.map(([key, name]) => (
            <tr key={key}>
              <td>{name}</td>
              <td className="is-num">{percent(scores[key])}</td>
              <td className="is-num">{weights[key] === undefined ? "Not applied" : percent(weights[key])}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3>Rubric</h3>
      {rubric.score === null ? (
        <p className="scr-muted">Not available ({rubric.reason_code ?? "no result"}). The other criteria were used.</p>
      ) : (
        <dl className="scr-rubric">
          {SUB_SCORES.map(([score, name, text]) => (
            <div key={score}>
              <dt>{name}: {rubric[score]}/10</dt>
              <dd>{rubric[text]}</dd>
            </div>
          ))}
        </dl>
      )}

      <h3>Experience</h3>
      <p>{experience.explanation}</p>

      <h3>Skills</h3>
      <Skills title="Matched" items={candidate.matched_skills} tone="is-ok" />
      <Skills title="Missing" items={candidate.missing_skills} tone="is-warn" />
      <Skills title="Additional (not scored)" items={candidate.additional_skills} tone="" />

      <h3>Evidence</h3>
      <ul className="scr-evidence">
        {candidate.evidence.map((item) => (
          <li key={item.requirement}>
            <strong>{percent(item.score)}</strong> {item.requirement}
            {item.best_chunk_id && chunks[item.best_chunk_id] && <blockquote>{chunks[item.best_chunk_id]}</blockquote>}
          </li>
        ))}
      </ul>

      <ExtractedData extracted={extracted} application={application} />
    </section>
  );
}
