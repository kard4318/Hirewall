// /hr/directory: search the (fictional) employee directory and open a person's record; HR only
import { useEffect, useState } from "react";
import { request } from "../../scheduling/api.js";
import { useHrSession } from "../HrSession.jsx";

const DEPARTMENTS = ["Engineering", "Support", "Sales", "Product & Design", "Operations", "People & Finance"];
const SITES = ["Tunis", "Paris", "Remote"];
const CONTRACTS = { permanent: "Permanent", fixed_term: "Fixed term", intern: "Intern" };
const REASONS = { career_growth: "Career growth", compensation: "Compensation", management: "Management", relocation: "Relocation",
  personal: "Personal", performance: "Performance", restructuring: "Restructuring", retirement: "Retirement" };

function useDirectory(params) {
  const { token, signOut } = useHrSession();
  const [state, setState] = useState({ status: "loading", data: null });
  const key = JSON.stringify(params);
  useEffect(() => {
    let alive = true;
    const query = new URLSearchParams(Object.entries(JSON.parse(key)).filter(([, v]) => v !== null && v !== "")).toString();
    setState((s) => ({ status: "loading", data: s.data }));
    request(`/api/hr/directory?${query}`, { token })
      .then((data) => alive && setState({ status: "ready", data }))
      .catch((err) => (err.status === 401 ? signOut() : alive && setState({ status: "error", data: null })));
    return () => { alive = false; };
  }, [key, token, signOut]);
  return state;
}

function Record({ id, onClose }) {
  const { token, signOut } = useHrSession();
  const [record, setRecord] = useState(null);
  useEffect(() => {
    let alive = true;
    setRecord(null);
    request(`/api/hr/directory/${encodeURIComponent(id)}`, { token })
      .then((data) => alive && setRecord(data))
      .catch((err) => (err.status === 401 ? signOut() : alive && setRecord({ error: true })));
    return () => { alive = false; };
  }, [id, token, signOut]);

  if (!record) return <aside className="record a-panel"><div className="skeleton"><span /><span /><span /></div></aside>;
  if (record.error) return <aside className="record a-panel"><p className="panel-state">Couldn't open this record.</p></aside>;
  const done = record.training.filter((t) => t.completed).length;
  return (
    <aside className="record a-panel" aria-label={`Record of ${record.name}`}>
      <header className="a-panel-head record-head">
        <div>
          <p className="label">{record.employee_id} · {record.status === "active" ? "Active" : "Left"}</p>
          <h2 className="a-panel-title">{record.name}</h2>
          <p className="a-panel-note">{record.job_title} · {record.department}</p>
        </div>
        <button className="btn-link" onClick={onClose}>Close</button>
      </header>
      <dl className="record-grid">
        <dt>Email</dt><dd><a href={`mailto:${record.email}`}>{record.email}</a></dd>
        <dt>Level</dt><dd>{record.level}</dd>
        <dt>Site</dt><dd>{record.site}</dd>
        <dt>Contract</dt><dd>{CONTRACTS[record.contract] || record.contract}</dd>
        <dt>Hired</dt><dd className="mono">{record.hire_date}</dd>
        <dt>Tenure</dt><dd className="mono">{record.tenure_years} years</dd>
        <dt>Manager</dt><dd>{record.manager ? `${record.manager.name} (${record.manager.job_title})` : "–"}</dd>
        <dt>Direct reports</dt><dd className="mono">{record.direct_reports}</dd>
        {record.end_date && (<>
          <dt>Left on</dt><dd className="mono">{record.end_date}</dd>
          <dt>Exit</dt><dd>{record.exit_type}{record.exit_reason ? ` · ${REASONS[record.exit_reason] || record.exit_reason}` : ""}</dd>
        </>)}
      </dl>
      <p className="label record-sub">Training · {done} of {record.training.length} completed</p>
      <ul className="record-training">
        {record.training.map((t) => (
          <li key={t.course}><span>{t.course}</span><span className="mono">{t.hours} h</span>
            <span className={`stamp ${t.completed ? "stamp-booked" : "stamp-passed"}`}>{t.completed ? "Done" : "Open"}</span></li>
        ))}
        {record.training.length === 0 && <li className="muted">No training assigned.</li>}
      </ul>
      <p className="a-footnote">Age band and gender are only shown in aggregate, never on a person's record.</p>
    </aside>
  );
}

