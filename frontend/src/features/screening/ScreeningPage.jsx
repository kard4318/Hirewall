// /hr/screening: upload resumes, score a job, watch the orbit, review candidates, propose a shortlist
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { screeningApi, shortId } from "./api.js";
import { CandidateDetail } from "./CandidateDetail.jsx";
import { JobPanel } from "./JobPanel.jsx";
import { RankingTable } from "./RankingTable.jsx";
import { TalentOrbitView } from "./TalentOrbitView.jsx";
import { UploadPanel } from "./UploadPanel.jsx";
import "./screening.css";

const POLL_MS = 1500;

export function ScreeningPage() {
  const { token, signOut } = useHrSession();
  const [error, setError] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState(null);
  const [task, setTask] = useState(null);
  const [names, setNames] = useState(null);
  const [run, setRun] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [checked, setChecked] = useState(() => new Set());
  const [blind, setBlind] = useState(true);
  const [identities, setIdentities] = useState({});
  const [paused, setPaused] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  const [proposal, setProposal] = useState(null);
  const polling = useRef(null);

  const call = useCallback(async (action) => {
    setError(null);
    try {
      return await action(token);
    } catch (err) {
      if (err.status === 401) signOut();
      else setError(err.message || "Request failed");
      return null;
    }
  }, [token, signOut]);

  const refreshCandidates = useCallback(async () => {
    const data = await call((t) => screeningApi.candidates(t));
    if (data) setCandidates(data.candidates);
  }, [call]);

  useEffect(() => {
    refreshCandidates();
    call((t) => screeningApi.jobs(t)).then((data) => {
      if (data) {
        setJobs(data.jobs);
        setJobId((current) => current ?? data.jobs[0]?.job_id ?? null);
      }
    });
  }, [call, refreshCandidates]);

  const taskId = task?.status === "done" ? null : task?.task_id;
  useEffect(() => {
    if (!taskId) return undefined;
    polling.current = setInterval(async () => {
      const next = await call((t) => screeningApi.task(t, taskId));
      if (next) {
        setTask(next);
        refreshCandidates();
      }
    }, POLL_MS);
    return () => clearInterval(polling.current);
  }, [taskId, call, refreshCandidates]);

  const runId = run && run.status !== "done" && run.status !== "failed" ? run.run_id : null;
  useEffect(() => {
    if (!runId) return undefined;
    const timer = setInterval(async () => {
      const next = await call((t) => screeningApi.run(t, runId));
      if (next) setRun(next);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [runId, call]);

  const upload = async (files) => {
    const started = await call((t) => screeningApi.upload(t, files));
    if (started) {
      // File names stay in this browser: the server never stores them.
      setNames(files.map((file) => file.name));
      setTask({ task_id: started.task_id, status: "queued", total: files.length, done: 0, files: [] });
    }
  };

  const loadDemo = async () => {
    const started = await call((t) => screeningApi.demo(t));
    if (started) {
      setNames(null);
      setTask({ task_id: started.task_id, status: "queued", total: 0, done: 0, files: [] });
    }
  };

  const createJob = async (job) => {
    const created = await call((t) => screeningApi.createJob(t, job));
    if (!created) return false;
    setJobs((list) => [...list, created]);
    setJobId(created.job_id);
    return true;
  };

  const score = async () => {
    const started = await call((t) => screeningApi.startRun(t, jobId));
    if (started) {
      setChecked(new Set());
      setProposal(null);
      const first = await call((t) => screeningApi.run(t, started.run_id));
      if (first) setRun(first);
    }
  };

  const reveal = async (id) => {
    const record = await call((t) => screeningApi.identity(t, id));
    if (record) {
      setIdentities((current) => ({ ...current, [id]: record }));
      setBlind(false);
    }
  };

  const labelFor = useCallback((id) => {
    const name = !blind && identities[id]?.full_name;
    return name || shortId(id);
  }, [blind, identities]);

  const scored = useMemo(() => run?.candidates ?? [], [run]);
  const pendingIds = useMemo(() => run?.pending ?? [], [run]);
  const statuses = useMemo(() => run?.statuses ?? {}, [run]);
  const selected = scored.find((c) => c.candidate_id === selectedId) ?? null;

  const job = jobs.find((j) => j.job_id === (run?.job_id ?? jobId));
  const profiles = useMemo(() => Object.fromEntries(candidates.map((c) => [c.candidate_id, c])), [candidates]);

  const orbitRows = useMemo(() => {
    const done = scored.map((c) => ({
      id: c.candidate_id,
      score: c.total_score,
      profile: c.profile,
      status: statuses[c.candidate_id] ?? "pending",
      quarantined: c.injection_flag,
      warning: c.hidden_text_removed && !c.injection_flag,
      label: labelFor(c.candidate_id),
    }));
    const waiting = (run ? pendingIds : candidates.map((c) => c.candidate_id)).map((id) => ({
      id,
      score: 0,
      profile: profiles[id]?.profile ?? "Other",
      pending: true,
      label: labelFor(id),
    }));
    return [...done, ...waiting];
  }, [scored, pendingIds, statuses, run, candidates, profiles, labelFor]);

  // Polling returns new objects every time, so the scene only updates when something it draws has changed.
  const signature = JSON.stringify([job?.title, orbitRows]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const orbitData = useMemo(() => ({ job: { title: job?.title ?? "Job offer" }, candidates: orbitRows }), [signature]);

  const toggle = (id) => setChecked((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  const propose = async (kind) => {
    const ids = [...checked];
    const flagged = scored.filter((c) => checked.has(c.candidate_id) && c.injection_flag).length;
    if (kind === "shortlist" && flagged && !window.confirm(`${flagged} selected candidate(s) are flagged for possible prompt injection. Propose anyway?`)) return;
    const created = await call((t) => screeningApi.propose(t, run.run_id, ids, kind));
    if (created) setProposal({ ...created, kind, count: ids.length });
  };

  const taskBusy = Boolean(task && task.status !== "done");
  const finished = run?.status === "done";

  return (
    <main className="scr-page">
      <header className="scr-header">
        <div>
          <h1>Talent Orbit</h1>
          <p className="scr-muted">Scores are a reading aid. Every shortlist or rejection needs a person's approval.</p>
        </div>
        <label className="scr-toggle">
          <input type="checkbox" checked={blind} onChange={(event) => setBlind(event.target.checked)} /> Blind review
        </label>
      </header>
      {error && <p className="scr-alert" role="alert">{error.replaceAll("_", " ")}</p>}

      <div className="scr-grid">
        <div className="scr-side">
          <UploadPanel task={task} names={names} count={candidates.length} busy={taskBusy} onFiles={upload} onDemo={loadDemo} />
          <JobPanel
            jobs={jobs}
            jobId={jobId}
            onPick={setJobId}
            onCreate={createJob}
            onScore={score}
            canScore={candidates.length > 0 && !taskBusy && Boolean(jobId)}
            run={run}
          />
        </div>

        <div className="scr-center">
          <section className="scr-card scr-orbit-card">
            <TalentOrbitView
              data={orbitData}
              selectedId={selectedId}
              paused={paused}
              onSelect={(candidate) => candidate && !candidate.pending && setSelectedId(candidate.id)}
            />
            <button type="button" className="scr-link" onClick={() => setPaused((value) => !value)}>
              {paused ? "Resume orbits" : "Pause orbits"}
            </button>
          </section>

          <section className="scr-card">
            <div className="scr-row is-between">
              <h2>Ranking</h2>
              <div className="scr-row">
                <button type="button" className="scr-btn is-primary" disabled={!finished || !checked.size} onClick={() => propose("shortlist")}>
                  Propose shortlist ({checked.size})
                </button>
                <button type="button" className="scr-btn" disabled={!finished || !checked.size} onClick={() => propose("rejection")}>
                  Propose rejection
                </button>
              </div>
            </div>
            {proposal && (
              <p className="scr-note" aria-live="polite">
                {proposal.kind === "shortlist" ? "Shortlist" : "Rejection"} of {proposal.count} proposed.{" "}
                <Link to={`/hr/approvals?id=${encodeURIComponent(proposal.approval_id)}`}>Review it in the approval queue</Link>
              </p>
            )}
            <RankingTable
              candidates={scored}
              pending={pendingIds}
              statuses={statuses}
              labelFor={labelFor}
              selectedId={selectedId}
              checked={checked}
              onSelect={setSelectedId}
              onToggle={toggle}
            />
          </section>
        </div>

        <CandidateDetail
          candidate={selected}
          label={selected ? labelFor(selected.candidate_id) : ""}
          identity={selected ? identities[selected.candidate_id] : null}
          blind={blind}
          onReveal={() => reveal(selected.candidate_id)}
        />
      </div>
    </main>
  );
}
