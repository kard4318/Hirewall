// API client for the public job offers and applications (no login)
import { ApiError, request } from "../scheduling/api.js";

export const applyApi = {
  jobs: () => request("/api/jobs"),
  job: (id) => request(`/api/jobs/${encodeURIComponent(id)}`),
  async submit(id, form) {
    const res = await fetch(`/api/jobs/${encodeURIComponent(id)}/applications`, { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(res.status, data.detail);
    return data;
  },
};

const LABELS = {
  internship: "Internship", full_time: "Full time", part_time: "Part time", fixed_term: "Fixed term",
  freelance: "Freelance", other: "Other", onsite: "On site", hybrid: "Hybrid", remote: "Remote",
};
export const label = (value) => LABELS[value] ?? value;
