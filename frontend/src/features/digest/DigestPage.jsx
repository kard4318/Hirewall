// /hr/digest: the daily inbox digest, grouped by type and urgency, with emails needing a human answer first
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useHrSession } from "../analytics/HrSession.jsx";
import { digestApi } from "./api.js";
import "./digest.css";

const POLL_MS = 2500;
const DATE_KEY = "hirewall.digest.date";
const SCROLL_KEY = "hirewall.digest.scroll";
const TYPE_KEY = "hirewall.digest.type";
const URGENCY_KEY = "hirewall.digest.urgency-level";
const URGENCIES = [
  ["high", "High"],
  ["normal", "Normal"],
  ["low", "Low"],
];
const remembered = (key) => {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
};
const remember = (key, value) => {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    // The page still works without storage. It just will not remember this.
  }
};
const when = (iso) => {
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime())
    ? ""
    : parsed.toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};
const TILES = [
  ["needs_answer", "Need a human answer"],
  ["draft_waiting", "Drafts to approve"],
  ["quarantined", "Quarantined"],
  ["ready_to_draft", "Ready to draft"],
  ["no_action", "No action"],
  ["handled", "Handled"],
];
const BUCKET_LABELS = {
  needs_answer: "needs a human answer",
  draft_waiting: "draft to approve",
  quarantined: "quarantined",
  ready_to_draft: "ready to draft",
  no_action: "no action",
  handled: "handled",
};

function DigestItem({ item }) {
  return (
    <li className={`digest-item urgency-${item.urgency}`}>
      <Link
        to={`../inbox?email=${encodeURIComponent(item.email_id)}`}
        className="digest-link"
        onClick={() => remember(SCROLL_KEY, String(window.scrollY))}
      >
        <span className="digest-line">
          <b>{item.sender}</b>
          <span className="mono">{when(item.received_at)}</span>
        </span>
        <span className="digest-summary">{item.summary}</span>
        <span className="digest-tags">
          <span className={`tag urgency-tag-${item.urgency}`}>{item.urgency} urgency</span>
          <span className="tag">{BUCKET_LABELS[item.bucket]}</span>
          {item.summary_source !== "model" && item.summary_source !== "quarantine_notice" && (
            <span className="muted" title="The model's summary was not used">subject line</span>
          )}
        </span>
      </Link>
    </li>
  );
}

function FilterSelect({ id, label, allLabel, allCount, options, value, onChange }) {
  return (
    <div className="digest-filter">
      <label className="label" htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{allLabel} ({allCount})</option>
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.name} ({option.count})</option>
        ))}
      </select>
    </div>
  );
}

