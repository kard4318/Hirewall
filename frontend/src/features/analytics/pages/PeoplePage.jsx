// /hr/people: headcount over time and the workforce by department, site, contract, tenure, age band and gender
import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, COLORS, gridProps, Patterns } from "../chartTheme.jsx";
import { BarList } from "../components/BarList.jsx";
import { FilterBar } from "../components/FilterBar.jsx";
import { LedgerTooltip } from "../components/LedgerTooltip.jsx";
import { Panel } from "../components/Panel.jsx";
import { useHrSession } from "../HrSession.jsx";
import { usePeriodParams } from "../usePeriodParams.js";
import { useReport } from "../useReport.js";

const LABELS = { fixed_term: "Fixed term", permanent: "Permanent", intern: "Intern", F: "Women", M: "Men", undisclosed: "Undisclosed" };
const AGGREGATE_NOTE = "Aggregate only, groups under 5 hidden.";

function GroupPanel({ title, kicker, dimension, params, i, note }) {
  const report = useReport("headcount/by", { ...(params || {}), dimension }, { enabled: Boolean(params) });
  return (
    <Panel i={i} kicker={kicker} title={title} report={report} note={note}
      isEmpty={(d) => !d.groups.length && !d.total?.suppressed}>
      {report.data && (report.data.total?.suppressed
        ? <p className="panel-state">This selection has fewer than 5 people, so it is hidden.</p>
        : <BarList groups={report.data.groups} label={(g) => LABELS[g.key] || g.key}
            format={(v) => v} />)}
    </Panel>
  );
}

export function PeoplePage() {
  const { asOf, meta } = useHrSession();
  const [filters, setFilters] = useState({ period: "12m", department: null, site: null, contract: null });
  const params = usePeriodParams(filters, asOf);
  const series = useReport("headcount/timeseries", { ...(params || {}), from: meta?.earliest, granularity: "quarter" },
    { enabled: Boolean(params && meta?.earliest) });
  const rows = (series.data?.points || []).map((p) => ({
    label: p.label, headcount: p.suppressed ? null : p.headcount, hires: p.suppressed ? null : p.hires,
    exits: p.suppressed ? null : p.exits,
  }));

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">People analytics</p>
        <h1 className="display">People</h1>
      </header>
      <FilterBar filters={filters} onChange={setFilters} />

      <Panel i={0} kicker="Since 2021 · by quarter" title="Headcount over time" report={series}
        note="Line: headcount at quarter end. Solid bars: hires. Hatched bars: exits.">
        <div className="chart-box" style={{ height: 280 }}>
          <ResponsiveContainer>
            <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
              <Patterns />
              <CartesianGrid {...gridProps} />
              <XAxis dataKey="label" {...axisProps} interval="preserveStartEnd" minTickGap={18} />
              <YAxis {...axisProps} allowDecimals={false} />
              <Tooltip content={<LedgerTooltip />} />
              <Bar dataKey="hires" name="Hires" fill={COLORS.moss} barSize={8} isAnimationActive={false} />
              <Bar dataKey="exits" name="Exits" fill="url(#hatch-vermilion)" stroke={COLORS.vermilionInk} barSize={8} isAnimationActive={false} />
              <Line dataKey="headcount" name="Headcount" stroke={COLORS.ink} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      </Panel>

      <div className="a-grid two">
        <GroupPanel i={1} kicker={`Headcount on ${asOf || "…"}`} title="By department" dimension="department" params={params} />
        <GroupPanel i={2} kicker="Time since hire" title="Tenure bands" dimension="tenure_band" params={params} />
      </div>
      <div className="a-grid three">
        <GroupPanel i={3} kicker="Where people work" title="By site" dimension="site" params={params} />
        <GroupPanel i={4} kicker="Contract type" title="By contract" dimension="contract" params={params} />
        <GroupPanel i={5} kicker="Demographics" title="Age band" dimension="age_band" params={params} note={AGGREGATE_NOTE} />
      </div>
      <div className="a-grid three">
        <GroupPanel i={6} kicker="Demographics" title="Gender" dimension="gender" params={params} note={AGGREGATE_NOTE} />
      </div>
      <p className="a-footnote">Counts are headcount on the period end date ({asOf || "…"}), within the current filters.</p>
    </main>
  );
}
