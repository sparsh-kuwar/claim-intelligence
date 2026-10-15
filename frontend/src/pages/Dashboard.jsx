import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api.js";
import { STATUS_META, formatDateTime } from "../lib/format.js";
import { ConfidenceBar, ErrorBox, SeverityPill, StatusBadge } from "../components/ui.jsx";
import { useConfig } from "../App.jsx";

const ORDER = ["NEEDS_REVIEW", "READY_FOR_APPROVAL", "APPROVED", "ESCALATED", "PROCESSING"];

export default function Dashboard({ reviewQueue = false }) {
  const { confidenceThreshold } = useConfig();
  const [status, setStatus] = useState(reviewQueue ? "NEEDS_REVIEW" : "");
  const [search, setSearch] = useState("");
  const [data, setData] = useState({ items: [], total: 0, counts: {} });
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => setStatus(reviewQueue ? "NEEDS_REVIEW" : ""), [reviewQueue]);

  useEffect(() => {
    const t = setTimeout(() => {
      setLoading(true);
      api.list({ status, search, limit: 100 })
        .then((d) => { setData(d); setError(null); })
        .catch(setError)
        .finally(() => setLoading(false));
    }, 200);
    return () => clearTimeout(t);
  }, [status, search]);

  const totalAll = Object.values(data.counts || {}).reduce((a, b) => a + b, 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{reviewQueue ? "Human Review Queue" : "Claims Dashboard"}</h1>
          <p className="muted">
            {reviewQueue
              ? "Claims the validation engine could not clear automatically. Nothing here is treated as verified until a reviewer decides."
              : "Every claim flows AI prediction → confidence → business validation → final status."}
          </p>
        </div>
        <Link to="/new" className="btn btn-primary">+ New Claim</Link>
      </div>

      <div className="stat-row">
        <button className={`stat ${status === "" ? "stat-active" : ""}`} onClick={() => setStatus("")}>
          <div className="stat-num">{totalAll}</div><div className="stat-label">All claims</div>
        </button>
        {ORDER.map((s) => (
          <button key={s} className={`stat stat-${STATUS_META[s].tone} ${status === s ? "stat-active" : ""}`}
                  onClick={() => setStatus(s)} data-testid={`stat-${s}`}>
            <div className="stat-num">{data.counts?.[s] ?? 0}</div>
            <div className="stat-label">{STATUS_META[s].label}</div>
          </button>
        ))}
      </div>

      <div className="card">
        <div className="toolbar">
          <input className="input" placeholder="Search claim ID, customer, model, serial…" value={search}
                 onChange={(e) => setSearch(e.target.value)} aria-label="Search claims" />
          <span className="muted">{loading ? "Loading…" : `${data.total} claim(s)`}</span>
        </div>
        <ErrorBox error={error} />
        <table className="table" data-testid="claims-table">
          <thead>
            <tr>
              <th>Claim ID</th><th>Customer</th><th>Model / Serial</th><th>Category</th>
              <th>Severity</th><th style={{ width: 170 }}>AI Confidence</th><th>Status</th><th>Submitted</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.claimId} onClick={() => navigate(`/claims/${c.claimId}`)} className="row-link">
                <td className="mono strong">{c.claimId}</td>
                <td>{c.customer}</td>
                <td><div>{c.equipmentModel}</div><div className="muted mono small">{c.serialNumber || "no serial"}</div></td>
                <td>{c.categoryHint || <span className="muted">—</span>}</td>
                <td><SeverityPill value={c.severityHint} /></td>
                <td><ConfidenceBar value={c.aiConfidence} threshold={confidenceThreshold} /></td>
                <td><StatusBadge status={c.validationStatus} /></td>
                <td className="small muted">{formatDateTime(c.createdAt)}</td>
              </tr>
            ))}
            {!loading && data.items.length === 0 && (
              <tr><td colSpan={8} className="empty">No claims here yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