export function DigestPage() {
  const { token, signOut } = useHrSession();
  const [date, setDate] = useState(() => remembered(DATE_KEY) ?? "");
  const [typeFilter, setTypeFilter] = useState(() => remembered(TYPE_KEY) ?? "");
  const [urgencyFilter, setUrgencyFilter] = useState(() => remembered(URGENCY_KEY) ?? "");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const timer = useRef(null);
  // With no day remembered, the first read opens the latest saved digest.
  const openLatest = useRef(remembered(DATE_KEY) === null);
  const scrollRestored = useRef(false);

  const chooseDate = useCallback((value) => {
    openLatest.current = false;
    remember(DATE_KEY, value);
    setDate(value);
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await digestApi.read(token, date);
      if (openLatest.current) {
        openLatest.current = false;
        if (!next.digest && next.job?.state !== "running" && next.saved?.length) {
          chooseDate(next.saved[0] === "all" ? "" : next.saved[0]);
          return next;
        }
      }
      setData(next);
      setError(next.job?.state === "failed" ? "The digest could not be generated. Please try again." : null);
      return next;
    } catch (err) {
      if (err.status === 401) signOut();
      else setError(err.message || "Request failed");
      return null;
    }
  }, [token, date, signOut, chooseDate]);

  useEffect(() => {
    let active = true;
    const tick = async () => {
      const next = await load();
      if (active && next?.job?.state === "running") timer.current = setTimeout(tick, POLL_MS);
    };
    tick();
    return () => {
      active = false;
      clearTimeout(timer.current);
    };
  }, [load, data?.job?.state]);

  async function generate() {
    setError(null);
    try {
      await digestApi.generate(token, date);
      await load();
    } catch (err) {
      if (err.status === 401) signOut();
      else setError((err.message || "Request failed").replaceAll("_", " "));
    }
  }

  const digest = data?.digest;
  const running = data?.job?.state === "running";

  function changeFilter(key, setter, next) {
    remember(key, next);
    setter(next);
  }
  const clearFilters = () => {
    changeFilter(TYPE_KEY, setTypeFilter, "");
    changeFilter(URGENCY_KEY, setUrgencyFilter, "");
  };

  // A remembered value this period does not have must not hide everything while the list shows "All".
  const groups = digest?.groups ?? [];
  const activeType = groups.some((group) => group.type === typeFilter) ? typeFilter : "";
  const activeUrgency = URGENCIES.some(([value]) => value === urgencyFilter) ? urgencyFilter : "";
  const typeMatches = (item) => !activeType || item.type === activeType;
  const urgencyMatches = (item) => !activeUrgency || item.urgency === activeUrgency;
  const matches = (item) => typeMatches(item) && urgencyMatches(item);
  const allItems = groups.flatMap((group) => group.items);
  const filtering = Boolean(activeType || activeUrgency);
  const shownNeeds = (digest?.needs_answer ?? []).filter(matches);
  const shownGroups = groups
    .map((group) => {
      const items = group.items.filter(matches);
      const urgency = { high: 0, normal: 0, low: 0 };
      items.forEach((item) => {
        urgency[item.urgency] += 1;
      });
      return { ...group, items, urgency, total: items.length };
    })
    .filter((group) => group.items.length > 0);
  const shownTotal = shownGroups.reduce((sum, group) => sum + group.total, 0);

  // Coming back from an email returns to the same place in the list.
  useEffect(() => {
    if (!digest || scrollRestored.current) return;
    scrollRestored.current = true;
    const position = Number(remembered(SCROLL_KEY));
    remember(SCROLL_KEY, null);
    if (position) window.scrollTo(0, position);
  }, [digest]);

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">Talent flow · email</p>
        <h1 className="display">Daily digest</h1>
      </header>

      <section className="a-panel digest-controls">
        <label className="label" htmlFor="digest-date">Day (leave empty for the whole inbox)</label>
        <input id="digest-date" type="date" value={date} onChange={(event) => chooseDate(event.target.value)} />
        <button className="btn btn-primary" onClick={generate} disabled={running}>
          {running ? "Generating…" : digest ? "Generate again" : "Generate digest"}
        </button>
        {running && <p className="muted" role="status">The local model reads each new email, which can take a few minutes.</p>}
        {data?.saved?.length > 0 && (
          <div className="digest-saved">
            <span className="label">Saved digests</span>
            {[...data.saved].sort().map((scope) => {
              const value = scope === "all" ? "" : scope;
              return (
                <button
                  key={scope}
                  className={`btn ${value === date ? "btn-primary" : ""}`}
                  aria-pressed={value === date}
                  onClick={() => chooseDate(value)}
                >
                  {scope === "all" ? "Whole inbox" : scope}
                </button>
              );
            })}
          </div>
        )}
      </section>

      {error && <p className="notice" role="alert">{error}</p>}
      {data && !digest && !running && (
        <p className="panel-state">No digest for this period yet. Generate one to see the inbox grouped by type and urgency.</p>
      )}

      {digest && (
        <>
          <p className="digest-headline">{digest.headline}</p>
          <p className="muted">Generated {when(digest.generated_at)}. Statuses are current. Nothing here sends a reply.</p>
          <ul className="digest-tiles">
            {TILES.map(([key, label]) => (
              <li key={key} className={key === "needs_answer" || key === "quarantined" ? "is-strong" : ""}>
                <span className="digest-count">{digest.counts[key]}</span>
                <span className="label">{label}</span>
              </li>
            ))}
          </ul>

          <section className="a-panel digest-filters" aria-label="Filter the digest">
            <FilterSelect
              id="digest-urgency"
              label="Urgency"
              allLabel="All urgency levels"
              allCount={allItems.filter(typeMatches).length}
              value={activeUrgency}
              onChange={(value) => changeFilter(URGENCY_KEY, setUrgencyFilter, value)}
              options={URGENCIES.map(([value, name]) => ({
                value,
                name,
                count: allItems.filter((item) => item.urgency === value && typeMatches(item)).length,
              }))}
            />
            <FilterSelect
              id="digest-type"
              label="Type"
              allLabel="All types"
              allCount={allItems.filter(urgencyMatches).length}
              value={activeType}
              onChange={(value) => changeFilter(TYPE_KEY, setTypeFilter, value)}
              options={groups.map((group) => ({
                value: group.type,
                name: group.label,
                count: group.items.filter(urgencyMatches).length,
              }))}
            />
            <p className="digest-filter-result muted" role="status">
              Showing {shownTotal} of {digest.total} emails.
              {filtering && (
                <button type="button" className="btn digest-clear" onClick={clearFilters}>Clear filters</button>
              )}
            </p>
          </section>

          {filtering && shownTotal === 0 && <p className="panel-state">No emails match these filters.</p>}

          {(!filtering || shownNeeds.length > 0) && (
            <section className="a-panel" aria-labelledby="digest-needs">
              <header className="a-panel-head">
                <h2 className="a-panel-title" id="digest-needs">Needs a human answer</h2>
              </header>
              {shownNeeds.length === 0 && <p className="panel-state">Nothing is waiting for a human answer.</p>}
              <ul className="digest-list">
                {shownNeeds.map((item) => <DigestItem key={item.email_id} item={item} />)}
              </ul>
            </section>
          )}

          {shownGroups.map((group) => (
            <section className="a-panel" key={group.type} aria-label={group.label}>
              <header className="a-panel-head digest-group-head">
                <h2 className="a-panel-title">{group.label}</h2>
                <span className="mono">
                  {group.total} · {group.urgency.high} high · {group.urgency.normal} normal · {group.urgency.low} low
                </span>
              </header>
              <ul className="digest-list">
                {group.items.map((item) => <DigestItem key={item.email_id} item={item} />)}
              </ul>
            </section>
          ))}
        </>
      )}
    </main>
  );
}
