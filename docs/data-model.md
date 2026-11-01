# Data Model

Entities, relationships and storage (relational DB and Neo4j skill graph).

TODO: the other services and the Neo4j skill graph.

## Screener

The screener stores JSON documents in SQLite under `core.paths.runtime_dir()`.

| File | Table | Holds |
|---|---|---|
| `screener.sqlite3` | `candidates` | `StoredCandidate`: pseudonymous document and profile, unique by content hash |
| | `postings` | `JobPosting`: draft, published or closed offers |
| | `applications` | `Application`: unique by job and candidate |
| | `jobs` | hand-written `JobOffer`s |
| | `runs`, `tasks`, `proposals`, `rubric_cache` | scoring runs, background tasks, prepared decisions, cached rubric results |
| `screener_identity.sqlite3` | `identity` | what was found in a CV, one row per candidate |
| | `application_contacts` | what was typed in the form, one row per submission |
| `candidate_status.sqlite3` | `candidate_status` | decisions recorded by `core/executor` after human approval |

Samples and presets are read from `data/job_offers/*.json` and are never stored.

```
JobPosting 1---* Application *---1 StoredCandidate 1---1 identity
                                                   1---* application_contacts
JobOffer (sample, preset, hand-written, or a published or closed JobPosting) 1---* ScreeningRun
```

- One CV is one candidate, whichever jobs it applies to.
- Only `reveal_identity` and `decision_contact` read `screener_identity.sqlite3`, and each call is audited.
- `scheduler_handoff.json` holds the name and address of candidates a person approved for an invitation.
- A cover letter lives on its `Application` and never reaches scoring.
