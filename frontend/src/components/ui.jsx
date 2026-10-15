import { STATUS_META, confidenceBand } from "../lib/format.js";

export function StatusBadge({ status }) {
  const m = STATUS_META[status] || { label: status, tone: "neutral" };
  return <span className={`badge badge-${m.tone}`} data-testid="status-badge">{m.label}</span>;
}

export function ConfidenceBar({ value, threshold = 80 }) {
  const band = confidenceBand(value, threshold);
  if (band === "none") return <span className="muted">—</span>;
  return (
    <div className={`conf conf-${band}`} title={`${value}% (threshold ${threshold}%)`}>
      <div className="conf-track">
        <div className="conf-fill" style={{ width: `${value}%` }} />
        <div className="conf-threshold" style={{ left: `${threshold}%` }} />
      </div>
      <span className="conf-num">{value}%</span>
    </div>
  );
}

export function SeverityPill({ value }) {
  if (!value) return <span className="muted">—</span>;
  return <span className={`sev sev-${value.toLowerCase()}`}>{value}</span>;
}

export function ErrorBox({ error }) {
  if (!error) return null;
  const details = Array.isArray(error.details) ? error.details : [];
  return (
    <div className="alert alert-bad" role="alert">
      <strong>{error.message}</strong>
      {details.length > 0 && (
        <ul>
          {details.map((d, i) => (
            <li key={i}>{typeof d === "string" ? d : `${d.field}: ${d.message}`}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Pipeline({ stages }) {
  return (
    <ol className="pipeline" data-testid="pipeline">
      {stages.map((s, i) => (
        <li key={s.key} className={`stage stage-${s.state}`}>
          <div className="stage-dot">{i + 1}</div>
          <div>
            <div className="stage-label">{s.label}</div>
            <div className="stage-note">{s.note}</div>
          </div>
        </li>
      ))}
    </ol>
  );
}
