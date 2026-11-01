// API client for the resume screener and the approval queue, HR token required
import { ApiError, request } from "../scheduling/api.js";

const base = "/api/screener";
const enc = encodeURIComponent;

async function postForm(token, path, body) {
  const res = await fetch(`${base}${path}`, { method: "POST", headers: { Authorization: `Bearer ${token}` }, body });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, data.detail);
  return data;
}

function upload(token, files, jobId) {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  if (jobId) body.append("job_id", jobId);
  return postForm(token, "/candidates", body);
}

function extractOffer(token, file) {
  const body = new FormData();
  body.append("file", file);
  return postForm(token, "/jobs/extract", body);
}

export const screeningApi = {
  upload,
  extractOffer,
  posting: (token, id) => request(`${base}/jobs/${enc(id)}/posting`, { token }),
  updatePosting: (token, id, details) => request(`${base}/jobs/${enc(id)}`, { method: "PUT", token, body: details }),
  publish: (token, id) => request(`${base}/jobs/${enc(id)}/publish`, { method: "POST", token }),
  closeOffer: (token, id) => request(`${base}/jobs/${enc(id)}/close`, { method: "POST", token }),
  applications: (token, id) => request(`${base}/jobs/${enc(id)}/applications`, { token }),
  extracted: (token, id) => request(`${base}/candidates/${enc(id)}/extracted`, { token }),
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
