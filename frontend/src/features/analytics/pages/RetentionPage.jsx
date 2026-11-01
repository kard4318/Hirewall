// /hr/retention: attrition trend and split, department heatmap, exit reasons, engagement, training and findings
import { useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { daysBefore } from "../api.js";
import { axisProps, COLORS, gridProps, Patterns, pct } from "../chartTheme.jsx";
import { BarList } from "../components/BarList.jsx";
import { EngagementMultiples } from "../components/EngagementMultiples.jsx";
import { FilterBar } from "../components/FilterBar.jsx";
import { Heatmap } from "../components/Heatmap.jsx";
import { LedgerTooltip } from "../components/LedgerTooltip.jsx";
import { Panel } from "../components/Panel.jsx";
import { Highlight } from "../components/RecapCard.jsx";
import { useHrSession } from "../HrSession.jsx";
import { usePeriodParams } from "../usePeriodParams.js";
import { useReport } from "../useReport.js";
import { quarter } from "../../../shared/format.js";

const TREND_DAYS = 730; // trend charts show two years so quarters can be compared
const REASONS = { career_growth: "Career growth", compensation: "Compensation", management: "Management", relocation: "Relocation",
  personal: "Personal", performance: "Performance", restructuring: "Restructuring", retirement: "Retirement" };

export function RetentionPage() {
  const { asOf } = useHrSession();
  const [filters, setFilters] = useState({ period: "12m", department: null, site: null, contract: null });
  const params = usePeriodParams(filters, asOf);
  const ready = { enabled: Boolean(params) };
  const trend = params ? { ...params, from: daysBefore(asOf, TREND_DAYS) } : {};
  const quarterly = useReport("attrition/quarterly", trend, ready);
  const byDept = useReport("attrition/by-department", trend, ready);
  const reasons = useReport("attrition/exit-reasons", params || {}, ready);
  const engagement = useReport("engagement", trend, ready);
  const training = useReport("training", params || {}, ready);
  const findings = useReport("recap", params || {}, ready);

  const rows = (quarterly.data?.quarters || []).map((q) => ({
    quarter: quarter(q.partial ? `${q.quarter}*` : q.quarter, { short: true }),
    rate: q.suppressed ? null : q.rate, voluntary: q.suppressed ? null : q.voluntary, involuntary: q.suppressed ? null : q.involuntary,
  }));
  const companyCompletion = training.data?.company?.completion;

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">People analytics</p>
        <h1 className="display">Retention &amp; engagement</h1>
      </header>
      <FilterBar filters={filters} onChange={setFilters} />

      <div className="a-grid two">
        <Panel i={0} kicker="Last 2 years · by quarter" title="Attrition" report={quarterly}
          note={quarterly.data ? `Line: attrition rate. Bars: exits, solid voluntary, hatched involuntary or retirement. Company quarterly average ${pct(quarterly.data.company_quarterly_average)}. * partial quarter.` : null}>
          <div className="chart-box" style={{ height: 260 }}>
            <ResponsiveContainer>
              <ComposedChart data={rows} margin={{ top: 8, right: 4, bottom: 0, left: -10 }}>
                <Patterns />
                <CartesianGrid {...gridProps} />
                <XAxis dataKey="quarter" {...axisProps} interval={0} angle={-30} textAnchor="end" height={40} />
                <YAxis yAxisId="exits" {...axisProps} allowDecimals={false} />
                <YAxis yAxisId="rate" orientation="right" {...axisProps} tickFormatter={(v) => pct(v, 0)} />
                <Tooltip content={<LedgerTooltip format={(v, key) => (key === "rate" ? pct(v) : v)} />} />
                <Bar yAxisId="exits" dataKey="voluntary" name="Voluntary exits" stackId="x" fill={COLORS.ink} barSize={14} isAnimationActive={false} />
                <Bar yAxisId="exits" dataKey="involuntary" name="Involuntary / retirement" stackId="x" fill="url(#hatch-vermilion)" stroke={COLORS.vermilionInk} barSize={14} isAnimationActive={false} />
                <Line yAxisId="rate" dataKey="rate" name="Attrition rate" stroke={COLORS.vermilionInk} strokeWidth={2} dot={{ r: 3 }} isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel i={1} kicker="Findings" title="What the numbers say" report={findings}
          isEmpty={(d) => d.highlights.length === 0} note="Each finding shows the rule that triggered it.">
          {findings.data && <ul className="highlights">{findings.data.highlights.map((h) => <Highlight key={h.rule + h.text} item={h} />)}</ul>}
        </Panel>
      </div>

      <Panel i={2} kicker="Last 2 years" title="Attrition by department and quarter" report={byDept}>
        {byDept.data && <Heatmap matrix={byDept.data.matrix} quarters={byDept.data.quarters} />}
      </Panel>

      <div className="a-grid two">
        <Panel i={3} kicker="Selected period" title="Why people left" report={reasons}
          isEmpty={(d) => !d.reasons.length && !d.total?.suppressed}
          note={reasons.data?.total?.n ? `${reasons.data.total.n} exits in the period.` : null}>
          {reasons.data && (reasons.data.total?.suppressed
            ? <p className="panel-state">Fewer than 5 exits in this selection, so reasons are hidden.</p>
            : <BarList groups={reasons.data.reasons} label={(g) => REASONS[g.key] || g.key} tone="vermilion" />)}
        </Panel>
        <Panel i={4} kicker="Active employees" title="Training completion" report={training}
          note={companyCompletion !== undefined ? `Marker: company figure ${pct(companyCompletion, 0)}.` : null}>
          {training.data && (
            <BarList groups={training.data.departments} value={(g) => g.completion} format={(v) => pct(v, 0)} max={1}
              marker={companyCompletion} markerLabel="Company completion" tone="moss" />
          )}
        </Panel>
      </div>

      <Panel i={5} kicker="Last 2 years · survey score 1 to 5" title="Engagement by department" report={engagement}
        note="Solid line: department. Dashed line: company. Group size is the number of respondents.">
        {engagement.data && <EngagementMultiples data={engagement.data} />}
      </Panel>
    </main>
  );
}
