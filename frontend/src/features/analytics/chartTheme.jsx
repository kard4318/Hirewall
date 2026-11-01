// Ledger chart theme: palette, ruled grid, tabular ticks, hatch patterns (series never rely on colour alone)
import { count, decimal, percent } from "../../shared/format.js";

export const COLORS = {
  ink: "#17150F",
  inkSoft: "#4A4639",
  vermilion: "#E5412D",
  vermilionInk: "#B3301F",
  moss: "#2F5D3A",
  ochre: "#B9892E",
  slate: "#5B6B73",
  rule: "rgba(23,21,15,0.12)",
  paper: "#F2ECDF",
};

export const SERIES = [COLORS.ink, COLORS.vermilion, COLORS.moss, COLORS.ochre, COLORS.slate, COLORS.inkSoft];

export const tick = { fontFamily: "Schibsted Grotesk, sans-serif", fontSize: 11, fill: COLORS.inkSoft, style: { fontVariantNumeric: "tabular-nums lining-nums" } };

export const gridProps = { stroke: COLORS.rule, strokeDasharray: "0", vertical: false };

export const axisProps = { tick, tickLine: false, axisLine: { stroke: COLORS.inkSoft, strokeWidth: 1 } };

/** SVG pattern defs, to place inside a recharts chart. Use fill="url(#hatch-vermilion)" etc. */
export function Patterns() {
  return (
    <defs>
      <pattern id="hatch-vermilion" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="6" height="6" fill="#F7D9D3" />
        <line x1="0" y1="0" x2="0" y2="6" stroke={COLORS.vermilionInk} strokeWidth="2.2" />
      </pattern>
      <pattern id="dots-ochre" width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="6" height="6" fill="#F1E3C4" />
        <circle cx="3" cy="3" r="1.4" fill="#7A5A1C" />
      </pattern>
      <pattern id="solid-moss" width="6" height="6" patternUnits="userSpaceOnUse">
        <rect width="6" height="6" fill={COLORS.moss} />
      </pattern>
    </defs>
  );
}

// Kept for existing imports; both delegate to the shared formatter.
export const pct = (v, digits = 1) => percent(v, digits);
export const num = (v, digits = 0) => (digits === 0 ? count(v) : decimal(v, digits));
