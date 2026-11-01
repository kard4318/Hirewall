// API client for the daily inbox digest, HR token required
import { request } from "../scheduling/api.js";

const base = "/api/hr/digest";

export const digestApi = {
  read: (token, date) => request(date ? `${base}?date=${encodeURIComponent(date)}` : base, { token }),
  generate: (token, date) => request(`${base}/generate`, { method: "POST", token, body: date ? { date } : {} }),
};
