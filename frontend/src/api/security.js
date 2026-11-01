// API calls for the security page (hr_admin only)
import { request } from "../features/scheduling/api.js";

export const securityApi = {
  summary: (token) => request("/api/hr/security/summary", { token }),
};
