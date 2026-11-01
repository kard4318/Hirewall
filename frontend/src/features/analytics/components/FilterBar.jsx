// Filter bar: period preset plus optional department / site / contract selects (refetch happens on change)
import { PERIODS } from "../api.js";

const DEPARTMENTS = ["Engineering", "Support", "Sales", "Product & Design", "Operations", "People & Finance"];
const SITES = ["Tunis", "Paris", "Remote"];
const CONTRACTS = [["permanent", "Permanent"], ["fixed_term", "Fixed term"], ["intern", "Intern"]];

export function FilterBar({ filters, onChange, groups = true, children }) {
  const set = (key) => (event) => onChange({ ...filters, [key]: event.target.value || null });
  return (
    <form className="filter-bar" onSubmit={(e) => e.preventDefault()} aria-label="Filters">
      <label>
        <span className="label">Period</span>
        <select value={filters.period} onChange={set("period")}>
          {PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </label>
      {groups && (
        <>
          <label>
            <span className="label">Department</span>
            <select value={filters.department || ""} onChange={set("department")}>
              <option value="">All departments</option>
              {DEPARTMENTS.map((d) => <option key={d}>{d}</option>)}
            </select>
          </label>
          <label>
            <span className="label">Site</span>
            <select value={filters.site || ""} onChange={set("site")}>
              <option value="">All sites</option>
              {SITES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label>
            <span className="label">Contract</span>
            <select value={filters.contract || ""} onChange={set("contract")}>
              <option value="">All contracts</option>
              {CONTRACTS.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
            </select>
          </label>
        </>
      )}
      {children}
    </form>
  );
}
