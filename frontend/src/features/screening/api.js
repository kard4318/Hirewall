// API client for the resume screener and the approval queue, HR token required
import { ApiError, request } from "../scheduling/api.js";

const base = "/api/screener";
const enc = encodeURIComponent;

async function upload(token, files) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  const res = await fetch(`${base}/candidates`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail);
  return data;
}

export const screeningApi = {
  upload,
  demo: (token) => request(`${base}/candidates/demo`, { method: "POST", token }),
  task: (token, id) => request(`${base}/tasks/${enc(id)}`, { token }),
  candidates: (token) => request(`${base}/candidates`, { token }),
  jobs: (token) => request(`${base}/jobs`, { token }),
  createJob: (token, job) => request(`${base}/jobs`, { method: "POST", token, body: job }),
  startRun: (token, jobId) => request(`${base}/jobs/${enc(jobId)}/runs`, { method: "POST", token }),
  run: (token, id) => request(`${base}/runs/${enc(id)}`, { token }),
  propose: (token, runId, candidateIds, kind) =>
    request(`${base}/runs/${enc(runId)}/shortlist-proposals`, {
      method: "POST", token, body: { candidate_ids: candidateIds, kind },
    }),
  identity: (token, id) => request(`${base}/candidates/${enc(id)}/identity`, { token }),
};

export const approvalsApi = {
  list: (token) => request("/api/hr/approvals", { token }),
  decide: (token, id, decision) =>
    request(`/api/hr/approvals/${enc(id)}/decision`, { method: "POST", token, body: decision }),
  audit: (token) => request("/api/hr/audit-log?limit=30", { token }),
};

export const percent = (value) => (value === null || value === undefined ? "N/A" : `${Math.round(value * 100)}%`);
export const shortId = (id) => id.replace(/^cand-/, "").slice(0, 8);
