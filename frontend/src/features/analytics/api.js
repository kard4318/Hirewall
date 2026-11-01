// API client for People Analytics (HR token required); builds query strings from the active filters
import { request } from "../scheduling/api.js";

export function analyticsPath(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  }
  const text = query.toString();
  return `/api/hr/analytics/${path}${text ? `?${text}` : ""}`;
}

export const getAnalytics = (token, path, params) => request(analyticsPath(path, params), { token });

/** ISO date `days` before `asOf` (both "YYYY-MM-DD"). */
export function daysBefore(asOf, days) {
  const d = new Date(`${asOf}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export const PERIODS = [
  { id: "12m", label: "Last 12 months", days: 365 },
  { id: "6m", label: "Last 6 months", days: 182 },
  { id: "3m", label: "Last quarter", days: 91 },
];
