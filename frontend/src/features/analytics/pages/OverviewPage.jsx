// /hr/overview: KPI tiles, weekly recap with highlights, what needs HR now, and what the agents did
import { useMemo, useState } from "react";
import { daysBefore } from "../api.js";
import { num, pct } from "../chartTheme.jsx";
import { ActivityChart } from "../components/ActivityChart.jsx";
import { FilterBar } from "../components/FilterBar.jsx";
import { KpiTile } from "../components/KpiTile.jsx";
import { NeedsYouCard } from "../components/NeedsYouCard.jsx";
import { Panel } from "../components/Panel.jsx";
import { RecapCard } from "../components/RecapCard.jsx";
import { SplitBar } from "../components/SplitBar.jsx";
import { useHrSession } from "../HrSession.jsx";
import { usePeriodParams } from "../usePeriodParams.js";
import { useReport } from "../useReport.js";
import { deltaPts } from "../../../shared/format.js";

function mondayOf(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
}
const longDate = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", timeZone: "UTC" });

export function OverviewPage() {
  const { asOf } = useHrSession();
  const [filters, setFilters] = useState({ period: "12m" });
  const [weekOffset, setWeekOffset] = useState(0);
  const params = usePeriodParams(filters, asOf);
  const weekStart = useMemo(() => (asOf ? daysBefore(mondayOf(asOf), 7 * weekOffset) : null), [asOf, weekOffset]);

  const summary = useReport("summary", params || {}, { enabled: Boolean(params) });
  const recap = useReport("recap", { ...(params || {}), week_start: weekStart }, { enabled: Boolean(params) });
  const activity = useReport("agent-activity", { weeks: 8 }, { enabled: Boolean(asOf) });
  const t = summary.data?.tiles;

  return (
    <main className="a-page">
      <header className="a-page-head">
        <p className="label">People analytics · Talent flow</p>
        <h1 className="display">Overview</h1>
      </header>
      <FilterBar filters={filters} onChange={setFilters} groups={false}>
        <div className="week-picker" role="group" aria-label="Recap week">
          <span className="label">Recap week</span>
          <div className="week-row">
            <button type="button" className="btn btn-small" onClick={() => setWeekOffset((w) => w + 1)}
              disabled={weekOffset >= 7} aria-label="Previous week">◀</button>
            <span className="week-label">{weekStart ? `Week of ${longDate(weekStart)}` : "…"}</span>
            <button type="button" className="btn btn-small" onClick={() => setWeekOffset((w) => w - 1)}
              disabled={weekOffset === 0} aria-label="Next week">▶</button>
          </div>
        </div>
      </FilterBar>

      <section className="kpis" aria-label="Key figures">
        <KpiTile i={0} label="Headcount" tile={t?.headcount} format={(v) => num(v)} />
        <KpiTile i={1} label="Attrition · 12 months" tile={t?.attrition_rate_12m} format={(v) => pct(v)}
          deltaFormat={(v) => deltaPts(v).replace(/^[+−]/, "")} goodWhen="down" />
        <KpiTile i={2} label="Average tenure" tile={t?.avg_tenure_years} format={(v) => `${num(v, 1)} y`}
          deltaFormat={(v) => `${num(v, 2)} y`} />
        <KpiTile i={3} label="Open roles" tile={t?.open_roles} format={(v) => num(v)} hint="from open positions" />
        <KpiTile i={4} label="Interviews booked · 30 days" tile={t?.interviews_booked_30d} format={(v) => num(v)} />
        <KpiTile i={5} label="Hours saved · 4 weeks" tile={t?.hours_saved_estimate} format={(v) => `${num(v, 1)} h`}
          deltaFormat={(v) => `${num(v, 1)} h`} />
      </section>

      <div className="a-grid two">
        <Panel i={1} kicker="Weekly recap" title={weekStart ? `Week of ${longDate(weekStart)}` : "Weekly recap"} report={recap}
          note="Written from the numbers by templates; no AI text.">
          {recap.data && <RecapCard recap={recap.data} />}
        </Panel>
        <Panel i={2} kicker="Needs you now" title="Waiting on a human">
          <NeedsYouCard />
        </Panel>
      </div>

      <Panel i={3} kicker="Agents · last 8 weeks" title="What the agents did" report={activity}
        note={activity.data ? `${num(activity.data.hours_saved, 1)} hours of HR work saved (estimate)` : null}>
        {activity.data && <ActivityChart weeks={activity.data.weeks} />}
      </Panel>

      <div className="a-grid three">
        <Panel i={4} kicker="Approvals · 8 weeks" title="Human decisions on agent drafts" report={activity}>
          {activity.data && (
            <SplitBar label="Approval outcomes" parts={[
              { label: "Approved", value: activity.data.approvals.approve, style: "ink" },
              { label: "Edited", value: activity.data.approvals.edit, style: "dots" },
              { label: "Rejected", value: activity.data.approvals.reject, style: "hatch" },
            ]} />
          )}
        </Panel>
        <Panel i={5} kicker="Handbook assistant · 8 weeks" title="Employee questions" report={activity}>
          {activity.data && (
            <SplitBar label="Questions" parts={[
              { label: "Answered", value: activity.data.qa.answered, style: "moss" },
              { label: "Passed to HR", value: activity.data.qa.escalated, style: "dots" },
            ]} />
          )}
        </Panel>
        <Panel i={6} kicker="Security · 8 weeks" title="Blocked messages" report={activity}
          isEmpty={(d) => Object.keys(d.blocked_by_reason).length === 0}>
          {activity.data && (
            <ul className="blocked-list">
              {Object.entries(activity.data.blocked_by_reason).sort((a, b) => b[1] - a[1]).map(([reason, n]) => (
                <li key={reason}><span className="stamp stamp-pending_approval">{reason.replaceAll("_", " ")}</span><b>{n}</b></li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </main>
  );
}
