// Engagement by department as small multiples: each panel names its department, with the company line for reference
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, COLORS, gridProps } from "../chartTheme.jsx";
import { LedgerTooltip } from "./LedgerTooltip.jsx";
import { Suppressed } from "./Panel.jsx";

export function EngagementMultiples({ data }) {
  const company = Object.fromEntries(data.company.map((c) => [c.quarter, c.suppressed ? null : c.score]));
  return (
    <div className="multiples">
      {data.departments.map((dept) => {
        const rows = dept.series.map((s) => ({ quarter: s.quarter, score: s.suppressed ? null : s.score, company: company[s.quarter] }));
        const last = [...rows].reverse().find((r) => r.score !== null);
        return (
          <figure key={dept.department} className="multiple">
            <figcaption>
              <b>{dept.department}</b> {last ? <span className="mono">{last.score.toFixed(1)}</span> : <Suppressed />}
            </figcaption>
            <div className="chart-box" style={{ height: 110 }}>
              <ResponsiveContainer>
                <LineChart data={rows} margin={{ top: 6, right: 6, bottom: 0, left: -30 }}>
                  <CartesianGrid {...gridProps} />
                  <XAxis dataKey="quarter" {...axisProps} tick={false} height={4} />
                  <YAxis {...axisProps} domain={[2.5, 4.5]} ticks={[3, 4]} />
                  <Tooltip content={<LedgerTooltip format={(v) => v.toFixed(2)} />} />
                  <Line dataKey="company" name="Company" stroke={COLORS.slate} strokeDasharray="4 3" strokeWidth={1.2} dot={false} isAnimationActive={false} />
                  <Line dataKey="score" name={dept.department} stroke={COLORS.ink} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </figure>
        );
      })}
    </div>
  );
}
