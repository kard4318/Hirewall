# Hirewall

Hirewall provides secure AI agents for HR: the agent executes, the human decides. AI agents screen resumes, summarize the recruiter inbox, draft replies, propose interview slots and answer employee HR questions, while a security layer defends against prompt injection, data poisoning and malicious uploads, and every outgoing action waits in an approval queue until a human approves it.

## Folder overview

| Folder | Contents |
|---|---|
| `docs/` | Architecture, API contract, data model, security, demo script, credits |
| `data/` | Fictional demo data (resumes, job offers, emails, calendar, HR documents) and attack samples |
| `backend/gateway/` | HTTP API: routers, schemas, auth, middleware |
| `backend/orchestrator/` | Agent workflow graph, state, routing, approval pauses, checkpoints |
| `backend/services/` | Agent services: screener, summarizer, drafter, scheduler, employee_qa |
| `backend/security/` | Input/output defenses and the red-team attack suite |
| `backend/core/` | Shared building blocks: LLM client, DB, approval queue, executor, audit, integrations, logging |
| `backend/tests/` | Integration and end-to-end tests |
| `frontend/` | React (Vite) web app |
| `scripts/` | Data generation, seeding, attack suite runner, demo reset |
| `deploy/` | Deployment assets (Neo4j init) |
| `.github/` | PR template, CODEOWNERS, CI workflow |

## Team rules

1. `docs/api-contract.md` is the source of truth, written before code.
2. Branches are named `feat/<name>-<thing>` and merged into `main` by PR only.
3. No secrets are committed; only `.env.example`.
4. Fictional data only, no real personal data.
5. Credit third-party code in [docs/CREDITS.md](docs/CREDITS.md).
6. Services never import from other services, only from `core/` and `security/`.
7. Only `core/executor` may send or record anything, and only after human approval.

## Ownership

| Folder | Owner |
|---|---|
| `docs/` | TBD |
| `data/` | TBD |
| `backend/gateway/` | TBD |
| `backend/orchestrator/` | TBD |
| `backend/services/screener/` | TBD |
| `backend/services/summarizer/` | TBD |
| `backend/services/drafter/` | TBD |
| `backend/services/scheduler/` | TBD |
| `backend/services/employee_qa/` | TBD |
| `backend/security/` | TBD |
| `backend/core/` | TBD |
| `frontend/` | TBD |
| `scripts/` | TBD |
| `deploy/` | TBD |

## Run the drafter locally

The drafter runs a local model through [Ollama](https://ollama.com), so it is free, needs no API key, and sends no data to a cloud service. Sending is simulated: approved emails are written to a local outbox file, `.runtime/outbox.jsonl`.

Install Ollama, then download the default model (about 4 GB, and a GPU with 6 GB of memory is enough):

```bash
winget install Ollama.Ollama   # or download it from ollama.com
ollama pull qwen3.5:4b
```

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r backend/requirements.txt   # .venv/bin/python on macOS and Linux
cp .env.example .env
```

Then, using that Python:

```bash
python scripts/run_drafter_demo.py draft --all          # draft replies for the fictional inbox and attack emails
python scripts/run_drafter_demo.py list --status pending
python scripts/run_drafter_demo.py approve <id> --by "Nadia Karim"
python scripts/run_drafter_demo.py outbox
python scripts/run_drafter_demo.py audit
python scripts/run_drafter_demo.py reset
```

The script runs the LangGraph orchestrator described in [docs/architecture.md](docs/architecture.md), which also explains how to add a service. It also has `show`, `edit`, `reject`, `redraft`, and `graph` commands. Run the backend tests from `backend/` with `python -m pytest .`. They use no API key and make no network calls.

## Run the screener

The screener reads resumes, scores candidates against a job and shows them in the Talent Orbit view. It only ranks and explains: a recruiter proposes a shortlist, and a person approves it in the approval queue before anything is recorded. Everything runs locally. See [its README](backend/services/screener/README.md).

Follow the setup in "Run the drafter locally" for Python, Ollama and `.env`. In `.env`, also set `HR_PASSCODE`, `HR_TOKEN_SECRET` and `SCHEDULER_TOKEN_SECRET` (two different random values), and set `LLM_MODEL` if you pulled another model. The first scoring run downloads the embedding model once (about 450 MB). To skip that for a quick look, set `SCREENER_EMBEDDER=hashing`, which gives rough semantic scores.

```bash
# Terminal 1, from backend/
python -m gateway.main

# Terminal 2, from frontend/
npm install
npm run dev
```

Open http://localhost:5173/hr/screening and sign in with `HR_PASSCODE`. Then:

1. Choose **Load demo candidates**, or drop PDF and DOCX resumes.
2. Pick a job and choose **Score candidates**. Grey moons glide inward as results arrive.
3. Open a candidate. Review is blind by default; **Reveal identity** is recorded in the audit log.
4. Tick candidates and choose **Propose shortlist**, then follow the link to the approval queue.
5. Approve it. A shortlisted candidate gets the Scheduler's invitation, and a rejected one gets a rejection email, at the address in their CV. The result for each candidate and the audit events appear on the same page.

Emails only reach candidates with `EMAIL_MODE=smtp` and `SMTP_HOST`, `SMTP_FROM`, `SMTP_USER` and `SMTP_PASSWORD` in `.env`. Otherwise they stay in a local outbox and the page says so. For Gmail, use `SMTP_HOST=smtp.gmail.com` and an app password. Set `PUBLIC_BASE_URL` to an address candidates can open, because `localhost` only works on your own machine.

To run it with no gateway, no Ollama and no download, with a placeholder rubric:

```bash
python scripts/demo_screener.py --demo --job job-preset-backend --fake-llm
```

## Credits

See [docs/CREDITS.md](docs/CREDITS.md).
