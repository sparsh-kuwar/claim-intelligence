import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api.js";
import { FIELD_LABELS, SOURCE_LABELS, formatDateTime, humanize, pipelineStages } from "../lib/format.js";
import { ConfidenceBar, ErrorBox, Pipeline, SeverityPill, StatusBadge } from "../components/ui.jsx";
import { useConfig } from "../App.jsx";

const REVIEWABLE = ["NEEDS_REVIEW", "READY_FOR_APPROVAL"];

export default function ClaimDetail() {
  const { claimId } = useParams();
  const { confidenceThreshold: threshold, categories, severities } = useConfig();
  const [claim, setClaim] = useState(null);
  const [record, setRecord] = useState(null);
  const [error, setError] = useState(null);
  const [actionError, setActionError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reviewer, setReviewer] = useState("analyst");
  const [comment, setComment] = useState("");

  const load = useCallback(async () => {
    try {
      const c = await api.get(claimId);
      setClaim(c);
      setComment(c.reviewerComment || "");
      setRecord(c.validationStatus === "APPROVED" ? await api.exportRecord(claimId) : null);
      setError(null);
    } catch (e) { setError(e); }
  }, [claimId]);

  useEffect(() => { load(); }, [load]);

  async function run(fn) {
    setBusy(true); setActionError(null);
    try {
      const c = await fn();
      if (c) {
        setClaim(c);
        if (c.validationStatus === "APPROVED") setRecord(await api.exportRecord(claimId));
      }
    } catch (e) { setActionError(e); }
    finally { setBusy(false); }
  }

  const reviewField = (field, action, value) =>
    run(() => api.review(claimId, { reviewer, fieldReviews: { [field]: { action, value } } }));
  const saveComment = () => run(() => api.review(claimId, { reviewer, fieldReviews: {}, comment }));
  const approve = () => run(() => api.approve(claimId, { reviewer, comment: comment || null }));
  const escalate = () => {
    if (!comment.trim()) {
      setActionError({ message: "Enter an escalation reason in the reviewer comment box." });
      return;
    }
    run(() => api.escalate(claimId, { reviewer, reason: comment }));
  };
  const analyze = () => run(() => api.analyze(claimId));

  if (error) return <ErrorBox error={error} />;
  if (!claim) return <p className="muted">Loading…</p>;

  const a = claim.aiAnalysis;
  const v = claim.validation;
  const reviewable = REVIEWABLE.includes(claim.validationStatus);
  const mustReview = new Set(v?.fieldsRequiringReview || []);
  const pending = [...mustReview].filter((f) => !claim.fieldReviews?.[f]);

  return (
    <>
      <Link to="/" className="back">← All claims</Link>
      <div className="page-head">
        <div>
          <h1 className="mono" data-testid="claim-title">{claim.claimId}</h1>
          <p className="muted">{claim.customer} · {claim.equipmentModel} · submitted {formatDateTime(claim.createdAt)}</p>
        </div>
        <StatusBadge status={claim.validationStatus} />
      </div>

      <Pipeline stages={pipelineStages(claim, threshold)} />

      {claim.validationStatus === "NEEDS_REVIEW" && (
        <div className="alert alert-warn" data-testid="review-warning">
          <b>⚠ Human review required.</b> Values below are AI predictions, <u>not verified facts</u>.
          Failed rules: {v.failedRules.join(", ")}.
          {pending.length > 0 && <> Decide on: <b>{pending.map((f) => FIELD_LABELS[f]).join(", ")}</b>.</>}
        </div>
      )}
      {claim.validationStatus === "PROCESSING" && (
        <div className="alert alert-info">Not analyzed yet. <button className="btn btn-sm" onClick={analyze} disabled={busy}>Run AI analysis</button></div>
      )}

      <div className="grid-main">
        <div className="stack">
          {a && (
            <div className="card">
              <div className="card-head">
                <h2>AI Claim Intelligence</h2>
                <span className="muted small">provider: <b>{claim.aiProvider}</b> · overall (weakest critical field): <b>{claim.aiConfidence}%</b></span>
              </div>
              <table className="table ai-table" data-testid="ai-table">
                <thead><tr><th>Field</th><th>AI prediction</th><th style={{ width: 150 }}>Confidence</th><th>Review</th></tr></thead>
                <tbody>
                  {Object.keys(FIELD_LABELS).map((f) => (
                    <AIRow key={f} field={f} ai={a[f]} review={claim.fieldReviews?.[f]} threshold={threshold}
                           required={mustReview.has(f)} reviewable={reviewable} busy={busy}
                           categories={categories} severities={severities} onReview={reviewField} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {record && (
            <div className="card" data-testid="final-record">
              <div className="card-head">
                <h2>Validated Claim Record</h2>
                <div className="actions">
                  <button className="btn btn-sm" onClick={() => navigator.clipboard?.writeText(JSON.stringify(record, null, 2))}>Copy JSON</button>
                  <button className="btn btn-sm btn-primary" onClick={() => download(record)} data-testid="download-json">Download JSON</button>
                </div>
              </div>
              <p className="muted small">Built from reviewer-validated values and system-of-record data — not copied from raw AI output.
                Stored in PostgreSQL · <code>GET /api/claims/{claim.claimId}/export</code></p>
              <div className="provenance">
                {Object.entries(record.provenance).map(([f, p]) => (
                  <span key={f} className={`prov prov-${p.source.toLowerCase()}`} title={`AI confidence ${p.aiConfidence}%`}>
                    {FIELD_LABELS[f]}: {SOURCE_LABELS[p.source]}
                  </span>
                ))}
              </div>
              <pre className="json">{JSON.stringify(record, null, 2)}</pre>
            </div>
          )}

          <div className="card">
            <h2>Audit Trail</h2>
            <ul className="timeline" data-testid="timeline">
              {claim.events.map((e, i) => (
                <li key={i}>
                  <span className="tl-type">{humanize(e.eventType)}</span>
                  <span className="muted small"> by {e.actor} · {formatDateTime(e.createdAt)}</span>
                  <EventDetails e={e} />
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="stack">
          {reviewable && (
            <div className="card decision-card" data-testid="decision-panel">
              <h2>Reviewer Decision</h2>
              <label className="field"><span className="field-label">Reviewer</span>
                <input className="input" value={reviewer} onChange={(e) => setReviewer(e.target.value)} maxLength={100} />
              </label>
              <label className="field"><span className="field-label">Reviewer comment / escalation reason</span>
                <textarea className="input" rows={3} value={comment} onChange={(e) => setComment(e.target.value)}
                          placeholder="e.g. Technician evidence required." data-testid="comment" maxLength={2000} />
              </label>
              <ErrorBox error={actionError} />
              <div className="actions">
                <button className="btn btn-ok" onClick={approve} disabled={busy} data-testid="approve">Approve Claim</button>
                <button className="btn btn-bad" onClick={escalate} disabled={busy} data-testid="escalate">Escalate</button>
                <button className="btn btn-sm" onClick={saveComment} disabled={busy || !comment.trim()}>Save comment</button>
              </div>
              {claim.validationStatus === "NEEDS_REVIEW" && (
                <p className="muted small">Approval is blocked until every flagged field has a decision and a comment is given.</p>
              )}
            </div>
          )}
          {claim.validationStatus === "ESCALATED" && (
            <div className="alert alert-bad"><b>Escalated</b> by {claim.reviewedBy}: {claim.reviewerComment}</div>
          )}

          {v && (
            <div className="card">
              <h2>Business Validation</h2>
              <p className="muted small">Threshold: {v.threshold}% · registry warranty: <b>{humanize(v.registryWarrantyStatus)}</b></p>
              <ul className="rules" data-testid="rules">
                {v.rules.map((r) => (
                  <li key={r.id} className={r.passed ? "rule-pass" : "rule-fail"}>
                    <span className="rule-icon">{r.passed ? "✓" : "✕"}</span>
                    <div><div><b>{r.id}</b> {r.name}</div><div className="small muted">{r.message}</div></div>
                  </li>
                ))}
              </ul>
              {v.aiMeta?.fallbackReason && <p className="small muted">LLM fallback: {v.aiMeta.fallbackReason}</p>}
              {v.aiMeta?.groundingNotes?.map((n) => <p key={n} className="small muted">Grounding: {n}</p>)}
            </div>
          )}

          <div className="card">
            <h2>Intake</h2>
            <dl className="kv">
              <dt>Customer</dt><dd>{claim.customer}</dd>
              <dt>Model</dt><dd>{claim.equipmentModel}</dd>
              <dt>Serial</dt><dd className="mono">{claim.serialNumber || <span className="text-bad">missing</span>}</dd>
              <dt>Service date</dt><dd>{claim.serviceDate}</dd>
              <dt>Warranty (claimed)</dt><dd>{humanize(claim.warrantyStatus)}</dd>
              <dt>Attachment</dt>
              <dd>{claim.attachmentName ? <a href={api.attachmentUrl(claim.claimId)} target="_blank" rel="noreferrer">{claim.attachmentName}</a> : "—"}</dd>
            </dl>
            <div className="description">{claim.description}</div>
          </div>
        </div>
      </div>
    </>
  );
}

function AIRow({ field, ai, review, threshold, required, reviewable, busy, categories, severities, onReview }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const low = ai.value !== null && ai.confidence < threshold;
  const startEdit = () => { setDraft(review?.value ?? ai.value ?? ""); setEditing(true); };
  const save = () => { onReview(field, "EDIT", draft); setEditing(false); };

  let input = <input className="input input-sm" value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />;
  if (field === "severity") input = (
    <select className="input input-sm" value={draft} onChange={(e) => setDraft(e.target.value)}>
      {severities.map((s) => <option key={s}>{s}</option>)}
    </select>);
  if (field === "category") input = (
    <select className="input input-sm" value={draft} onChange={(e) => setDraft(e.target.value)}>
      {categories.map((s) => <option key={s}>{s}</option>)}
    </select>);

  return (
    <tr className={`${required && !review ? "row-flag" : ""}`} data-testid={`row-${field}`}>
      <td>
        <div className="strong">{FIELD_LABELS[field]}</div>
        {required && !review && <span className="tag tag-warn">REVIEW REQUIRED</span>}
        {low && <span className="tag tag-low">LOW CONFIDENCE</span>}
      </td>
      <td>
        <div className={review?.action === "REJECT" || review?.action === "EDIT" ? "struck" : ""}>
          {field === "severity" ? <SeverityPill value={ai.value} /> : ai.value ?? <span className="muted">not found</span>}
        </div>
        {review?.action === "EDIT" && <div className="edited">→ {review.value}</div>}
        {ai.evidence && <div className="evidence">{ai.evidence}</div>}
      </td>
      <td><ConfidenceBar value={ai.value === null ? null : ai.confidence} threshold={threshold} /></td>
      <td className="review-cell">
        {review && !editing && <span className={`decision decision-${review.action.toLowerCase()}`}>{review.action === "EDIT" ? "EDITED" : review.action + "ED"}</span>}
        {reviewable && !editing && (
          <div className="btn-group">
            <button className="btn btn-xs" disabled={busy || ai.value === null} onClick={() => onReview(field, "ACCEPT")} data-testid={`accept-${field}`}>Accept</button>
            <button className="btn btn-xs" disabled={busy} onClick={startEdit} data-testid={`edit-${field}`}>Edit</button>
            <button className="btn btn-xs" disabled={busy} onClick={() => onReview(field, "REJECT")} data-testid={`reject-${field}`}>Reject</button>
          </div>
        )}
        {editing && (
          <div className="edit-box">
            {input}
            <div className="btn-group">
              <button className="btn btn-xs btn-primary" disabled={!String(draft).trim()} onClick={save} data-testid={`save-${field}`}>Save</button>
              <button className="btn btn-xs" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </div>
        )}
      </td>
    </tr>
  );
}

function EventDetails({ e }) {
  const d = e.details || {};
  if (e.eventType === "VALIDATED") return <div className="small">outcome {d.outcome}{d.failedRules?.length ? ` · failed ${d.failedRules.join(", ")}` : ""}</div>;
  if (e.eventType === "AI_ANALYZED") return <div className="small">overall confidence {d.overallConfidence}%</div>;
  if (e.eventType === "REVIEWED") return (
    <div className="small">
      {Object.entries(d.changes || {}).map(([f, c]) => (
        <div key={f}>{FIELD_LABELS[f]}: {c.action}{c.action === "EDIT" ? ` “${c.aiValue}” → “${c.newValue}”` : ""}</div>
      ))}
      {d.comment && <div>comment: “{d.comment}”</div>}
    </div>);
  if (e.eventType === "ESCALATED") return <div className="small">reason: {d.reason}</div>;
  if (e.eventType === "APPROVED") return <div className="small">path {d.approvalPath}{d.comment ? ` · “${d.comment}”` : ""}</div>;
  return null;
}

function download(record) {
  const blob = new Blob([JSON.stringify(record, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${record.claimId}.json`;
  link.click();
  URL.revokeObjectURL(url);
}
