// One place for every number, date and label the UI prints (en-GB). Never emits ->, >=, <= (not in the font subsets).
export const DASH = "–";
const missing = (v) => v === null || v === undefined || Number.isNaN(v);
const fmt = (digits) => new Intl.NumberFormat("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** "2026Q3" -> "Q3 2026", or "Q3 ’26" when short. Unknown shapes pass through. */
export function quarter(label, { short = false } = {}) {
  const m = /^(\d{4})Q([1-4])(\*?)$/.exec(String(label ?? ""));
  if (!m) return label ?? DASH;
  return short ? `Q${m[2]} ’${m[1].slice(2)}${m[3]}` : `Q${m[2]} ${m[1]}${m[3]}`;
}

/** 3.94 -> "3.9×" */
export const ratio = (v, digits = 1) => (missing(v) ? DASH : `${fmt(digits).format(v)}×`);

/** 0.253 -> "25.3%" (input is a fraction) */
export const percent = (v, digits = 1) => (missing(v) ? DASH : `${fmt(digits).format(v * 100)}%`);

/** Change in a fraction, as percentage points with a real minus sign: 0.012 -> "+1.2 pts", -0.004 -> "−0.4 pts" */
export function deltaPts(v, digits = 1) {
  if (missing(v)) return DASH;
  const value = fmt(digits).format(Math.abs(v * 100));
  const sign = Number(value) === 0 ? "" : v > 0 ? "+" : "−";
  return `${sign}${value} pts`;
}

/** Signed plain number: 0.25 -> "+0.3", -1 -> "−1" */
export function signed(v, digits = 1, unit = "") {
  if (missing(v)) return DASH;
  const value = fmt(digits).format(Math.abs(v));
  const sign = Number(value) === 0 ? "" : v > 0 ? "+" : "−";
  return `${sign}${value}${unit}`;
}

/** 1234 -> "1,234" ; decimal(3.456, 1) -> "3.5" */
export const count = (v) => (missing(v) ? DASH : fmt(0).format(Math.round(v)));
export const decimal = (v, digits = 1) => (missing(v) ? DASH : fmt(digits).format(v));

/** Group size: "n = 77" */
export const groupSize = (v) => (missing(v) ? DASH : `n = ${count(v)}`);

/** "2026-06-04" or a Date -> "4 Jun 2026" (calendar dates are read in UTC so they never shift a day) */
export function date(value, { withYear = true } = {}) {
  if (!value) return DASH;
  const d = typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00Z`) : new Date(value);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", ...(withYear ? { year: "numeric" } : {}), timeZone: "UTC" });
}

/** Timestamp in the viewer's zone: "4 Jun 2026, 14:05" */
export function dateTime(value) {
  if (!value) return DASH;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return DASH;
  return d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
