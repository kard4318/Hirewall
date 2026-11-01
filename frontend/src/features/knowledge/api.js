// API client for the knowledge desk: employee sign-in and questions, and the HR question desk
import { request } from "../scheduling/api.js";

const EMPLOYEE_TOKEN_KEY = "hrwall.employee.token";

export const employeeSession = {
  get() {
    try { return sessionStorage.getItem(EMPLOYEE_TOKEN_KEY); } catch { return null; }
  },
  set(token) {
    try { sessionStorage.setItem(EMPLOYEE_TOKEN_KEY, token); } catch { /* private mode: memory only */ }
  },
  clear() {
    try { sessionStorage.removeItem(EMPLOYEE_TOKEN_KEY); } catch { /* nothing stored */ }
  },
};

export const knowledgeApi = {
  login: (username, password) => request("/api/employee/login", { method: "POST", body: { username, password } }),
  ask: (token, question) => request("/api/knowledge/ask", { method: "POST", token, body: { question } }),
  escalate: (token, id, contact) =>
    request(`/api/knowledge/questions/${encodeURIComponent(id)}/escalate`, {
      method: "POST", token, body: contact ? { contact } : {},
    }),
};

export const hrKnowledgeApi = {
  questions: (token) => request("/api/hr/knowledge/questions?limit=60", { token }),
  escalations: (token) => request("/api/hr/knowledge/escalations", { token }),
  stats: (token) => request("/api/hr/knowledge/stats", { token }),
  resolve: (token, id) => request(`/api/hr/knowledge/questions/${encodeURIComponent(id)}/resolve`, { method: "POST", token }),
  reply: (token, id, message) =>
    request(`/api/hr/knowledge/questions/${encodeURIComponent(id)}/reply`, { method: "POST", token, body: { message } }),
};

export const KIND_LABELS = {
  answered: "Answered",
  not_found: "Not in the handbook",
  refused_personal: "Personal record",
  sensitive: "Confidential",
  blocked: "Refused",
  error: "Unavailable",
};