export function DirectoryPage() {
  const [draft, setDraft] = useState("");
  const [params, setParams] = useState({ q: "", department: "", site: "", contract: "", status: "active", page: 1 });
  const [openId, setOpenId] = useState(null);
  const result = useDirectory(params);

  useEffect(() => {  // search as you type, without a request per keystroke
    const id = setTimeout(() => setParams((p) => (p.q === draft ? p : { ...p, q: draft, page: 1 })), 250);
    return () => clearTimeout(id);
  }, [draft]);

  const set = (key) => (e) => setParams((p) => ({ ...p, [key]: e.target.value, page: 1 }));
  const data = result.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">People · HR only</p>
        <h1 className="display">Directory</h1>
      </header>
      <form className="filter-bar" onSubmit={(e) => e.preventDefault()} aria-label="Directory filters">
        <label className="grow">
          <span className="label">Search</span>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Name, email, title or E-0001" maxLength={80} />
        </label>
        <label><span className="label">Status</span>
          <select value={params.status} onChange={set("status")}>
            <option value="active">Active</option><option value="left">Left</option><option value="all">All</option>
          </select></label>
        <label><span className="label">Department</span>
          <select value={params.department} onChange={set("department")}>
            <option value="">All departments</option>{DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}
          </select></label>
        <label><span className="label">Site</span>
          <select value={params.site} onChange={set("site")}>
            <option value="">All sites</option>{SITES.map((s) => <option key={s}>{s}</option>)}
          </select></label>
        <label><span className="label">Contract</span>
          <select value={params.contract} onChange={set("contract")}>
            <option value="">All contracts</option>{Object.entries(CONTRACTS).map(([v, t]) => <option key={v} value={v}>{t}</option>)}
          </select></label>
      </form>

      <div className={`directory${openId ? " has-record" : ""}`}>
        <section className="a-panel" aria-label="Employees">
          <header className="a-panel-head">
            <p className="label">{data ? `${data.total} people` : "…"}</p>
            <h2 className="a-panel-title">Employees</h2>
          </header>
          {result.status === "error" && <p className="panel-state">Couldn't load the directory. Run python scripts\generate_people_data.py if it is missing.</p>}
          {!data && result.status === "loading" && <div className="skeleton"><span /><span /><span /></div>}
          {data && (
            <>
              <div className="table-wrap">
                <table className="people-table">
                  <thead><tr><th>Name</th><th>Title</th><th>Department</th><th>Site</th><th>Contract</th><th>Hired</th><th>Tenure</th></tr></thead>
                  <tbody>
                    {data.employees.map((e) => (
                      <tr key={e.employee_id} className={openId === e.employee_id ? "is-open" : ""}>
                        <td><button className="name-link" onClick={() => setOpenId(e.employee_id)}>{e.name}</button>
                          <span className="row-id">{e.employee_id}{e.status === "left" ? " · left" : ""}</span></td>
                        <td>{e.job_title}</td><td>{e.department}</td><td>{e.site}</td>
                        <td>{CONTRACTS[e.contract] || e.contract}</td><td className="mono">{e.hire_date}</td>
                        <td className="mono">{e.tenure_years} y</td>
                      </tr>
                    ))}
                    {data.employees.length === 0 && <tr><td colSpan={7} className="muted">No one matches these filters.</td></tr>}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <button className="btn btn-small" disabled={params.page <= 1} onClick={() => setParams((p) => ({ ...p, page: p.page - 1 }))}>◀ Previous</button>
                <span className="mono">Page {data.page} of {pages}</span>
                <button className="btn btn-small" disabled={params.page >= pages} onClick={() => setParams((p) => ({ ...p, page: p.page + 1 }))}>Next ▶</button>
              </div>
            </>
          )}
        </section>
        {openId && <Record id={openId} onClose={() => setOpenId(null)} />}
      </div>
    </main>
  );
}
