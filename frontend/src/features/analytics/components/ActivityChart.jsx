// 8-week agent activity: lines told apart by dash, marker shape and a labelled legend, not by colour alone
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { axisProps, COLORS, gridProps } from "../chartTheme.jsx";
import { LedgerTooltip } from "./LedgerTooltip.jsx";

const SERIES = [
  { key: "resume_screened", name: "Resumes screened", color: COLORS.ink, dash: "0", dot: "circle" },
  { key: "kb_question", name: "Employee questions", color: COLORS.ochre, dash: "6 3", dot: "triangle" },
  { key: "booking_created", name: "Interviews booked", color: COLORS.moss, dash: "2 3", dot: "square" },
  { key: "approval_decided", name: "Approval decisions", color: COLORS.slate, dash: "10 3 2 3", dot: "diamond" },
];

function Marker({ cx, cy, shape, color }) {
  if (cx === undefined || cy === undefined) return null;
  if (shape === "square") return <rect x={cx - 3} y={cy - 3} width={6} height={6} fill={color} />;
  if (shape === "triangle") return <path d={`M${cx},${cy - 4} L${cx + 4},${cy + 3} L${cx - 4},${cy + 3} Z`} fill={color} />;
  if (shape === "diamond") return <path d={`M${cx},${cy - 4} L${cx + 4},${cy} L${cx},${cy + 4} L${cx - 4},${cy} Z`} fill={color} />;
  return <circle cx={cx} cy={cy} r={3.2} fill={color} />;
}

const weekLabel = (iso) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

export function ActivityChart({ weeks }) {
  const rows = weeks.map((w) => ({ week: weekLabel(w.week_start), ...Object.fromEntries(SERIES.map((s) => [s.key, w.counts[s.key] || 0])) }));
  return (
    <figure className="chart-figure">
      <div className="chart-box" style={{ height: 240 }}>
        <ResponsiveContainer>
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -18 }}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey="week" {...axisProps} />
            <YAxis {...axisProps} allowDecimals={false} />
            <Tooltip content={<LedgerTooltip labelFormat={(l) => `Week of ${l}`} />} />
            {SERIES.map((s) => (
              <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={1.8} strokeDasharray={s.dash}
                isAnimationActive={false} dot={(props) => <Marker key={`${s.key}-${props.index}`} {...props} shape={s.dot} color={s.color} />} />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="chart-legend">
        {SERIES.map((s) => (
          <span key={s.key}>
            <svg width="28" height="10" aria-hidden="true">
              <line x1="0" y1="5" x2="28" y2="5" stroke={s.color} strokeWidth="2" strokeDasharray={s.dash} />
              <Marker cx={14} cy={5} shape={s.dot} color={s.color} />
            </svg>
            {s.name}
          </span>
        ))}
      </figcaption>
    </figure>
  );
}
