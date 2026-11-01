// API client for the recruiter inbox (drafter / classifier service), HR token required
import { request } from "../scheduling/api.js";

const base = "/api/hr/inbox";
const one = (id) => `${base}/${encodeURIComponent(id)}`;

export const inboxApi = {
  list: (token) => request(base, { token }),
  sent: (token) => request(`${base}/sent`, { token }),
  get: (token, id) => request(one(id), { token }),
  triage: (token, id) => request(`${one(id)}/triage`, { method: "POST", token }),
  draft: (token, id) => request(`${one(id)}/draft`, { method: "POST", token }),
  decide: (token, id, decision) => request(`${one(id)}/decision`, { method: "POST", token, body: decision }),
};

export const statusLabel = (status) => (status || "not_started").replaceAll("_", " ");
