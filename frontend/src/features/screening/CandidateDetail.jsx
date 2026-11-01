// Detail panel. Resume and model text is rendered as plain text only
import { percent } from "./api.js";

const CRITERIA = [["semantic", "Semantic match"], ["rubric", "Rubric"], ["experience", "Experience"]];
const SUB_SCORES = [
  ["skills_coverage", "Skills coverage", "skills_text"],
  ["related_experience", "Related experience", "experience_text"],
  ["field_closeness", "Field and role", "field_text"],
];

function Skills({ title, items, tone }) {
  if (!items.length) return null;
  return (
    <div className="scr-skills">
      <h4>{title}</h4>
      <div>{items.map((skill) => <span key={skill} className={`scr-pill ${tone}`}>{skill}</span>)}</div>
    </div>
  );
}

export function CandidateDetail({ candidate, label, identity, blind, onReveal }) {
  if (!candidate) return <section className="scr-card scr-detail"><p className="scr-muted">Select a candidate in the orbit or the table.</p></section>;
  const { rubric, experience, weights_used: weights, scores } = candidate;
  const chunks = Object.fromEntries(candidate.evidence_chunks.map((chunk) => [chunk.chunk_id, chunk.text]));

  return (
    <section className="scr-card scr-detail" aria-label={`Details for ${label}`}>
      <h2>{label}</h2>
      <p className="scr-muted">{candidate.profile} · rank {candidate.rank}</p>

      {!identity && (
        <button type="button" className="scr-btn" onClick={onReveal}>Reveal identity (recorded in the audit log)</button>
      )}
      {identity && !blind && (
        <dl className="scr-identity">
          <dt>Name</dt><dd>{identity.full_name || "Not found"}</dd>
          {identity.emails.length > 0 && <><dt>Email</dt><dd>{identity.emails.join(", ")}</dd></>}
          {identity.phones.length > 0 && <><dt>Phone</dt><dd>{identity.phones.join(", ")}</dd></>}
          {identity.links.length > 0 && <><dt>Links</dt><dd>{identity.links.join(", ")}</dd></>}
        </dl>
      )}

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
    </section>
  );
}
