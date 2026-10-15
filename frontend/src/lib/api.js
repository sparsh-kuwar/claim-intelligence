// VITE_API_URL may be a full URL or a bare hostname (Render's Blueprint provides a hostname).
const RAW_API = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");
const API_ORIGIN = /^https?:\/\//.test(RAW_API) ? RAW_API : `https://${RAW_API}`;
const BASE = API_ORIGIN + "/api";

export class ApiError extends Error {
  constructor(status, code, message, details) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function request(path, { method = "GET", json, formData } = {}) {
  const opts = { method, headers: {} };
  if (json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(json);
  } else if (formData) {
    opts.body = formData;
  }
  let res;
  try {
    res = await fetch(BASE + path, opts);
  } catch {
    throw new ApiError(0, "NETWORK", "Cannot reach the API server. If it has been idle it can take up to a minute to start; try again shortly.");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error || {};
    throw new ApiError(res.status, e.code || "HTTP_" + res.status, e.message || res.statusText, e.details);
  }
  return body;
}

export const api = {
  config: () => request("/config"),
  list: (params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v));
    return request("/claims" + (q.toString() ? "?" + q : ""));
  },
  get: (id) => request(`/claims/${id}`),
  create: (formData) => request("/claims", { method: "POST", formData }),
  analyze: (id) => request(`/claims/${id}/analyze`, { method: "POST" }),
  review: (id, body) => request(`/claims/${id}/review`, { method: "PATCH", json: body }),
  approve: (id, body) => request(`/claims/${id}/approve`, { method: "POST", json: body }),
  escalate: (id, body) => request(`/claims/${id}/escalate`, { method: "POST", json: body }),
  exportRecord: (id) => request(`/claims/${id}/export`),
  attachmentUrl: (id) => `${BASE}/claims/${id}/attachment`,
};
