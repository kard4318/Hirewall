// API client for the scheduling feature: HR dashboard calls (bearer token) and candidate booking calls
const HR_TOKEN_KEY = "hirewall.hr.token";

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `HTTP ${status}`);
    this.status = status;
  }
}

export async function request(path, { method = "GET", body, token } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail);
  return data;
}

export const hrSession = {
  get() {
    try { return sessionStorage.getItem(HR_TOKEN_KEY); } catch { return null; }
  },
  set(token) {
    try { sessionStorage.setItem(HR_TOKEN_KEY, token); } catch { /* private mode: token lives in memory only */ }
  },
  clear() {
    try { sessionStorage.removeItem(HR_TOKEN_KEY); } catch { /* nothing stored */ }
  },
};

export const getMeta = () => request("/api/meta");

export const hrApi = {
  login: (passcode) => request("/api/hr/login", { method: "POST", body: { passcode } }),
  jobs: (token) => request("/api/hr/jobs", { token }),
  candidates: (token, jobId) => request(`/api/hr/jobs/${encodeURIComponent(jobId)}/candidates`, { token }),
  invite: (token, candidateId) =>
    request(`/api/hr/candidates/${encodeURIComponent(candidateId)}/invite`, { method: "POST", token }),
  cancel: (token, bookingId) =>
    request(`/api/hr/bookings/${encodeURIComponent(bookingId)}/cancel`, { method: "POST", token }),
  approve: (token, bookingId) =>
    request(`/api/hr/bookings/${encodeURIComponent(bookingId)}/approve`, { method: "POST", token }),
  decline: (token, bookingId) =>
    request(`/api/hr/bookings/${encodeURIComponent(bookingId)}/decline`, { method: "POST", token }),
  audit: (token) => request("/api/hr/audit?limit=30", { token }),
  calendarEmbed: (token) => request("/api/hr/calendar-embed", { token }),
  settings: (token) => request("/api/hr/settings", { token }),
  setStrict: (token, enabled) => request("/api/hr/settings/strict", { method: "POST", token, body: { enabled } }),
};

export const candidateApi = {
  state: (linkToken) => request(`/api/schedule/${encodeURIComponent(linkToken)}/state`),
  say: (linkToken, text) =>
    request(`/api/schedule/${encodeURIComponent(linkToken)}/message`, { method: "POST", body: { text } }),
  act: (linkToken, action) =>
    request(`/api/schedule/${encodeURIComponent(linkToken)}/message`, { method: "POST", body: { action } }),
};
